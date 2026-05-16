"""Add companion-ui/companion-app to sys.path so companion_ui package is importable."""
import sys
from pathlib import Path

_pkg_root = Path(__file__).resolve().parents[2] / "companion-ui" / "companion-app"
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))
