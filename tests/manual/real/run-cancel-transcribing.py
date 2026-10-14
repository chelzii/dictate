"""Real desktop F8 during transcription, followed by another dictation.

Run in the initialized user's X11 desktop with a known Mandarin WAV. No chat messages sent.
"""
import time
from harness import (VirtualMic, activate, clear, correct, desktop_text, fixtures,
                     key, save, start_recording, status, wait_for)

rows=[]
with fixtures(),VirtualMic() as mic:
    activate('后台听写桌面验收')
    clear()
    key('F8')  # Recover a previous orphaned draft without deleting its text.
    time.sleep(.5)
    start_recording(mic)
    mic.play()
    key('F9')
    wait_for(lambda: status().get('phase')=='transcribing',10,interval=.01)
    key('F8')
    wait_for(lambda: status().get('phase') in ['cancelled','error'],15)
    time.sleep(4)
    assert desktop_text()=='','Cancelled transcript must not be inserted'
    rows.append({'case':'F8 during transcription inserts nothing','pass':True})
    print('PASS F8 during transcription: no target insertion',flush=True)
    activate('后台听写桌面验收')
    clear()
    try:
        start_recording(mic)
    except Exception:
        print('REPRODUCED restart blocked:',status().get('status'),flush=True)
        raise
    mic.play()
    key('F9')
    wait_for(lambda: status().get('phase') in ['done','error'],90)
    assert status()['phase']=='done' and correct(desktop_text()),status().get('status')
    rows.append({'case':'new dictation after cancelled transcription','pass':True})
    print('PASS next real dictation transcribes and inserts',flush=True)
save('results-cancel-transcribing.json',{'rows':rows,'pass':True})
