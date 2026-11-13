#!/usr/bin/env python3
"""Windows-Empfänger mit Systray, Python >= 3.8, ohne pip-Abhängigkeiten.

Fensterlos starten: pythonw.exe get_clipboard_win.py
Windows PowerShell stellt die Windows-Forms-Zwischenablage und das Tray bereit.
Die Netzwerkzugriffe laufen separat, damit das Tray auch bei SMB-Ausfällen reagiert.
"""

import argparse
import base64
import configparser
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time


FILENAMES = ("clipboard_text", "clipboard_image")


def load_settings(path):
    config = configparser.ConfigParser(interpolation=None)
    with path.open(encoding="utf-8-sig") as stream:
        config.read_file(stream)
    windows = config["windows"] if config.has_section("windows") else {}
    receiver = config["receiver"] if config.has_section("receiver") else {}
    directory = receiver.get("directory", "")
    if not directory:
        share = windows.get("share", "//192.168.178.111/Austausch")
        remote = windows.get("remote_dir", "Clipboard")
        directory = share.rstrip("/\\") + "/" + remote.strip("/\\")
    directory = Path(directory)
    if not directory.is_absolute():
        directory = path.parent / directory
    result = {"directory": directory}
    for name, default in (("poll_interval", "0.5"), ("settle_time", "1.0")):
        value = float(receiver.get(name, default))
        if not math.isfinite(value) or value <= 0:
            raise ValueError(name + " muss eine positive, endliche Zahl sein.")
        result[name] = value
    result["load_existing"] = config.getboolean("receiver", "load_existing", fallback=False)
    return result


def signature(path):
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns, stat.st_ino


class Watcher:
    """Unveränderte Dateien ignorieren, Schreibvorgänge erst stabil lesen.

    Erst nach erfolgreichem Schreiben in die Zwischenablage wird bestätigt.
    Ein fehlgeschlagener Zugriff lässt den letzten erfolgreichen Stand bestehen.
    """

    def __init__(self, directory, settle_time=1.0, load_existing=False):
        self.directory = Path(directory)
        self.settle_time = settle_time
        self.load_existing = load_existing
        self.initialized = False
        self.accepted = {}
        self.pending = {}

    def scan(self, now=None):
        now = time.monotonic() if now is None else now
        # Anders als Path.exists() unterscheidet scandir einen SMB-Ausfall
        # von einzelnen, noch nicht vorhandenen Clipboard-Dateien.
        with os.scandir(self.directory) as entries:
            names = {entry.name for entry in entries}
        current = {}
        for name in FILENAMES:
            if name in names:
                try:
                    current[name] = signature(self.directory / name)
                except FileNotFoundError:
                    pass  # Während der Auflistung ersetzt/gelöscht.
        if not self.initialized:
            self.initialized = True
            if not self.load_existing:
                self.accepted = current.copy()
        for name in FILENAMES:
            if name not in current:
                self.accepted.pop(name, None)
                self.pending.pop(name, None)
        ready = []
        for name, stamp in current.items():
            if self.accepted.get(name) == stamp:
                self.pending.pop(name, None)
                continue
            previous = self.pending.get(name)
            if previous is None or previous[0] != stamp:
                self.pending[name] = (stamp, now)
            elif now - previous[1] >= self.settle_time:
                ready.append((name, stamp))
        return sorted(ready, key=lambda item: (item[1][0], item[0]))

    def snapshot(self, name, stamp):
        path = self.directory / name
        if signature(path) != stamp:
            return None
        data = path.read_bytes()
        if signature(path) != stamp or len(data) != stamp[1]:
            return None
        if name == "clipboard_text":
            text = data.decode("utf-8-sig")
            if "\x00" in text:
                raise ValueError("clipboard_text enthält NUL-Zeichen.")
        elif not data:
            raise ValueError("clipboard_image ist leer.")
        return data

    def acknowledge(self, name, stamp):
        self.accepted[name] = stamp
        self.pending.pop(name, None)


