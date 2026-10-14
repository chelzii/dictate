#!/usr/bin/env python3
"""Build a stable release archive and checksum from a source whitelist."""
import hashlib
import json
import zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


def build():
    version = json.loads((ROOT / 'extension/manifest.json').read_text())['version']
    files = [ROOT / name for name in ['README.md', 'LICENSE', 'CHANGELOG.md', 'CONTRIBUTING.md', 'SECURITY.md', 'pyproject.toml', 'VALIDATION.md']]
    files += [p for directory in ['extension', 'native/dictate', 'docs'] for p in (ROOT / directory).rglob('*')
              if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
    files += [ROOT / 'scripts' / name for name in ['dictate.py', 'install.py']]
    out = ROOT / 'dist' / f'dictate-{version}.zip'
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo('dictate/' + path.relative_to(ROOT).as_posix(), (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    out.with_suffix('.zip.sha256').write_text(digest + '  ' + out.name + '\n')
    print(out)
    return out


if __name__ == '__main__':
    build()
