#!/usr/bin/env python3
"""Zwischenablage einmalig auf eine SMB-Freigabe übertragen (Python >= 3.8)."""

import argparse
import base64
import configparser
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass


class SyncError(Exception):
    """Ein Fehler, der ohne Traceback angezeigt werden kann."""


@dataclass
class Clipboard:
    filename: str
    data: bytes
    format: str


def run(command, timeout, **kwargs):
    try:
        result = subprocess.run(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=timeout, check=False, **kwargs
        )
    except FileNotFoundError:
        raise SyncError("Systemwerkzeug fehlt: " + command[0]) from None
    except subprocess.TimeoutExpired:
        raise SyncError("Zeitlimit überschritten: " + command[0]) from None
    if result.returncode:
        detail = (result.stderr + result.stdout).decode("utf-8", errors="replace").strip()
        raise SyncError("{} fehlgeschlagen: {}".format(command[0], detail[:1500]))
    return result.stdout


def load_config(path):
    # Keine %-Interpolation: Passwörter können Prozentzeichen enthalten.
    config = configparser.ConfigParser(interpolation=None)
    try:
        with path.open(encoding="utf-8-sig") as stream:
            config.read_file(stream)
    except configparser.Error:
        raise SyncError("Ungültige INI-Datei: " + str(path)) from None
    section = "windows" if sys.platform == "win32" else "linux"
    if section not in config:
        raise SyncError("Konfigurationsabschnitt fehlt: [" + section + "]")
    settings = dict(config[section])
    for key in ("share", "remote_dir"):
        if key not in settings:
            raise SyncError("Konfigurationswert fehlt: " + key)
    share = settings["share"].replace("\\", "/").rstrip("/")
    if not re.fullmatch(r"//[^/\s]+/[^/\r\n]+", share):
        raise SyncError("share muss //Server/Freigabe enthalten.")
    settings["share"] = share
    remote_dir = settings["remote_dir"].replace("\\", "/").strip("/")
    if any(part in (".", "..") for part in remote_dir.split("/")):
        raise SyncError("remote_dir darf keine .- oder ..-Komponenten enthalten.")
    # smbclient hat einen eigenen Befehlsparser, auch ohne Shell.
    if any(c in remote_dir for c in '\";\r\n\x00'):
        raise SyncError("remote_dir enthält unzulässige Steuer- oder Befehlszeichen.")
    settings["remote_dir"] = remote_dir
    try:
        timeout = float(settings.get("timeout", "30"))
    except ValueError:
        raise SyncError("timeout muss eine positive Zahl sein.") from None
    if not math.isfinite(timeout) or timeout <= 0:
        raise SyncError("timeout muss eine positive, endliche Zahl sein.")
    settings["timeout"] = timeout
    if section == "linux":
        for key in ("username", "password", "local_dir"):
            if not settings.get(key):
                raise SyncError("Konfigurationswert fehlt: " + key)
        for key in ("username", "password", "domain"):
            if any(c in settings.get(key, "") for c in "\r\n\x00"):
                raise SyncError("Ungültiger Anmeldewert: " + key)
        local = Path(settings["local_dir"]).expanduser()
        settings["local_dir"] = local if local.is_absolute() else path.parent / local
    return settings


def linux_backend(requested):
    if requested != "auto":
        return requested
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    raise SyncError("Keine grafische Sitzung erkannt (DISPLAY/WAYLAND_DISPLAY).")


def choose_format(formats, kind):
    images = [f for f in formats if f.startswith("image/")]
    preferred = ["image/png", "image/jpeg", "image/bmp", "image/tiff", "image/webp"]
    images.sort(key=lambda f: preferred.index(f) if f in preferred else len(preferred))
    if kind != "text" and images:
        return images[0], True
    if kind != "image":
        for target in ("text/plain;charset=utf-8", "text/plain;charset=UTF-8", "UTF8_STRING", "text/plain"):
            if target in formats:
                return target, False
        for target in formats:
            if target.startswith("text/plain;"):
                return target, False
        if "STRING" in formats:
            return "STRING", False
    raise SyncError("Zwischenablage enthält keinen unterstützten {}inhalt.".format(
        {"auto": "Text- oder Bild", "text": "Text", "image": "Bild"}[kind]))


def read_linux(settings, backend, kind):
    timeout = settings["timeout"]
    if backend == "wayland":
        tool = settings.get("wl_paste", "wl-paste")
        formats = run([tool, "--list-types"], timeout)
        prefix = [tool, "--no-newline", "--type"]
    else:
        tool = settings.get("xclip", "xclip")
        prefix = [tool, "-selection", "clipboard", "-out", "-target"]
        formats = run(prefix + ["TARGETS"], timeout)
    target, is_image = choose_format(formats.decode("utf-8").splitlines(), kind)
    data = run(prefix + [target], timeout)
    if is_image:
        if not data:
            raise SyncError("Die Zwischenablage liefert leere Bilddaten.")
        return Clipboard("clipboard_image", data, target)
    charset = re.search(r"charset\s*=\s*[\"']?([^;\"'\s]+)", target, re.I)
    encoding = charset.group(1) if charset else ("latin-1" if target == "STRING" else "utf-8")
    try:
        data = data.decode(encoding).encode("utf-8")
    except (LookupError, UnicodeError):
        raise SyncError("Text konnte nicht als {} gelesen werden.".format(encoding)) from None
    return Clipboard("clipboard_text", data, "text/plain; charset=utf-8")


