#!/usr/bin/env bash
# Prüft Systempakete und Sitzung, ohne die Zwischenablage zu lesen oder zu ändern.
set -euo pipefail

usage() {
    cat <<'EOF'
Verwendung: ./check_requirements.sh [Optionen]

  --role both|sender|receiver  Zu prüfende Rolle (Standard: both)
  --backend both|auto|x11|wayland
                              Clipboard-Unterstützung (Standard: both)
  --no-indicator              Empfänger ohne Panel prüfen
  --directory PFAD           Eingangsordner (Standard: ~/Clipboard)
  --check-only               Nur prüfen; niemals Installation anbieten/ausführen
  -h, --help                 Diese Hilfe anzeigen

Ohne --check-only wird die Installation fehlender Pakete angeboten. Sie erfolgt
nur nach ausdrücklicher Bestätigung, über apt-get und gegebenenfalls sudo.
Als normaler Desktop-Benutzer in einem Terminal starten, nicht mit sudo.
Exitcodes: 0 = Pakete/Module vorhanden (Hinweise beachten), 1 = Voraussetzungen
fehlen oder Installation fehlgeschlagen, 2 = ungültiger Aufruf/nicht unterstütztes OS.
EOF
}

ok() { printf '[OK] %s\n' "$*"; }
note() { printf '[HINWEIS] %s\n' "$*"; warnings=$((warnings + 1)); }
problem() { printf '[FEHLT] %s\n' "$*"; failures=$((failures + 1)); }
has_command() { command -v "$1" >/dev/null 2>&1; }

reset_results() {
    missing_packages=()
    failures=0
    warnings=0
}

add_package() {
    local existing
    for existing in "${missing_packages[@]}"; do
        [[ "$existing" != "$1" ]] || return 0
    done
    missing_packages+=("$1")
}

need_command() {
    if has_command "$1"; then
        ok "$1"
    else
        problem "$1 – Paket: $2"
        add_package "$2"
    fi
}

installed() {
    [[ "$(dpkg-query -W -f='${Status}' "$1" 2>/dev/null || true)" == 'install ok installed' ]]
}

need_package() {
    if installed "$1"; then
        ok "Paket $1"
    else
        problem "Paket $1"
        add_package "$1"
    fi
}

python_probe() { timeout 10 /usr/bin/python3 -I -c "$1" >/dev/null 2>&1; }

panel_host_active() {
    local status=''
    if has_command gdbus; then
        status=$(timeout 5 gdbus call --session --dest org.kde.StatusNotifierWatcher \
            --object-path /StatusNotifierWatcher --method org.freedesktop.DBus.Properties.Get \
            org.kde.StatusNotifierWatcher IsStatusNotifierHostRegistered 2>/dev/null || true)
    fi
    [[ "$status" == *true* ]]
}

check_python() {
    if [[ ! -x /usr/bin/python3 ]]; then
        problem 'System-Python /usr/bin/python3 fehlt.'
        add_package python3
    elif ! python_probe 'import sys; sys.exit(sys.version_info < (3, 10))'; then
        problem 'Python 3.10 oder neuer erforderlich. Die Systemversion ist zu alt oder defekt.'
        note 'Eine unterstützte Ubuntu-/Mint-Version mit Python >= 3.10 verwenden. Kein PPA und kein Austausch von /usr/bin/python3 erfolgt automatisch.'
    else
        ok "$(/usr/bin/python3 --version) unter /usr/bin/python3"
        if python_probe 'import argparse, configparser, ctypes, dataclasses, datetime, importlib, logging, os, pathlib, posixpath, queue, re, select, shutil, signal, stat, struct, subprocess, sys, tempfile, threading'; then
            ok 'Benötigte Python-Standardbibliotheken einschließlich ctypes/inotify-Anbindung'
        else
            problem 'Python-Standardbibliothek unvollständig oder defekt.'
            add_package python3
            add_package libpython3-stdlib
        fi
    fi

    if [[ "$role" != sender && "$indicator" == true ]]; then
        if python_probe 'import gi'; then
            ok 'Python-Modul gi (PyGObject)'
        else
            problem 'Python-Modul gi fehlt oder ist nicht importierbar.'
            add_package python3-gi
        fi
        if python_probe 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk, GLib'; then
            ok 'GTK 3 und GLib'
        else
            problem 'GTK-3-/GLib-Python-Anbindung fehlt oder ist nicht importierbar.'
            add_package gir1.2-gtk-3.0
        fi
        if python_probe 'import gi; gi.require_version("AyatanaAppIndicator3", "0.1"); from gi.repository import AyatanaAppIndicator3'; then
            ok 'Ayatana AppIndicator'
        elif python_probe 'import gi; gi.require_version("AppIndicator3", "0.1"); from gi.repository import AppIndicator3'; then
            ok 'AppIndicator (kompatible ältere Bibliothek)'
        else
            problem 'AppIndicator-Python-Anbindung fehlt oder ist nicht importierbar.'
            add_package gir1.2-ayatanaappindicator3-0.1
        fi
    fi
}

