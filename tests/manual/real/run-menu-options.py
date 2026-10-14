"""Menu options: pause auto-finish (停顿 3 秒自动结束) and idle auto-hide (空闲时自动隐藏)."""
import time

from harness import (D, VirtualMic, activate, clear, correct, desktop_text, fixtures, key, panel_window, restart_daemon,
                     save, start_recording, status, timings, wait_for)

results = []
try:
    restart_daemon(autoStopOnPause=True, autoHide=True)
    with fixtures(), VirtualMic() as mic:
        wait_for(lambda: panel_window() is None, 5)
        results.append({'case': 'auto-hide: no panel while idle', 'pass': True})
        activate('后台听写桌面验收')
        clear()
        before = time.time()
        key('F9')
        wait_for(panel_window, 5)
        wait_for(lambda: status().get('phase') == 'recording' and status().get('lastKeyAt', 0) >= before, 30)
        mic.route_chrome()
        mic.play()
        ended = time.time()
        # No second F9: three seconds of silence after the speech finish the recording.
        wait_for(lambda: status().get('lastInsertAt', 0) > ended, 30)
        waited = round(status()['lastInsertAt'] - ended, 1)
        assert correct(desktop_text()), desktop_text()
        results.append({'case': 'F9 shows the hidden panel; pause auto-finish transcribes without a second F9',
                        'secondsFromSpeechEndToPaste': waited, 'transcript': desktop_text(), 'pass': True})
        wait_for(lambda: panel_window() is None, 10)
        results.append({'case': 'panel hides again after returning to idle', 'pass': True})
finally:
    restart_daemon(autoStopOnPause=False, autoHide=False)
for r in results:
    print('PASS', r, flush=True)
save('results-menu-options.json', results)
D.close()
