# Zwischenablage auf eine Netzwerkfreigabe übertragen

Das Tool liest bei jedem Aufruf einmal die Zwischenablage, überträgt ihren Inhalt
auf die konfigurierte SMB-/Windows-Freigabe und beendet sich. Es verwendet das
installierte Python ab Version 3.8 und ausschließlich dessen Standardbibliothek.
Dieses Sendeskript führt keine automatische Überwachung aus. Der zusätzliche
Windows-Empfänger `get_clipboard_win.py` läuft dagegen im Hintergrund.

## Start unter Linux

```bash
/usr/bin/python3 /home/te/src/cliboard-sync-2/clipboard_sync.py
```

Benötigte Systemprogramme: `smbclient` sowie `xclip` für X11 oder `wl-paste`
aus dem Paket `wl-clipboard` für Wayland. Auf diesem Rechner sind alle drei
vorhanden. Falls sie auf einem anderen Debian-/Ubuntu-Rechner fehlen:

```bash
sudo apt install smbclient xclip wl-clipboard
```

Das Tool muss innerhalb der angemeldeten grafischen Sitzung laufen. Unter
Wayland wird `wl-paste` verwendet, auch wenn zusätzlich XWayland verfügbar ist.
Der Wayland-Compositor muss den Zwischenablagezugriff durch `wl-paste`
unterstützen. Bei Bedarf lässt sich die Auswahl ausdrücklich vorgeben:

```bash
python3 clipboard_sync.py --backend x11
python3 clipboard_sync.py --backend wayland
```

### Tastenkombination unter Linux

In den Tastatureinstellungen des Desktops eine eigene Tastenkombination
anlegen, beispielsweise **Strg+Alt+U**, und folgenden Befehl zuweisen:

```text
/usr/bin/python3 /home/te/src/cliboard-sync-2/clipboard_sync.py
```

Nach Verschieben des Projektordners den Pfad anpassen. Das Tool registriert
selbst keine globalen Tastenkombinationen. Die Zuweisung erfolgt über den
Desktop und funktioniert deshalb auch unter Wayland. Bei Fehlern den Befehl
im Terminal ausführen, um die Fehlermeldung zu sehen.

## Start unter Windows

Den Projektordner einschließlich `config.ini` auf den Windows-Rechner kopieren.
Installiertes Python 3 und Windows PowerShell genügen; keine `pip`-Pakete sind
nötig. `start_windows.cmd` verwendet zuerst `py -3`, andernfalls `python`.

```bat
start_windows.cmd
```

Die Freigabe `\\192.168.178.111\Austausch\Clipboard` muss mit den bereits
in Windows gespeicherten Anmeldedaten erreichbar sein. Python schreibt direkt
auf diesen UNC-Pfad. Die Werte dafür stammen aus `[windows]` in `config.ini`.

Für eine Tastenkombination eine **Verknüpfung** auf `start_windows.cmd` auf dem
Desktop erstellen. In deren Eigenschaften unter **Tastenkombination** etwa
**Strg+Alt+U** festlegen. Bei einem Fehler hält der Starter das Fenster offen.
Alternativ direkt `py -3 clipboard_sync.py` in einem Terminal ausführen.

### Einschränkung von Clip.exe

`clip.exe` kann ausschließlich Text **in** die Zwischenablage schreiben.
Es bietet keine Lesefunktion für Text oder Bilder. Deshalb kann die Vorgabe,
damit die Zwischenablage auszulesen, technisch nicht erfüllt werden. Siehe
[Microsoft: clip](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/clip).

