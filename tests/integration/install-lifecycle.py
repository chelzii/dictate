"""Real installer lifecycle in an isolated HOME and nested X desktop.

Requires Xephyr and an existing dependency venv supplied with --dependency-venv.
Reuses only dependency files; installation, processes, settings and sockets are isolated.
No ChatGPT login, browser interaction or user service changes.
"""
import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--dependency-venv', required=True)
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='dictate-install-lifecycle-') as tmp:
    home = Path(tmp)
    display = ':' + str(next(n for n in range(7, 60) if not Path(f'/tmp/.X{n}-lock').exists()))
    server = subprocess.Popen(['Xephyr', display, '-screen', '800x600', '-ac', '-br', '-noreset'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    install = home / '.local/share/chatgpt-dictation'
    install.mkdir(parents=True)
    (install / 'venv').symlink_to(Path(args.dependency_venv).resolve(), target_is_directory=True)
    env = dict(os.environ, HOME=str(home), DISPLAY=display, XDG_SESSION_TYPE='x11',
               XDG_CACHE_HOME=str(home / 'cache'), XDG_CONFIG_HOME=str(home / 'config'),
               DICTATION_INSTALL_ROOT=str(install), DICTATION_SOCKET=str(home / 'daemon.sock'))
    command = ['python3', str(ROOT / 'scripts/dictate.py')]
    def run(*args, ok=True):
        result = subprocess.run(command + list(args), env=env, text=True, capture_output=True, timeout=30)
        if ok:
            assert result.returncode == 0, result.stdout + result.stderr
        else:
            assert result.returncode != 0, result.stdout
        return result
    try:
        time.sleep(1.5)
        run('install', '--extension-id', 'a' * 32)
        assert json.loads(run('status', '--json').stdout)['running']
        print('PASS fresh installation starts real daemon and floating panel', flush=True)
        settings = home / 'config/chatgpt-dictation/settings.json'
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text('{"sounds":false}')
        run('install', '--extension-id', 'a' * 32)
        run('update', '--source', str(ROOT))
        assert json.loads(run('status', '--json').stdout)['running']
        print('PASS repeat installation and source update', flush=True)
        old = os.readlink(install / 'current')
        broken = home / 'broken-source/native/dictate'
        shutil.copytree(ROOT / 'native/dictate', broken, ignore=shutil.ignore_patterns('__pycache__'))
        (broken / 'daemon.py').write_text('if __name__ == "__main__":\n    raise RuntimeError("intentional failed startup")\n')
        failure = run('update', '--source', str(home / 'broken-source'), ok=False)
        assert os.readlink(install / 'current') == old
        for _ in range(50):
            if json.loads(run('status', '--json').stdout)['running']:
                break
            time.sleep(.1)
        else:
            raise AssertionError('old daemon not restored')
        print('PASS real startup failure restores previous code and restarts old daemon', flush=True)
        run('uninstall')
        assert not install.exists()
        assert not (home / '.local/bin/dictate').exists()
        assert settings.read_text() == '{"sounds":false}'
        print('PASS uninstall removes service, preserves settings', flush=True)
    finally:
        if install.exists():
            run('uninstall')
        server.terminate()
        server.wait(timeout=5)
