#!/usr/bin/env python3
"""Per-user dictation daemon for the X11 desktop session.

Owns the global F9/F8 keys, the floating status panel, the microphone level meter and
desktop paste. It runs independently of Chrome (started at login); the extension reaches
it through bridge.py, Chrome's native-messaging host, over a Unix socket. When F9 is
pressed and no extension is connected, the daemon starts Chrome in the background and
replays the key once the extension connects.
"""
import array
import collections
import hashlib
import json
import os
import select
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from Xlib import X, XK, display
from Xlib.ext import xtest

try:
    import pulsectl
except ImportError:  # The level meter is optional; dictation works without it.
    pulsectl = None

HERE = Path(__file__).resolve().parent
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}')
# Audio tools (pulsectl, pw-record) need it; a daemon started outside the session may lack it.
os.environ.setdefault('XDG_RUNTIME_DIR', str(RUNTIME))
SOCKET_PATH = Path(os.environ.get('DICTATION_SOCKET', str(RUNTIME / 'chatgpt-dictation.sock')))
CACHE = Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache'))) / 'chatgpt-dictation'
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'chatgpt-dictation'
# Chrome started for dictation opens no window. Without one Chrome would quit right away;
# --keep-alive-for-test keeps it running in the background (it then also stays after the
# last window is closed, which dictation needs). Tests point these at an isolated profile.
CHROME_COMMAND = json.loads(os.environ.get('DICTATION_CHROME_COMMAND',
                                           '["google-chrome", "--no-startup-window", "--keep-alive-for-test"]'))
CHROME_PROFILE = os.environ.get('DICTATION_CHROME_PROFILE')

KEYS = {'F9': 'toggle', 'F8': 'cancel'}
LOCK_MASKS = [0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask]
DEFAULT_SETTINGS = {'autoHide': False, 'sounds': False, 'autoStopOnPause': False, 'sleeping': False}
SOUNDS = {'start': 'message-new-instant', 'done': 'complete', 'warning': 'dialog-warning', 'error': 'dialog-error'}
ACTIVE_PHASES = {'starting', 'recording', 'transcribing', 'cancelling'}
MAX_TEXT = 512 * 1024
VOICE_LEVEL = 0.05        # peak level (0..1) treated as speech
SILENCE_WARNING_S = 4     # no speech at all for this long -> "check the microphone"
PAUSE_STOP_S = 3          # optional auto-finish after this much silence following speech
LIMIT_WARNING_S = 60      # warn this long before the recording limit
CHROME_LAUNCH_TIMEOUT_S = 45
EXTENSION_CONNECT_TIMEOUT_S = 8
HISTORY_SIZE = 10
DEBUG = bool(os.environ.get('DICTATION_DEBUG'))


def debug(*parts):
    if DEBUG:
        with (CACHE / 'daemon-debug.log').open('a') as f:
            f.write(f'{time.time():.3f} ' + ' '.join(str(p) for p in parts) + '\n')


def write_json(path, data, mode=0o600):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.chmod(mode)
    tmp.replace(path)


def chrome_running():
    """True if a Chrome browser process (not a helper) for our profile exists."""
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if (proc / 'comm').read_text().strip() != 'chrome':
                continue
            args = (proc / 'cmdline').read_bytes().split(b'\0')
        except OSError:
            continue
        if any(a.startswith(b'--type=') for a in args):
            continue
        dirs = [a.split(b'=', 1)[1].decode(errors='replace') for a in args if a.startswith(b'--user-data-dir=')]
        if CHROME_PROFILE:
            if CHROME_PROFILE in dirs:
                return True
        elif not dirs:
            return True
    return False


def set_clipboard(text):
    subprocess.run(['xclip', '-selection', 'clipboard', '-in'], input=text.encode(),
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2, check=True)


def get_clipboard():
    try:
        return subprocess.run(['xclip', '-selection', 'clipboard', '-out'], capture_output=True,
                              timeout=.5, check=True).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


class Lines:
    """Newline-delimited JSON over a byte stream."""

    def __init__(self):
        self.buffer = b''

    def feed(self, chunk):
        self.buffer += chunk
        *lines, self.buffer = self.buffer.split(b'\n')
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out


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
                    ['/usr/bin/python3', str(HERE / 'overlay.py')], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
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


