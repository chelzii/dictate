#!/usr/bin/env python3
"""Install (or --uninstall) the desktop side for this user's unpacked extension. No sudo.

Installs into ~/.local/share/chatgpt-dictation:
  daemon     long-running F9/F8 + panel + paste service, started at login (not Chrome)
  bridge     Chrome's native-messaging host, relays to the daemon
  overlay    the floating status panel
"""
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

HOST_NAME = 'com.chelizi.chatgpt_dictation'
SOURCE = Path(__file__).resolve().parent
INSTALL = Path.home() / '.local/share/chatgpt-dictation'
AUTOSTART = Path.home() / '.config/autostart/chatgpt-dictation.desktop'
CACHE = Path.home() / '.cache/chatgpt-dictation'
BROWSERS = ['google-chrome', 'chromium']


def manifests():
    return [Path.home() / '.config' / b / 'NativeMessagingHosts' / f'{HOST_NAME}.json' for b in BROWSERS]


def stop_daemon():
    try:
        pid = int((CACHE / 'daemon.pid').read_text())
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError):
        return
    for _ in range(30):
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.1)


def launcher(path, command):
    path.write_text('#!/bin/sh\nexec ' + ' '.join(shlex.quote(str(c)) for c in command) + '\n')
    path.chmod(0o755)


def install(extension_id):
    if len(extension_id) != 32 or any(c not in 'abcdefghijklmnop' for c in extension_id):
        raise SystemExit('Invalid extension ID')
    if not shutil.which('xclip'):
        raise SystemExit('请先安装 xclip（本机文字插入所需）。')
    INSTALL.mkdir(parents=True, exist_ok=True)
    venv = INSTALL / 'venv'
    python = venv / 'bin/python'
    if not python.exists():
        subprocess.run([sys.executable, '-m', 'venv', str(venv)], check=True)
    for module, package in [('Xlib', 'python-xlib==0.33'), ('pulsectl', 'pulsectl')]:
        if subprocess.run([str(python), '-c', f'import {module}'], capture_output=True).returncode:
            result = subprocess.run([str(python), '-m', 'pip', 'install', '-q', package])
            if result.returncode and module == 'Xlib':
                raise SystemExit('python-xlib 安装失败。')
            if result.returncode:
                print('提示：pulsectl 安装失败，录音音量条不可用，其余功能正常。')
    for name in ['daemon.py', 'bridge.py', 'overlay.py']:
        shutil.copy2(SOURCE / name, INSTALL / name)
    for stale in ['host.py', 'launch']:  # replaced by daemon + bridge
        (INSTALL / stale).unlink(missing_ok=True)
    launcher(INSTALL / 'daemon', [python, INSTALL / 'daemon.py'])
    launcher(INSTALL / 'bridge', ['/usr/bin/python3', INSTALL / 'bridge.py'])
    manifest = {'name': HOST_NAME, 'description': 'F9/F8 desktop dictation bridge', 'path': str(INSTALL / 'bridge'),
                'type': 'stdio', 'allowed_origins': [f'chrome-extension://{extension_id}/']}
    for path in manifests():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2) + '\n')
    # Start the small daemon (not Chrome) at login so F9 works before Chrome is open.
    AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
    AUTOSTART.write_text('[Desktop Entry]\nType=Application\nName=ChatGPT 后台听写\n'
                         f'Exec={INSTALL / "daemon"}\nX-GNOME-Autostart-enabled=true\nNoDisplay=true\n')
    stop_daemon()
    if os.environ.get('DISPLAY'):
        subprocess.Popen([str(INSTALL / 'daemon')], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    print('Installed per-user dictation service:', INSTALL)


def uninstall():
    stop_daemon()
    for path in manifests() + [AUTOSTART]:
        path.unlink(missing_ok=True)
    shutil.rmtree(INSTALL, ignore_errors=True)
    print('Removed. Chrome extension itself: remove it at chrome://extensions.')


if __name__ == '__main__':
    args = sys.argv[1:]
    if '--uninstall' in args:
        uninstall()
    else:
        if len(args) != 1:
            raise SystemExit('Usage: python3 native/install.py EXTENSION_ID | --uninstall')
        install(args[0])
