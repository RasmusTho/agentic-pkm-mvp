from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_no_duplicate_relation_index_module() -> None:
    relation_index_modules = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "app").glob("store*/relation_index.py")
    )

    assert relation_index_modules == ["app/store/relation_index.py"]
    assert (REPO_ROOT / "app" / "stores" / "relation_candidates.py").is_file()
