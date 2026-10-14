#!/usr/bin/env python3
"""Chrome native-messaging host: relays between the extension and the dictation daemon.

Chrome speaks length-prefixed JSON on stdin/stdout; the daemon speaks JSON lines on a
Unix socket. If the daemon is not running (e.g. it was never started this session),
the bridge starts it. Standard library only.
"""
import json
import os
import select
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}')
SOCKET_PATH = Path(os.environ.get('DICTATION_SOCKET', str(RUNTIME / 'chatgpt-dictation.sock')))
DAEMON = HERE / 'daemon'          # launcher written by install.py
MAX_MESSAGE = 1024 * 1024


def connect():
    for attempt in range(50):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(str(SOCKET_PATH))
            return sock
        except OSError:
            sock.close()
        if attempt == 0 and DAEMON.exists():
            subprocess.Popen([str(DAEMON)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(0.1)
    sys.exit(1)


def to_chrome(message):
    data = json.dumps(message, ensure_ascii=False).encode()
    sys.stdout.buffer.write(struct.pack('<I', len(data)) + data)
    sys.stdout.buffer.flush()


def main():
    sock = connect()
    stdin = sys.stdin.buffer.fileno()
    from_chrome, from_daemon = b'', b''
    while True:
        ready, _, _ = select.select([stdin, sock], [], [])
        if stdin in ready:
            chunk = os.read(stdin, 65536)
            if not chunk:
                return
            from_chrome += chunk
            while len(from_chrome) >= 4:
                size = struct.unpack('<I', from_chrome[:4])[0]
                if size > MAX_MESSAGE:
                    return
                if len(from_chrome) < 4 + size:
                    break
                body, from_chrome = from_chrome[4:4 + size], from_chrome[4 + size:]
                sock.sendall(body.replace(b'\n', b' ') + b'\n')
        if sock in ready:
            chunk = sock.recv(65536)
            if not chunk:
                return
            from_daemon += chunk
            *lines, from_daemon = from_daemon.split(b'\n')
            for line in lines:
                try:
                    to_chrome(json.loads(line))
                except ValueError:
                    pass


if __name__ == '__main__':
    main()
