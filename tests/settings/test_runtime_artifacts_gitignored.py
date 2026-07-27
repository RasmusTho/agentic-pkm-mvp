"""Settings-compiler runtime artifacts must be `.gitignore`d.

`app/settings/compiler.py` publishes staged settings via dot-prefixed
siblings of ``runtime/settings/`` — ``.settings.lock`` (acquired on every
compile and left behind afterwards), ``.settings.next``,
``.settings.previous``, and ``.settings.staged-*`` temp dirs. The
``/runtime/settings/`` entry in `.gitignore` covers the directory itself but
not these siblings, so a plain test run left ``runtime/.settings.lock``
untracked and dirtied `git status --porcelain` (verified fix for the #3891 /
#3892 CI-consolidation branch hygiene failure).

The `.gitignore` posture anchors runtime-artifact patterns to each known
project root that produces them (see the comment block in `.gitignore`), so
this suite asserts coverage for both producers: the repo root and
``companion-ui/companion-app`` (whose tests run with that cwd).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.settings import compiler

pytestmark = pytest.mark.not_pg

REPO_ROOT = Path(__file__).resolve().parents[2]

# The cwd-relative roots that produce runtime/ artifacts, per the anchored
# .gitignore comment block.
PRODUCER_ROOTS = ("", "companion-ui/companion-app/")


def _compiler_sibling_artifacts() -> list[str]:
    """Dot-prefixed runtime/ siblings the compiler creates, from source."""
    parent = compiler.RUNTIME.parent.as_posix()  # "runtime"
    name = compiler.RUNTIME.name  # "settings"
    return [
        f"{parent}/.{name}.lock",
        f"{parent}/.{name}.next",
        f"{parent}/.{name}.previous",
        f"{parent}/.{name}.staged-sample",
    ]


def _is_ignored(relpath: str) -> bool:
    """True when `.gitignore` covers ``relpath`` (path need not exist)."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", relpath],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    return result.returncode == 0


@pytest.mark.parametrize("producer_root", PRODUCER_ROOTS)
def test_compiler_runtime_siblings_are_gitignored(producer_root: str) -> None:
    for artifact in _compiler_sibling_artifacts():
        relpath = f"{producer_root}{artifact}"
        assert _is_ignored(relpath), (
            f"{relpath!r} is not covered by .gitignore; the settings "
            "compiler writes it as a sibling of runtime/settings/ and it "
            "must never dirty `git status --porcelain` after a test run."
        )


@pytest.mark.parametrize("producer_root", PRODUCER_ROOTS)
def test_published_settings_symlink_is_gitignored(producer_root: str, tmp_path: Path) -> None:
    """``runtime/settings`` must be ignored even when it is a *symlink*.

    ``app/settings/compiler.py`` publishes the winning generation by pointing
    ``runtime/settings`` at a ``.settings.staged-*`` sibling, so the path is a
    symlink rather than a real directory. Git treats a symlink as a file, so a
    directory-only pattern (``/runtime/settings/``, with the trailing slash)
    does not match it and leaves ``?? runtime/settings`` in
    ``git status --porcelain`` after any compile.
    """
    parent = compiler.RUNTIME.parent.as_posix()
    name = compiler.RUNTIME.name
    relpath = f"{producer_root}{parent}/{name}"

    assert _is_ignored(relpath), (
        f"{relpath!r} is not covered by .gitignore. The settings compiler "
        "publishes it as a symlink to a .settings.staged-* dir; drop the "
        "trailing slash from the pattern so it matches a symlink too."
    )


def _pattern_matches_symlink(repo: Path, relpath: str) -> bool:
    """Materialize ``relpath`` as a real symlink and ask git if it is ignored."""
    target = repo / f"{relpath}-target"
    target.mkdir(parents=True, exist_ok=True)
    link = repo / relpath
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target.name)
    return _is_ignored_in(repo, relpath)


def _is_ignored_in(repo: Path, relpath: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", relpath],
        cwd=repo,
        capture_output=True,
    )
    return result.returncode == 0


def test_settings_pattern_matches_a_real_symlink(tmp_path: Path) -> None:
    """Prove the pattern against an actual on-disk symlink, not just a path string.

    ``git check-ignore`` can answer from the pattern alone, so this builds a
    throwaway repo, copies the real ``.gitignore`` into it, materializes
    ``runtime/settings`` as a genuine symlink, and asserts git ignores it. This
    is the check that fails when the trailing slash comes back.
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text(
        (REPO_ROOT / ".gitignore").read_text(encoding="utf-8"), encoding="utf-8"
    )

    assert _pattern_matches_symlink(tmp_path, "runtime/settings")

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "runtime/settings" not in status, (
        f"a published settings symlink still dirties git status:\n{status}"
    )


def test_ignore_patterns_stay_anchored_to_producer_roots() -> None:
    """Tracked source/test `runtime/` trees must NOT be swallowed.

    The .gitignore comment block requires anchored patterns precisely so a
    broad glob never hides files under e.g. ``app/runtime/`` or
    ``tests/runtime/``. Guard that the fix kept that property.
    """
    for tracked_root in ("app/runtime", "tests/runtime"):
        probe = f"{tracked_root}/.settings.lock"
        assert not _is_ignored(probe), (
            f"{probe!r} is gitignored — the runtime-artifact pattern lost "
            "its anchoring and now hides tracked source/test trees."
        )