check_tools() {
    if [[ "$role" != receiver ]]; then
        need_command sftp openssh-client
        need_command ssh openssh-client
    fi
    if [[ "$backend" == both || "$backend" == x11 ]]; then
        need_command xclip xclip
    fi
    if [[ "$backend" == both || "$backend" == wayland ]]; then
        if [[ "$role" != receiver ]]; then need_command wl-paste wl-clipboard; fi
        if [[ "$role" != sender ]]; then need_command wl-copy wl-clipboard; fi
    fi
    if [[ "$role" != sender ]]; then
        need_command file file
        need_command systemctl systemd
        need_command journalctl systemd
        need_package dbus-user-session
        need_package openssh-server
        if [[ "$indicator" == true ]]; then
            need_command gdbus libglib2.0-bin
            if panel_host_active; then
                ok 'Panel-Unterstützung bereits aktiv; kein zusätzliches Panel-Paket nötig'
            else
                case "$desktop" in
                    *gnome*|*unity*) need_package gnome-shell-extension-appindicator ;;
                    *cinnamon*) need_package xapp-sn-watcher ;;
                    *mate*)
                        if installed xapp-sn-watcher; then ok 'XApp-StatusNotifier-Unterstützung vorhanden';
                        else need_package mate-indicator-applet; fi ;;
                    *xfce*) need_package xfce4-panel ;;
                    *) note 'Desktop nicht eindeutig erkannt; ein AppIndicator-/StatusNotifier-fähiges Panel muss vorhanden sein.' ;;
                esac
            fi
        fi
    fi
}

