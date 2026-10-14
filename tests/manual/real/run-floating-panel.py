"""Floating panel: real mouse drag (idle and recording) keeps keyboard focus; position persists."""
import json
import time

from harness import (CACHE, D, X, VirtualMic, activate, clear, correct, desktop_text, finish_and_wait, fixtures,
                     geometry, hud, panel_window, root, save, screenshot, start_recording, xtest, HERE)


def focus_state():
    active = root.get_full_property(D.intern_atom('_NET_ACTIVE_WINDOW'), X.AnyPropertyType).value[0]
    return int(active), D.get_input_focus().focus


def drag_panel(dx, dy):
    before, focus = hud()['position'], focus_state()
    x, y, w, h = geometry(panel_window())
    x, y = x + w - 30, y + h // 2
    xtest.fake_input(D, X.MotionNotify, x=x, y=y)
    xtest.fake_input(D, X.ButtonPress, 1)
    D.sync()
    time.sleep(.15)
    for step in range(1, 9):
        xtest.fake_input(D, X.MotionNotify, x=x + dx * step // 8, y=y + dy * step // 8)
        D.sync()
        time.sleep(.04)
    xtest.fake_input(D, X.ButtonRelease, 1)
    D.sync()
    time.sleep(.3)
    after = hud()['position']
    assert after != before, (before, after)
    assert json.loads((CACHE / 'floating-position.json').read_text()) == after
    assert focus_state() == focus
    return {'before': before, 'after': after, 'focusPreserved': True}


with fixtures(), VirtualMic() as mic:
    activate('后台听写桌面验收')
    clear()
    idle = drag_panel(-120, -60)
    screenshot(panel_window(), HERE / 'floating-idle.png', pad=4)
    start_recording(mic)
    mic.play()
    screenshot(panel_window(), HERE / 'floating-recording.png', pad=4)
    recording = drag_panel(120, 60)
    finish_and_wait()
    assert correct(desktop_text()), desktop_text()
    assert hud()['position'] == recording['after']
save('results-floating-panel.json', {'scope': 'Real GTK panel, real mouse drag via XTest, real ChatGPT transcription',
                                      'idleDrag': idle, 'recordingDrag': recording, 'transcript': desktop_text(),
                                      'pass': True})
print('PASS drag idle/recording, focus preserved, position kept, transcription', flush=True)
D.close()
