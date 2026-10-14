import hashlib
import importlib.util
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('dictate_release', ROOT / 'scripts/package.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def test_archive_is_deterministic_and_excludes_private_runtime_files(self):
        with tempfile.TemporaryDirectory(prefix='dictate-release-test-') as tmp:
            root = Path(tmp)
            (root / 'extension').mkdir()
            (root / 'extension/manifest.json').write_text('{"version":"1.2.3"}')
            (root / 'native/dictate/__pycache__').mkdir(parents=True)
            (root / 'native/dictate/__pycache__/secret.pyc').write_bytes(b'private')
            (root / 'docs').mkdir()
            (root / 'scripts').mkdir()
            for name in ['README.md', 'LICENSE', 'CHANGELOG.md', 'CONTRIBUTING.md', 'SECURITY.md', 'pyproject.toml', 'VALIDATION.md', 'scripts/install.py', 'scripts/dictate.py']:
                (root / name).write_text('fixture')
            with patch.object(release, 'ROOT', root):
                out = release.build()
                first = out.read_bytes()
                release.build()
            self.assertEqual(first, out.read_bytes())
            self.assertIn(hashlib.sha256(first).hexdigest(), out.with_suffix('.zip.sha256').read_text())
            with zipfile.ZipFile(out) as z:
                self.assertIsNone(z.testzip())
                self.assertTrue(all(n.startswith('dictate/') and '__pycache__' not in n for n in z.namelist()))

    def test_documentation_relative_links_exist(self):
        for p in [ROOT / 'README.md', ROOT / 'CONTRIBUTING.md', ROOT / 'VALIDATION.md', *list((ROOT / 'docs').glob('*.md'))]:
            for target in re.findall(r'\]\(([^)]+)\)', p.read_text()):
                if '://' not in target and not target.startswith('#'):
                    self.assertTrue((p.parent / target.split('#')[0]).exists(), (p, target))
