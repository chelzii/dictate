"""Optional microphone peak meter. No audio is archived."""
import array
import os
import subprocess

try:
    import pulsectl
except ImportError:
    pulsectl = None

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
