"""Private mpv JSON IPC over an inherited socket; no TCP port or shell command."""
import json
import socket
import subprocess
import threading
from qqmusic import UserError, media_url


class Player:
    def __init__(self, event):
        self.event = event
        self.process = None
        self.socket = None
        self.reader = None

    def start(self):
        if self.process and self.process.poll() is None:
            return
        self.close()
        parent, child = socket.socketpair()
        try:
            self.process = subprocess.Popen([
                'mpv', '--no-config', '--no-video', '--idle=yes', '--no-terminal',
                '--input-default-bindings=no', '--input-terminal=no', '--load-scripts=no',
                '--ytdl=no', '--audio-display=no', '--network-timeout=12',
                '--demuxer-max-bytes=16MiB', '--demuxer-lavf-propagate-opts=no',
                '--volume=70', '--referrer=https://y.qq.com/',
                f'--input-ipc-client=fd://{child.fileno()}',
            ], pass_fds=(child.fileno(),), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (FileNotFoundError, OSError):
            parent.close()
            raise UserError('mpv_missing') from None
        finally:
            child.close()
        self.socket = parent
        self.reader = threading.Thread(target=self.read, args=(parent,), daemon=True)
        self.reader.start()
        for index, prop in enumerate(('pause', 'time-pos', 'duration', 'volume', 'idle-active')):
            self.command(['observe_property', index + 1, prop])

    def read(self, channel):
        try:
            with channel.makefile('rb') as stream:
                while line := stream.readline(65537):
                    if len(line) > 65536:
                        break
                    try:
                        value = json.loads(line)
                        self.event(value)
                    except (ValueError, TypeError):
                        continue
        except OSError:
            pass
        self.event({'event': 'disconnected'})

    def command(self, command):
        if not self.socket:
            raise UserError('player_failed')
        try:
            self.socket.sendall((json.dumps({'command': command}) + '\n').encode())
        except OSError:
            raise UserError('player_failed') from None

    def play(self, url):
        url = media_url(url)
        self.start()
        self.command(['loadfile', url, 'replace'])
        self.command(['set_property', 'pause', False])

    def close(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            self.process = None
        if self.socket:
            self.socket.close()
            self.socket = None
