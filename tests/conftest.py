import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_SRC = _REPO_ROOT / "src"
for p in (_SRC, _REPO_ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)
