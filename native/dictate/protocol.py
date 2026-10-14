"""Newline-delimited JSON used by the bridge and panel."""
import json

class Lines:
    """Newline-delimited JSON over a byte stream."""

    def __init__(self):
        self.buffer = b''

    def feed(self, chunk):
        self.buffer += chunk
        *lines, self.buffer = self.buffer.split(b'\n')
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out
