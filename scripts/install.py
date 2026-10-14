#!/usr/bin/env python3
"""Compatibility convenience entry: EXTENSION_ID, or --uninstall."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'native'))
from dictate.cli import main
args = sys.argv[1:]
if args == ['--uninstall']:
    sys.exit(main(['uninstall']))
if len(args) != 1:
    sys.exit('Usage: python3 scripts/install.py EXTENSION_ID | --uninstall')
sys.exit(main(['install', '--extension-id', args[0]]))
