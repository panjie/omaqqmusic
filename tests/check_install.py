"""Fast install-time checks; no network, credentials, or desktop access."""
import ast
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
for name in ('main.py', 'qqmusic.py', 'player.py'):
    ast.parse((root / 'backend' / name).read_text())
for name in ('en', 'zh'):
    json.loads((root / 'i18n' / f'{name}.json').read_text())