# Eigene Vektorsymbole, direkt mit Windows-Bordmitteln gezeichnet. Keine
# externen Icon-Dateien oder Python-Pakete nötig. Die Formen bleiben auch
# ohne Farberkennung unterscheidbar: Pfeil, Textzeilen, Landschaft, Ausrufezeichen.
TRAY_ICON_SCRIPT = r"""
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ClipboardIconHandles {
    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool DestroyIcon(IntPtr handle);
}
'@
function New-ClipboardIcon {
    param(
        [ValidateSet('ready', 'text', 'image', 'error')][string]$State,
        [ValidateRange(16, 128)][int]$Size = 32
    )
    $colors = @{ ready = '#1675C5'; text = '#12834B'; image = '#8046C5'; error = '#B96408' }
    $accent = [Drawing.ColorTranslator]::FromHtml($colors[$State])
    $canvas = New-Object Drawing.Bitmap(($Size * 4), ($Size * 4))
    $small = New-Object Drawing.Bitmap($Size, $Size)
    $graphics = [Drawing.Graphics]::FromImage($canvas)
    $output = [Drawing.Graphics]::FromImage($small)
    $brush = New-Object Drawing.SolidBrush($accent)
    $pen = New-Object Drawing.Pen($accent, 2.5)
    $body = New-Object Drawing.Drawing2D.GraphicsPath
    $clip = New-Object Drawing.Drawing2D.GraphicsPath
    $handle = [IntPtr]::Zero
    $borrowedIcon = $null
    try {
        $graphics.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $graphics.ScaleTransform(($Size * 4 / 32.0), ($Size * 4 / 32.0))
        $pen.StartCap = [Drawing.Drawing2D.LineCap]::Round
        $pen.EndCap = [Drawing.Drawing2D.LineCap]::Round
        $pen.LineJoin = [Drawing.Drawing2D.LineJoin]::Round
        # Helle Außenkontur und farbiges Klemmbrett: auf heller und dunkler
        # Taskleiste sichtbar. Alle Koordinaten beziehen sich auf 32 x 32.
        $body.AddArc(4, 4, 8, 8, 180, 90)
        $body.AddArc(20, 4, 8, 8, 270, 90)
        $body.AddArc(20, 23, 8, 8, 0, 90)
        $body.AddArc(4, 23, 8, 8, 90, 90)
        $body.CloseFigure()
        $graphics.FillPath([Drawing.Brushes]::White, $body)
        $graphics.DrawPath($pen, $body)
        $clip.AddArc(10, 1, 6, 6, 180, 180)
        $clip.AddArc(16, 1, 6, 6, 180, 180)
        $clip.AddLine(22, 4, 22, 8)
        $clip.AddLine(22, 8, 10, 8)
        $clip.CloseFigure()
        $graphics.FillPath($brush, $clip)
        $graphics.FillRectangle([Drawing.Brushes]::White, 13, 4, 6, 1)
        switch ($State) {
            'ready' {
                $graphics.DrawLine($pen, 16, 12, 16, 24)
                $graphics.DrawLine($pen, 11, 19, 16, 24)
                $graphics.DrawLine($pen, 16, 24, 21, 19)
            }
            'text' {
                $graphics.DrawLine($pen, 10, 13, 22, 13)
                $graphics.DrawLine($pen, 10, 19, 22, 19)
                $graphics.DrawLine($pen, 10, 25, 18, 25)
            }
            'image' {
                $graphics.FillEllipse($brush, 18, 11, 4, 4)
                $points = [Drawing.PointF[]]@(
                    [Drawing.PointF]::new(9, 26), [Drawing.PointF]::new(14, 16),
                    [Drawing.PointF]::new(18, 22), [Drawing.PointF]::new(21, 18),
                    [Drawing.PointF]::new(24, 26)
                )
                $graphics.FillPolygon($brush, $points)
            }
            'error' {
                $graphics.FillRectangle($brush, 14, 11, 4, 10)
                $graphics.FillEllipse($brush, 14, 24, 4, 4)
            }
        }
        $output.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $output.PixelOffsetMode = [Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $output.DrawImage($canvas, 0, 0, $Size, $Size)
        $handle = $small.GetHicon()
        $borrowedIcon = [Drawing.Icon]::FromHandle($handle)
        # Die Kopie besitzt ihren Handle selbst; den temporären HICON freigeben.
        return $borrowedIcon.Clone()
    } finally {
        if ($null -ne $borrowedIcon) { $borrowedIcon.Dispose() }
        if ($handle -ne [IntPtr]::Zero) { [void][ClipboardIconHandles]::DestroyIcon($handle) }
        $clip.Dispose()
        $body.Dispose()
        $pen.Dispose()
        $brush.Dispose()
        $output.Dispose()
        $graphics.Dispose()
        $small.Dispose()
        $canvas.Dispose()
    }
}
"""


