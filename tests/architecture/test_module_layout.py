from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_no_duplicate_relation_index_module() -> None:
    relation_index_modules = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "app").glob("store*/relation_index.py")
    )

    assert relation_index_modules == ["app/store/relation_index.py"]
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
    for path in REPO_ROOT.glob("**/*.py"):
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
    for path in REPO_ROOT.glob("**/*.py"):
        if path.resolve() == this_file:
            # Skip this test file itself — it contains app.memory in assertion strings.
            continue
        text = path.read_text(errors="replace")
        match = old_import_re.search(text)
        assert not match, (
            f"{path} still references app.memory (old package) — update to app.memory_kv"
        )