# clip.exe ist ein Schreibwerkzeug. Die Windows-eigene .NET-API liest die
# Zwischenablage über PowerShell im erforderlichen STA-Modus aus.
WINDOWS_READER = r"""
$ErrorActionPreference = 'Stop'
try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $dir = $env:CLIPBOARD_SYNC_OUTPUT
    $kind = $env:CLIPBOARD_SYNC_KIND
    if ($kind -ne 'text' -and [System.Windows.Forms.Clipboard]::ContainsImage()) {
        $image = [System.Windows.Forms.Clipboard]::GetImage()
        try {
            $image.Save([IO.Path]::Combine($dir, 'clipboard_image'), [System.Drawing.Imaging.ImageFormat]::Png)
        } finally { if ($null -ne $image) { $image.Dispose() } }
        [Console]::Out.Write('clipboard_image')
    } elseif ($kind -ne 'image' -and [System.Windows.Forms.Clipboard]::ContainsText()) {
        $text = [System.Windows.Forms.Clipboard]::GetText()
        $utf8 = New-Object System.Text.UTF8Encoding($false)
        [IO.File]::WriteAllText([IO.Path]::Combine($dir, 'clipboard_text'), $text, $utf8)
        [Console]::Out.Write('clipboard_text')
    } else { throw 'Die Zwischenablage enthaelt keinen passenden Text oder kein Bild.' }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
"""


def read_windows(settings, directory, kind):
    env = dict(os.environ, CLIPBOARD_SYNC_OUTPUT=str(directory), CLIPBOARD_SYNC_KIND=kind)
    encoded = base64.b64encode(WINDOWS_READER.encode("utf-16-le")).decode("ascii")
    filename = run([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-STA",
        "-EncodedCommand", encoded,
    ], settings["timeout"], env=env).decode("ascii").strip()
    if filename not in ("clipboard_text", "clipboard_image"):
        raise SyncError("Unerwartete Antwort der Windows-Zwischenablage.")
    return Clipboard(filename, (directory / filename).read_bytes(),
                     "image/png" if filename == "clipboard_image" else "text/plain; charset=utf-8")


def upload_linux(settings, directory, clipboard):
    # Datei statt -U user%pass: kein Passwort in der Prozessliste.
    auth = directory / "smb-auth"
    fd = os.open(str(auth), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            for key in ("username", "password", "domain"):
                if settings.get(key):
                    stream.write("{} = {}\n".format(key, settings[key]))
        target = "/".join(p for p in (settings["remote_dir"], clipboard.filename) if p)
        # Vollständiger Zielpfad: Ein fehlgeschlagenes cd darf niemals dazu
        # führen, dass versehentlich ins Wurzelverzeichnis geschrieben wird.
        run([
            settings.get("smbclient", "smbclient"), "-m", "SMB3", settings["share"],
            "-A", str(auth), "-c", 'put "{}" "{}"'.format(clipboard.filename, target),
        ], settings["timeout"], cwd=str(directory))
    except SyncError as error:
        raise SyncError(str(error).replace(settings["password"], "***")) from None
    finally:
        auth.unlink(missing_ok=True)


def upload_windows(settings, directory, clipboard):
    destination = Path(settings["share"].replace("/", "\\"))
    if settings["remote_dir"]:
        destination = destination.joinpath(*settings["remote_dir"].split("/"))
    # Windows verwendet die bereits gespeicherten Netzwerkanmeldedaten.
    # Das Zielverzeichnis muss existieren, ebenso wie beim Linux-Aufruf.
    shutil.copyfile(directory / clipboard.filename, destination / clipboard.filename)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().with_name("config.ini"))
    parser.add_argument("--backend", choices=("auto", "x11", "wayland"), default="auto",
                        help="Linux-Zwischenablage (Standard: automatisch)")
    parser.add_argument("--type", choices=("auto", "text", "image"), default="auto",
                        help="Inhalt auswählen (auto: Bild hat Vorrang vor Text)")
    args = parser.parse_args(argv)
    try:
        if sys.platform not in ("linux", "win32"):
            raise SyncError("Unterstützt werden Linux und Windows.")
        settings = load_config(args.config.resolve())
        local_dir = settings.get("local_dir")
        if local_dir is not None:
            local_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix="clipboard-sync-", dir=local_dir) as temporary:
            directory = Path(temporary)
            if sys.platform == "win32":
                clipboard = read_windows(settings, directory, args.type)
            else:
                clipboard = read_linux(settings, linux_backend(args.backend), args.type)
            (directory / clipboard.filename).write_bytes(clipboard.data)
            if sys.platform == "win32":
                upload_windows(settings, directory, clipboard)
            else:
                upload_linux(settings, directory, clipboard)
        print("Übertragen: {} ({} Bytes, {})".format(
            clipboard.filename, len(clipboard.data), clipboard.format))
        return 0
    except (SyncError, OSError, UnicodeError) as error:
        print("Fehler: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
