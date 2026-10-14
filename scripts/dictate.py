#!/usr/bin/env python3
"""Run dictate commands from a checkout or release archive."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'native'))
from dictate.cli import main
sys.exit(main())
