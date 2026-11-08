#!/usr/bin/env bash
# Render the actual panel with synthetic data; never start the music service.
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
preview_dir=$(mktemp -d /tmp/qqmusic-preview.XXXXXX)
trap 'rm -rf -- "$preview_dir"' EXIT
mkdir -p "$preview_dir/runtime"
chmod 700 "$preview_dir/runtime"
ln -s /usr/share/omarchy/shell/Commons "$preview_dir/Commons"
ln -s /usr/share/omarchy/shell/Ui "$preview_dir/Ui"
ln -s "$project_dir" "$preview_dir/Music"
cp "$project_dir/tests/Preview.qml" "$preview_dir/shell.qml"
printf '%s' "${QQ_PREVIEW_LANGUAGE:-zh}" > "$preview_dir/language"
# Deliberately not a scannable code: the preview never requests login credentials.
printf '%s' '<svg xmlns="http://www.w3.org/2000/svg" width="180" height="180"><rect width="180" height="180" fill="white"/><path d="M20 20h45v45H20zM115 20h45v45h-45zM20 115h45v45H20zM85 85h30v30H85zM130 130h30v30h-30z" fill="black"/></svg>' > "$preview_dir/qr.svg"
export QQ_PREVIEW_SCENARIO="${1:-playing}"
export QQ_PREVIEW_OUTPUT="${2:-/tmp/qqmusic-preview.png}"
QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORMTHEME=basic QT_QUICK_BACKEND=software \
  XDG_RUNTIME_DIR="$preview_dir/runtime" timeout 12 quickshell -p "$preview_dir/shell.qml"
test -s "$QQ_PREVIEW_OUTPUT"
printf 'Preview: %s\n' "$QQ_PREVIEW_OUTPUT"