check_session() {
    if [[ -n "${WAYLAND_DISPLAY:-}" || -n "${DISPLAY:-}" ]]; then
        ok "Grafische Sitzungsvariablen vorhanden (${XDG_SESSION_TYPE:-unbekannt}, ${XDG_CURRENT_DESKTOP:-unbekannt})"
    else
        note 'Keine grafische Sitzung erkannt. Tools und Dienstinstallation in einem Desktop-Terminal starten.'
    fi
    if [[ "$role" != sender ]]; then
        if has_command systemctl; then
            if timeout 5 systemctl --user show-environment >/dev/null 2>&1; then
                ok 'systemd-Benutzermanager erreichbar'
                if ! timeout 5 systemctl --user is-active --quiet graphical-session.target 2>/dev/null; then
                    note 'graphical-session.target nicht aktiv. Auf diesem Desktop install_get_clipboard.sh beim Anmelden über den Desktop-Autostart ausführen.'
                fi
                if timeout 5 systemctl --user is-active --quiet get-clipboard.service 2>/dev/null; then
                    ok 'get-clipboard.service läuft'
                else
                    note 'Empfängerdienst noch nicht aktiv. Nach der Einrichtung ./install_get_clipboard.sh ausführen.'
                fi
            else
                note 'systemd-Benutzermanager nicht erreichbar; als angemeldeter Desktop-Benutzer außerhalb einer Sandbox prüfen.'
            fi
            if installed openssh-server; then
                if timeout 5 systemctl is-active --quiet ssh.service 2>/dev/null || timeout 5 systemctl is-active --quiet ssh.socket 2>/dev/null; then
                    ok 'SSH-Dienst oder SSH-Socket aktiv'
                else
                    note 'SSH-Server nicht als aktiv erkannt. Auf dem Empfangsrechner prüfen: systemctl status ssh.service ssh.socket. Bei Bedarf: sudo systemctl enable --now ssh.service'
                fi
            fi
        fi
        if [[ -d "$directory" && -r "$directory" && -w "$directory" && -x "$directory" ]]; then
            ok "Eingangsordner zugänglich: $directory"
        elif [[ -e "$directory" ]]; then
            problem "Eingangspfad ist kein zugänglicher, beschreibbarer Ordner: $directory"
        else
            note "Eingangsordner fehlt: $directory – wird bei Installation/Start des Empfängers angelegt; der Benutzer benötigt Schreibrechte im übergeordneten Ordner."
        fi
        if [[ "$indicator" == true ]]; then
            if python_probe 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk; import sys; sys.exit(not Gtk.init_check([])[0])'; then
                ok 'GTK kann die grafische Sitzung öffnen'
            else
                note 'GTK-Displayzugriff fehlt. Nach Paketinstallation DISPLAY/WAYLAND_DISPLAY und XAUTHORITY in der Desktop-Sitzung prüfen.'
            fi
            if panel_host_active; then
                ok 'Aktiver StatusNotifier-/AppIndicator-Panel-Host erreichbar'
            else
                case "$desktop" in
                    *gnome*|*unity*) note 'Panel-Host nicht erreichbar. In „Erweiterungen“ Ubuntu AppIndicators/AppIndicator Support aktivieren, gegebenenfalls ab- und anmelden.' ;;
                    *cinnamon*) note 'Panel-Host nicht erreichbar. In den Cinnamon-Applets das XApp-Status-Applet aktivieren, gegebenenfalls ab- und anmelden.' ;;
                    *mate*) note 'Panel-Host nicht erreichbar. Das Indicator-/StatusNotifier-Applet zum Panel hinzufügen.' ;;
                    *xfce*) note 'Panel-Host nicht erreichbar. Das Panel-Element „Status Tray Plugin“ mit StatusNotifier-Unterstützung hinzufügen/aktivieren (ab Xfce 4.15 integriert).' ;;
                    *) note 'Kein Panel-Host erreichbar. StatusNotifier-/AppIndicator-Unterstützung im Desktop aktivieren.' ;;
                esac
            fi
        fi
    fi
    if [[ "$role" != receiver ]]; then
        if [[ -f "$project_dir/config.ini" ]]; then
            ok 'config.ini vorhanden (Zielangaben und SSH-Anmeldung separat prüfen)'
        else
            note 'SFTP-Ziel noch konfigurieren: config.example.ini nach config.ini kopieren und anpassen oder --host/--user/--remote-dir beim Sender angeben.'
        fi
        note 'SSH-Schlüssel/Agent, bekannter Hostschlüssel, Netzwerkzugang und Schreibrechte am Ziel separat prüfen. Es wird keine Verbindung zum Ziel aufgebaut.'
    fi
}

check_all() {
    reset_results
    printf '\nPrüfung: %s | Rolle: %s | Backend: %s\n' "$os_name" "$role" "$backend"
    check_python
    check_tools
    check_session
    printf '\nErgebnis: %d fehlende/defekte Voraussetzungen, %d Hinweise.\n' "$failures" "$warnings"
}

confirm_install() {
    local answer
    if [[ ! -t 0 ]]; then
        printf '%s\n' 'Keine interaktive Eingabe: Es wird nichts installiert. Für ein Installationsangebot in einem Terminal ohne --check-only starten.'
        return 1
    fi
    read -r -p 'Die aufgeführten Pakete jetzt installieren? [j/N] ' answer || return 1
    case "${answer,,}" in j|ja|y|yes) return 0 ;; *) return 1 ;; esac
}

