# Clipboard Sync
Synchronising the clipboard between two PCs on a local network (text and image) 

`clipboard_sync.py` überträgt unter Linux die aktuelle Zwischenablage per
SFTP auf einen anderen Rechner. Starten, übertragen, beenden: Der Sender läuft
nur bei Bedarf. Der zusätzliche Empfänger `get_clipboard.py` überwacht auf dem
Zielrechner den Eingangsordner und übernimmt eingehende Dateien automatisch in
die lokale Zwischenablage.

- Text wird als UTF-8 in **`clipboard_text`** gespeichert.
- Bilder werden unverändert in **`clipboard_image`** gespeichert, bevorzugt als
  PNG, sofern die Quellanwendung PNG anbietet. Auch JPEG und andere angebotene
  Bildformate sind möglich. Der Dateiname hat **keine Erweiterung**.
- Bei mehreren angebotenen Formaten hat ein Bild Vorrang. `--type text` bzw.
  `--type image` erzwingt die Auswahl.
- Eine bestehende Datei desselben Namens wird überschrieben. Die Datei des
  anderen Typs bleibt bestehen. Bei einer unterbrochenen Übertragung kann die
  Zieldatei unvollständig sein.
- X11 nutzt `xclip`, Wayland nutzt `wl-paste`. Die Sitzung wird automatisch
  erkannt. Unter Wayland muss der Compositor den Zugriff durch `wl-paste`
  unterstützen. Es erfolgt kein stiller Wechsel auf die XWayland-Zwischenablage.

## Einrichtung

### Herunterladen und kopieren
Kopieren Sie alle Dateien dieses Projekts beispielsweise in den Ordner ~/Scripts/clipboard-sync" in Ihrem Homeverzeichnis.

Wenn git installiert ist (`sudo apt install git`), verwenden Sie

```bash
mkdir ~/Scripts
git clone https://github.com/Myria-de/clipboard-sync.git
```
Andernfalls laden Sie das Projekt als unter "Releases" herunter.

Nach der Ersteinrichtung müssen die Dateien hier verbleiben.

### Voraussetzungen prüfen und fehlende Pakete installieren

Als normaler Desktop-Benutzer in einem Terminal starten:

```bash
./check_requirements.sh
```

Das Skript prüft auf Ubuntu und Linux Mint standardmäßig beide Tools einschließlich
X11, Wayland, Panel-Indikator und systemd. Es prüft System-Python ab Version 3.10,
die tatsächlich importierbaren Python-Module, GTK/GLib, Ayatana AppIndicator bzw.
die ältere AppIndicator-Bibliothek, `xclip`, `wl-copy`/`wl-paste`, `file` und OpenSSH.
Auf einem Empfangsrechner (PC-B) wird auch `openssh-server` für eingehende SFTP-Transfers
benötigt. Abhängig vom Desktop wird vorhandene Panel-Unterstützung erkannt oder
ein passendes Systempaket vorgeschlagen.

Fehlende Pakete werden gesammelt und mit den Installationsbefehlen angezeigt.
Nach ausdrücklicher Bestätigung führt das Skript `sudo apt-get update` und
`sudo apt-get install ...` aus; anschließend wiederholt es die Prüfung. Bei
Ablehnung, leerer Antwort oder fehlendem interaktiven Terminal erfolgt keine
Installation. Die Installation von `openssh-server` kann den SSH-Server starten;
darauf weist das Skript vor der Bestätigung hin. Es verändert weder die
Zwischenablage noch die SFTP-Konfiguration oder Desktop-Einstellungen.

```bash
./check_requirements.sh --check-only
./check_requirements.sh --role sender --backend auto
./check_requirements.sh --role receiver --directory "$HOME/Clipboard"
./check_requirements.sh --role receiver --no-indicator --backend x11
./check_requirements.sh --help
```

`--role` akzeptiert `both`, `sender` und `receiver`; `--backend` akzeptiert `both`,
`auto`, `x11` und `wayland`. Standard ist jeweils `both`, damit auch der Wechsel
zwischen X11 und Wayland vorbereitet ist. `--no-indicator` lässt GUI- und
Panel-Voraussetzungen aus. `--check-only` führt ausschließlich Prüfungen aus und
zeigt gegebenenfalls Installationsbefehle an, ohne nach einer Installation zu fragen.

Neben Paketen prüft das Skript Displayzugriff, systemd-Benutzermanager, aktiven
Panel-Host, SSH-Dienst und die Rechte des Eingangsordners. Nicht aktive Panel-Applets,
eine fehlende grafische Sitzung oder eine noch ausstehende Dienstinstallation
werden mit Handlungshinweisen gemeldet. Diese Schritte erledigt das Skript nicht
automatisch. SSH-Anmeldung, Hostschlüssel, Firewall, SFTP-Subsystem und Zugriffsrechte
auf dem anderen Rechner müssen separat geprüft werden; es baut keine Verbindung
zum Ziel auf. Ein vorhandenes `config.ini` wird lediglich erkannt, nicht ausgewertet.

