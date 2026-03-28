#!/usr/bin/env python3
"""
Build script for creating platform-specific executables.

Usage:
    python build.py          # Build for current platform
    python build.py --clean  # Clean build artifacts before building
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.build_common import run_build

if __name__ == '__main__':
    run_build("UnfnshedAdmin", Path(__file__).parent)
