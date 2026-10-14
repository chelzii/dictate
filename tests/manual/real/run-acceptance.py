"""Main real acceptance suite: F9/F8 on desktop and web inputs, key-hold, meter, silence, recovery."""
import json
import subprocess
import time

from harness import (D, X, XK, VirtualMic, activate, clear, click_at, correct, desktop_text, finish_and_wait,
                     fixtures, geometry, hud, key, panel_window, save, start_recording, status, wait_for, xtest)
from harness import BROWSER_FIXTURE

results = []


def passed(name, **extra):
    results.append({'test': name, 'pass': True, **extra})
    print('PASS', name, json.dumps(extra, ensure_ascii=False) if extra else '', flush=True)


def clipboard():
    return subprocess.run(['xclip', '-selection', 'clipboard', '-out'], capture_output=True).stdout.decode()


with fixtures(browser=True), VirtualMic() as mic:
    for n in range(2):
        activate('后台听写桌面验收')
        clear()
        start_recording(mic)
        mic.play()
        finish_and_wait()
        assert correct(desktop_text()), desktop_text()
        passed('desktop Chinese transcription', cycle=n + 1, transcript=desktop_text())
        time.sleep(1.5)

    # Holding F9 makes X auto-repeat it; that must count as one press.
    activate('后台听写桌面验收')
    clear()
    code = D.keysym_to_keycode(XK.string_to_keysym('F9'))
    before = time.time()
    xtest.fake_input(D, X.KeyPress, code)
    D.sync()
    time.sleep(1.3)
    xtest.fake_input(D, X.KeyRelease, code)
    D.sync()
    wait_for(lambda: status().get('phase') == 'recording' and status().get('lastKeyAt', 0) >= before, 30)
    time.sleep(2)
    assert status()['phase'] == 'recording', status()
    mic.route_chrome()
    peaks = []
    play = mic.play_async()
    while play.poll() is None:
        peaks.append(max(hud().get('meter') or [0]))
        time.sleep(.1)
    finish_and_wait()
    assert correct(desktop_text()), desktop_text()
    assert max(peaks) > 0.1, peaks
    passed('holding F9 1.3 s starts once; level meter follows the speech', meterPeak=max(peaks))
    time.sleep(1.5)

    # Silence: no speech reaches the microphone -> the panel says so.
    activate('后台听写桌面验收')
    clear()
    start_recording(mic)
    detail = wait_for(lambda: hud().get('detail') if '没有检测到声音' in hud().get('detail', '') else None, 10)
    key('F8')
    wait_for(lambda: status().get('phase') == 'cancelled', 15)
    time.sleep(.5)
    assert not mic.chrome_streams()
    assert desktop_text() == ''
    passed('silence warning; F8 cancels, inserts nothing, releases the microphone', detail=detail)
    time.sleep(1.5)

    # Stopping without any speech: ChatGPT returns nothing; say so quickly instead of timing out.
    activate('后台听写桌面验收')
    clear()
    start_recording(mic)
    time.sleep(1.5)
    stopped = time.time()
    key('F9')
    wait_for(lambda: status().get('phase') == 'error', 20)
    took = round(time.time() - stopped, 1)
    assert '没有识别到语音' in status().get('status', ''), status()
    assert took < 8, took
    passed('stopping without speech reports it promptly', seconds=took)
    time.sleep(1.5)

    # Web page input through the same global F9.
    activate('后台听写浏览器验收')
    clear()
    start_recording(mic)
    mic.play()
    finish_and_wait()
    text = json.loads(BROWSER_FIXTURE.read_text())['text']
    assert correct(text), text
    passed('Chrome webpage Chinese transcription via global F9', transcript=text)
    time.sleep(1.5)

    # Focus changes during transcription: refuse to paste; one click on the panel copies it.
    activate('后台听写桌面验收')
    clear()
    start_recording(mic)
    mic.play()
    activate('后台听写浏览器验收')
    key('F9')
    wait_for(lambda: status().get('phase') == 'error', 60)
    assert desktop_text() == ''
    state = wait_for(lambda: hud() if hud().get('hint') == '点击复制' else None, 5)
    x, y, w, h = geometry(panel_window())
    click_at(x + w // 2, y + h // 2)
    wait_for(lambda: hud().get('phase') == 'copied', 5)
    copied = clipboard()
    assert correct(copied), copied
    assert hud()['history'] >= 1
    passed('changed window refuses paste; clicking the panel copies the transcript', detail=state['detail'])

save('results-acceptance.json', {
    'scope': 'Installed extension + dictation daemon + real ChatGPT; real X11 keys/mouse via XTest; '
             'known Mandarin through a temporary virtual microphone',
    'date': time.strftime('%Y-%m-%d'), 'results': results})
D.close()
