#!/usr/bin/python3
"""Optionaler GTK/AppIndicator für den Clipboard-Empfänger."""

from dataclasses import dataclass
from datetime import datetime
import importlib
import logging
from pathlib import Path
import queue
import threading

from clipboard_sync import SyncError

LOG = logging.getLogger("get_clipboard")
ICONS = Path(__file__).resolve().parent / "icons"


def load_gui():
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib, Gtk
        for namespace in ("AyatanaAppIndicator3", "AppIndicator3"):
            try:
                gi.require_version(namespace, "0.1")
                indicator = importlib.import_module(f"gi.repository.{namespace}")
                return Gtk, GLib, indicator
            except (ValueError, ImportError):
                continue
    except (ImportError, ValueError):
        pass
    raise SyncError("Panel-Indikator benötigt Systempakete: python3-gi, gir1.2-gtk-3.0 "
                    "und gir1.2-ayatanaappindicator3-0.1 (alternativ gir1.2-appindicator3-0.1).")


@dataclass
class IndicatorState:
    unseen: int = 0
    last_file: str = ""
    last_time: str = ""
    error: str = ""

    def incoming(self, name: str, error: str = ""):
        self.unseen += 1
        self.last_file = name
        self.last_time = datetime.now().astimezone().strftime("%d.%m.%Y %H:%M:%S")
        self.error = error

    def acknowledge(self):
        self.unseen = 0

    @property
    def icon(self):
        return "error" if self.error else "new" if self.unseen else "idle"

    @property
    def title(self):
        if self.error:
            return "Fehler beim letzten Eingang"
        if self.unseen:
            return f"Neue Eingänge: {self.unseen}"
        return "Keine neuen Eingänge"


class PanelIndicator:
    def __init__(self, directory: Path, identifier="clipboard-sync-receiver"):
        self.Gtk, self.GLib, self.api = load_gui()
        if not self.Gtk.init_check([])[0]:
            raise SyncError("Panel-Indikator kann die grafische Sitzung nicht öffnen.")
        self.state = IndicatorState()
        self.indicator = self.api.Indicator.new(
            identifier, str(ICONS / "clipboard-idle.svg"),
            self.api.IndicatorCategory.APPLICATION_STATUS)
        self.indicator.set_title("Clipboard-Empfang")
        self.menu = self.Gtk.Menu()
        self.status = self.info("")
        self.last = self.info("Noch kein Eingang seit dem Start")
        self.info(f"Ordner: {directory}")
        self.error_item = self.info("")
        self.menu.append(self.Gtk.SeparatorMenuItem())
        self.acknowledge_item = self.Gtk.MenuItem(label="Als gesehen markieren")
        self.acknowledge_item.connect("activate", self.acknowledge)
        self.menu.append(self.acknowledge_item)
        self.indicator.set_menu(self.menu)
        self.menu.show_all()
        self.refresh()
        self.indicator.set_status(self.api.IndicatorStatus.ACTIVE)

    def info(self, label):
        item = self.Gtk.MenuItem(label=label)
        item.set_sensitive(False)
        self.menu.append(item)
        return item

    def acknowledge(self, *_):
        self.state.acknowledge()
        self.refresh()

    def close(self):
        self.indicator.set_status(self.api.IndicatorStatus.PASSIVE)

    def incoming(self, name: str, error: str = ""):
        self.state.incoming(name, error)
        self.refresh()

    def refresh(self):
        self.indicator.set_icon_full(str(ICONS / f"clipboard-{self.state.icon}.svg"), self.state.title)
        self.indicator.set_label(str(self.state.unseen) if self.state.unseen else "", "99")
        self.status.set_label(self.state.title)
        if self.state.last_file:
            self.last.set_label(f"Zuletzt: {self.state.last_file} – {self.state.last_time}")
        self.error_item.set_label(" ".join(self.state.error.split())[:240])
        self.error_item.set_visible(bool(self.state.error))
        self.acknowledge_item.set_sensitive(self.state.unseen > 0)


def run_with_indicator(directory, writer, stopped, receive) -> int:
    panel = PanelIndicator(directory)
    updates = queue.SimpleQueue()
    result = [0]

    def notify(name, error=""):
        # GTK ausschließlich im Hauptthread bedienen.
        updates.put((name, error))

    def worker():
        try:
            receive(directory, writer, stopped, notify=notify)
        except Exception:
            LOG.exception("Empfänger wurde wegen eines Fehlers beendet.")
            result[0] = 1
        finally:
            stopped.set()

    def tick():
        while True:
            try:
                name, error = updates.get_nowait()
            except queue.Empty:
                break
            panel.incoming(name, error)
        if stopped.is_set():
            panel.Gtk.main_quit()
            return False
        return True

    thread = threading.Thread(target=worker, name="clipboard-receiver")
    thread.start()
    timer = panel.GLib.timeout_add(200, tick)
    LOG.info("Panel-Indikator gestartet.")
    try:
        panel.Gtk.main()
    finally:
        stopped.set()
        thread.join()
        # Der Timer kann sich beim regulären Stop bereits selbst entfernt haben.
        if panel.GLib.MainContext.default().find_source_by_id(timer):
            panel.GLib.source_remove(timer)
        panel.close()
    return result[0]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True,
                        help="Verfügbarkeit der Panel-Bibliotheken prüfen")
    parser.parse_args()
    try:
        load_gui()
    except SyncError as exc:
        parser.exit(1, f"{exc}\n")
    print("GTK/AppIndicator verfügbar.")
