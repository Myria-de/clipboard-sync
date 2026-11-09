#!/usr/bin/env bash
set -euo pipefail
if [[ ! -x /usr/bin/python3 ]]; then
    printf '%s\n' 'System-Python fehlt. Bitte python3 installieren.' >&2
    exit 1
fi
/usr/bin/python3 -c 'import sys; sys.exit("Python 3.10 oder neuer erforderlich.") if sys.version_info < (3, 10) else print("System-Python bereit. Für den Panel-Indikator werden GTK/AppIndicator-Systempakete benötigt; siehe README.md.")'
for tool in sftp xclip wl-paste wl-copy file; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf 'Hinweis: %s ist nicht installiert. Siehe README.md.\n' "$tool"
    fi
done