Exitcodes: `0` = geprüfte Pakete/Module vorhanden (Sitzungs-/Konfigurationshinweise
beachten), `1` = fehlende/defekte Voraussetzung oder Installationsfehler,
`2` = ungültiger Aufruf bzw. nicht unterstütztes Betriebssystem. Eine zu alte
System-Python-Version wird gemeldet; das Skript ersetzt sie nicht durch ein PPA.

### Manuelle Einrichtung

PC-A und PC-B: System-Python unter `/usr/bin/python3` (**3.10 oder neuer**), OpenSSH-Client und das zur Sitzung passende
Zwischenablageprogramm müssen installiert sein. Für Debian/Ubuntu:

```bash
sudo apt install python3 openssh-client xclip wl-clipboard file
./setup.sh
```

`setup.sh` prüft die Version des System-Python und meldet fehlende Hilfsprogramme.
Sender und Empfänger ohne Panel verwenden ausschließlich Python-Standardbibliotheken.
Der optionale Panel-Indikator benötigt GTK/AppIndicator aus den Systempaketen (siehe
unten). Alle Tools laufen direkt mit `/usr/bin/python3`; pip und eine virtuelle
Python-Umgebung sind nicht nötig.

Auf dem Zielrechner (PC-B) muss ein SSH-Server mit aktiviertem SFTP erreichbar sein.
Für einen Linux-Zielrechner mit Debian/Ubuntu kann dafür `openssh-server`
installiert werden. Den gewünschten Zielordner dort anlegen, beispielsweise
`mkdir -p ~/Clipboard`.

