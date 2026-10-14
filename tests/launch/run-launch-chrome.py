"""Chrome is not running: F9 starts it in the background and the key is replayed once the
extension connects; then dictation opens its ChatGPT page although Chrome has no window,
without taking focus from the input. Runs on a nested X server (Xephyr) with a throwaway
Chrome profile and its own daemon socket, so the user's Chrome and F9 are untouched.

Branded Chrome ignores --load-extension, so the test loads the unpacked extension over the
DevTools protocol right after the daemon has started Chrome (standing in for an installed one).
"""
import json
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
for deps in [HERE.parent / '.deps', Path('/tmp/dictation-real-test-deps')]:
    if deps.is_dir():
        sys.path.insert(0, str(deps))
from Xlib import X, XK, display  # noqa: E402
from Xlib.ext import xtest  # noqa: E402

WORK = Path('/tmp/dictation-launch-test')
subprocess.run(['rm', '-rf', str(WORK)])
PROFILE, CACHE, CONFIG = WORK / 'profile', WORK / 'cache', WORK / 'config'
for p in [PROFILE / 'NativeMessagingHosts', CACHE, CONFIG]:
    p.mkdir(parents=True)
DISPLAY = ':' + str(next(n for n in range(7, 60) if not Path(f'/tmp/.X{n}-lock').exists()))
PORT = '9333'
EXTENSION_ID = os.environ.get('DICTATION_EXTENSION_ID') or hashlib.sha256(str(ROOT).encode()).hexdigest()[:32].translate(str.maketrans('0123456789abcdef', 'abcdefghijklmnop'))
INSTALL = Path.home() / '.local/share/chatgpt-dictation'
env = dict(os.environ, DISPLAY=DISPLAY, DICTATION_SOCKET=str(WORK / 'daemon.sock'), XDG_CACHE_HOME=str(CACHE),
           XDG_CONFIG_HOME=str(CONFIG), DICTATION_CHROME_PROFILE=str(PROFILE),
           DICTATION_CHROME_COMMAND=json.dumps([
               'google-chrome', f'--user-data-dir={PROFILE}', '--no-startup-window', '--keep-alive-for-test',
               '--no-first-run', '--no-default-browser-check', f'--remote-debugging-port={PORT}',
               '--enable-unsafe-extension-debugging']))
bridge = WORK / 'bridge'
bridge.write_text(f'#!/bin/sh\nexec /usr/bin/python3 {ROOT / "native/bridge.py"}\n')
bridge.chmod(0o755)
(PROFILE / 'NativeMessagingHosts/com.chelizi.chatgpt_dictation.json').write_text(json.dumps({
    'name': 'com.chelizi.chatgpt_dictation', 'description': 'test', 'path': str(bridge), 'type': 'stdio',
    'allowed_origins': [f'chrome-extension://{EXTENSION_ID}/']}))
procs = []


def read(name):
    try:
        return json.loads((CACHE / 'chatgpt-dictation' / name).read_text())
    except (OSError, ValueError):
        return {}


def status():
    return read('desktop-status.json')


def hud():
    return read('hud-status.json')


def wait_for(fn, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            value = fn()
        except Exception:
            value = None
        if value:
            return value
        time.sleep(.1)
    raise RuntimeError(f'timeout; status={status()} hud={hud()}')


def cdp(*args):
    out = subprocess.run(['node', str(HERE / 'cdp.mjs'), PORT, *args], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def chrome_pids():
    out = subprocess.run(['pgrep', '-f', '--', f'--user-data-dir={PROFILE}'], capture_output=True, text=True).stdout
    return [int(p) for p in out.split()]


def press_f9(D):
    code = D.keysym_to_keycode(XK.string_to_keysym('F9'))
    xtest.fake_input(D, X.KeyPress, code)
    xtest.fake_input(D, X.KeyRelease, code)
    D.sync()


result = {}
try:
    procs.append(subprocess.Popen(['Xephyr', DISPLAY, '-screen', '1280x800', '-ac', '-br', '-noreset'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(1.5)
    assert not chrome_pids()
    procs.append(subprocess.Popen([str(INSTALL / 'venv/bin/python'), str(ROOT / 'native/daemon.py')], env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait_for(lambda: status().get('pid'), 10)
    procs.append(subprocess.Popen(['/usr/bin/python3', str(HERE.parent / 'real/desktop-fixture.py')], env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(2)
    D = display.Display(DISPLAY)

    def focus_id():
        focus = D.get_input_focus().focus
        return focus if isinstance(focus, int) else focus.id

    def find(window, title):
        for child in window.query_tree().children:
            name = child.get_full_property(D.intern_atom('_NET_WM_NAME'), X.AnyPropertyType)
            if name and bytes(name.value).decode(errors='replace') == title:
                return child
            found = find(child, title)
            if found:
                return found

    # No window manager in Xephyr: give the input window focus explicitly.
    fixture = wait_for(lambda: find(D.screen().root, '后台听写桌面验收'), 10)
    fixture.set_input_focus(X.RevertToParent, X.CurrentTime)
    D.sync()
    focus_before = focus_id()

    # 1. F9 with Chrome closed: the daemon starts it and holds the key.
    pressed = time.time()
    press_f9(D)
    result['hudWhileLaunching'] = wait_for(lambda: hud() if hud().get('detail') == '正在启动 Chrome…' else None, 5)
    wait_for(chrome_pids, 10)
    result['chromeRunningAfterS'] = round(time.time() - pressed, 2)
    time.sleep(3)
    assert chrome_pids(), 'windowless Chrome quit'
    result['windowlessChromeStaysAlive'] = True
    cdp('load', str(ROOT))
    wait_for(lambda: status().get('connected'), 20)
    result['extensionConnectedAfterS'] = round(time.time() - pressed, 2)
    # The replayed F9 reached the extension; this fresh profile has no dedicated page yet.
    first = wait_for(lambda: status() if status().get('phase') == 'error' else None, 20)
    assert '专用' in first.get('status', ''), first
    result['replayedKeyAnswer'] = first['status']

    # 2. Initialised, Chrome still without any window: F9 opens the page minimized, focus stays.
    cdp('eval', EXTENSION_ID, 'chrome.storage.local.set({backendInitialized:true})')
    time.sleep(1)
    press_f9(D)
    result['hudOpeningBackend'] = wait_for(lambda: hud() if hud().get('detail') == '正在打开 ChatGPT…' else None, 15)
    pages = wait_for(lambda: [u for u in json.loads(cdp('pages')) if 'chatgpt.com' in u], 20)
    windows = json.loads(cdp('eval', EXTENSION_ID, 'chrome.windows.getAll().then(w=>w.map(x=>x.state))'))
    time.sleep(2)
    result.update(backendPages=pages, chromeWindowStates=windows, focusKept=focus_id() == focus_before)
    # Xephyr has no window manager, so the window cannot actually be iconified here; on the
    # GNOME desktop it is minimized. What matters for pasting is that focus stayed on the input.
    assert len(windows) == 1, windows
    assert result['focusKept']
    result['pass'] = True
    print('PASS', json.dumps(result, ensure_ascii=False), flush=True)
finally:
    for pid in chrome_pids():
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    for proc in reversed(procs):
        proc.terminate()
    (ROOT / 'tests/real/results-launch-chrome.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
