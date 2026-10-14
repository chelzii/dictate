#!/usr/bin/env python3
"""Compatibility wrapper; prefer python3 scripts/package.py."""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parent / 'scripts/package.py'), run_name='__main__')
