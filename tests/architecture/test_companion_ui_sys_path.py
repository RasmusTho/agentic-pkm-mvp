"""Regression for #3941: companion_ui must be importable from any test tree.

The companion_ui package lives at companion-ui/companion-app/companion_ui,
outside the rootdir pythonpath. Test trees beyond tests/companion_ui import it
at module level (tests/api, tests/uat, tests/tts), so the root conftest.py must
put companion-ui/companion-app on sys.path for every collection target — not
just for runs that happen to pass through tests/companion_ui/conftest.py.

The module-level import below is the regression: without the root-conftest
guard, standalone collection of this file (like any out-of-tree importer)
aborts with ModuleNotFoundError.
"""
from pathlib import Path

import companion_ui


def test_companion_ui_importable_from_any_test_tree() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    expected = (repo_root / "companion-ui" / "companion-app" / "companion_ui").resolve()
    package_dirs = [Path(p).resolve() for p in companion_ui.__path__]
    assert expected in package_dirs, (
        "companion_ui resolved outside this checkout: "
        f"{package_dirs} (expected {expected}); a machine-local install or an "
        "absolute sys.path entry from another checkout is shadowing the repo copy"
    )
