#!/usr/bin/env python3
"""Line-delimited JSON stdio backend owned by the one Omarchy plugin service."""
import fcntl
import json
import math
import os
import queue
import random
import signal
import sys
import threading
import time
from qqmusic import QQMusic, UserError
from player import Player


class App:
    def __init__(self, api=None, player=None, output=None):
        self.api = api or QQMusic()
        self.events = queue.Queue(maxsize=256)
        self.player = player or Player(self.player_event)
        self.output = output or self.write
        self.results = []
        self.queue = []
        self.index = -1
        self.playback_mode = 'sequential'
        self.order = []
        self.playing = False
        self.paused = False
        self.position = 0
        self.duration = 0
        self.volume = 70
        self.last_status = 0

    @staticmethod
    def write(value):
        print(json.dumps(value, ensure_ascii=False, separators=(',', ':')), flush=True)

    def player_event(self, value):
        try:
            self.events.put(('player', value), timeout=1)
        except queue.Full:
            pass

    def status(self):
        return {'account': self.api.account(), 'track': self.queue[self.index] if 0 <= self.index < len(self.queue) else None,
                'playing': self.playing, 'paused': self.paused, 'position': self.position,
                'duration': self.duration, 'volume': self.volume,
                'playbackMode': self.playback_mode,
                'canPrevious': self.adjacent_index(-1) is not None,
                'canNext': self.adjacent_index(1) is not None}

    def reset_order(self):
        self.order = list(range(len(self.queue)))
        if self.playback_mode == 'shuffle' and self.index >= 0:
            self.order.remove(self.index)
            random.shuffle(self.order)
            self.order.insert(0, self.index)

    def adjacent_index(self, step):
        if self.index not in self.order:
            return None
        position = self.order.index(self.index) + step
        return self.order[position] if 0 <= position < len(self.order) else None

    def advance(self, step):
        index = self.adjacent_index(step)
        if index is None:
            raise UserError('invalid_request')
        return self.play_index(index)

    def emit_status(self):
        self.output({'event': 'state', 'data': self.status()})
        self.last_status = time.monotonic()

    def play_index(self, index, tracks=None):
        new_queue = tracks is not None
        tracks = tracks if tracks is not None else self.queue
        if not 0 <= index < len(tracks):
            raise UserError('invalid_request')
        url = self.api.play_url(tracks[index])
        # Commit the new queue only after resolving the URL and starting mpv.
        self.player.play(url)
        self.queue, self.index = list(tracks), index
        if new_queue:
            self.reset_order()
        self.playing, self.paused = False, False
        self.position, self.duration = 0, 0
        self.emit_status()
        return {'loading': True}

    def dispatch(self, command, args):
        if command == 'status':
            return self.status()
        if command == 'playback_mode':
            mode = args.get('mode')
            if mode not in ('sequential', 'shuffle'):
                raise UserError('invalid_request')
            if mode != self.playback_mode:
                self.playback_mode = mode
                self.reset_order()
            self.emit_status()
            return {}
        if command == 'login':
            return self.api.start_login()
        if command == 'login_poll':
            result = self.api.poll_login()
            self.emit_status()
            return result
        if command == 'login_cancel':
            self.api.qr = None
            return {}
        if command == 'logout':
            self.player.close()
            self.queue, self.results, self.index = [], [], -1
            self.order = []
            self.playing, self.paused, self.position, self.duration = False, False, 0, 0
            self.api.logout()
            self.emit_status()
            return {}
        if command in ('search', 'playlist', 'favorites'):
            result = (self.api.search(args.get('query', ''), int(args.get('page', 1))) if command == 'search'
                      else self.api.favorites() if command == 'favorites'
                      else self.api.playlist(args.get('id', '')))
            self.results = result['songs']
            return result
        if command == 'playlists':
            return {'playlists': self.api.playlists()}
        if command == 'play':
            return self.play_index(int(args.get('index', -1)), self.results)
        if command in ('previous', 'next'):
            return self.advance(1 if command == 'next' else -1)
        if command == 'toggle':
            if self.index < 0:
                raise UserError('invalid_request')
            if not self.playing:
                return self.play_index(self.index)
            self.player.command(['cycle', 'pause'])
            return {}
        if command == 'seek':
            value = float(args.get('seconds', 0))
            if not self.playing or not math.isfinite(value):
                raise UserError('invalid_request')
            self.player.command(['seek', max(0, min(self.duration, value)), 'absolute'])
            return {}
        if command == 'volume':
            value = float(args.get('value', 70))
            if not math.isfinite(value):
                raise UserError('invalid_request')
            self.player.command(['set_property', 'volume', max(0, min(100, value))])
            return {}
        raise UserError('invalid_request')

    def handle(self, request):
        request_id = request.get('id')
        try:
            args = request.get('args', {})
            if not isinstance(args, dict):
                raise UserError('invalid_request')
            result = self.dispatch(request.get('command'), args)
            self.output({'id': request_id, 'ok': True, 'data': result})
        except UserError as exc:
            failure = {'id': request_id, 'ok': False, 'error': str(exc)}
            if request.get('command') in ('login', 'login_poll'):
                failure['stage'] = self.api.login_stage
                try:
                    self.api.record_login_failure(str(exc))
                except OSError:
                    pass
            self.output(failure)
        except (ValueError, TypeError, KeyError, AttributeError, IndexError):
            self.output({'id': request_id, 'ok': False, 'error': 'upstream_changed'})
        except Exception:
            # Do not expose OAuth codes, cookies or signed URLs in errors/logs.
            self.output({'id': request_id, 'ok': False, 'error': 'backend_error'})

    def on_player(self, event):
        kind = event.get('event')
        if kind == 'property-change':
            prop, value = event.get('name'), event.get('data')
            if prop == 'pause':
                self.paused = bool(value)
            elif prop in ('time-pos', 'duration', 'volume'):
                if isinstance(value, (int, float)) and math.isfinite(value):
                    setattr(self, {'time-pos': 'position'}.get(prop, prop), max(0, value))
            elif prop == 'idle-active' and value:
                self.playing = False
            if prop != 'time-pos' or time.monotonic() - self.last_status >= 1:
                self.emit_status()
        elif kind == 'file-loaded':
            self.playing = True
            self.emit_status()
        elif kind == 'end-file':
            self.playing = False
            self.emit_status()
            if event.get('reason') == 'eof' and self.adjacent_index(1) is not None:
                try:
                    self.advance(1)
                except UserError as exc:
                    self.output({'event': 'error', 'error': str(exc)})
                except Exception:
                    self.output({'event': 'error', 'error': 'upstream_changed'})
            elif event.get('reason') == 'error':
                self.output({'event': 'error', 'error': 'playback_failed'})
        elif kind == 'disconnected':
            self.playing = False
            self.emit_status()

    def read_input(self):
        while line := sys.stdin.buffer.readline(65537):
            if len(line) > 65536:
                break
            try:
                request = json.loads(line)
                if isinstance(request, dict):
                    self.events.put(('request', request))
            except (ValueError, UnicodeError):
                continue
        self.events.put(('quit', {}))

    def run(self):
        threading.Thread(target=self.read_input, daemon=True).start()
        self.output({'event': 'ready', 'data': self.status()})
        try:
            while True:
                kind, value = self.events.get()
                if kind == 'quit':
                    break
                if kind == 'request':
                    self.handle(value)
                else:
                    self.on_player(value)
        finally:
            self.player.close()


def main():
    os.umask(0o077)
    app = App()
    # A second shell/preview must not start a competing player or overwrite login state.
    with (app.api.directory / 'backend.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            App.write({'event': 'error', 'error': 'already_running'})
            return 1
        def stop(*_):
            app.player.close()
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        app.run()
    return 0


if __name__ == '__main__':
    sys.exit(main())