Die Implementierung liest stattdessen mit der vorhandenen Windows PowerShell
und den .NET-Methoden
[Clipboard.GetText](https://learn.microsoft.com/en-us/dotnet/api/system.windows.forms.clipboard.gettext)
und [Clipboard.GetImage](https://learn.microsoft.com/en-us/dotnet/api/system.windows.forms.clipboard.getimage).
PowerShell wird im hierfür erforderlichen STA-Modus aufgerufen. Bilder werden
als PNG gespeichert, Text als UTF-8 ohne BOM.

## Konfiguration

Standardmäßig wird `config.ini` **neben dem Python-Skript** verwendet,
unabhängig vom Arbeitsverzeichnis der Verknüpfung. Eine andere Datei kann mit
`--config /pfad/config.ini` gewählt werden.

Die beiliegende `config.ini` enthält die angegebenen Linux-Anmeldedaten und die
Freigabe. `config.ini.example` dient als Vorlage ohne Passwort.

| Einstellung | Bedeutung |
| --- | --- |
| `share` | Freigabe, hier `//192.168.178.111/Austausch` |
| `remote_dir` | Vorhandener Unterordner auf der Freigabe, hier `Clipboard`; leer bedeutet Freigabewurzel |
| `username`, `password`, `domain` | Linux-Anmeldedaten; `domain` ist optional |
| `local_dir` | Linux-Arbeitsordner für temporäre Dateien; relativ zur INI-Datei oder absolut |
| `smbclient`, `xclip`, `wl_paste` | Linux-Programmnamen oder absolute Programmpfade |
| `timeout` | Zeitlimit in Sekunden je externem Programmaufruf, standardmäßig 30 |

`local_dir = ./Clipboard` legt den Arbeitsordner neben der INI-Datei an.
Für den Pfad aus dem ursprünglichen Beispiel kann stattdessen
`local_dir = /home/te/Clipboard` eingetragen werden. Jeder Aufruf verwendet
darin einen eigenen temporären Unterordner, der danach entfernt wird. Unter
Windows wird das temporäre Verzeichnis des angemeldeten Benutzers verwendet.
Das Windows-Zeitlimit gilt für PowerShell; die Dauer des Schreibens auf die
Freigabe wird von Windows bestimmt.

Die Linux-Übertragung verwendet `smbclient -m SMB3` und `put`. Das Passwort
wird über eine temporäre Authentifizierungsdatei mit Dateirechten `0600`
übergeben und erscheint nicht in den Prozessargumenten. Das entspricht der
[`smbclient`-Option `-A`](https://www.samba.org/samba/docs/current/man-html/smbclient.1).
`config.ini` ist ebenfalls auf `0600` gesetzt und in `.gitignore` eingetragen.
Nach eigenem Kopieren unter Linux gegebenenfalls `chmod 600 config.ini` ausführen.

## Dateien und Formate

- Text landet in **`clipboard_text`**, UTF-8 ohne BOM. Zeilenumbrüche und leere
  Textinhalte bleiben erhalten; es wird kein Zeilenumbruch angehängt.
- Bilder landen in **`clipboard_image`**, ohne Dateiendung. Unter Linux wird
  bevorzugt PNG ausgelesen; sonst ein anderes angebotenes Bildformat, etwa JPEG.
  Die Bytes werden unverändert übertragen. Unter Windows wird PNG erzeugt.
- Wenn Text und Bild angeboten werden, hat das Bild Vorrang. Mit `--type text`
  beziehungsweise `--type image` lässt sich die Auswahl erzwingen.
- Eine vorhandene Datei desselben Namens wird überschrieben. Die Datei des
  anderen Typs bleibt erhalten und kann daher von einer früheren Übertragung
  stammen. Die Kopie auf der Freigabe ist nicht atomar; bei einem Abbruch kann
  eine unvollständige Zieldatei zurückbleiben.
- Der Zielordner muss existieren. Dateilisten aus einem Dateimanager werden
  nicht als Bilddateien eingelesen; ein Bild muss als Bildinhalt kopiert werden.
- Erfolg liefert Exit-Code `0`, Übertragungs-/Konfigurationsfehler `1` und
  ungültige Kommandozeilenargumente `2`. Ausgabe und Fehlermeldungen erscheinen
  im Terminal. Das Tool verändert die lokale Zwischenablage nicht.

Das Sendeskript überträgt Dateien. Zum automatischen Übernehmen auf einem
Windows-Zielrechner dient der folgende Empfänger.

## Windows-Empfänger mit Systray

`get_clipboard_win.py` überwacht `clipboard_text` und `clipboard_image` im
Ordner `\\192.168.178.111\Austausch\Clipboard`. Es benötigt Python ab 3.8 und
die in Windows enthaltene Windows PowerShell mit Windows Forms; zusätzliche
Python-Pakete sind nicht erforderlich.

Per Doppelklick auf **`start_get_clipboard_win.cmd`** starten. Der Starter ruft
`pyw -3` beziehungsweise `pythonw` auf; nach dem Start bleibt kein Terminalfenster
offen. Alternativ:

```bat
pythonw.exe get_clipboard_win.py
```

Der Empfänger läuft in der angemeldeten Windows-Sitzung. Die Freigabe muss mit
den in Windows gespeicherten Anmeldedaten erreichbar sein; bei Bedarf vorher
im Explorer öffnen. Die Linux-Zugangsdaten aus der INI werden nicht verwendet.
Für den Autostart eine Verknüpfung auf den Starter im Ordner `shell:startup`
anlegen (über **Win+R** öffnen).

- Eigene Klemmbrett-Symbole zeigen den Zustand: **blau mit Empfangspfeil** bedeutet
  Bereitschaft, **grün mit Textzeilen** neuen Text, **violett mit Landschaft** ein
  neues Bild und **orange mit Ausrufezeichen** einen Fehler. Die Symbole werden
  direkt im Skript gezeichnet; zusätzliche Icon-Dateien sind nicht erforderlich.
  Nach einem Empfang erscheint außerdem eine Windows-Benachrichtigung. Der
  Tooltip enthält Typ und Uhrzeit des letzten Empfangs. Windows kann das Symbol
  im ausgeklappten Bereich des Systrays verbergen und Benachrichtigungen je nach
  Systemeinstellung unterdrücken.
- Linksklick oder **Hinweis quittieren** im Rechtsklickmenü setzt das Symbol
  zurück. **Beenden** beendet den Empfänger. Die Zwischenablage bleibt erhalten.
- Ein Warnsymbol signalisiert Zugriffs- oder Verarbeitungsfehler. Nach einem
  Netzwerkausfall versucht der Empfänger den Zugriff weiter. Das Tray bleibt
  während der Netzwerkzugriffe bedienbar.
- Bereits vorhandene Dateien werden beim ersten erfolgreichen Ordnerzugriff
  als Ausgangsstand erfasst. Erst spätere Änderungen oder neue Dateien werden
  übernommen. Mit `load_existing = yes` werden auch vorhandene Inhalte geladen.
- Text wird als UTF-8 (auch mit BOM) eingelesen, einschließlich leerem Text und
  vorhandener Zeilenumbrüche. Bilddateien werden anhand ihres Inhalts dekodiert,
  unabhängig von einer Dateiendung. Unterstützt werden die Windows-GDI+-Formate
  wie PNG, JPEG, BMP, GIF und TIFF; bei GIF/TIFF wird ein einzelnes Bild übernommen.
  WebP wird von diesem Backend nicht unterstützt. Ungültige Bilder und ungültiger
  UTF-8-Text werden abgewiesen, bevor die Zwischenablage beschrieben wird.
- Ändern sich beide Dateien innerhalb eines Prüfzyklus, werden die stabilen
  Dateien nach Änderungszeit übernommen, die neuere zuletzt. Die Zwischenablage
  enthält anschließend den zuletzt erfolgreich übernommenen Typ. Der Empfänger
  schreibt nichts auf die Freigabe zurück.
- Pro Eingangsordner läuft höchstens ein Empfänger in derselben Windows-Sitzung.

Die vorhandenen Werte `share` und `remote_dir` aus `[windows]` legen den
Eingangsordner fest. Zusätzliche Einstellungen in `config.ini`:

```ini
[receiver]
; Leer: share und remote_dir aus [windows] verwenden.
directory =
poll_interval = 0.5
settle_time = 1.0
load_existing = no
```

`directory` kann alternativ einen vollständigen UNC-Pfad oder einen lokalen
Testordner enthalten. Relative Pfade beziehen sich auf die INI-Datei.
`poll_interval` ist der Prüfzyklus in Sekunden; `settle_time` die erforderliche
Ruhezeit nach einer erkannten Änderung. Beide müssen positiv sein. Standardmäßig
werden Inhalte ungefähr 1–2 Sekunden nach Abschluss einer Änderung übernommen.
`--config "C:\Pfad\config.ini"` wählt eine andere Konfiguration.

Die Überwachung vergleicht Dateimetadaten und prüft diese zusätzlich vor und
nach dem Lesen. Da das Sendeskript Dateien direkt überschreibt, ist die Ruhezeit
eine Heuristik: Eine längere Schreibpause kann wie eine fertige Übertragung
aussehen. Bei langsamen Übertragungen `settle_time` erhöhen. Mehrere Änderungen
zwischen zwei Prüfungen können zusammenfallen; bei identischen Metadaten kann
eine Änderung unbemerkt bleiben. Vollständig atomare Übertragungen würden eine
entsprechende Anpassung des Senders erfordern.

Das Protokoll steht unter
`%LOCALAPPDATA%\ClipboardReceiver\get_clipboard_win.log` (mit Größenbegrenzung
und zwei Sicherungen). Es enthält Status und Fehler, keine Clipboard-Inhalte.
Für die Fehlersuche lässt sich `python get_clipboard_win.py` im Terminal starten.
Die lokale Zwischenablage wird über
[`Clipboard.SetDataObject`](https://learn.microsoft.com/en-us/dotnet/api/system.windows.forms.clipboard.setdataobject)
im STA-Modus geschrieben; die persistente Kopie bleibt nach dem Beenden erhalten.

