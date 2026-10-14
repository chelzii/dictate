"""Shared helpers for the real acceptance tests (real Chrome extension + real ChatGPT).

Known Mandarin speech is fed through a temporary virtual microphone; the ChatGPT
transcription itself is never mocked. Test-only Python dependencies (python-xlib,
pulsectl, pillow) are looked up in tests/.deps, or /tmp/dictation-real-test-deps:
    pip install --target tests/.deps python-xlib pulsectl pillow
"""
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
for deps in [HERE.parent / '.deps', Path('/tmp/dictation-real-test-deps')]:
    if deps.is_dir():
        sys.path.insert(0, str(deps))

import pulsectl  # noqa: E402
from Xlib import X, XK, display, protocol  # noqa: E402
from Xlib.ext import xtest  # noqa: E402

UID = os.getuid()
ENV = dict(os.environ, XDG_RUNTIME_DIR=f'/run/user/{UID}')
PULSE = f'unix:/run/user/{UID}/pulse/native'
CACHE = Path.home() / '.cache/chatgpt-dictation'
SPEECH = Path(os.environ.get('DICTATION_TEST_SPEECH', '/tmp/dictation-real-test-zh.wav'))
EXPECTED = ['今天', '下午', '开会', '提前', '准备', '会议', '资料']
DESKTOP_FIXTURE = Path('/tmp/dictation-desktop-fixture.json')
BROWSER_FIXTURE = Path('/tmp/dictation-browser-fixture.json')

D = display.Display()
root = D.screen().root


def status():
    return json.loads((CACHE / 'desktop-status.json').read_text())


def hud():
    return json.loads((CACHE / 'hud-status.json').read_text())


def timings():
    return [json.loads(line) for line in (CACHE / 'timings.jsonl').read_text().splitlines()]


def desktop_text():
    return json.loads(DESKTOP_FIXTURE.read_text())['text']


def correct(text):
    return all(word in text for word in EXPECTED)


