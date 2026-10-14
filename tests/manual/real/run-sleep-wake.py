"""Right-click close, then F9 wakes: cold-opens ChatGPT (with a visible note) and transcribes."""
import time

from harness import (D, VirtualMic, activate, clear, click_at, correct, desktop_text, finish_and_wait, fixtures,
                     geometry, hud, key, menu_window, panel_window, save, start_recording, status, timings, wait_for)

results = []
with fixtures(), VirtualMic() as mic:
    x, y, w, h = geometry(wait_for(panel_window, 5))
    click_at(x + w // 2, y + h // 2, 3)
    wait_for(menu_window, 3)
    time.sleep(.3)
    key('Up')      # with nothing selected, Up selects the last item: 关闭听写
    key('Return')
    wait_for(lambda: status().get('phase') == 'sleeping', 15)
    wait_for(lambda: panel_window() is None, 5)
    assert not mic.chrome_streams()
    results.append({'case': 'right-click close: sleeping, panel gone, microphone released', 'pass': True})
    print('PASS close', flush=True)

    activate('后台听写桌面验收')
    clear()
    key('F8')  # asleep: F8 belongs to other programs again and must not wake dictation
    time.sleep(.5)
    assert status()['phase'] == 'sleeping' and panel_window() is None
    before = time.time()
    key('F9')
    seen = wait_for(lambda: hud() if hud().get('detail') == '正在打开 ChatGPT…' else None, 15)
    wait_for(lambda: status().get('phase') == 'recording' and status().get('lastKeyAt', 0) >= before, 60)
    mic.route_chrome()
    mic.play()
    finish_and_wait()
    entry = timings()[-1]
    assert correct(desktop_text()), desktop_text()
    assert entry['coldStart'], entry
    results.append({'case': 'F9 wakes, cold-opens ChatGPT with a note, transcribes', 'hud': seen,
                    'transcript': desktop_text(), 'timing': entry, 'pass': True})
    print('PASS wake', entry, flush=True)
    time.sleep(1.5)
    clear()
    start_recording(mic)
    key('F8')
    wait_for(lambda: status().get('phase') == 'cancelled', 15)
    time.sleep(.5)
    assert not mic.chrome_streams()
    results.append({'case': 'F8 cancel after wake releases the microphone', 'pass': True})
    print('PASS cancel after wake', flush=True)
save('results-sleep-wake.json', results)
D.close()
