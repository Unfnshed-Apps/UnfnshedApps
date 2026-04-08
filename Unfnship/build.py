#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.build_common import run_build

if __name__ == '__main__':
    run_build("Unfnship", Path(__file__).parent)
