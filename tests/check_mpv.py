"""Run in a normal desktop terminal to verify real mpv IPC without playing audio."""
from pathlib import Path
import queue
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from player import Player
from qqmusic import UserError

events = queue.Queue()
player = Player(events.put)
try:
    player.start()
    player.command(['get_property', 'mpv-version'])
    for _ in range(30):
        event = events.get(timeout=5)
        if event.get('error') == 'success' and isinstance(event.get('data'), str):
            print('mpv IPC OK:', event['data'])
            break
        if event.get('event') == 'disconnected':
            raise UserError('mpv disconnected; check socket permissions')
    else:
        raise UserError('mpv did not reply')
    player.command(['get_property', 'tls-verify'])
    for _ in range(30):
        event = events.get(timeout=5)
        if event.get('error') == 'success' and isinstance(event.get('data'), bool):
            if event['data'] is not True:
                raise UserError('mpv TLS certificate verification is disabled')
            print('mpv TLS certificate verification OK: enabled')
            break
        if event.get('event') == 'disconnected':
            raise UserError('mpv disconnected before TLS verification check')
    else:
        raise UserError('mpv did not report TLS verification setting')
except (UserError, OSError, queue.Empty) as exc:
    print('mpv IPC check failed:', str(exc) or 'timeout', file=sys.stderr)
    sys.exit(1)
finally:
    player.close()
