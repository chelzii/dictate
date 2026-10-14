"""Read-only environment and installation diagnostics (never acquires daemon IPC)."""
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from .config import CACHE, INSTALL, SOCKET_PATH


def installed_status():
    try:
        data = json.loads((CACHE / 'desktop-status.json').read_text())
        pid = int(data['pid'])
        proc = Path('/proc') / str(pid)
        command = (proc / 'cmdline').read_bytes()
        alive = proc.stat().st_uid == os.getuid() and (b'dictate.daemon' in command or b'chatgpt-dictation/daemon.py' in command)
    except (OSError, ValueError, KeyError, TypeError):
        data, alive = {}, False
    return {'installed': (INSTALL / 'daemon').exists(), 'running': alive,
            'connected': bool(alive and data.get('connected')), 'phase': data.get('phase') if alive else 'stopped',
            'socket': SOCKET_PATH.exists()}


def environment_checks():
    checks = []
    def add(name, ok, required, detail):
        checks.append({'name': name, 'ok': bool(ok), 'required': required, 'detail': detail})
    session = os.environ.get('XDG_SESSION_TYPE', '')
    add('X11 desktop', bool(os.environ.get('DISPLAY')) and session != 'wayland', True,
        '需要 X11 桌面终端；Wayland 暂不支持。')
    for command in ['google-chrome', 'xclip']:
        add(command, shutil.which(command), True, f'请安装 {command}。')
    add('Python venv', importlib.util.find_spec('venv') is not None, True, '请安装 python3-venv。')
    try:
        gtk = subprocess.run(['/usr/bin/python3', '-c', "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        gtk = False
    add('GTK3 / PyGObject', gtk, True, '请安装 python3-gi gir1.2-gtk-3.0。')
    for command, detail in [('pw-record', '音量条与停顿自动结束需要 PipeWire。'),
                            ('canberra-gtk-play', '提示音可选；安装 libcanberra-gtk3-bin。')]:
        add(command, shutil.which(command), False, detail)
    return checks


def report():
    checks = environment_checks()
    return {'ok': all(c['ok'] for c in checks if c['required']), 'checks': checks,
            'service': installed_status(),
            'next': '扩展连接后，仍需首次手动完成 ChatGPT 登录、麦克风授权与页面绑定。'}
