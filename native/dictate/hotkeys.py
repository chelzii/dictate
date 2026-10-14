"""Global key defaults and X11 target identity rules."""
from Xlib import X

KEYS = {"F9": "toggle", "F8": "cancel"}
LOCK_MASKS = [0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask]

def same_target(now, target):
    # Toolkits move focus between a top-level window and its own focus child right after
    # activation; only a different top-level window or a different child counts as a change.
    if not isinstance(target, dict) or now['window'] != target.get('window'):
        return False
    return now['focus'] == target.get('focus') or now['window'] in (now['focus'], target.get('focus'))
