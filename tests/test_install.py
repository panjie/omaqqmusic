"""Install and upgrade in a disposable XDG directory; never touch the live bar."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def test_install_upgrade_keeps_backup_outside_plugin_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            bin_dir = base / 'bin'
            bin_dir.mkdir()
            command = bin_dir / 'omarchy'
            command.write_text('''#!/usr/bin/env bash
set -euo pipefail
case "$1 $2" in
  'plugin validate') exec /usr/share/omarchy/bin/omarchy-plugin-validate "$3" ;;
  'plugin disable') exit 0 ;;
  'plugin enable') printf '%s\\n' "$*" >> "$XDG_CONFIG_HOME/enable.log" ;;
  *) exit 2 ;;
esac
''')
            command.chmod(0o755)
            rescan = bin_dir / 'omarchy-shell'
            rescan.write_text('#!/bin/sh\n[ "$1 $2" = "shell rescanPlugins" ]\n')
            rescan.chmod(0o755)
            env = {**os.environ, 'PATH': str(bin_dir) + ':' + os.environ['PATH'],
                   'XDG_CONFIG_HOME': str(base / 'config with spaces')}
            for run in range(2):
                result = subprocess.run(['bash', str(ROOT / 'install.sh')],
                                        env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
            config = Path(env['XDG_CONFIG_HOME'])
            target = config / 'omarchy/plugins/local.qqmusic'
            for name in ('Service.qml', 'NativePanel.qml', 'backend/main.py', 'backend/player.py', 'i18n/zh.json'):
                self.assertTrue((target / name).is_file(), name)
            self.assertEqual(len(list((config / 'omarchy/plugins').iterdir())), 1)
            self.assertEqual(len(list((config / 'omarchy/plugin-backups').iterdir())), 1)
            self.assertEqual((config / 'enable.log').read_text().splitlines(),
                             ['plugin enable local.qqmusic --section right'] * 2)


if __name__ == '__main__':
    unittest.main()