class Meter:
    """Peak level of the microphone Chrome records from, via a parallel pw-record stream.

    Audio is only reduced to a peak value per chunk; nothing is stored.
    """

    def __init__(self):
        self.proc = None
        self.source = None
        self.pulse = None
        self.rest = b''

    def refresh(self):
        source = self._chrome_source()
        if source != self.source:
            self._kill()
            self.source = source
            if source:
                self._start(source)

    def _chrome_source(self):
        if pulsectl is None:
            return None
        try:
            if self.pulse is None:
                self.pulse = pulsectl.Pulse('chatgpt-dictation-meter')
            streams = [s for s in self.pulse.source_output_list()
                       if 'chrome' in s.proplist.get('application.name', '').lower()]
            return self.pulse.source_info(streams[-1].source).name if streams else None
        except Exception:
            self._close_pulse()
            return None

    def _start(self, source):
        args = ['pw-record', '--rate', '8000', '--channels', '1', '--format', 's16', '--latency', '50ms']
        if source.endswith('.monitor'):
            args += ['--target', source[:-len('.monitor')], '-P', '{ stream.capture.sink=true }']
        else:
            args += ['--target', source]
        try:
            self.proc = subprocess.Popen(args + ['-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            self.proc = None
        self.rest = b''

    def fileno(self):
        return self.proc.stdout.fileno() if self.proc else None

    def read(self):
        chunk = os.read(self.proc.stdout.fileno(), 8192)
        if not chunk:
            self._kill()
            return None
        data = self.rest + chunk
        even = len(data) // 2 * 2
        self.rest = data[even:]
        samples = array.array('h', data[:even])
        return max(map(abs, samples)) / 32768 if samples else None

    def _kill(self):
        if self.proc:
            self.proc.kill()
            self.proc.wait()
            self.proc.stdout.close()
        self.proc = None

    def _close_pulse(self):
        if self.pulse:
            try:
                self.pulse.close()
            except Exception:
                pass
        self.pulse = None

    def stop(self):
        self._kill()
        self._close_pulse()
        self.source = None


class Daemon:
    def __init__(self):
        CACHE.mkdir(mode=0o700, parents=True, exist_ok=True)
        CONFIG.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.settings_path = CONFIG / 'settings.json'
        try:
            self.settings = {**DEFAULT_SETTINGS, **json.loads(self.settings_path.read_text())}
        except (OSError, ValueError):
            self.settings = dict(DEFAULT_SETTINGS)
        self.status = {'pid': os.getpid(), 'connected': False, 'phase': 'idle', 'keys': {'toggle': 'F9', 'cancel': 'F8'},
                       'sleeping': self.settings['sleeping']}
        self.phase = 'idle'
        self.closing = False
        self.bridge = None
        self.bridge_lines = Lines()
        self.extension_ready = False
        self.pending = None          # key replayed once Chrome/the extension connects
        self.serial = 0
        self.restore = []            # clipboard restores: (deadline, our_text, previous)
        self.history = collections.deque(maxlen=HISTORY_SIZE)
        self.recording = None        # per-recording meter/limit bookkeeping
        self.meter = Meter()
        self.panel = Panel()
        self.panel.on_spawn = self.push_menu
        self.d = display.Display()
        self.root = self.d.screen().root
        self.active_atom = self.d.intern_atom('_NET_ACTIVE_WINDOW')
        self.codes = {self.d.keysym_to_keycode(XK.string_to_keysym(name)): action for name, action in KEYS.items()}
        self.cancel_code = next(code for code, action in self.codes.items() if action == 'cancel')
        self.timings = CACHE / 'timings.jsonl'
        self.grab_retry = None       # monotonic time of the next attempt while F9/F8 are taken

    # ---- state -------------------------------------------------------------------------------
    @property
    def sleeping(self):
        return self.settings['sleeping']

    def save_settings(self):
        write_json(self.settings_path, self.settings)

    def record(self, **values):
        self.status.update(values)
        write_json(CACHE / 'desktop-status.json', self.status)

    def show(self, phase, status='', **extra):
        if self.sleeping:
            return
        self.panel.send({'phase': phase, 'status': status, **{k: v for k, v in extra.items() if v is not None}})

    def push_menu(self):
        history = [{'text': h['text'], 'at': h['at']} for h in self.history]
        message = {'type': 'menu', 'history': history, 'settings': self.settings}
        line = (json.dumps(message, ensure_ascii=False) + '\n').encode()
        try:
            self.panel.proc.stdin.write(line)
            self.panel.proc.stdin.flush()
        except (OSError, AttributeError):
            pass

    def update_setting(self, key, value):
        if key in DEFAULT_SETTINGS and key != 'sleeping':
            self.settings[key] = bool(value)
            self.save_settings()
            self.push_menu()

    def sound(self, name):
        if self.settings['sounds']:
            try:
                subprocess.Popen(['canberra-gtk-play', '-i', SOUNDS[name]], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            except FileNotFoundError:
                pass

    def set_sleep(self, value):
        self.closing = False
        self.settings['sleeping'] = value
        self.save_settings()
        if value:
            self.root.ungrab_key(self.cancel_code, X.AnyModifier)
            self.d.sync()
            self.stop_recording()
            self.panel.close()
            self.record(phase='sleeping', sleeping=True, status='听写已关闭，按 F9 重新打开。')
        else:
            self.grab(self.cancel_code)
            self.record(sleeping=False)

    # ---- X11 keys and paste ------------------------------------------------------------------
    def grab(self, code):
        errors = []
        for mask in LOCK_MASKS:
            self.root.grab_key(code, mask, False, X.GrabModeAsync, X.GrabModeAsync,
                               onerror=lambda error, request: errors.append(str(error)))
        self.d.sync()
        return not errors

    def focus(self):
        prop = self.root.get_full_property(self.active_atom, X.AnyPropertyType)
        window = int(prop.value[0]) if prop is not None and len(prop.value) else 0
        child = self.d.get_input_focus().focus
        return {'window': window, 'focus': int(child.id) if hasattr(child, 'id') else int(child)}

    @staticmethod
    def same_target(now, target):
        # Toolkits move focus between a top-level window and its own focus child right after
        # activation; only a different top-level window or a different child counts as a change.
        if not isinstance(target, dict) or now['window'] != target.get('window'):
            return False
        return now['focus'] == target.get('focus') or now['window'] in (now['focus'], target.get('focus'))

    def key_down(self, code):
        keymap = self.d.query_keymap()
        return bool(keymap[code // 8] & (1 << (code % 8)))

    def on_x_events(self):
        while self.d.pending_events():
            event = self.d.next_event()
            # Act on release so F9 is no longer held when a short result is pasted. Holding a
            # key makes X send repeated release/press pairs while it stays down: ignore those.
            if event.type not in (X.KeyPress, X.KeyRelease) or event.detail not in self.codes:
                continue
            down = self.key_down(event.detail) if event.type == X.KeyRelease else None
            debug('key', 'press' if event.type == X.KeyPress else 'release', event.detail, event.time, 'down' if down else '')
            if event.type != X.KeyRelease or down:
                continue
            self.on_key(self.codes[event.detail])

    def on_key(self, action, key_at=None):
        key_at = key_at or time.time()
        target = self.focus()
        self.record(lastKey='F9' if action == 'toggle' else 'F8', lastKeyAt=key_at, lastKeyTarget=target)
        if self.closing:
            return
        if self.sleeping:
            if action == 'cancel':
                return
            self.set_sleep(False)
        if action == 'cancel' and self.pending:
            self.pending = None
            self.show('cancelled', '已取消启动。')
            return
        if not self.extension_ready:
            if action == 'toggle':
                self.connect_chrome({'action': 'toggle', 'target': target, 'keyAt': int(key_at * 1000)})
            return
        if action == 'toggle' and self.phase in ['idle', 'done', 'cancelled', 'error', 'sleeping']:
            self.show('starting', '正在准备后台 ChatGPT 听写页。')
        elif action == 'toggle' and self.phase == 'recording':
            self.show('transcribing', 'F8 可以取消等待。')
        elif action == 'cancel':
            self.show('cancelling')
        self.command(action, target=target, keyAt=int(key_at * 1000))

    def command(self, action, **fields):
        debug('command', action, fields.get('keyAt'))
        self.serial += 1
        self.send_bridge({'type': 'desktop-command', 'action': action, 'requestId': str(self.serial), **fields})

    def paste(self, text, target):
        if self.sleeping or self.closing:
            raise ValueError('听写已关闭，本次转写不会插入。')
        if not isinstance(text, str) or not text or len(text.encode()) > MAX_TEXT:
            raise ValueError('转写文字为空或过长。')
        if not self.same_target(self.focus(), target):
            raise ValueError('输入窗口或焦点已改变，右键悬浮窗可复制这次的文字。')
        # Plain UTF-8 text only; rich clipboard formats cannot be losslessly restored.
        previous = get_clipboard()
        if not self.same_target(self.focus(), target):
            raise ValueError('输入焦点已改变，右键悬浮窗可复制这次的文字。')
        set_clipboard(text)
        if not self.same_target(self.focus(), target):
            raise ValueError('输入焦点已改变，文字已放入剪贴板。')
        # Never generate Return: chat text is inserted, never sent.
        keys = [self.d.keysym_to_keycode(XK.string_to_keysym(k)) for k in ['Control_L', 'v']]
        for k in keys:
            xtest.fake_input(self.d, X.KeyPress, k)
        for k in reversed(keys):
            xtest.fake_input(self.d, X.KeyRelease, k)
        self.d.sync()
        self.restore.append((time.monotonic() + 1.5, text.encode(), previous))
        self.record(lastInsertLength=len(text), lastInsertSHA256=hashlib.sha256(text.encode()).hexdigest(),
                    lastInsertTarget=target, lastInsertAt=time.time())

    def restore_clipboard(self):
        now = time.monotonic()
        for item in self.restore[:]:
            deadline, ours, previous = item
            if now < deadline:
                continue
            self.restore.remove(item)
            # Restore only if nobody copied something else in the meantime.
            if previous is not None and get_clipboard() == ours:
                try:
                    subprocess.run(['xclip', '-selection', 'clipboard', '-in'], input=previous,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2, check=True)
                except subprocess.SubprocessError:
                    pass

    # ---- Chrome connection -------------------------------------------------------------------
    def connect_chrome(self, command):
        if chrome_running():
            detail, timeout = '正在连接 Chrome 扩展…', EXTENSION_CONNECT_TIMEOUT_S
        else:
            detail, timeout = '正在启动 Chrome…', CHROME_LAUNCH_TIMEOUT_S
            try:
                subprocess.Popen(CHROME_COMMAND, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError as e:
                self.show('error', f'无法启动 Chrome：{e}')
                return
        self.pending = {**command, 'deadline': time.monotonic() + timeout, 'launchedAt': time.time()}
        self.record(pending=command['action'])
        self.show('starting', detail, detail=detail)

    def flush_pending(self):
        pending, self.pending = self.pending, None
        self.record(pending=None)
        if not pending:
            return
        action = pending.pop('action')
        pending.pop('deadline')
        pending.pop('launchedAt')
        if action == 'toggle':
            self.show('starting', '正在准备后台 ChatGPT 听写页。')
        self.command(action, **pending)

    def accept_bridge(self, server):
        conn, _ = server.accept()
        conn.setblocking(False)
        if self.bridge:
            self.bridge.close()
        self.bridge, self.bridge_lines, self.extension_ready = conn, Lines(), False
        self.record(connected=True)
        self.send_bridge({'type': 'hello'})

    def drop_bridge(self):
        if self.bridge:
            self.bridge.close()
        self.bridge, self.extension_ready = None, False
        self.record(connected=False)
        if self.phase in ACTIVE_PHASES:
            self.stop_recording()
            self.phase = 'error'
            self.show('error', 'Chrome 连接已断开，本次听写已中止。')

    def send_bridge(self, message):
        if not self.bridge:
            return
        data = (json.dumps(message, ensure_ascii=False) + '\n').encode()
        try:
            self.bridge.setblocking(True)
            self.bridge.sendall(data)
            self.bridge.setblocking(False)
        except OSError:
            self.drop_bridge()

    def on_bridge(self, message):
        kind = message.get('type')
        debug('from-extension', kind, message.get('phase', ''), message.get('action', ''))
        if kind == 'mode':
            self.extension_ready = True
            # Test-only knob: a shorter recording limit from settings.json.
            if self.settings.get('recordLimitMs'):
                self.send_bridge({'type': 'config', 'recordLimitMs': self.settings['recordLimitMs']})
            if self.pending:
                # The user pressed F9 to start: that wakes dictation whatever the stored mode.
                if self.sleeping:
                    self.set_sleep(False)
                self.flush_pending()
            elif self.sleeping and not message.get('sleeping'):
                # Closed from the panel while Chrome was away: close the extension side too.
                self.command('sleep')
            else:
                self.set_sleep(bool(message.get('sleeping')))
                if not self.sleeping:
                    self.show('idle')
        elif kind == 'command-result' and message.get('action') == 'sleep' and not message.get('ok'):
            self.closing = False
            self.record(phase='error', status=message.get('error'))
            self.show('error', message.get('error', '关闭未完成，请重试。'))
        elif kind == 'status':
            self.on_status(message)
        elif kind == 'insert':
            text, target = message.get('text'), message.get('target')
            if isinstance(text, str) and text:
                self.history.appendleft({'text': text, 'at': time.strftime('%H:%M')})
                self.push_menu()
            try:
                self.paste(text, target)
                answer = {'ok': True}
            except Exception as e:
                answer = {'ok': False, 'error': str(e)}
            self.send_bridge({'type': 'insert-result', 'requestId': message.get('requestId'), **answer})
        elif kind == 'timing' and isinstance(message.get('entry'), dict):
            self.log_timing(message['entry'])

    def on_status(self, message):
        phase = message.get('phase', 'idle')
        if phase == 'sleeping':
            self.set_sleep(True)
            return
        if self.closing or self.sleeping:
            return
        previous, self.phase = self.phase, phase
        self.record(phase=phase, status=message.get('status'), lastCommandOk=message.get('ok'))
        if phase == 'recording' and previous != 'recording':
            self.start_recording(message.get('limitMs') or 480000)
            self.sound('start')
        elif phase != 'recording' and previous == 'recording':
            self.stop_recording()
        if phase == 'done':
            self.sound('done')
        elif phase == 'error':
            self.sound('error')
        extra = {k: message[k] for k in ['detail', 'fix', 'limitMs'] if message.get(k)}
        self.show(phase, message.get('status', ''), **extra)

    def log_timing(self, entry):
        # Per-dictation latency breakdown from the extension; keep the newest 500 entries.
        try:
            with self.timings.open('a') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            lines = self.timings.read_text().splitlines()
            if len(lines) > 1000:
                self.timings.write_text('\n'.join(lines[-500:]) + '\n')
        except OSError:
            pass

    # ---- recording: meter, silence and limit ---------------------------------------------------
    def start_recording(self, limit_ms):
        now = time.monotonic()
        self.recording = {'start': now, 'limit': limit_ms / 1000, 'voice': False, 'lastVoice': None,
                          'silentWarned': False, 'limitWarned': False, 'pauseStopped': False, 'nextRefresh': now}
        self.meter.stop()

    def stop_recording(self):
        self.recording = None
        self.meter.stop()

    def on_level(self, level):
        rec = self.recording
        if rec is None or level is None:
            return
        self.panel.send({'type': 'level', 'value': round(level, 3)})
        if level >= VOICE_LEVEL:
            rec['voice'], rec['lastVoice'] = True, time.monotonic()
            if rec['silentWarned']:
                rec['silentWarned'] = False
                self.panel.send({'type': 'detail', 'text': ''})

    def recording_tick(self):
        rec = self.recording
        if rec is None:
            return
        now = time.monotonic()
        if now >= rec['nextRefresh']:
            # Chrome's capture stream can appear late or move to another device.
            rec['nextRefresh'] = now + 1.5
            self.meter.refresh()
        elapsed = now - rec['start']
        if self.meter.source and not rec['voice'] and elapsed > SILENCE_WARNING_S and not rec['silentWarned']:
            rec['silentWarned'] = True
            self.panel.send({'type': 'detail', 'text': '没有检测到声音，请检查麦克风'})
        if (self.settings['autoStopOnPause'] and rec['voice'] and not rec['pauseStopped']
                and now - rec['lastVoice'] > PAUSE_STOP_S):
            rec['pauseStopped'] = True
            self.show('transcribing', '检测到停顿，自动结束。', detail='检测到停顿，自动结束并转写')
            self.command('toggle', target=self.focus(), keyAt=int(time.time() * 1000))
        if rec['limit'] - elapsed <= LIMIT_WARNING_S and not rec['limitWarned']:
            rec['limitWarned'] = True
            self.sound('warning')

    # ---- panel actions -------------------------------------------------------------------------
    def on_panel(self, message):
        action = message.get('action')
        if action == 'sleep':
            if self.closing or self.sleeping:
                return
            if self.extension_ready:
                self.closing = True
                self.record(phase='closing')
                self.show('closing', '正在停止录音并关闭专用页。')
                self.command('sleep')
            else:
                self.set_sleep(True)
        elif action == 'copy':
            index = message.get('index', 0)
            if 0 <= index < len(self.history):
                try:
                    set_clipboard(self.history[index]['text'])
                    self.show('copied', '已复制到剪贴板。')
                except (subprocess.SubprocessError, FileNotFoundError):
                    self.show('error', '复制失败，请确认已安装 xclip。')
        elif action == 'open-backend':
            if self.extension_ready:
                self.command('open-backend')
            else:
                self.connect_chrome({'action': 'open-backend'})
        elif action == 'setting':
            self.update_setting(message.get('key'), message.get('value'))

    # ---- main loop -------------------------------------------------------------------------------
    def timeout(self):
        deadlines = [d for d, _, _ in self.restore]
        if self.pending:
            deadlines.append(self.pending['deadline'])
        if self.recording:
            deadlines.append(time.monotonic() + 0.5)
        if self.grab_retry is not None:
            deadlines.append(self.grab_retry)
        return max(0, min(deadlines) - time.monotonic()) if deadlines else None

    def grab_keys(self):
        ok = all(self.grab(code) for code in self.codes if not (code == self.cancel_code and self.sleeping))
        if ok:
            if self.grab_retry is not None:
                self.record(error=None)
                self.show('idle')
            self.grab_retry = None
        else:
            # Another program (or a previous instance shutting down) holds the keys: retry.
            if self.grab_retry is None:
                self.record(error='F9/F8 已被其他全局快捷键占用。')
                self.show('error', 'F9/F8 已被其他程序占用，正在重试。')
            self.grab_retry = time.monotonic() + 5

    def run(self, server):
        self.grab_keys()
        self.record()
        if not self.sleeping and self.grab_retry is None:
            self.show('idle')
        x_fd = self.d.fileno()
        while True:
            self.on_x_events()  # Xlib may already hold events read during other requests.
            sources = {server.fileno(): 'server', x_fd: 'x'}
            for name, fd in [('bridge', self.bridge.fileno() if self.bridge else None),
                             ('panel', self.panel.fileno()), ('meter', self.meter.fileno())]:
                if fd is not None:
                    sources[fd] = name
            ready, _, _ = select.select(list(sources), [], [], self.timeout())
            for fd in ready:
                kind = sources[fd]
                if kind == 'server':
                    self.accept_bridge(server)
                elif kind == 'bridge' and self.bridge and self.bridge.fileno() == fd:
                    try:
                        chunk = self.bridge.recv(65536)
                    except BlockingIOError:
                        continue
                    except OSError:
                        chunk = b''
                    if not chunk:
                        self.drop_bridge()
                        continue
                    for message in self.bridge_lines.feed(chunk):
                        self.on_bridge(message)
                elif kind == 'panel' and self.panel.fileno() == fd:
                    for message in self.panel.read():
                        self.on_panel(message)
                elif kind == 'meter' and self.meter.fileno() == fd:
                    self.on_level(self.meter.read())
            self.restore_clipboard()
            self.recording_tick()
            if self.grab_retry is not None and time.monotonic() >= self.grab_retry:
                self.grab_keys()
            if self.pending and time.monotonic() > self.pending['deadline']:
                self.pending = None
                self.record(pending=None)
                self.show('error', 'Chrome 扩展没有连接上。请确认扩展已启用，然后再按 F9。')

    def shutdown(self):
        for code in self.codes:
            for mask in LOCK_MASKS:
                self.root.ungrab_key(code, mask)
        self.d.sync()
        self.d.close()
        self.meter.stop()
        self.panel.close()
        self.record(connected=False, running=False)


def listen():
    """Bind the daemon socket, or return None if another daemon already serves it."""
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.connect(str(SOCKET_PATH))
        probe.close()
        return None
    except OSError:
        probe.close()
    SOCKET_PATH.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o177)
    try:
        server.bind(str(SOCKET_PATH))
    finally:
        os.umask(old)
    server.listen(2)
    server.setblocking(False)
    return server


def main():
    server = listen()
    if server is None:
        print('chatgpt-dictation daemon already running', file=sys.stderr)
        return
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    daemon = Daemon()
    (CACHE / 'daemon.pid').write_text(str(os.getpid()))
    try:
        daemon.run(server)
    finally:
        daemon.shutdown()
        server.close()
        SOCKET_PATH.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
