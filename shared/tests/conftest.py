import sys
from pathlib import Path

# Ensure shared package and monorepo root are importable
_monorepo = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_monorepo))
