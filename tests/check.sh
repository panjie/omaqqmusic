#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_dir"
omarchy plugin validate .
python3 -B tests/check_install.py .
python3 -B -m unittest discover -s tests -p 'test_*.py' -v
bash -n install.sh
if [[ -x /usr/lib/qt6/bin/qmlformat ]]; then
  for file in BarWidget.qml Service.qml NativePanel.qml PlainLabel.qml; do
    /usr/lib/qt6/bin/qmlformat --normalize "$file" >/dev/null
  done
fi
