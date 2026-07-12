"""SET-4 / SETTINGS-02: single default registry gate.

Audit finding F3: the same behavior-shaping env knob carried different literal
defaults at different call sites, so two components silently disagreed about one
value. Every such default is now declared once in ``app/settings/env_defaults.py``
and read through its accessors. This gate fails when a call site re-inlines a
literal default for a registered key (``os.getenv("KEY", "literal")``) — the
mechanism by which the split-truth divergence regrows.

The gate covers every registered key generically, not only the two F3 repairs, so
adding a duplicate default literal for any future registered key also fails CI.

Source: docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F3
"""

from __future__ import annotations

import re
from pathlib import Path

from app.settings.env_defaults import ENV_DEFAULTS

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
# The single declaration site is allowed to name the keys; nothing else may inline
# a literal default for them.
REGISTRY_MODULE = Path("app/settings/env_defaults.py")


def _duplicate_default_sites(
    root: Path, keys, *, allow: tuple[Path, ...] = ()
) -> list[tuple[str, int, str]]:
    """Return ``(relpath, lineno, line)`` for every place a registered key is read
    with an inlined literal default — ``os.getenv("KEY", <string-literal>)``.

    A deliberate no-default read (``os.getenv("KEY")`` with no second argument) is
    not a default declaration and is intentionally not reported.
    """
    root = Path(root)
    rel_base = root.parent
    patterns = {
        key: re.compile(
            r"""os\.getenv\(\s*["']""" + re.escape(key) + r"""["']\s*,\s*["'][^"']*["']"""
        )
        for key in keys
    }
    violations: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(rel_base)
        if rel in allow:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for pattern in patterns.values():
                if pattern.search(line):
                    violations.append((str(rel), lineno, line.strip()))
    return violations


def test_no_duplicated_default_literals() -> None:
    """No app call site inlines a literal default for a registered env key."""
    violations = _duplicate_default_sites(
        APP_ROOT, ENV_DEFAULTS.keys(), allow=(REGISTRY_MODULE,)
    )
    assert not violations, (
        "Registered env defaults must be read through app/settings/env_defaults.py, "
        f"not re-inlined at call sites: {violations}"
    )


def test_gate_detects_new_duplicate(tmp_path: Path) -> None:
    """The gate flags a newly introduced duplicate default for any registered key."""
    key = next(iter(ENV_DEFAULTS))
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "offender.py").write_text(
        f'import os\n\nvalue = os.getenv("{key}", "999")\n', encoding="utf-8"
    )

    violations = _duplicate_default_sites(pkg, ENV_DEFAULTS.keys())

    assert violations, "gate must flag a newly introduced duplicate default literal"
    assert violations[0][0] == "app/offender.py"


def test_no_default_read_is_not_flagged(tmp_path: Path) -> None:
    """A deliberate no-default read (unset-vs-set distinction) is not a violation."""
    key = next(iter(ENV_DEFAULTS))
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "deliberate.py").write_text(
        f'import os\n\nvalue = os.getenv("{key}")\n', encoding="utf-8"
    )

    violations = _duplicate_default_sites(pkg, ENV_DEFAULTS.keys())

    assert not violations
