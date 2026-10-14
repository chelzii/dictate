#!/usr/bin/python3
"""Movable dictation status capsule; it never accepts keyboard focus.

Input (JSON lines on stdin, from daemon.py):
  {"phase", "status", "detail"?, "fix"?, "limitMs"?}   status update
  {"type": "level", "value": 0..1}                       microphone peak while recording
  {"type": "detail", "text"}                             replace the live detail line
  {"type": "menu", "history": [...], "settings": {...}}  right-click menu state
Output (JSON lines on stdout): {"action": "sleep" | "copy" | "open-backend" | "setting", ...}
Its visible state is mirrored to hud-status.json for the acceptance tests.
"""
import json
import os
import sys
import time
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, GLib, Gtk

CACHE = Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache'))) / 'chatgpt-dictation'
CACHE.mkdir(parents=True, exist_ok=True)
HUD_STATE = CACHE / 'hud-status.json'
POSITION_FILE = CACHE / 'floating-position.json'

# phase -> (title, key hints, seconds before returning to idle)
PHASES = {
    'closing': ('正在关闭', [], 0),
    'idle': ('听写已就绪', [('F9', '开始')], 0),
    'starting': ('正在启动', [('F8', '取消')], 0),
    'recording': ('正在录音', [('F9', '结束'), ('F8', '取消')], 0),
    'transcribing': ('正在转写', [('F8', '取消')], 0),
    'cancelling': ('正在取消', [], 0),
    'done': ('已填入', [], 2.5),
    'copied': ('已复制', [], 2),
    'cancelled': ('已取消', [], 2.5),
    'error': ('听写未完成', [], 12),
}
BUSY = {'starting', 'transcribing', 'cancelling', 'closing'}
ICONS = {'done': 'object-select-symbolic', 'copied': 'edit-copy-symbolic', 'error': 'dialog-warning-symbolic',
         'cancelled': 'window-close-symbolic'}
FIX_HINTS = {'open-backend': '点击处理', 'copy': '点击复制'}
# Status texts that only repeat the title are not shown as a detail line.
REDUNDANT = {'听写已取消。', '文字已填入原输入框。'}
HINT_SECONDS = 4          # key hints first, then the remaining time
WARNING_SECONDS = 60
BAR_COUNT = 5
SHADOW = 8

CSS = '''
window {background-color:transparent;}
window.solid {background-color:#1d1f25;}
#panel {min-width:236px;background-color:#1d1f25;color:#eef0f4;border:1px solid rgba(255,255,255,.08);border-radius:20px;
  padding:9px 15px 9px 13px;box-shadow:0 3px 8px rgba(0,0,0,.40);font-family:"Ubuntu Sans",sans-serif;}
window.solid #panel {border-radius:0;box-shadow:none;}
#panel.has-detail {border-radius:14px;}
#panel.warning {border-color:rgba(242,184,75,.75);}
#title {font-size:13px;font-weight:600;}
#panel.idle:not(.hover) #title {color:rgba(238,240,244,.62);}
#panel.idle:not(.hover) #dot {opacity:.7;}
#timer {font-family:monospace;font-size:12px;color:#ff8f8f;}
#hint {font-size:11px;color:rgba(238,240,244,.55);}
#panel.warning #hint, #panel.warning #timer {color:#f2b84b;}
#panel.error #hint {color:#9ec3ff;}
#detail {font-size:11px;color:rgba(238,240,244,.72);}
#panel.warning #detail {color:#f2b84b;}
#dot {min-width:8px;min-height:8px;margin:4px;border-radius:50%;background-color:#5fb38f;}
#panel.recording #dot {background-color:#ff5c5c;animation:pulse 1.4s ease-out infinite;}
@keyframes pulse {from {box-shadow:0 0 0 0 rgba(255,92,92,.55);} to {box-shadow:0 0 0 6px rgba(255,92,92,0);}}
.bar {min-width:3px;border-radius:2px;background-color:rgba(255,143,143,.85);}
spinner {color:#f2b84b;}
#icon {color:#7c8696;}
#panel.done #icon, #panel.copied #icon {color:#5fd08e;}
#panel.error #icon {color:#ff7070;}
'''


