#!/usr/bin/python3
"""Abgeschlossene Dateiänderungen in ~/Clipboard in die Zwischenablage übernehmen."""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
from pathlib import Path
import select
import shutil
import signal
import stat
import struct
import subprocess
import tempfile
import threading

from clipboard_sync import SyncError, choose_backend

LOG = logging.getLogger("get_clipboard")
NAMES = {"clipboard_text", "clipboard_image"}
MODIFY, CLOSE_WRITE, MOVED_TO = 0x2, 0x8, 0x80
DELETE, MOVED_FROM = 0x200, 0x40
DELETE_SELF, MOVE_SELF, OVERFLOW, IGNORED = 0x400, 0x800, 0x4000, 0x8000
ISDIR = 0x40000000
HEADER = struct.Struct("iIII")


class DirectoryWatch:
    """Linux-inotify ohne zusätzliche Python-Pakete."""

    def __init__(self, directory: Path):
        libc = ctypes.CDLL(None, use_errno=True)
        libc.inotify_init1.argtypes = [ctypes.c_int]
        libc.inotify_init1.restype = ctypes.c_int
        libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        libc.inotify_add_watch.restype = ctypes.c_int
        self.fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 fehlgeschlagen")
        mask = MODIFY | CLOSE_WRITE | MOVED_TO | DELETE | MOVED_FROM | DELETE_SELF | MOVE_SELF
        if libc.inotify_add_watch(self.fd, os.fsencode(directory), mask) < 0:
            error = ctypes.get_errno()
            self.close()
            raise OSError(error, "Eingangsordner lässt sich nicht überwachen", str(directory))

    def close(self):
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def events(self, timeout: float = 0.5) -> list[tuple[int, str]]:
        if not select.select([self.fd], [], [], timeout)[0]:
            return []
        result = []
        while True:
            try:
                data = os.read(self.fd, 65536)
            except BlockingIOError:
                break
            offset = 0
            while offset < len(data):
                _, mask, _, size = HEADER.unpack_from(data, offset)
                offset += HEADER.size
                name = os.fsdecode(data[offset:offset + size].split(b"\0", 1)[0])
                offset += size
                result.append((mask, name))
        return result


def ready_files(events: list[tuple[int, str]]) -> list[str]:
    ready = {}
    for mask, name in events:
        if mask & (DELETE_SELF | MOVE_SELF | IGNORED):
            raise SyncError("Der überwachte Ordner wurde entfernt oder verschoben. Dienst neu starten.")
        if mask & OVERFLOW:
            raise SyncError("inotify-Ereignisse gingen verloren. Dienst neu starten und Datei erneut senden.")
        if name not in NAMES or mask & ISDIR:
            continue
        if mask & (MODIFY | DELETE | MOVED_FROM):
            ready.pop(name, None)
        if mask & (CLOSE_WRITE | MOVED_TO):
            ready.pop(name, None)
            ready[name] = None
    return list(ready)


def read_payload(path: Path) -> tuple[bytes, str]:
    # Keine Symlinks oder Spezialdateien lesen, die blockieren könnten.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise SyncError(f"{path.name} ist keine reguläre Datei.")
        data = handle.read()
        after = os.fstat(handle.fileno())
    current = path.stat(follow_symlinks=False)
    snapshot = lambda info: (info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    if snapshot(before) != snapshot(after) or snapshot(after) != snapshot(current):
        raise SyncError(f"{path.name} wurde während des Lesens verändert; nächste Änderung abwarten.")
    if path.name == "clipboard_text":
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SyncError("clipboard_text enthält keinen gültigen UTF-8-Text.") from exc
        return data, "text/plain;charset=utf-8"
    if not data:
        raise SyncError("clipboard_image ist leer.")
    result = subprocess.run(["file", "--brief", "--mime-type", "-"], input=data,
                            capture_output=True, timeout=10, check=True)
    mime = result.stdout.decode("ascii").strip()
    if not mime.startswith("image/"):
        raise SyncError(f"clipboard_image enthält kein erkanntes Bildformat ({mime}).")
    return data, mime


class ClipboardWriter:
    def __init__(self, backend: str):
        self.backend = choose_backend(backend)
        program = "wl-copy" if self.backend == "wayland" else "xclip"
        for executable in (program, "file"):
            if not shutil.which(executable):
                raise SyncError(f"Benötigtes Programm fehlt: {executable}")
        self.process = None
        self.errors = None

    @staticmethod
    def stop(process):
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
            process.wait()

    def close(self):
        self.stop(self.process)
        self.process = None
        if self.errors is not None:
            self.errors.close()
            self.errors = None

    def write(self, data: bytes, mime: str):
        if self.backend == "wayland":
            command = ["wl-copy", "--foreground", "--type", mime]
        else:
            target = "UTF8_STRING" if mime.startswith("text/plain") else mime
            command = ["xclip", "-selection", "clipboard", "-in", "-quiet", "-target", target]
        errors = tempfile.TemporaryFile()
        try:
            # Vordergrundprozesse behalten die Clipboard-Ownership. Keine unbeaufsichtigten Forks.
            with tempfile.TemporaryFile() as source:
                source.write(data)
                source.seek(0)
                process = subprocess.Popen(command, stdin=source, stdout=subprocess.DEVNULL, stderr=errors)
            try:
                code = process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                code = None
            if code not in (None, 0):
                errors.seek(0)
                detail = errors.read().decode("utf-8", errors="replace").strip()
                raise SyncError(f"Zwischenablage konnte nicht gesetzt werden: {detail}")
        except BaseException:
            errors.close()
            raise
        self.close()
        self.process, self.errors = process, errors


def receive(directory: Path, writer: ClipboardWriter, stopped: threading.Event, notify=None):
    directory.mkdir(parents=True, exist_ok=True)
    watcher = DirectoryWatch(directory)
    LOG.info("Überwache %s (%s); warte auf neue Dateiänderungen.", directory, writer.backend)
    try:
        while not stopped.is_set():
            for name in ready_files(watcher.events()):
                if stopped.is_set():
                    break
                try:
                    data, mime = read_payload(directory / name)
                    writer.write(data, mime)
                except (OSError, SyncError, subprocess.SubprocessError) as exc:
                    LOG.error("%s: %s", name, exc)
                    if notify is not None:
                        notify(name, str(exc))
                    continue
                LOG.info("%s übernommen (%d Bytes, %s).", name, len(data), mime)
                if notify is not None:
                    notify(name)
    finally:
        watcher.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path.home() / "Clipboard",
                        help="Eingangsordner (Standard: ~/Clipboard)")
    parser.add_argument("--backend", choices=("auto", "x11", "wayland"), default="auto")
    parser.add_argument("--indicator", action="store_true", help="Panel-Indikator anzeigen (GTK/AppIndicator)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    stopped = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stopped.set())
    writer = None
    try:
        writer = ClipboardWriter(args.backend)
        directory = args.directory.expanduser().absolute()
        if args.indicator:
            from clipboard_indicator import run_with_indicator
            return run_with_indicator(directory, writer, stopped, receive)
        receive(directory, writer, stopped)
    except (OSError, SyncError) as exc:
        LOG.error("%s", exc)
        return 1
    finally:
        if writer is not None:
            writer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