# Nur lokale, atomar veröffentlichte Nachrichten werden vom UI-Timer gelesen.
# Keine Netzwerkzugriffe im STA-/UI-Thread. Bilddaten werden vor dem Ersetzen
# der Zwischenablage dekodiert. copy=true erhält den Inhalt nach Programmende.
TRAY_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
""" + TRAY_ICON_SCRIPT + r"""
[System.Windows.Forms.Application]::EnableVisualStyles()
$ipc = $env:CLIPBOARD_RECEIVER_IPC
$requestPath = [IO.Path]::Combine($ipc, 'request.json')
$responsePath = [IO.Path]::Combine($ipc, 'response.json')
$utf8 = New-Object System.Text.UTF8Encoding($false, $true)
$mutex = New-Object System.Threading.Mutex($false, $env:CLIPBOARD_RECEIVER_MUTEX)
$ownsMutex = $false
try { $ownsMutex = $mutex.WaitOne(0) }
catch [System.Threading.AbandonedMutexException] { $ownsMutex = $true }
if (-not $ownsMutex) { $mutex.Dispose(); exit 0 }
$icons = @{}
try {
    foreach ($state in @('ready', 'text', 'image', 'error')) {
        $icons[$state] = New-ClipboardIcon -State $state -Size ([System.Windows.Forms.SystemInformation]::SmallIconSize.Width)
    }
} catch {
    foreach ($icon in $icons.Values) { $icon.Dispose() }
    $mutex.ReleaseMutex()
    $mutex.Dispose()
    throw
}
$tray = New-Object System.Windows.Forms.NotifyIcon
$tray.Icon = $icons.ready
$tray.Text = 'Clipboard: wartet auf Änderungen'
$tray.Visible = $true
$menu = New-Object System.Windows.Forms.ContextMenuStrip
$ack = $menu.Items.Add('Benachrichtigungen abschalten')
$ack.add_Click({ $tray.Icon = $icons.ready })
$quit = $menu.Items.Add('Beenden')
$quit.add_Click({ [System.Windows.Forms.Application]::Exit() })
$tray.ContextMenuStrip = $menu
$tray.add_MouseClick({
    if ($_.Button -eq [System.Windows.Forms.MouseButtons]::Left) {
        $tray.Icon = $icons.ready
    }
})
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 150
$timer.add_Tick({
    try {
        # Auch bei abrupt beendetem Python-Prozess kein verwaistes Tray.
        $parent = Get-Process -Id ([int]$env:CLIPBOARD_RECEIVER_PARENT) -ErrorAction SilentlyContinue
        if ($null -eq $parent) { [System.Windows.Forms.Application]::Exit(); return }
        if (-not [IO.File]::Exists($requestPath)) { return }
        $request = [IO.File]::ReadAllText($requestPath, $utf8) | ConvertFrom-Json
        $response = @{ ok = $true; error = '' }
        try {
            if ($request.kind -eq 'status') {
                $tray.Text = ([string]$request.message).Substring(0, [Math]::Min(63, $request.message.Length))
                if ($request.error) {
                    $tray.Icon = $icons.error
                    $tray.ShowBalloonTip(4000, 'Clipboard-Empfänger', $request.message, 'Warning')
                } else { $tray.Icon = $icons.ready }
            } else {
                $data = New-Object System.Windows.Forms.DataObject
                $image = $null
                $bitmap = $null
                try {
                    if ($request.kind -eq 'text') {
                        $text = [IO.File]::ReadAllText([IO.Path]::Combine($ipc, 'payload'), $utf8)
                        $data.SetData([System.Windows.Forms.DataFormats]::UnicodeText, $false, $text)
                    } elseif ($request.kind -eq 'image') {
                        $image = [System.Drawing.Image]::FromFile([IO.Path]::Combine($ipc, 'payload'))
                        $bitmap = New-Object System.Drawing.Bitmap($image)
                        $data.SetImage($bitmap)
                    } else { throw 'Unbekannter Nachrichtentyp.' }
                    [System.Windows.Forms.Clipboard]::SetDataObject($data, $true, 10, 100)
                } finally {
                    if ($null -ne $bitmap) { $bitmap.Dispose() }
                    if ($null -ne $image) { $image.Dispose() }
                }
                $label = if ($request.kind -eq 'text') { 'Text' } else { 'Bild' }
                $tray.Icon = $icons[$request.kind]
                $tray.Text = 'Clipboard: ' + $label + ' empfangen ' + (Get-Date -Format 'HH:mm:ss')
                $tray.ShowBalloonTip(3000, 'Clipboard empfangen', $label + ' in die Zwischenablage kopiert.', 'Info')
            }
        } catch {
            $response.ok = $false
            $response.error = $_.Exception.Message
        }
        [IO.File]::Delete($requestPath)
        [IO.File]::WriteAllText($responsePath + '.tmp', ($response | ConvertTo-Json -Compress), $utf8)
        [IO.File]::Move($responsePath + '.tmp', $responsePath)
    } catch {
        [Console]::Error.WriteLine($_.Exception.Message)
        [System.Windows.Forms.Application]::Exit()
    }
})
try {
    $timer.Start()
    [System.Windows.Forms.Application]::Run()
} finally {
    $timer.Stop()
    $timer.Dispose()
    $tray.Visible = $false
    $tray.Dispose()
    foreach ($icon in $icons.Values) { $icon.Dispose() }
    $menu.Dispose()
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
"""


class TrayBridge:
    def __init__(self, directory, process, stop):
        self.directory = directory
        self.process = process
        self.stop = stop

    def request(self, message, payload=None):
        if self.stop.is_set():
            raise InterruptedError("Empfänger wurde beendet.")
        if payload is not None:
            (self.directory / "payload").write_bytes(payload)
        temporary = self.directory / "request.tmp"
        temporary.write_text(json.dumps(message, ensure_ascii=True), encoding="utf-8")
        temporary.replace(self.directory / "request.json")
        response = self.directory / "response.json"
        while not self.stop.wait(0.1):
            if self.process.poll() is not None:
                raise InterruptedError("Systray wurde beendet.")
            try:
                result = json.loads(response.read_text(encoding="utf-8"))
            except FileNotFoundError:
                continue
            response.unlink()
            if payload is not None:
                (self.directory / "payload").unlink(missing_ok=True)
            if not result["ok"]:
                raise ValueError(result["error"])
            return
        raise InterruptedError("Empfänger wurde beendet.")


def monitor(settings, bridge, stop):
    watcher = Watcher(settings["directory"], settings["settle_time"], settings["load_existing"])
    last_error = None
    while not stop.is_set():
        try:
            changes = watcher.scan()
            errors = []
            for name, stamp in changes:
                if stop.is_set():
                    return
                try:
                    payload = watcher.snapshot(name, stamp)
                    if payload is None:
                        continue
                    bridge.request({"kind": "text" if name == "clipboard_text" else "image"}, payload)
                    watcher.acknowledge(name, stamp)
                    logging.info("Empfangen: %s (%s Bytes)", name, len(payload))
                except (OSError, UnicodeError, ValueError) as error:
                    errors.append(name + ": " + str(error))
            if errors:
                raise ValueError("; ".join(errors))
            if last_error is not None:
                logging.info("Überwachung wieder bereit.")
                if not changes:
                    bridge.request({"kind": "status", "message": "Clipboard: Überwachung wieder bereit", "error": False})
            last_error = None
        except InterruptedError:
            return
        except (OSError, UnicodeError, ValueError) as error:
            message = str(error)
            if message != last_error:
                logging.warning("%s", message)
                try:
                    bridge.request({"kind": "status", "message": "Clipboard: " + message[:230], "error": True})
                except InterruptedError:
                    return
                last_error = message
        if stop.wait(settings["poll_interval"]):
            return


def setup_logging():
    directory = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "ClipboardReceiver"
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / "get_clipboard_win.log", maxBytes=500_000,
                                  backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(message)s")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().with_name("config.ini"))
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        print("Dieses Tool benötigt Windows.", file=sys.stderr)
        return 1
    stop = threading.Event()
    process = None
    try:
        setup_logging()
        settings = load_settings(args.config.resolve())
        # Gleicher Eingangsordner: nur ein Empfänger je Windows-Sitzung.
        key = hashlib.sha256(str(settings["directory"]).lower().encode()).hexdigest()[:24]
        encoded = base64.b64encode(TRAY_SCRIPT.encode("utf-16-le")).decode("ascii")
        with tempfile.TemporaryDirectory(prefix="clipboard-receiver-") as temporary:
            directory = Path(temporary)
            env = dict(os.environ, CLIPBOARD_RECEIVER_IPC=temporary,
                       CLIPBOARD_RECEIVER_PARENT=str(os.getpid()),
                       CLIPBOARD_RECEIVER_MUTEX="Local\\ClipboardReceiver-" + key)
            with (directory / "host.log").open("wb") as host_log:
                process = subprocess.Popen([
                    "powershell.exe", "-NoProfile", "-NonInteractive", "-STA",
                    "-WindowStyle", "Hidden", "-EncodedCommand", encoded,
                ], env=env, stdin=subprocess.DEVNULL, stdout=host_log, stderr=host_log,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                bridge = TrayBridge(directory, process, stop)
                worker = threading.Thread(target=monitor, args=(settings, bridge, stop), daemon=True)
                worker.start()
                logging.info("Überwache %s", settings["directory"])
                try:
                    result = process.wait()
                finally:
                    stop.set()
                    if process.poll() is None:
                        process.terminate()
                    process.wait()
                    worker.join(timeout=2)
            detail = (directory / "host.log").read_bytes().decode("utf-8", errors="replace").strip()
            if detail:
                logging.warning("Windows-Host: %s", detail)
            if result:
                raise RuntimeError("Windows-Host konnte nicht ausgeführt werden. Siehe Protokoll.")
        return 0
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, configparser.Error, RuntimeError) as error:
        logging.exception("Empfänger fehlgeschlagen")
        if sys.stderr is not None:
            print("Fehler: " + str(error), file=sys.stderr)
        # Auch bei pythonw ohne Konsole sind Startfehler sichtbar.
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(error), "Clipboard-Empfänger", 0x10)
        return 1
    finally:
        stop.set()
        if process is not None and process.poll() is None:
            process.terminate()


if __name__ == "__main__":
    sys.exit(main())
