#!/usr/bin/python3
"""Die Linux-Zwischenablage einmalig per OpenSSH-SFTP übertragen."""

from __future__ import annotations

import argparse
import configparser
import os
from pathlib import Path
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass


class SyncError(Exception):
    """Ein verständlicher Fehler für die Kommandozeile."""


@dataclass(frozen=True)
class Clipboard:
    data: bytes
    kind: str
    mime: str

    @property
    def filename(self) -> str:
        return f"clipboard_{self.kind}"


def run_clipboard(command: list[str]) -> bytes:
    try:
        result = subprocess.run(command, capture_output=True, timeout=10, check=False)
    except FileNotFoundError as exc:
        package = "wl-clipboard" if command[0] == "wl-paste" else "xclip"
        raise SyncError(f"{command[0]} fehlt. Bitte das Paket {package} installieren.") from exc
    except subprocess.TimeoutExpired as exc:
        raise SyncError("Die Zwischenablage antwortet nicht (Zeitlimit: 10 Sekunden).") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise SyncError(f"Zwischenablage nicht lesbar oder leer: {detail}")
    return result.stdout


def choose_backend(requested: str) -> str:
    if requested != "auto":
        return requested
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session == "wayland" or (session != "x11" and os.environ.get("WAYLAND_DISPLAY")):
        return "wayland"
    if session == "x11" or os.environ.get("DISPLAY"):
        return "x11"
    raise SyncError("Keine grafische Sitzung erkannt. In der Desktop-Sitzung starten "
                    "oder --backend x11/wayland angeben.")


def select_type(offered: list[str], kind: str) -> tuple[str, str]:
    # Bilddaten haben Vorrang vor einer gleichzeitig angebotenen Textbeschreibung.
    if kind in ("auto", "image"):
        images = [t for t in offered if t.lower().startswith("image/")]
        for preferred in ("image/png", "image/jpeg", "image/webp", "image/bmp", "image/tiff"):
            if preferred in images:
                return preferred, "image"
        if images:
            return images[0], "image"
    if kind in ("auto", "text"):
        for preferred in ("text/plain;charset=utf-8", "UTF8_STRING", "text/plain", "STRING"):
            if preferred in offered:
                return preferred, "text"
        for mime in offered:
            if mime.lower().split(";", 1)[0].strip() == "text/plain":
                return mime, "text"
    raise SyncError("Die Zwischenablage enthält kein passendes Bild bzw. keinen Klartext. "
                    "Im Dateimanager kopierte Dateien werden nicht übertragen.")


def read_clipboard(backend: str, kind: str) -> Clipboard:
    backend = choose_backend(backend)
    base = (["wl-paste"] if backend == "wayland"
            else ["xclip", "-selection", "clipboard", "-out"])
    query = ["--list-types"] if backend == "wayland" else ["-target", "TARGETS"]
    offered = run_clipboard(base + query).decode("utf-8", errors="replace").splitlines()
    mime, selected_kind = select_type([t.strip() for t in offered], kind)
    flags = ["--no-newline", "--type", mime] if backend == "wayland" else ["-target", mime]
    data = run_clipboard(base + flags)
    if not data:
        raise SyncError("Die Zwischenablage ist leer. Es wurde nichts übertragen.")
    if selected_kind == "text":
        # X11 STRING ist Latin-1; Klartext wird auf dem Ziel als UTF-8 gespeichert.
        charset = "latin-1" if mime == "STRING" else "utf-8"
        match = re.search(r"charset\s*=\s*[\"']?([^;\s\"']+)", mime, re.IGNORECASE)
        if match:
            charset = match.group(1)
        try:
            data = data.decode(charset).encode("utf-8")
        except (LookupError, UnicodeError) as exc:
            raise SyncError(f"Text lässt sich nicht als {charset} lesen: {exc}") from exc
    return Clipboard(data, selected_kind, mime)


