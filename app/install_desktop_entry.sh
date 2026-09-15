#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-$(pwd)}"
ROOT="$(cd "$ROOT" && pwd)"
if [[ ! -f "$ROOT/pt_asset_gui.py" ]]; then echo "pt_asset_gui.py not found in $ROOT" >&2; exit 2; fi
APPDIR="$HOME/.local/share/applications"
mkdir -p "$APPDIR"
DESKTOP="$APPDIR/pt-asset-tool.desktop"
# Desktop Exec parsing requires quoting because the normal project path may contain spaces.
printf '%s\n' \
  '[Desktop Entry]' \
  'Type=Application' \
  'Name=PT Asset Tool' \
  'Comment=Summit Tale asset catalog, comparison, validation and guarded editing shell' \
  "Exec=\"$ROOT/pt-asset-gui\"" \
  "Path=$ROOT" \
  'Terminal=false' \
  'Categories=Development;Graphics;' \
  'StartupNotify=true' > "$DESKTOP"
chmod 644 "$DESKTOP"
echo "desktop_entry_installed=$DESKTOP"
