from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.builderops.cli import builderops
from app.builderops.ckm.ingest_repo import iter_docs
from app.builderops.ckm.linkers import link_deterministic
from app.builderops.ckm.seed import seed_capabilities
from app.builderops.ckm.store import CkmStore

REPO_ROOT = Path(__file__).resolve().parents[3]


def _store(tmp_path: Path) -> CkmStore:
    store = CkmStore(tmp_path / "builderops.sqlite3")
    store.ensure_schema()
    seed_capabilities(store, repo_root=REPO_ROOT)
    return store


def _ingest_docs(store: CkmStore) -> None:
    for artifact in iter_docs(REPO_ROOT):
        store.upsert_artifact(
            source_ref=artifact.natural_key,
            artifact_kind=artifact.artifact_kind,
            source=artifact.source,
            watermark=artifact.source_watermark,
            provenance=artifact.provenance,
        )


def test_matrix_rows_become_edges_on_live_matrix(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _ingest_docs(store)
    result = link_deterministic(store, REPO_ROOT)
    matrix_edges = [
        edge for edge in store.list_evidence_edges()
        if json.loads(edge.source_ref)["basis"].startswith("matrix:")
    ]
    assert result["matrix"] > 0
    assert matrix_edges
    capability_by_id = {item.id: item for item in store.list_capabilities()}
    assert {
        capability_by_id[edge.capability_id].boundary_ref for edge in matrix_edges
    } >= {"RCA", "GOV", "SIP"}


def test_edges_carry_method_lifecycle_basis(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _ingest_docs(store)
    link_deterministic(store, REPO_ROOT)
    edges = store.list_evidence_edges()
    assert edges
    assert all(edge.extraction_method == "deterministic" for edge in edges)
    assert all(edge.lifecycle == "confirmed" for edge in edges)
    assert all(json.loads(edge.source_ref)["basis"] for edge in edges)


def test_link_idempotent_incremental(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _ingest_docs(store)
    first = link_deterministic(store, REPO_ROOT)
    first_count = len(store.list_evidence_edges())
    second = link_deterministic(store, REPO_ROOT)
    assert first["matrix"] > 0
    assert sum(second[name] for name in ("matrix", "spec", "adr", "test_code", "github_ref")) == 0
    assert len(store.list_evidence_edges()) == first_count


def test_unlinked_backlog_reported(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert_artifact(
        source_ref="docs/unlinked.md",
        artifact_kind="document",
        source="repo_docs",
        watermark="one",
        provenance='{"source_ref":"docs/unlinked.md"}',
    )
    result = link_deterministic(store, REPO_ROOT)
    assert result["unlinked_artifacts"] == 1

    runner = CliRunner()
    invocation = runner.invoke(
        builderops,
        ["--db-path", str(store.db_path), "ckm", "link", "--repo-root", str(REPO_ROOT)],
    )
    assert invocation.exit_code == 0
    assert "unlinked artifacts: 1" in invocation.output
