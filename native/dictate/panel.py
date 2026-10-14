"""Own and supervise the non-focusing GTK panel process."""
import json
import os
import subprocess
from .config import CACHE
from .protocol import Lines

class Panel:
    """The GTK status panel (overlay.py), a child process fed JSON lines."""

    def __init__(self):
        self.proc = None
        self.lines = Lines()

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def send(self, message):
        line = (json.dumps(message, ensure_ascii=False) + '\n').encode()
        # Respawn once if the panel exited.
        for _ in range(2):
            if not self.alive():
                self.close()
                self.proc = subprocess.Popen(
                    ['/usr/bin/python3', '-m', 'dictate.overlay'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=(CACHE / 'hud-errors.log').open('a'))
                self.lines = Lines()
                self.on_spawn()
            try:
                self.proc.stdin.write(line)
                self.proc.stdin.flush()
                return True
            except OSError:
                self.close()
        return False

    def on_spawn(self):
        """Replaced by the daemon to replay menu state into a fresh panel."""

    def fileno(self):
        return self.proc.stdout.fileno() if self.alive() else None

    def read(self):
        chunk = os.read(self.proc.stdout.fileno(), 65536)
        if not chunk:
            self.close()
            return []
        return self.lines.feed(chunk)

    def close(self):
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            proc.stdin.close()
            proc.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            proc.terminate()
        proc.stdout.close()
