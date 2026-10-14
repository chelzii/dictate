"""Shared user paths and runtime defaults; legacy paths remain compatible."""
import json
import os
from pathlib import Path

HOST_NAME = 'com.chelizi.chatgpt_dictation'
INSTALL = Path(os.environ.get('DICTATION_INSTALL_ROOT', str(Path.home() / '.local/share/chatgpt-dictation')))
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}')
# Audio tools (pulsectl, pw-record) need it; a daemon started outside the session may lack it.
os.environ.setdefault('XDG_RUNTIME_DIR', str(RUNTIME))
SOCKET_PATH = Path(os.environ.get('DICTATION_SOCKET', str(RUNTIME / 'chatgpt-dictation.sock')))
CACHE = Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache'))) / 'chatgpt-dictation'
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'chatgpt-dictation'
# Chrome started for dictation opens no window. Without one Chrome would quit right away;
# --keep-alive-for-test keeps it running in the background (it then also stays after the
# last window is closed, which dictation needs). Tests point these at an isolated profile.
CHROME_COMMAND = json.loads(os.environ.get('DICTATION_CHROME_COMMAND',
                                           '["google-chrome", "--no-startup-window", "--keep-alive-for-test"]'))
CHROME_PROFILE = os.environ.get('DICTATION_CHROME_PROFILE')

DEFAULT_SETTINGS = {'autoHide': False, 'sounds': False, 'autoStopOnPause': False, 'sleeping': False}
SOUNDS = {'start': 'message-new-instant', 'done': 'complete', 'warning': 'dialog-warning', 'error': 'dialog-error'}
ACTIVE_PHASES = {'starting', 'recording', 'transcribing', 'cancelling'}
MAX_TEXT = 512 * 1024
VOICE_LEVEL = 0.05        # peak level (0..1) treated as speech
SILENCE_WARNING_S = 4     # no speech at all for this long -> "check the microphone"
PAUSE_STOP_S = 3          # optional auto-finish after this much silence following speech
LIMIT_WARNING_S = 60      # warn this long before the recording limit
CHROME_LAUNCH_TIMEOUT_S = 45
EXTENSION_CONNECT_TIMEOUT_S = 8
HISTORY_SIZE = 10
DEBUG = bool(os.environ.get('DICTATION_DEBUG'))