def wait_for(fn, timeout=100, interval=.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(interval)
    raise RuntimeError('Wait timed out: ' + json.dumps(status(), ensure_ascii=False))


def windows():
    found = []
    for wid in root.get_full_property(D.intern_atom('_NET_CLIENT_LIST'), X.AnyPropertyType).value:
        w = D.create_resource_object('window', int(wid))
        p = w.get_full_property(D.intern_atom('_NET_WM_NAME'), X.AnyPropertyType)
        found.append((w, bytes(p.value).decode(errors='replace') if p else '', w.get_wm_class()))
    return found


def activate(title):
    candidates = [w for w, t, c in windows() if title in t]
    assert len(candidates) == 1, [t for w, t, c in windows()]
    w = candidates[0]
    root.send_event(protocol.event.ClientMessage(window=w, client_type=D.intern_atom('_NET_ACTIVE_WINDOW'),
                                                 data=(32, [2, X.CurrentTime, 0, 0, 0])),
                    event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
    w.set_input_focus(X.RevertToParent, X.CurrentTime)
    D.sync()
    # Wait until the toolkit has moved focus to its focus child and it stays there.
    last, stable_since, end = None, time.monotonic(), time.monotonic() + 2
    while time.monotonic() < end:
        focus = D.get_input_focus().focus
        focus = focus if isinstance(focus, int) else focus.id
        if focus != last:
            last, stable_since = focus, time.monotonic()
        elif time.monotonic() - stable_since > .5:
            break
        time.sleep(.05)
    return w.id


def close_window(title):
    for w, t, c in windows():
        if t.startswith(title):
            root.send_event(protocol.event.ClientMessage(window=w, client_type=D.intern_atom('_NET_CLOSE_WINDOW'),
                                                         data=(32, [X.CurrentTime, 2, 0, 0, 0])),
                            event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
    D.sync()


def key(*names):
    codes = [D.keysym_to_keycode(XK.string_to_keysym(n)) for n in names]
    for k in codes:
        xtest.fake_input(D, X.KeyPress, k)
    for k in reversed(codes):
        xtest.fake_input(D, X.KeyRelease, k)
    D.sync()


def clear():
    key('Control_L', 'a')
    key('BackSpace')
    time.sleep(.1)


def click_at(x, y, button=1):
    xtest.fake_input(D, X.MotionNotify, x=int(x), y=int(y))
    xtest.fake_input(D, X.ButtonPress, button)
    xtest.fake_input(D, X.ButtonRelease, button)
    D.sync()


def panel_window():
    panels = [w for w, t, c in windows() if t == '后台听写状态' and w.get_attributes().map_state == X.IsViewable]
    return panels[0] if len(panels) == 1 else None


def geometry(w):
    g = w.get_geometry()
    xy = root.translate_coords(w, 0, 0)
    return xy.x, xy.y, g.width, g.height


def menu_window():
    for w in root.query_tree().children:
        if w.get_attributes().map_state != X.IsViewable:
            continue
        prop = w.get_full_property(D.intern_atom('_NET_WM_WINDOW_TYPE'), X.AnyPropertyType)
        if prop and D.intern_atom('_NET_WM_WINDOW_TYPE_POPUP_MENU') in prop.value:
            return w
    return None


def screenshot(w, path, pad=0):
    from PIL import ImageGrab
    x, y, width, height = geometry(w)
    ImageGrab.grab(xdisplay=os.environ.get('DISPLAY', ':1'),
                   bbox=(x - pad, y - pad, x + width + pad, y + height + pad)).save(path)


@contextmanager
def fixtures(browser=False):
    """The GTK desktop input window (and optionally the local browser page)."""
    procs = [subprocess.Popen(['/usr/bin/python3', str(HERE / 'desktop-fixture.py')],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    if browser:
        procs.append(subprocess.Popen(['/usr/bin/python3', '-I', str(HERE / 'browser-fixture.py')],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        time.sleep(1)
        subprocess.Popen(['google-chrome', '--new-window', 'http://127.0.0.1:18769/'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_for(lambda: any('后台听写桌面验收' in t for _, t, _ in windows()), 10)
    if browser:
        wait_for(lambda: any(t.startswith('后台听写浏览器验收') for _, t, _ in windows()), 15)
    try:
        yield
    finally:
        if browser:
            close_window('后台听写浏览器验收')
        for proc in procs:
            proc.terminate()


class VirtualMic:
    """Temporary null sink; Chrome's capture stream is moved to its monitor and fed known speech."""

    def __enter__(self):
        self.pulse = pulsectl.Pulse('dictation-acceptance', server=PULSE)
        self.module = self.pulse.module_load('module-null-sink',
                                             'sink_name=dictation_test_sink sink_properties=device.description=DictationTest')
        return self

    def __exit__(self, *exc):
        self.pulse.module_unload(self.module)
        self.pulse.close()

    def chrome_streams(self):
        return [s for s in self.pulse.source_output_list()
                if 'chrome' in s.proplist.get('application.name', '').lower()]

    def route_chrome(self):
        streams = wait_for(self.chrome_streams, 10)
        assert len(streams) == 1, streams
        source = next(s for s in self.pulse.source_list() if s.name == 'dictation_test_sink.monitor')
        self.pulse.source_output_move(streams[0].index, source.index)

    def play_async(self, path=SPEECH):
        return subprocess.Popen(['pw-cat', '--playback', '--target', 'dictation_test_sink', str(path)], env=ENV,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def play(self, path=SPEECH):
        subprocess.run(['pw-cat', '--playback', '--target', 'dictation_test_sink', str(path)], env=ENV, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def start_recording(mic, timeout=30):
    """Press F9 and wait until recording; returns the press time."""
    before = time.time()
    key('F9')
    wait_for(lambda: status().get('phase') == 'recording' and status().get('lastKeyAt', 0) >= before, timeout)
    mic.route_chrome()
    return before


def finish_and_wait(timeout=60):
    """Press F9 again and wait for the paste; returns the press time."""
    before = time.time()
    key('F9')
    wait_for(lambda: status().get('lastInsertAt', 0) > before, timeout)
    wait_for(lambda: status().get('phase') in ['done', 'error'], 20)
    return before


def restart_daemon(**settings):
    """Apply settings.json changes: stop the daemon; the extension's bridge restarts it on reconnect."""
    path = Path.home() / '.config/chatgpt-dictation/settings.json'
    data = json.loads(path.read_text())
    for k, v in settings.items():
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    path.write_text(json.dumps(data))
    old = int((CACHE / 'daemon.pid').read_text())
    os.kill(old, 15)
    wait_for(lambda: status().get('pid') != old and status().get('connected') and status().get('running') is not False, 30)
    time.sleep(1)


def save(name, data):
    (HERE / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
