#!/usr/bin/env python3
"""Portable automated checks; no account or active desktop needed."""
import os
import subprocess
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
env = dict(os.environ, PYTHONPATH=str(root / 'native'))
for command in [[sys.executable, 'scripts/check-version.py'],
                [sys.executable, '-m', 'compileall', '-q', 'native', 'scripts', 'tests'],
                [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/unit', '-v'],
                ['node', 'tests/integration/smoke.mjs']]:
    subprocess.run(command, cwd=root, env=env, check=True)
