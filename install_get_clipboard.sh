#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
"$project_dir/setup_get_clipboard.sh"
/usr/bin/python3 "$project_dir/clipboard_indicator.py" --check
if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    printf '%s\n' 'Installation aus einem Terminal in der grafischen Sitzung starten.' >&2
    exit 1
fi
/usr/bin/python3 - "$project_dir" <<'PY'
from pathlib import Path
import os
import sys

project = Path(sys.argv[1])
destination = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd/user"
destination.mkdir(parents=True, exist_ok=True)
escaped = str(project).replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
unit = (project / "systemd/get-clipboard.service.in").read_text().replace("@PROJECT@", escaped)
(destination / "get-clipboard.service").write_text(unit)
(Path.home() / "Clipboard").mkdir(mode=0o700, exist_ok=True)
PY
# Nur tatsächlich vorhandene Sitzungsvariablen übernehmen.
for name in DISPLAY WAYLAND_DISPLAY XAUTHORITY XDG_SESSION_TYPE XDG_CURRENT_DESKTOP; do
    if [[ -v "$name" ]]; then
        systemctl --user import-environment "$name"
    fi
done
systemctl --user daemon-reload
systemctl --user enable get-clipboard.service
systemctl --user restart get-clipboard.service
systemctl --user --no-pager status get-clipboard.service
