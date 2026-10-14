"""Plain-text clipboard access with bounded subprocess calls."""
import subprocess

def set_clipboard(text):
    subprocess.run(['xclip', '-selection', 'clipboard', '-in'], input=text.encode(),
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2, check=True)


def get_clipboard():
    try:
        return subprocess.run(['xclip', '-selection', 'clipboard', '-out'], capture_output=True,
                              timeout=.5, check=True).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
