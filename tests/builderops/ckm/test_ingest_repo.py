from __future__ import annotations

import subprocess
from pathlib import Path

from app.builderops.ckm.ingest_repo import ingest_repo, iter_docs, iter_source, iter_tests
from app.builderops.ckm.store import CkmStore


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    _write(tmp_path / "docs/adr/ADR-0001.md", "State: Accepted\n\n# An ADR\n")
    _write(tmp_path / "docs/CAPABILITY_THING/TASK.md", "---\ntask_id: X\n---\n\n# A spec\n")
    _write(tmp_path / "docs/guide.md", "State: Draft\n\n# A guide\n")
    _write(tmp_path / "tests/unit/test_example.py", "def test_one():\n    pass\n")
    _write(tmp_path / "app/example.py", '\"\"\"Example module.\"\"\"\n')
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.name=CKM", "-c", "user.email=ckm@example.test", "commit", "-qm", "fixture"],
        check=True,
    )
    return tmp_path


def _store(tmp_path: Path) -> CkmStore:
    return CkmStore(tmp_path / "state" / "builderops.sqlite3")


def test_adapters_yield_typed_provenanced_records(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    artifacts = [*iter_docs(root), *iter_tests(root), *iter_source(root)]
    assert artifacts
    assert {artifact.artifact_kind for artifact in artifacts} >= {"adr", "spec", "document", "test", "source_file"}
    assert all(artifact.natural_key and artifact.provenance and artifact.payload_summary for artifact in artifacts)


def test_incremental_watermark_semantics(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    store = _store(tmp_path)
    first = ingest_repo(store, root)
    assert first["docs"]["changed"] == 3
    assert ingest_repo(store, root)["docs"]["changed"] == 0
    _write(root / "docs/guide.md", "State: Accepted\n\n# A guide\n")
    changed = ingest_repo(store, root)
    assert changed["docs"]["changed"] == 1
    assert changed["docs"]["watermark"] != first["docs"]["watermark"]


def test_kind_classification_for_adr_and_spec(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    kinds = {artifact.natural_key: artifact.artifact_kind for artifact in iter_docs(root)}
    assert kinds["docs/adr/ADR-0001.md"] == "adr"
    assert kinds["docs/CAPABILITY_THING/TASK.md"] == "spec"


def test_ingest_is_readonly_and_offline(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    before = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], check=True, text=True, capture_output=True).stdout
    ingest_repo(_store(tmp_path), root)
    after = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], check=True, text=True, capture_output=True).stdout
    assert after == before == ""
