from __future__ import annotations

import importlib
import subprocess
from pathlib import Path

from app.builderops.ckm.ingest_repo import ingest_repo, iter_docs, iter_git, iter_source, iter_tests
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
    artifacts = [*iter_docs(root), *iter_tests(root), *iter_source(root), *iter_git(root, None)]
    assert artifacts
    assert {artifact.artifact_kind for artifact in artifacts} >= {"adr", "spec", "document", "test", "source_file", "commit"}
    assert all(artifact.natural_key and artifact.provenance and artifact.payload_summary for artifact in artifacts)


def test_incremental_watermark_semantics(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    store = _store(tmp_path)
    first = ingest_repo(store, root)
    assert first["docs"]["changed"] == 3
    with store._connect() as conn:
        rows_before = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "ckm_artifact",
                "ckm_watermark",
                "builderops_records",
                "builderops_idempotency_keys",
            )
        }
    assert ingest_repo(store, root)["docs"]["changed"] == 0
    with store._connect() as conn:
        rows_after = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in rows_before
        }
    assert rows_after == rows_before
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


def test_ingest_reconciles_deleted_tree_artifacts(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    store = _store(tmp_path)
    ingest_repo(store, root)
    (root / "docs/guide.md").unlink()
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=CKM", "-c", "user.email=ckm@example.test", "commit", "-qm", "remove guide"], check=True)
    result = ingest_repo(store, root)
    assert result["docs"]["removed"] == 1
    assert store.get_artifact_by_source_ref("docs/guide.md") is None


def test_cold_git_ingest_pages_through_history_before_advancing_watermark(tmp_path: Path, monkeypatch) -> None:
    root = _repo(tmp_path / "repo")
    for number in range(4):
        _write(root / f"docs/{number}.md", f"# {number}\\n")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "-c", "user.name=CKM", "-c", "user.email=ckm@example.test", "commit", "-qm", f"commit {number}"], check=True)
    module = importlib.import_module("app.builderops.ckm.ingest_repo")
    original_git = module._git
    log_calls: list[tuple[str, ...]] = []

    def tracked_git(path: Path, *args: str) -> str:
        if args[0] == "log":
            log_calls.append(args)
        return original_git(path, *args)

    monkeypatch.setattr(module, "_git", tracked_git)
    store = _store(tmp_path)
    result = ingest_repo(store, root, git_limit=2)
    assert result["git"]["artifacts"] == 5
    assert store.get_watermark("git") == subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, text=True, capture_output=True
    ).stdout.strip()
    assert [next(arg for arg in call if arg.startswith("--skip=")) for call in log_calls] == ["--skip=0", "--skip=2", "--skip=4"]


def test_git_watermark_stays_on_snapshot_when_head_moves_during_ingest(
    tmp_path: Path, monkeypatch
) -> None:
    root = _repo(tmp_path / "repo")
    snapshot_head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    module = importlib.import_module("app.builderops.ckm.ingest_repo")
    original_iter_git = module.iter_git

    def moving_iter_git(*args, **kwargs):
        yield from original_iter_git(*args, **kwargs)
        _write(root / "docs/late.md", "# Late commit\n")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=CKM",
                "-c",
                "user.email=ckm@example.test",
                "commit",
                "-qm",
                "late commit",
            ],
            check=True,
        )

    monkeypatch.setattr(module, "iter_git", moving_iter_git)
    store = _store(tmp_path)
    ingest_repo(store, root, git_limit=2)

    late_head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    assert late_head != snapshot_head
    assert store.get_watermark("git") == snapshot_head
    assert store.get_artifact_by_source_ref(f"git:{late_head}") is None

    monkeypatch.setattr(module, "iter_git", original_iter_git)
    result = ingest_repo(store, root, git_limit=2)
    assert result["git"]["changed"] == 1
    assert store.get_watermark("git") == late_head
    assert store.get_artifact_by_source_ref(f"git:{late_head}") is not None
