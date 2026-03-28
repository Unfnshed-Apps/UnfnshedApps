import sys
from pathlib import Path

_app_dir = Path(__file__).resolve().parent.parent
_monorepo = _app_dir.parent
sys.path.insert(0, str(_app_dir))
sys.path.insert(0, str(_monorepo))