def quote_sftp(path: str) -> str:
    # SFTP hat einen eigenen Parser. Keine Shell starten; Steuerzeichen ablehnen.
    if any(ord(char) < 32 or ord(char) == 127 for char in path):
        raise SyncError("Dateipfade dürfen keine Steuerzeichen enthalten.")
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def upload(clipboard: Clipboard, args: argparse.Namespace) -> str:
    if not shutil.which("sftp"):
        raise SyncError("sftp fehlt. Bitte openssh-client installieren.")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:%-]*", args.host):
        raise SyncError("Ungültiger Host. Eine IP-Adresse, einen Hostnamen oder SSH-Alias angeben.")
    if args.user and not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@-]*", args.user):
        raise SyncError("Ungültiger SSH-Benutzername.")
    if not args.remote_dir:
        raise SyncError("Der Zielordner darf nicht leer sein.")
    remote = posixpath.join(args.remote_dir, clipboard.filename)
    # Relative Pfade mit '-' dürfen nicht als SFTP-Option interpretiert werden.
    if not remote.startswith("/"):
        remote = "./" + remote
    remote_quoted = quote_sftp(remote)
    command = ["sftp", "-q", "-b", "-", "-oBatchMode=yes", "-oStrictHostKeyChecking=yes",
               "-oConnectTimeout=10", "-oServerAliveInterval=15", "-oServerAliveCountMax=2"]
    if args.port is not None:
        if not 1 <= args.port <= 65535:
            raise SyncError("Der Port muss zwischen 1 und 65535 liegen.")
        command += ["-P", str(args.port)]
    if args.identity:
        command += ["-i", str(Path(args.identity).expanduser())]
    if args.user:
        command += ["-o", f"User={args.user}"]
    command += [f"[{args.host}]" if ":" in args.host else args.host]
    with tempfile.TemporaryDirectory(prefix="clipboard-sync-") as directory:
        local = Path(directory) / clipboard.filename
        local.write_bytes(clipboard.data)
        local.chmod(0o600)
        batch = f"put {quote_sftp(str(local))} {remote_quoted}\nbye\n"
        try:
            result = subprocess.run(command, input=batch.encode("utf-8"),
                                    capture_output=True, timeout=120, check=False)
        except subprocess.TimeoutExpired as exc:
            raise SyncError("SFTP-Zeitlimit überschritten (120 Sekunden). "
                            "Die Zieldatei kann unvollständig sein.") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise SyncError(f"SFTP-Übertragung fehlgeschlagen: {detail}\n"
                        "Hostschlüssel, SSH-Schlüssel/Agent, Zielordner und Schreibrechte prüfen. "
                        "Die Zieldatei kann unvollständig sein.")
    return remote


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    default_config = Path(__file__).resolve().with_name("config.ini")
    preliminary = argparse.ArgumentParser(add_help=False)
    preliminary.add_argument("--config", type=Path, default=default_config)
    known, _ = preliminary.parse_known_args(argv)
    config = configparser.ConfigParser(interpolation=None)
    if known.config.exists():
        with known.config.open(encoding="utf-8") as handle:
            config.read_file(handle)
        if not config.has_section("sftp"):
            raise SyncError("In der Konfiguration fehlt der Abschnitt [sftp].")
    elif known.config != default_config:
        raise SyncError(f"Konfigurationsdatei fehlt: {known.config}")
    defaults = dict(config["sftp"]) if config.has_section("sftp") else {}
    parser = argparse.ArgumentParser(description=__doc__, parents=[preliminary])
    parser.add_argument("--host", default=defaults.get("host"), help="Ziel-IP, Hostname oder SSH-Alias")
    parser.add_argument("--user", default=defaults.get("user"), help="SSH-Benutzername")
    parser.add_argument("--port", type=int, default=defaults.get("port"), help="SSH-Port (sonst SSH-Konfiguration/22)")
    parser.add_argument("--identity", default=defaults.get("identity"), help="Pfad zum privaten SSH-Schlüssel")
    parser.add_argument("--remote-dir", default=defaults.get("remote_dir", "."), help="Vorhandener Zielordner")
    parser.add_argument("--backend", choices=("auto", "x11", "wayland"), default="auto")
    parser.add_argument("--type", dest="kind", choices=("auto", "text", "image"), default="auto",
                        help="Inhalt auswählen (auto: Bild bevorzugen)")
    args = parser.parse_args(argv)
    if not args.host:
        raise SyncError("Ziel fehlt. --host angeben oder config.example.ini nach config.ini kopieren und anpassen.")
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        clipboard = read_clipboard(args.backend, args.kind)
        remote = upload(clipboard, args)
    except (SyncError, OSError, configparser.Error) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Abgebrochen.", file=sys.stderr)
        return 130
    print(f"Übertragen: {args.host}:{remote} ({len(clipboard.data)} Bytes, {clipboard.mime})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