install_missing() {
    [[ ${#missing_packages[@]} -gt 0 ]] || return 1
    printf '\nFehlende Pakete:'
    printf ' %s' "${missing_packages[@]}"
    printf '\nInstallationsbefehle (erst nach Bestätigung):\n  sudo apt-get update\n  sudo apt-get install'
    printf ' %q' "${missing_packages[@]}"
    printf '\n'
    if [[ "$role" != sender ]]; then
        local package
        for package in "${missing_packages[@]}"; do
            if [[ "$package" == openssh-server ]]; then
                printf '%s\n' 'Hinweis: openssh-server ermöglicht eingehende SSH/SFTP-Verbindungen und wird bei der Paketinstallation üblicherweise gestartet.'
            fi
        done
    fi
    [[ "$check_only" == false ]] || return 1
    confirm_install || { printf '%s\n' 'Keine Installation durchgeführt.'; return 1; }
    local -a elevate=()
    if (( EUID != 0 )); then
        if ! has_command sudo; then
            printf '%s\n' 'sudo fehlt. Die oben gezeigten apt-get-Befehle durch einen Administrator ausführen.' >&2
            return 1
        fi
        elevate=(sudo)
    fi
    if ! "${elevate[@]}" apt-get update; then
        printf '%s\n' 'Paketlisten konnten nicht aktualisiert werden. Netzwerk/Paketquellen prüfen; keine Installation ausgeführt.' >&2
        return 1
    fi
    if ! "${elevate[@]}" apt-get install -- "${missing_packages[@]}"; then
        printf '%s\n' 'Installation fehlgeschlagen oder abgebrochen. Anschließend erneut prüfen.' >&2
        return 1
    fi
}

main() {
    role=both
    backend=both
    indicator=true
    check_only=false
    directory="$HOME/Clipboard"
    project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    # Dieselben Systemprogramme wie beim Dienst verwenden, nicht Conda-/venv-Kopien.
    export PATH="/usr/sbin:/usr/bin:/sbin:/bin:$PATH"
    while (( $# )); do
        case "$1" in
            --role|--backend|--directory)
                if (( $# < 2 )) || [[ -z "$2" ]]; then printf 'Wert fehlt für %s\n' "$1" >&2; return 2; fi
                case "$1" in --role) role=$2 ;; --backend) backend=$2 ;; --directory) directory=$2 ;; esac
                shift 2 ;;
            --no-indicator) indicator=false; shift ;;
            --check-only) check_only=true; shift ;;
            -h|--help) usage; return 0 ;;
            *) printf 'Unbekannte Option: %s\n' "$1" >&2; usage >&2; return 2 ;;
        esac
    done
    case "$role" in both|sender|receiver) ;; *) printf '%s\n' 'Ungültige Rolle.' >&2; return 2 ;; esac
    case "$backend" in both|auto|x11|wayland) ;; *) printf '%s\n' 'Ungültiges Backend.' >&2; return 2 ;; esac
    if [[ "$backend" == auto ]]; then
        if [[ "${XDG_SESSION_TYPE:-}" == wayland || ( "${XDG_SESSION_TYPE:-}" != x11 && -n "${WAYLAND_DISPLAY:-}" ) ]]; then
            backend=wayland
        elif [[ "${XDG_SESSION_TYPE:-}" == x11 || -n "${DISPLAY:-}" ]]; then
            backend=x11
        else
            backend=both
        fi
    fi
    local ID='' ID_LIKE='' PRETTY_NAME='Linux'
    [[ ! -r /etc/os-release ]] || source /etc/os-release
    case "$ID" in
        ubuntu|linuxmint) ;;
        *) printf 'Unterstützt werden Ubuntu und Linux Mint; erkannt: %s\n' "$PRETTY_NAME" >&2; return 2 ;;
    esac
    if ! has_command apt-get || ! has_command dpkg-query; then
        printf '%s\n' 'apt-get/dpkg-query fehlen; automatische Prüfung/Installation nicht möglich.' >&2
        return 2
    fi
    os_name=$PRETTY_NAME
    desktop="${XDG_CURRENT_DESKTOP:-${DESKTOP_SESSION:-}}"
    desktop=${desktop,,}
    if (( EUID == 0 )); then
        printf '%s\n' 'Hinweis: Als root wird die Root-Sitzung geprüft. Für korrekte Desktop-/Dienstprüfungen als normaler Benutzer starten.'
    fi
    check_all
    if (( failures > 0 )); then
        if install_missing; then
            printf '\nInstallation beendet. Voraussetzungen werden erneut geprüft.\n'
            check_all
        fi
    fi
    if (( failures > 0 )); then
        printf '%s\n' 'Nicht alle Voraussetzungen erfüllt. Die oben aufgeführten Fehler beheben.'
        return 1
    fi
    printf '%s\n' 'Alle geprüften Pakete und Module sind verfügbar. Hinweise zur Sitzung/Konfiguration beachten.'
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
