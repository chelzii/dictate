#!/usr/bin/env python3
"""Build the release zip next to this directory: extension + native service, no tests."""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES = ['manifest.json', 'background.js', 'chatgpt-page.js', 'target.js', 'popup.html', 'popup.js', 'style.css',
         'README.md', 'native/daemon.py', 'native/bridge.py', 'native/overlay.py', 'native/install.py']
FILES += [str(path.relative_to(ROOT)) for path in sorted((ROOT / 'docs').rglob('*')) if path.is_file()]
FILES += ['VALIDATION.md']
OUT = ROOT.parent / 'dictate.zip'

with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED) as zf:
    for name in FILES:
        zf.write(ROOT / name, f'{ROOT.name}/{name}')
print(f'{OUT} ({len(FILES)} files, {OUT.stat().st_size // 1024} KB)')
