"""Real ChatGPT page adapter/cleanup check in a tab owned by Kimi WebBridge.

Requires the logged-in browser + local WebBridge, X11 test dependencies and known WAV.
Only dictates; never sends a chat message. Does not measure complete desktop paste latency.
"""
import json
import time
import urllib.request
from pathlib import Path
from harness import VirtualMic, correct, wait_for, save

ROOT = Path(__file__).resolve().parents[3]
SESSION = 'dictate-performance-real'


def command(action, args):
    request = urllib.request.Request('http://127.0.0.1:10086/command',
        data=json.dumps({'action': action, 'args': args, 'session': SESSION}).encode(),
        headers={'Content-Type': 'application/json'})
    data = json.loads(urllib.request.urlopen(request, timeout=30).read())
    assert data['ok'], data.get('error')
    return data.get('data', {})


def evaluate(code):
    return command('evaluate', {'code': code}).get('value')


try:
    command('navigate', {'url': 'https://chatgpt.com/', 'newTab': True, 'group_title': 'dictate 真实验收'})
    code = "globalThis.__backgroundDictationBuild='real-adapter-check';\n" + (ROOT / 'extension/content/chatgpt-page.js').read_text()
    evaluate(code)
    wait_for(lambda: evaluate("(()=>{const s=__backgroundDictationPage.state({});return s.start && !s.text?.trim();})()"), 20)
    message_count = evaluate("document.querySelectorAll('[data-message-author-role]').length")
    rows = []
    with VirtualMic() as mic:
        assert not mic.chrome_streams(), 'Another Chrome recording is active'
        for cycle in range(2):
            evaluate("__backgroundDictationPage.click('start',{})")
            wait_for(lambda: evaluate('__backgroundDictationPage.state({}).finish'), 15)
            mic.route_chrome()
            mic.play()
            evaluate('''(()=>{
                globalThis.realProbe={done:false,trace:[]};
                const started=performance.now();let previous='',readyAt=0;
                const tick=()=>{const s=__backgroundDictationPage.state({});const sig=JSON.stringify([s.text,s.start,s.finish,s.cancel]);
                    if(sig!==previous){realProbe.trace.push({ms:performance.now()-started,text:s.text,start:s.start,finish:s.finish,cancel:s.cancel});previous=sig;}
                    if(s.start && !s.finish && !s.cancel && s.text?.trim()){readyAt ||= performance.now();}
                    if(readyAt && performance.now()-readyAt>500){realProbe.done=true;clearInterval(realProbe.timer);}
                };
                realProbe.timer=setInterval(tick,10);__backgroundDictationPage.click('finish',{});tick();return true;
            })()''')
            probe = wait_for(lambda: evaluate('realProbe.done?realProbe:null'), 90)
            transcript = evaluate('__backgroundDictationPage.state({}).text')
            assert correct(transcript), 'Known speech was not transcribed completely'
            # Preserve only lengths/timing in the public-readable evidence, not raw transcripts.
            trace = [{**entry, 'textLength': len(entry['text'] or '')} for entry in probe['trace']]
            for entry in trace:
                entry.pop('text')
            cleared = evaluate('__backgroundDictationPage.clear(' + json.dumps(transcript) + ')')
            assert cleared and evaluate("!__backgroundDictationPage.state({}).text?.trim()")
            assert evaluate("document.querySelectorAll('[data-message-author-role]').length") == message_count
            rows.append({'cycle': cycle + 1, 'correct': True, 'clearSucceeded': True, 'trace': trace})
            print('PASS real ChatGPT adapter transcription and model-aware clear, cycle', cycle + 1, flush=True)
        # A fresh recording after both clears must also cancel and release capture.
        evaluate("__backgroundDictationPage.click('start',{})")
        wait_for(lambda: evaluate('__backgroundDictationPage.state({}).cancel'), 15)
        evaluate("__backgroundDictationPage.click('cancel',{})")
        wait_for(lambda: not mic.chrome_streams(), 10)
        print('PASS next recording and cancellation release the microphone; no chat messages sent', flush=True)
    save('results-page-adapter.json', {'rows': rows, 'scope': 'Real page adapter and cleanup; timings are DOM probe observations, not desktop latency', 'pass': True})
finally:
    try:
        evaluate("(()=>{if(globalThis.realProbe?.timer)clearInterval(realProbe.timer);const s=globalThis.__backgroundDictationPage?.state({});if(s?.cancel)__backgroundDictationPage.click('cancel',{});})()")
    finally:
        command('close_session', {})
