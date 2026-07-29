"""Shared helper for giving a test subprocess ``app.*``/``scripts.*``
importability without shadowing the interpreter's own ``sitecustomize.py``
(issue #4186).

Putting the repository root itself on a subprocess ``PYTHONPATH`` makes
Python's site machinery import the repo's own root-level ``sitecustomize.py``
(kept for the decision-receipt hook) instead of the *real* one the
interpreter would otherwise load -- e.g. Homebrew's, whose only load-bearing
line wires up the actual third-party site-packages directory via
``site.addsitedir(...)``. Python's site initialization imports only the FIRST
module literally named ``sitecustomize`` found on ``sys.path``, and
``PYTHONPATH`` entries land ahead of the stdlib, so the repo's file wins and
the real one never runs. Every third-party import in that subprocess then
fails with ``ModuleNotFoundError`` -- reproducible outside CI on any
Homebrew Python, unrelated to product code correctness.

The fix is to never put ``REPO_ROOT`` itself on a subprocess ``PYTHONPATH``.
Instead, symlink only the packages a subprocess actually needs (``app/`` and,
since ``app`` genuinely cross-imports helpers such as
``scripts.yaml_roundtrip`` and ``scripts.validate_issue_readiness``,
``scripts/`` too) into a private directory containing no ``sitecustomize.py``
of its own, and put THAT private directory on PYTHONPATH. First proven at
``tests/deploy/test_deploy_channel.py``.
"""
from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable


def isolated_app_pythonpath(
    private_dir: Path,
    repo_root: Path,
    *,
    optional_packages: Iterable[str] = (),
) -> str:
    """Return a ``PYTHONPATH`` value exposing only ``app/`` and ``scripts/``
    from *repo_root*.

    Creates *private_dir* if needed and symlinks ``app`` and ``scripts`` into
    it (idempotent across repeated calls with the same directory), then
    returns *private_dir* as a string suitable for a subprocess
    ``PYTHONPATH``. ``scripts/`` is included because ``app`` modules import
    from it directly (e.g. ``app.builderops.model_inquiry_promotion`` imports
    ``scripts.validate_issue_readiness``); omitting it would trade one
    ``ModuleNotFoundError`` for another. Callers can also declare optional
    top-level packages; each is linked only when its source directory exists.

    Never pass *repo_root* itself as (or on) a subprocess ``PYTHONPATH`` --
    see the module docstring for why.
    """
    private_dir.mkdir(parents=True, exist_ok=True)
    for package in ("app", "scripts", *optional_packages):
        source = repo_root / package
        if package not in {"app", "scripts"} and not source.is_dir():
            continue
        link = private_dir / package
        if not link.exists():
            link.symlink_to(source)
    return str(private_dir)
