"""Recording limit: live remaining time, warning in the last minute, auto-finish and transcribe.

Usage: run-record-limit.py [limit_seconds]   (default 480 = the real 8-minute limit)
Speech plays right after the start and again shortly before the limit.
"""
import sys
import time

from harness import (D, VirtualMic, activate, clear, correct, desktop_text, fixtures, hud, panel_window, restart_daemon,
                     save, screenshot, start_recording, status, timings, wait_for, HERE)

limit = int(sys.argv[1]) if len(sys.argv) > 1 else 480
if limit != 480:
    restart_daemon(recordLimitMs=limit * 1000)
try:
    with fixtures(), VirtualMic() as mic:
        activate('后台听写桌面验收')
        clear()
        started = start_recording(mic)
        mic.play()
        wait_for(lambda: hud().get('hint', '').startswith('剩余'), 10)
        early = hud()
        wait_for(lambda: hud().get('warning'), limit)
        warned = hud()
        screenshot(panel_window(), HERE / 'floating-limit-warning.png', pad=6)
        assert '自动结束' in warned['detail'], warned
        time.sleep(max(0, limit - (time.time() - started) - 12))
        mic.play()
        wait_for(lambda: status().get('phase') == 'transcribing', 30)
        auto = hud()
        wait_for(lambda: status().get('phase') in ['done', 'error'], 120)
        text = desktop_text()
        entry = timings()[-1]
        assert status()['phase'] == 'done', status()
        assert correct(text), text
        assert entry.get('autoFinish') == 'limit', entry
        assert abs(entry['recordMs'] - limit * 1000) < 3000, entry
        result = {'limitSeconds': limit, 'hudEarly': early, 'hudWarning': warned, 'hudAutoFinish': auto,
                  'transcript': text, 'timing': entry, 'pass': True}
        print('PASS', result, flush=True)
finally:
    if limit != 480:
        restart_daemon(recordLimitMs=None)
save(f'results-record-limit-{limit}s.json', result)
D.close()
