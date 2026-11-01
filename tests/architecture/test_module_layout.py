from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Generated / vendored / nested-checkout trees that are not this repo's source
# and must not be scanned by these architecture guards. Any hidden directory
# (name starting with ".") is pruned too — that covers .git, .venv, and the
# harness's nested git worktrees under .claude/worktrees/, which otherwise carry
# a copy of this very file and trip the import guards with false positives.
_PRUNE_DIRS = frozenset(
    {"__pycache__", "node_modules", "Archive", "tmp", "tmp-dev"}
)


def _iter_source_py() -> "list[Path]":
    """Yield every real-source ``*.py`` under the repo, pruning non-source trees."""
    sources: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(".")
            and d not in _PRUNE_DIRS
            and not d.endswith(".egg-info")
            and not (Path(dirpath) == REPO_ROOT and d.startswith("pytest-secure-"))
        ]
        for name in filenames:
            if name.endswith(".py"):
                sources.append(Path(dirpath) / name)
    return sources


def test_no_duplicate_relation_index_module() -> None:
    relation_index_modules = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "app").glob("store*/relation_index.py")
    )

    assert relation_index_modules == []
    assert (REPO_ROOT / "app" / "stores" / "relation_candidates.py").is_file()


def test_no_obs_observability_split() -> None:
    """app.obs must not exist; all observability lives in app.observability."""
    obs_dir = REPO_ROOT / "app" / "obs"
    assert not obs_dir.exists(), (
        "app/obs/ should have been deleted and merged into app/observability/"
    )

    # No importer should reference app.obs (use word-boundary regex so
    # app.observability is not a false positive).
    obs_import_re = re.compile(r'\bapp\.obs(?!ervability)\b')
    this_file = Path(__file__).resolve()
    for path in _iter_source_py():
        if path.resolve() == this_file:
            # Skip this test file itself — it contains app.obs in string literals.
            continue
        text = path.read_text(errors="replace")
        match = obs_import_re.search(text)
        assert not match, f"{path} still imports from app.obs"


def test_memory_package_renamed() -> None:
    """app/memory/ must not exist; KV substrate must be reachable as app.memory_kv."""
    old_dir = REPO_ROOT / "app" / "memory"
    new_dir = REPO_ROOT / "app" / "memory_kv"
    assert not old_dir.exists(), "app/memory/ should have been renamed to app/memory_kv/"
    assert new_dir.exists(), "app/memory_kv/ must exist after rename"

    old_import_re = re.compile(r'\bapp\.memory(?!_kv)\b')
    this_file = Path(__file__).resolve()
    for path in _iter_source_py():
        if path.resolve() == this_file:
            # Skip this test file itself — it contains app.memory in assertion strings.
            continue
        text = path.read_text(errors="replace")
        match = old_import_re.search(text)
        assert not match, (
            f"{path} still references app.memory (old package) — update to app.memory_kv"
        )


def test_import_guards_exclude_secure_fixture_roots_without_hiding_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(globals(), "REPO_ROOT", tmp_path)
    (tmp_path / "app" / "memory_kv").mkdir(parents=True)
    fixture_source = tmp_path / "pytest-secure-example" / "checkout" / "app" / "main.py"
    fixture_source.parent.mkdir(parents=True)
    fixture_source.write_text("import app.memory\nimport app.obs\n")
    genuine_source = tmp_path / "nested" / "pytest-secure-real" / "source.py"
    genuine_source.parent.mkdir(parents=True)
    genuine_source.write_text("import app.memory_kv\nimport app.observability\n")

    scanned = _iter_source_py()
    assert fixture_source not in scanned
    assert genuine_source in scanned
    test_memory_package_renamed()
    test_no_obs_observability_split()

    genuine_source.write_text("import app.memory\n")
    with pytest.raises(AssertionError, match="still references app.memory"):
        test_memory_package_renamed()
    genuine_source.write_text("import app.obs\n")
    with pytest.raises(AssertionError, match="still imports from app.obs"):
        test_no_obs_observability_split()

    real_read_text = Path.read_text
    def missing_source(path: Path, *args: object, **kwargs: object) -> str:
        if path == genuine_source:
            raise FileNotFoundError("real source became unavailable")
        return real_read_text(path, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(Path, "read_text", missing_source)
        with pytest.raises(FileNotFoundError, match="real source became unavailable"):
            test_memory_package_renamed()
