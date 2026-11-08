#!/usr/bin/env bash
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
config_root="${XDG_CONFIG_HOME:-$HOME/.config}"
target="$config_root/omarchy/plugins/local.qqmusic"
for dependency in python3 mpv omarchy omarchy-shell; do
  command -v "$dependency" >/dev/null || { printf 'Missing dependency: %s\n' "$dependency" >&2; exit 1; }
done
omarchy plugin validate "$source_dir"
python3 -B "$source_dir/tests/check_install.py" "$source_dir"
mkdir -p "$config_root/omarchy/plugins"
staging=$(mktemp -d "$config_root/omarchy/.qqmusic-install.XXXXXX")
trap 'rm -rf -- "$staging"' EXIT
cp -- "$source_dir"/{manifest.json,BarWidget.qml,Service.qml,NativePanel.qml,PlainLabel.qml,README.md,LICENSE,THIRD_PARTY_NOTICES.md} "$staging/"
mkdir -p "$staging/backend" "$staging/i18n" "$staging/docs"
cp -- "$source_dir/docs/preview.png" "$staging/docs/"
cp -- "$source_dir"/backend/*.py "$staging/backend/"
cp -- "$source_dir"/i18n/*.json "$staging/i18n/"
omarchy plugin validate "$staging"
if [[ -e "$target" || -L "$target" ]]; then
  mkdir -p "$config_root/omarchy/plugin-backups"
  backup="$config_root/omarchy/plugin-backups/local.qqmusic.$(date +%Y%m%d-%H%M%S).$$"
  # keepLoaded services survive hot reload; explicitly stop the old backend.
  omarchy-shell shell rescanPlugins
  omarchy plugin disable local.qqmusic
  mv -- "$target" "$backup"
  printf 'Previous plugin backed up to: %s\n' "$backup"
fi
mv -- "$staging" "$target"
omarchy-shell shell rescanPlugins
omarchy plugin enable local.qqmusic --section right
printf 'Installed. Click QQ Music in the bar, then QQ QR sign-in.\n'