def send(message):
    print(json.dumps(message, ensure_ascii=False), flush=True)


class Capsule:
    def __init__(self):
        self.phase = 'idle'
        self.record_started = 0
        self.limit = 480
        self.fix = None
        self.live_detail = ''      # from the daemon while a phase lasts (e.g. no sound)
        self.base_detail = ''      # came with the status, or the limit warning
        self.levels = [0.0] * BAR_COUNT
        self.history = []
        self.settings = {}
        self.drag = None
        self.press_at = None
        self.hovered = False
        self.pos = (0, 0)
        self.positioned = False
        self.last_snapshot = None
        self.tick_id = 0
        self.idle_id = 0
        try:
            self.saved_position = json.loads(POSITION_FILE.read_text())
        except (OSError, ValueError):
            self.saved_position = None
        self.build()

    # ---- widgets -----------------------------------------------------------------------------
    def build(self):
        w = self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        w.set_title('后台听写状态')
        w.set_decorated(False)
        w.set_resizable(False)
        w.set_accept_focus(False)
        w.set_focus_on_map(False)
        w.set_keep_above(True)
        w.set_skip_taskbar_hint(True)
        w.set_skip_pager_hint(True)
        w.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
        screen = w.get_screen()
        composited = screen.is_composited() and screen.get_rgba_visual() is not None
        if composited:
            w.set_visual(screen.get_rgba_visual())
        else:
            w.get_style_context().add_class('solid')
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # The whole capsule is the drag handle; the transparent margin leaves room for the shadow.
        box = self.event_box = Gtk.EventBox()
        box.set_visible_window(False)
        w.add(box)
        box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                       | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK
                       | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        panel = self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        panel.set_name('panel')
        box.add(panel)
        if composited:
            for side in ['top', 'bottom', 'start', 'end']:
                getattr(panel, 'set_margin_' + side)(SHADOW)
        row = Gtk.Box(spacing=8)
        panel.pack_start(row, False, False, 0)

        self.indicator = Gtk.Stack()
        self.indicator.set_size_request(16, 16)
        row.pack_start(self.indicator, False, False, 0)
        dot = Gtk.Box()
        dot.set_name('dot')
        dot.set_halign(Gtk.Align.CENTER)
        dot.set_valign(Gtk.Align.CENTER)
        self.indicator.add_named(dot, 'dot')
        self.spinner = Gtk.Spinner()
        self.indicator.add_named(self.spinner, 'spinner')
        self.icon = Gtk.Image()
        self.icon.set_name('icon')
        self.icon.set_pixel_size(14)
        self.indicator.add_named(self.icon, 'icon')

        self.title = Gtk.Label()
        self.title.set_name('title')
        self.title.set_xalign(0)
        row.pack_start(self.title, False, False, 0)
        self.timer = Gtk.Label()
        self.timer.set_name('timer')
        self.timer.set_width_chars(5)
        self.timer.set_no_show_all(True)
        row.pack_start(self.timer, False, False, 0)
        # Level meter: the last few microphone peaks, newest on the right.
        self.meter = Gtk.Box(spacing=2)
        self.meter.set_valign(Gtk.Align.CENTER)
        self.meter.set_no_show_all(True)
        self.bars = []
        for _ in range(BAR_COUNT):
            bar = Gtk.Box()
            bar.get_style_context().add_class('bar')
            bar.set_valign(Gtk.Align.CENTER)
            bar.set_size_request(3, 3)
            bar.show()
            self.meter.pack_start(bar, False, False, 0)
            self.bars.append(bar)
        row.pack_start(self.meter, False, False, 0)
        self.hint = Gtk.Label()
        self.hint.set_name('hint')
        self.hint.set_xalign(1)
        self.hint.set_margin_start(6)
        row.pack_end(self.hint, False, False, 0)

        self.detail = Gtk.Label()
        self.detail.set_name('detail')
        self.detail.set_xalign(0)
        self.detail.set_line_wrap(True)
        self.detail.set_max_width_chars(24)
        self.detail.set_margin_start(24)
        self.detail.set_no_show_all(True)
        panel.pack_start(self.detail, False, False, 0)

        box.connect('button-press-event', self.on_press)
        box.connect('motion-notify-event', self.on_motion)
        box.connect('button-release-event', self.on_release)
        box.connect('enter-notify-event', self.on_hover)
        box.connect('leave-notify-event', self.on_hover)
        w.connect('realize', lambda *_: self.set_cursor('grab'))
        self.menu = Gtk.Menu()
        self.build_menu()

    def build_menu(self):
        for child in self.menu.get_children():
            self.menu.remove(child)

        def item(label, callback, sensitive=True):
            entry = Gtk.MenuItem(label=label)
            entry.set_sensitive(sensitive)
            entry.connect('activate', lambda *_: callback())
            self.menu.append(entry)

        def check(label, key):
            entry = Gtk.CheckMenuItem(label=label)
            entry.set_active(bool(self.settings.get(key)))
            entry.connect('toggled', lambda e: send({'action': 'setting', 'key': key, 'value': e.get_active()}))
            self.menu.append(entry)

        item('复制上次结果', lambda: send({'action': 'copy', 'index': 0}), bool(self.history))
        recent = Gtk.MenuItem(label='最近转写')
        submenu = Gtk.Menu()
        for index, entry in enumerate(self.history):
            text = ' '.join(entry['text'].split())
            short = text if len(text) <= 22 else text[:22] + '…'
            sub = Gtk.MenuItem(label=f"{entry['at']}  {short}")
            sub.connect('activate', lambda _, i=index: send({'action': 'copy', 'index': i}))
            submenu.append(sub)
        recent.set_submenu(submenu)
        recent.set_sensitive(bool(self.history))
        self.menu.append(recent)
        item('打开专用 ChatGPT 页', lambda: send({'action': 'open-backend'}))
        self.menu.append(Gtk.SeparatorMenuItem())
        check('空闲时自动隐藏', 'autoHide')
        check('提示音', 'sounds')
        check('停顿 3 秒自动结束', 'autoStopOnPause')
        self.menu.append(Gtk.SeparatorMenuItem())
        item('关闭听写', self.close_dictation)
        self.menu.show_all()

    def close_dictation(self):
        send({'action': 'sleep'})
        self.update({'phase': 'closing'})

    # ---- geometry and pointer ---------------------------------------------------------------------
    def bounds(self, x, y):
        display = self.window.get_display()
        monitor = display.get_monitor_at_point(int(x), int(y)) or display.get_primary_monitor()
        area = monitor.get_workarea()
        width, height = self.window.get_size()
        return (max(area.x, min(int(x), area.x + area.width - width)),
                max(area.y, min(int(y), area.y + area.height - height)))

    def move_to(self, x, y):
        # Remember the requested position: get_position() lags until the WM applies the move.
        self.pos = self.bounds(x, y)
        self.window.move(*self.pos)

    def place(self):
        if self.positioned:
            return
        if self.saved_position:
            x, y = self.saved_position['x'], self.saved_position['y']
        else:
            area = self.window.get_display().get_primary_monitor().get_workarea()
            width, height = self.window.get_size()
            x, y = area.x + (area.width - width) // 2, area.y + area.height - height - 60
        self.move_to(x, y)
        self.positioned = True

    def keep_on_screen(self):
        # Size changes with content (e.g. the detail line); keep the capsule fully visible.
        self.move_to(*self.pos)
        self.snapshot()
        return False

    def set_cursor(self, name):
        if self.window.get_window():
            self.window.get_window().set_cursor(Gdk.Cursor.new_from_name(self.window.get_display(), name))

    def on_press(self, widget, event):
        if event.button == 3:
            self.menu.popup_at_pointer(event)
            return True
        if event.button != 1:
            return False
        self.drag = (event.x_root, event.y_root, *self.pos)
        self.press_at = (event.x_root, event.y_root)
        self.set_cursor('grabbing')
        return True

    def on_motion(self, widget, event):
        if self.drag and event.state & Gdk.ModifierType.BUTTON1_MASK:
            px, py, x, y = self.drag
            self.move_to(x + event.x_root - px, y + event.y_root - py)
            return True
        return False

    def on_release(self, widget, event):
        if event.button != 1 or not self.drag:
            return False
        self.drag = None
        self.set_cursor('grab')
        px, py = self.press_at
        if abs(event.x_root - px) < 4 and abs(event.y_root - py) < 4:
            # A click, not a drag: run the suggested fix for an error.
            if self.phase == 'error' and self.fix:
                send({'action': self.fix})
            return True
        POSITION_FILE.write_text(json.dumps(dict(zip('xy', self.pos))))
        self.snapshot()
        return True

    def on_hover(self, widget, event):
        # Ignore crossings into child widgets; only real enter/leave of the capsule counts.
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        self.hovered = event.type == Gdk.EventType.ENTER_NOTIFY
        self.dim()
        return False

    def dim(self):
        # Idle text recedes; the opaque background keeps whatever is behind from bleeding through.
        context = self.panel.get_style_context()
        if self.hovered or self.drag:
            context.add_class('hover')
        else:
            context.remove_class('hover')

    # ---- state ------------------------------------------------------------------------------------
    def snapshot(self):
        x, y = self.pos
        data = {'phase': self.phase, 'text': self.title.get_text(),
                'detail': self.detail.get_text() if self.detail.get_visible() else '',
                'hint': self.hint.get_text(), 'acceptFocus': self.window.get_accept_focus(),
                'shown': self.window.get_visible(), 'position': {'x': x, 'y': y}, 'draggable': True,
                'timer': self.timer.get_text(), 'warning': self.panel.get_style_context().has_class('warning'),
                'meter': [round(level, 2) for level in self.levels], 'history': len(self.history)}
        if data != self.last_snapshot:
            tmp = HUD_STATE.with_suffix('.tmp')
            tmp.write_text(json.dumps(data, ensure_ascii=False))
            tmp.replace(HUD_STATE)
            self.last_snapshot = data

    def set_detail(self):
        text = self.live_detail or self.base_detail
        context = self.panel.get_style_context()
        if text != self.detail.get_text() or bool(text) != self.detail.get_visible():
            self.detail.set_text(text)
            self.detail.set_visible(bool(text))
            if text:
                context.add_class('has-detail')
            else:
                context.remove_class('has-detail')
            self.event_box.set_tooltip_text(text or None)
            self.window.resize(1, 1)
            GLib.idle_add(self.keep_on_screen)
        self.snapshot()

    def tick(self):
        if self.phase != 'recording':
            self.tick_id = 0
            return False
        elapsed = time.monotonic() - self.record_started
        remaining = max(0, self.limit - elapsed)
        self.timer.set_text(f'{int(elapsed) // 60:02d}:{int(elapsed) % 60:02d}')
        context = self.panel.get_style_context()
        warning = remaining <= WARNING_SECONDS
        if warning and not context.has_class('warning'):
            context.add_class('warning')
            self.base_detail = f'快到 {round(self.limit / 60)} 分钟上限，到时会自动结束并转写'
            self.set_detail()
        if elapsed >= HINT_SECONDS or warning:
            left = int(remaining + 0.999)
            self.hint.set_text(f'剩余 {left // 60}:{left % 60:02d}')
        # Let the meter fall back when no level arrives (e.g. meter unavailable).
        self.levels = self.levels[1:] + [self.levels[-1] * 0.6]
        self.draw_meter()
        self.snapshot()
        return True

    def on_level(self, value):
        if self.phase == 'recording':
            self.levels = self.levels[1:] + [max(0.0, min(1.0, value))]
            self.draw_meter()

    def draw_meter(self):
        for bar, level in zip(self.bars, self.levels):
            bar.set_size_request(3, 3 + int(11 * min(1.0, (level / 0.5) ** 0.6)))

    def back_to_idle(self):
        self.idle_id = 0
        self.update({'phase': 'idle'})
        return False

    def update(self, message):
        phase = message.get('phase', 'idle')
        if phase not in PHASES:
            phase = 'error'
        status = (message.get('status') or '').strip()
        changed = phase != self.phase
        entering_recording = phase == 'recording' and changed
        context = self.panel.get_style_context()
        context.remove_class(self.phase)
        context.add_class(phase)
        if phase != 'recording':
            context.remove_class('warning')
        if message.get('limitMs'):
            self.limit = message['limitMs'] / 1000
        if changed:
            self.live_detail = ''
        self.phase = phase
        title, keys, linger = PHASES[phase]
        self.title.set_text(title)
        recording = phase == 'recording'
        if entering_recording:
            self.record_started = time.monotonic()
            self.levels = [0.0] * BAR_COUNT
            self.draw_meter()
            self.timer.set_text('00:00')
        self.timer.set_visible(recording)
        self.meter.set_visible(recording)
        if recording and not self.tick_id:
            self.tick_id = GLib.timeout_add(250, self.tick)
        self.fix = message.get('fix') if phase == 'error' else None
        if phase == 'error' and message.get('retryInsert'):
            self.hint.set_markup('<b>F8</b> 重新插入   点击复制')
        elif self.fix in FIX_HINTS:
            self.hint.set_text(FIX_HINTS[self.fix])
        elif changed or not recording:
            self.hint.set_markup('   '.join(f'<b>{k}</b> {GLib.markup_escape_text(t)}' for k, t in keys))
        if phase in BUSY:
            self.spinner.start()
            self.indicator.set_visible_child_name('spinner')
        else:
            self.spinner.stop()
            if phase in ICONS:
                self.icon.set_from_icon_name(ICONS[phase], Gtk.IconSize.MENU)
                self.indicator.set_visible_child_name('icon')
            else:
                self.indicator.set_visible_child_name('dot')
        # A repeated recording status keeps the limit warning; otherwise take the new detail.
        # An explicit detail shows in any phase; without one only failure reasons are shown.
        if not (recording and not changed and 'detail' not in message):
            self.base_detail = (message.get('detail') or '').strip() or (
                status if phase in ['error', 'cancelled'] and status not in REDUNDANT else '')
        if self.idle_id:
            GLib.source_remove(self.idle_id)
            self.idle_id = 0
        if linger:
            self.idle_id = GLib.timeout_add(int(linger * 1000), self.back_to_idle)
        self.dim()
        if phase == 'idle' and self.settings.get('autoHide') and not self.hovered:
            self.window.hide()
        else:
            self.window.show_all()
            self.place()
        self.set_detail()

    def on_message(self, message):
        kind = message.get('type')
        if kind == 'level':
            self.on_level(float(message.get('value') or 0))
        elif kind == 'detail':
            self.live_detail = (message.get('text') or '').strip()
            self.set_detail()
        elif kind == 'menu':
            settings = message.get('settings') or {}
            hide_changed = bool(settings.get('autoHide')) != bool(self.settings.get('autoHide'))
            self.history = message.get('history') or []
            self.settings = settings
            self.build_menu()
            if hide_changed and self.phase == 'idle':
                self.update({'phase': 'idle'})
            self.snapshot()
        else:
            self.update(message)


def main():
    capsule = Capsule()
    buffer = b''

    def on_input(fd, condition):
        nonlocal buffer
        chunk = os.read(fd, 65536) if condition & GLib.IO_IN else b''
        if not chunk:
            capsule.window.hide()
            capsule.snapshot()
            Gtk.main_quit()
            return False
        buffer += chunk
        *lines, buffer = buffer.split(b'\n')
        for line in lines:
            try:
                capsule.on_message(json.loads(line))
            except ValueError:
                pass
        return True

    GLib.io_add_watch(sys.stdin.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, on_input)
    capsule.update({'phase': 'idle'})
    Gtk.main()


if __name__ == '__main__':
    main()
