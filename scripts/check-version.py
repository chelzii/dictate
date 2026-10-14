#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path
root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--tag')
args = parser.parse_args()
versions = [json.loads((root/'extension/manifest.json').read_text())['version'],
            json.loads((root/'package.json').read_text())['version'],
            re.search(r'^version = "([^"]+)"', (root/'pyproject.toml').read_text(), re.M)[1]]
assert len(set(versions)) == 1, versions
if args.tag:
    assert args.tag == 'v' + versions[0], (args.tag, versions)
print('Version consistent:', versions[0])