Die Anmeldung verwendet SSH-Schlüssel oder den SSH-Agenten sowie die Einstellungen
aus `~/.ssh/config`. Einmalig die SSH-Verbindung zum Ziel einrichten (siehe auch https://devwelt.de/myria-de/heimserver/-/wikis/Fernzugriff-%C3%BCber-SSH):

```bash
# Falls noch kein geeigneter Schlüssel vorhanden ist:
ssh-keygen -t ed25519
# Eigenen Benutzer und Zielrechner einsetzen:
ssh-copy-id benutzer@192.168.1.50
ssh benutzer@192.168.1.50
```

Beim ersten Verbindungsaufbau den Host-Fingerabdruck mit dem Zielrechner abgleichen
und bestätigen. Das Tool akzeptiert ausschließlich bereits bekannte Hostschlüssel.
Bei einem verschlüsselten privaten Schlüssel diesen vor dem Aufruf mit
`ssh-add ~/.ssh/id_ed25519` in einen laufenden SSH-Agenten laden.
Das Tool fragt selbst kein SSH-Passwort ab; dadurch ist der Start per Tastenkürzel
ohne Terminal möglich.

```bash
cp config.example.ini config.ini
```

In `config.ini` mindestens `host`, `user` und `remote_dir` anpassen. Der Zielordner
muss existieren und beschreibbar sein. Relative Pfade beziehen sich auf das
SFTP-Startverzeichnis, normalerweise das Home-Verzeichnis des Zielbenutzers.
`~` und Umgebungsvariablen werden in Zielpfaden nicht expandiert.
SSH-Aliase sind bei `host` erlaubt; `user`, `port` und `identity` können dann
entfallen und aus der SSH-Konfiguration stammen.

## Aufruf

Text oder ein Bild kopieren, anschließend in derselben grafischen Sitzung:

```bash
./run.sh
```

Alternativ ohne Konfigurationsdatei:

```bash
./run.sh --host 192.168.1.50 --user benutzer --remote-dir /home/benutzer/Clipboard
```

Weitere Beispiele:

```bash
./run.sh --type text
./run.sh --type image --backend wayland
./run.sh --backend x11
./run.sh --config /pfad/zur/config.ini
./run.sh --port 2222 --identity ~/.ssh/id_ed25519
./run.sh --help
```

Kommandozeilenoptionen überschreiben die Konfiguration. `run.sh` verwendet immer
`/usr/bin/python3` und findet das Tool sowie die Standardkonfiguration auch
bei einem Aufruf aus einem anderen Verzeichnis. Sein absoluter Pfad lässt sich
in den Desktop-Einstellungen als Tastenkürzel hinterlegen:

```text
/home/[Benutzer]/src/clipboard-sync/run.sh
```

Das Tool liest die normale Zwischenablage (Strg+C), nicht die X11-Primärauswahl.
Ein Bild muss als Bild kopiert werden, etwa über „Bild kopieren“ im Browser.
Eine im Dateimanager kopierte Bilddatei ist meist nur eine Dateiliste und wird
nicht als Bildinhalt übertragen. Leere und nicht unterstützte Inhalte erzeugen
eine Fehlermeldung. Es wird nur eine Darstellung der Zwischenablage übertragen.

Erfolg wird mit Zielpfad und Bytezahl gemeldet, Fehler über die Standardfehlerausgabe.
Exitcodes: `0` Erfolg, `1` Laufzeitfehler, `2` ungültige Kommandozeile,
`130` Benutzerabbruch. Temporäre lokale Dateien werden nach dem Aufruf entfernt.

## Empfang mit get_clipboard.py

Den Projektordner auf dem **Empfangsrechner** (PC-B) ablegen und dort `./setup.sh`
ausführen, um die Voraussetzungen zu prüfen.
Der Empfänger (PC-B) benötigt `xclip` für X11 bzw. `wl-copy` aus `wl-clipboard` für
Wayland sowie das Programm `file` zur Erkennung von Bildformaten.

Manueller Start in einem Terminal der grafischen Sitzung:

```bash
/usr/bin/python3 get_clipboard.py --indicator
# Anderer Eingangsordner oder explizite Sitzung:
/usr/bin/python3 get_clipboard.py --directory /home/[Benutzer]/Clipboard --backend wayland --indicator
```

Standard ist `~/Clipboard`, also `/home/[Benutzer]/Clipboard` mit dem tatsächlichen
Benutzernamen. Ein fehlender Ordner wird
angelegt. Beim Sender muss `remote_dir` auf genau diesen Ordner des Empfängers
zeigen.

Der Empfänger (PC-B) reagiert ausschließlich auf `clipboard_text` und `clipboard_image`.
Er nutzt Linux-inotify und wartet auf `CLOSE_WRITE` (Ende eines Schreibzugriffs)
oder `MOVED_TO` (eine Datei wird unter dem erwarteten Namen in den Ordner
verschoben). Pausen bei einem noch offenen SFTP-Upload lösen keine Übernahme aus.
Eine abgebrochene SFTP-Verbindung kann allerdings ebenfalls eine unvollständige
Datei schließen: Der Empfänger kann den erfolgreichen Abschluss einer Übertragung
allein anhand dieser Dateien nicht garantieren. Dann die Datei erneut senden.
Der Ordner sollte auf einem lokalen Linux-Dateisystem liegen; Änderungen durch
andere Rechner an einem Netzwerkdateisystem liefern nicht zuverlässig inotify-Ereignisse.

Text wird als UTF-8 und Bilder werden mit dem anhand des Inhalts erkannten MIME-Typ
übernommen. Bytes und abschließende Zeilenumbrüche bleiben erhalten. Eine leere
Textdatei setzt einen leeren Text; leere oder nicht als Bild erkannte Bilddateien
werden abgewiesen. Die letzte bearbeitete Datei bestimmt die Zwischenablage.
Der Empfänger verändert die empfangenen Dateien nicht.

Bereits beim Start vorhandene Dateien werden **nicht** übernommen. Dadurch
überschreibt ein Dienstneustart die Zwischenablage nicht mit alten Daten. Änderungen
während der Dienst gestoppt war müssen erneut gesendet werden. Fehler werden
protokolliert; anschließend wartet der Empfänger auf die nächste Änderung.

### systemd-Benutzerdienst installieren

Für den Panel-Indikator auf Ubuntu und Linux Mint zunächst die Systempakete
installieren, sofern sie fehlen:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
```

Alternativ unterstützt das Tool die ältere Bibliothek `gir1.2-appindicator3-0.1`.
`/usr/bin/python3 clipboard_indicator.py --check` prüft die Bibliotheken.

Auf dem Empfangsrechner (PC-B) **als Desktop-Benutzer, ohne sudo**, in einem Terminal
der angemeldeten grafischen Sitzung ausführen:

```bash
./install_get_clipboard.sh
```

Das Installationsskript erzeugt `~/.config/systemd/user/get-clipboard.service`
(bzw. unter `$XDG_CONFIG_HOME`), übernimmt die aktuellen Sitzungsvariablen in
den systemd-Benutzermanager und aktiviert/startet den Dienst. Der Dienst nutzt
`/usr/bin/python3`, überwacht `%h/Clipboard` und aktiviert mit `--indicator` die
Panel-Anzeige. Das Installationsskript prüft vorher die benötigten Bibliotheken.
Der Projektordner muss deshalb an seinem Ort bleiben. Erneutes Ausführen des
Installationsskripts aktualisiert die Unit und startet den Dienst neu.

Der Dienst wird mit `graphical-session.target` bei der grafischen Anmeldung
gestartet und bei der Abmeldung beendet. Das funktioniert auf Desktops, die ihre
Sitzung mit diesem systemd-Target integrieren und die Display-Umgebung importieren,
beispielsweise GNOME. Auf anderen Desktops das Installationsskript einmal bei der
Anmeldung über deren Autostart aufrufen. Für Wayland muss der Compositor zusätzlich
den Clipboard-Zugriff durch `wl-copy` unterstützen. Es gibt keinen automatischen
Wechsel zur XWayland-Zwischenablage.

```bash
systemctl --user status get-clipboard.service
journalctl --user -u get-clipboard.service -f
systemctl --user restart get-clipboard.service
systemctl --user stop get-clipboard.service
# Autostart abschalten und Dienst stoppen:
systemctl --user disable --now get-clipboard.service
```

Ein anderer Ordner lässt sich mit `systemctl --user edit get-clipboard.service`
dauerhaft einstellen. Beispiel für diesen Projektpfad:

```ini
[Service]
ExecStart=
ExecStart=/usr/bin/python3 /home/te/src/clipboard-sync/get_clipboard.py --directory /home/Benutzer/Clipboard --indicator
```

Danach `systemctl --user daemon-reload` und
`systemctl --user restart get-clipboard.service` ausführen. Bei fehlendem
Display-Zugriff das Installationsskript erneut **aus der aktuellen Desktop-Sitzung**
starten, damit insbesondere `DISPLAY`, `WAYLAND_DISPLAY` und `XAUTHORITY` stimmen.
Ein Systemdienst als root und ein Start vor der grafischen Anmeldung sind für
den Zugriff auf die Benutzerzwischenablage ungeeignet.

### Panel-Anzeige unter Ubuntu und Linux Mint

Der Indikator zeigt eine kleine Zwischenablage im Panel:

| Symbol | Bedeutung |
| --- | --- |
| Grau mit Linien | Keine neuen, unbestätigten Eingänge seit dem Start |
| Grün mit Pluszeichen | Neue Daten wurden in die Zwischenablage übernommen |
| Rot mit Ausrufezeichen | Die zuletzt eingegangene Datei konnte nicht übernommen werden |

Eine Zahl neben dem Symbol zeigt, soweit das Panel Beschriftungen unterstützt,
die Anzahl der noch nicht bestätigten Eingangsereignisse. Im Menü stehen der
Zähler, Dateiname und Zeitpunkt des letzten Eingangs sowie der überwachte Ordner.
Es werden keine Clipboard-Inhalte im Menü angezeigt.

Mit **„Als gesehen markieren“** wird der Zähler zurückgesetzt. Das verändert
weder die Zwischenablage noch die Dateien. Ein Fehler bleibt rot sichtbar, bis
ein weiterer Eingang erfolgreich übernommen wurde. Beim Dienstneustart werden
Zähler und Markierung zurückgesetzt. Ein Einfügen in eine andere Anwendung setzt
die Markierung nicht automatisch zurück.

Die Panel-Anzeige nutzt die gleichen Abschlussereignisse wie der Empfänger;
laufende Uploads und fremde Dateinamen werden nicht als neue Eingänge gezählt.
Der Indikator ist Bestandteil des Empfängerprozesses und benötigt keinen zweiten
Überwachungsdienst. Ohne `--indicator` läuft der Empfänger weiterhin ohne GUI.
Bei einem bereits gestarteten Dienst keinen zweiten Empfänger manuell starten.

- **Ubuntu/GNOME:** Die Erweiterung „Ubuntu AppIndicators“ bzw. „AppIndicator and
  KStatusNotifierItem Support“ muss aktiviert sein. Bei Bedarf das Paket
  `gnome-shell-extension-appindicator` installieren und die Erweiterung über die
  Erweiterungen-Anwendung aktivieren; gegebenenfalls ab- und wieder anmelden.
- **Linux Mint:** Im verwendeten Desktop muss das Panel-Applet für Statussymbole
  bzw. das Benachrichtigungsfeld aktiviert sein (bei Cinnamon üblicherweise
  „XApp-Status-Applet“). Bei MATE/Xfce muss entsprechend ein StatusNotifier- bzw.
  AppIndicator-fähiges Panel-Applet vorhanden sein.

Eine laufende Empfangsüberwachung allein garantiert kein sichtbares Symbol, wenn
im Desktop das passende Panel-Applet deaktiviert ist. Bibliotheks- oder
Displayfehler stehen in `journalctl --user -u get-clipboard.service`.

Technische Referenzen: [OpenSSH-SFTP-Handbuch](https://man.openbsd.org/sftp),
[wl-clipboard](https://github.com/bugaevc/wl-clipboard),
[Linux-inotify](https://man7.org/linux/man-pages/man7/inotify.7.html),
[Ayatana AppIndicator](https://github.com/AyatanaIndicators/libayatana-appindicator),
[Ubuntu AppIndicator-Erweiterung](https://github.com/ubuntu/gnome-shell-extension-appindicator).
