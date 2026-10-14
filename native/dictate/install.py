"""Per-user installation with staged code, rollback and explicit extension identity."""
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from .config import CACHE, HOST_NAME, INSTALL
from .doctor import environment_checks

SOURCE = Path(__file__).resolve().parent
AUTOSTART = Path.home() / '.config/autostart/chatgpt-dictation.desktop'
COMMAND = Path.home() / '.local/bin/dictate'


def manifests():
    return [Path.home() / '.config' / b / 'NativeMessagingHosts' / f'{HOST_NAME}.json'
            for b in ['google-chrome', 'chromium']]


def daemon_pid():
    try:
        pid = int((CACHE / 'daemon.pid').read_text())
        proc = Path('/proc') / str(pid)
        command = (proc / 'cmdline').read_bytes()
        if proc.stat().st_uid == os.getuid() and (b'dictate.daemon' in command or b'chatgpt-dictation/daemon.py' in command):
            return pid
    except (OSError, ValueError):
        pass
    return None


def stop_daemon():
    pid = daemon_pid()
    if pid is None:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(50):
        if daemon_pid() != pid:
            return
        time.sleep(0.1)
    raise RuntimeError('旧服务未退出；没有切换程序，请停止服务后重试。')


def atomic_write(path, content, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(content)
    temporary.chmod(mode)
    temporary.replace(path)


def launcher(command):
    return '#!/bin/sh\nexport PYTHONPATH=' + shlex.quote(str(INSTALL / 'current')) + '\nexec ' + ' '.join(shlex.quote(str(c)) for c in command) + ' "$@"\n'


def prepare_python():
    python = INSTALL / 'venv/bin/python'
    if not python.exists():
        subprocess.run([sys.executable, '-m', 'venv', str(INSTALL / 'venv')], check=True)
    packages = [('Xlib', 'python-xlib==0.33'), ('pulsectl', 'pulsectl==24.12.0')]
    for module, requirement in packages:
        if subprocess.run([str(python), '-c', f'import {module}'], capture_output=True).returncode:
            result = subprocess.run([str(python), '-m', 'pip', 'install', requirement])
            if result.returncode and module == 'Xlib':
                raise RuntimeError('python-xlib 安装失败。')
            if result.returncode:
                print('提示：音量依赖安装失败，音量条和停顿自动结束不可用。')
    return python


def start_daemon():
    if os.environ.get('DISPLAY'):
        return subprocess.Popen([str(INSTALL / 'daemon')], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def verify_started(process):
    if process is None:
        raise RuntimeError('未启动服务：需要 X11 桌面终端。')
    for _ in range(80):
        if process.poll() is not None:
            raise RuntimeError('新服务启动失败，正在恢复旧安装。')
        try:
            data = json.loads((CACHE / 'desktop-status.json').read_text())
            if data.get('pid') == process.pid and data.get('running') is not False:
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise RuntimeError('新服务没有报告就绪，正在恢复旧安装。')


def install(extension_id):
    if len(extension_id) != 32 or any(c not in 'abcdefghijklmnop' for c in extension_id):
        raise ValueError('扩展 ID 必须为 Chrome 显示的 32 位 a–p 字符。')
    missing = [c for c in environment_checks() if c['required'] and not c['ok']]
    if missing:
        raise RuntimeError('环境检查未通过：\n' + '\n'.join(c['name'] + ': ' + c['detail'] for c in missing))
    existed = INSTALL.exists()
    paths = manifests() + [AUTOSTART, COMMAND, INSTALL / 'daemon', INSTALL / 'bridge', INSTALL / 'installation.json']
    previous = {p: (p.read_bytes(), p.stat().st_mode & 0o777) if p.exists() else None for p in paths}
    current = INSTALL / 'current'
    old_target = os.readlink(current) if current.is_symlink() else None
    release = None
    switched = False
    was_running = daemon_pid() is not None
    process = None
    try:
        INSTALL.mkdir(parents=True, exist_ok=True)
        python = prepare_python()
        releases = INSTALL / 'releases'
        releases.mkdir(exist_ok=True)
        release = Path(tempfile.mkdtemp(prefix='release-', dir=releases))
        shutil.copytree(SOURCE, release / 'dictate', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        env = dict(os.environ, PYTHONPATH=str(release))
        subprocess.run([str(python), '-c', 'import dictate.daemon; import dictate.bridge'], env=env, check=True, capture_output=True)
        subprocess.run(['/usr/bin/python3', '-c', 'import dictate.overlay'], env=env, check=True, capture_output=True)
        stop_daemon()
        temporary = INSTALL / 'current.new'
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(release.relative_to(INSTALL))
        temporary.replace(current)
        switched = True
        atomic_write(INSTALL / 'daemon', launcher([python, '-m', 'dictate.daemon']), 0o755)
        atomic_write(INSTALL / 'bridge', launcher(['/usr/bin/python3', '-m', 'dictate.bridge']), 0o755)
        atomic_write(COMMAND, launcher([python, '-m', 'dictate.cli']), 0o755)
        manifest = {'name': HOST_NAME, 'description': 'dictate desktop bridge', 'path': str(INSTALL / 'bridge'),
                    'type': 'stdio', 'allowed_origins': [f'chrome-extension://{extension_id}/']}
        for path in manifests():
            atomic_write(path, json.dumps(manifest, indent=2) + '\n')
        executable = '"' + str(INSTALL / 'daemon').replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`') + '"'
        atomic_write(AUTOSTART, '[Desktop Entry]\nType=Application\nName=dictate\nExec=' + executable + '\nX-GNOME-Autostart-enabled=true\nNoDisplay=true\n')
        atomic_write(INSTALL / 'installation.json', json.dumps({'extensionId': extension_id, 'release': release.name}) + '\n', 0o600)
        process = start_daemon()
        verify_started(process)
    except Exception:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        if switched:
            current.unlink(missing_ok=True)
            if old_target:
                current.symlink_to(old_target)
        for path, backup in previous.items():
            if backup is None:
                path.unlink(missing_ok=True)
            else:
                data, mode = backup
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                path.chmod(mode)
        if release:
            shutil.rmtree(release, ignore_errors=True)
        if not existed:
            shutil.rmtree(INSTALL, ignore_errors=True)
        if switched and was_running:
            start_daemon()
        raise
    print('Installed dictate:', INSTALL)
    print('运行 ~/.local/bin/dictate doctor 检查环境；首次登录与授权仍需手动完成。')


def update():
    try:
        extension_id = json.loads((INSTALL / 'installation.json').read_text())['extensionId']
    except (OSError, ValueError, KeyError):
        raise RuntimeError('没有安装记录，请先 install --extension-id YOUR_EXTENSION_ID。')
    install(extension_id)


def uninstall():
    stop_daemon()
    for path in manifests() + [AUTOSTART, COMMAND]:
        path.unlink(missing_ok=True)
    shutil.rmtree(INSTALL, ignore_errors=True)
    print('本机服务已卸载；请在 chrome://extensions 移除扩展。设置与缓存保留。')
