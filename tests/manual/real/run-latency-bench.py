"""Real latency benchmark: F9 -> recording, and second F9 -> text pasted (desktop input).

Usage: run-latency-bench.py LABEL [CYCLES]
"""
import statistics
import sys
import time

from harness import (D, VirtualMic, activate, clear, correct, desktop_text, finish_and_wait, fixtures, save,
                     start_recording, status, timings)

label = sys.argv[1] if len(sys.argv) > 1 else 'run'
cycles = int(sys.argv[2]) if len(sys.argv) > 2 else 4
rows = []
with fixtures(), VirtualMic() as mic:
    for n in range(cycles):
        activate('后台听写桌面验收')
        clear()
        t0 = time.time()
        start_recording(mic)
        t_rec = time.time()
        mic.play()
        t1 = finish_and_wait()
        rows.append({'start': round(t_rec - t0, 3), 'finish': round(status()['lastInsertAt'] - t1, 3),
                     'ok': correct(desktop_text()), 'timing': timings()[-1]})
        print(label, n + 1, rows[-1], flush=True)
        time.sleep(1.5)
summary = {'label': label, 'startMedian': statistics.median(r['start'] for r in rows),
           'finishMedian': statistics.median(r['finish'] for r in rows), 'allCorrect': all(r['ok'] for r in rows),
           'rows': rows}
save(f'latency-{label}.json', summary)
print('SUMMARY', {k: v for k, v in summary.items() if k != 'rows'})
D.close()
