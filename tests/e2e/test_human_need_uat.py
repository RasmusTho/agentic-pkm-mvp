from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import ask as ask_route
from app.agents.ask.graph import run_ask_graph
from app.ingest.external import ingest_external_folder
from app.ingest.vault_alpha import run_vault_alpha_ingest_paths
from app.retrieval.hybrid import get_store as get_hybrid_store
from app.retrieval.hybrid import reset_durable_rebuild_state
from app.stores import get_object_store, get_vector_index, reset_store_backends


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.human_uat,
    pytest.mark.skipif(
        os.getenv("RUN_HUMAN_UAT", "").strip().lower() not in {"1", "true", "yes", "on"},
        reason="opt-in human_uat scenarios; set RUN_HUMAN_UAT=1",
    ),
]


def _reset_runtime_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.delenv("REASONING_ENABLE", raising=False)
    reset_store_backends()
    reset_durable_rebuild_state()
    get_hybrid_store().set_documents([])
    monkeypatch.setattr(ask_route, "_HYBRID_WARMED", False, raising=False)


def _seed_archive_artifact(tmp_path: Path, *, filename: str, text: str) -> tuple[str, str]:
    """Ingest a supported retained artifact through the production external adapter."""
    artifact_path = tmp_path / "Archive" / "Vendor" / filename
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(text, encoding="utf-8")

    summary = ingest_external_folder(tmp_path)
    assert summary.scanned == 1
    assert summary.ingested == 1
    rows = list(get_vector_index().all_rows())
    assert len(rows) == 1
    return str(rows[0]["object_id"]), str(artifact_path.resolve())


def _seed_orientation_pack(tmp_path: Path) -> dict[str, Path]:
    """Seed the bounded indexed read surface used by the return-orientation UAT."""

    active_note = tmp_path / "Projects" / "atlas-migration.md"
    waiting_note = tmp_path / "Projects" / "atlas-waiting.md"
    source_note = tmp_path / "Sources" / "vendor-memo.md"
    unrelated_note = tmp_path / "Garden" / "seedlings.md"
    get_hybrid_store().set_documents(
        [
            {
                "doc_id": "atlas-active",
                "source_ref": str(active_note),
                "text": (
                    "Atlas migration is the active project. Current focus: migrate the API gateway. "
                    "Next step: draft the migration checklist and schedule the rollout review."
                ),
                "payload": {
                    "uuid": "atlas-active",
                    "title": "Atlas Migration",
                    "origin": "vault",
                    "plane": "vault",
                    "source_role": "vault_note",
                    "active_context_ref": "atlas-active",
                },
            },
            {
                "doc_id": "atlas-waiting",
                "source_ref": str(waiting_note),
                "text": (
                    "Atlas migration waiting item. Blocked pending finance approval and vendor confirmation. "
                    "Do not treat this as the next action."
                ),
                "payload": {
                    "uuid": "atlas-waiting",
                    "title": "Atlas Waiting",
                    "origin": "vault",
                    "plane": "vault",
                    "source_role": "vault_note",
                    "commitment_state": "waiting",
                },
            },
            {
                "doc_id": "atlas-source",
                "source_ref": str(source_note),
                "text": "Vendor migration memo for Atlas. Confirms gateway deprecation window and required cutover steps.",
                "payload": {
                    "uuid": "atlas-source",
                    "title": "Vendor Memo",
                    "origin": "vault",
                    "plane": "vault",
                    "source_role": "vault_note",
                    "target_ref": "atlas-active",
                },
            },
            {
                "doc_id": "unrelated-garden",
                "source_ref": str(unrelated_note),
                "text": "Garden seedlings note about watering tomatoes and spring soil temperature.",
                "payload": {
                    "uuid": "unrelated-garden",
                    "title": "Seedlings",
                    "origin": "vault",
                    "plane": "vault",
                    "source_role": "vault_note",
                    "zone": "garden",
                },
            },
        ]
    )
    ask_route._HYBRID_WARMED = True
    return {"active": active_note, "waiting": waiting_note, "source": source_note, "unrelated": unrelated_note}


def _seed_production_orientation_pack(tmp_path: Path) -> dict[str, Path]:
    """Seed indexed fields that real producers can carry; no orientation_role fixture field."""

    active_note = tmp_path / "Projects" / "atlas-migration.md"
    waiting_note = tmp_path / "Projects" / "atlas-waiting.md"
    source_note = tmp_path / "Sources" / "vendor-memo.md"
    unrelated_note = tmp_path / "Garden" / "seedlings.md"
    get_hybrid_store().set_documents(
        [
            {
                "doc_id": "atlas-active",
                "source_ref": str(active_note),
                "text": "Atlas migration active project. Next step is the gateway checklist.",
                "payload": {
                    "uuid": "atlas-active",
                    "title": "Atlas Migration",
                    "origin": "vault",
                    "plane": "vault",
                    "source_role": "vault_note",
                    "zone": "workbench",
                    "active_context_ref": "atlas-active",
                    "evidence_role": "evidence",
                },
            },
            {
                "doc_id": "atlas-waiting",
                "source_ref": str(waiting_note),
                "text": "Atlas migration is waiting for finance approval.",
                "payload": {
                    "uuid": "atlas-waiting",
                    "title": "Atlas Waiting",
                    "origin": "vault",
                    "plane": "vault",
                    "source_role": "vault_note",
                    "zone": "workbench",
                    "commitment_state": "waiting",
                    "target_ref": "atlas-active",
                    "evidence_role": "reference",
                },
            },
            {
                "doc_id": "atlas-source",
                "source_ref": str(source_note),
                "text": "Vendor memo supporting the Atlas migration gateway checklist.",
                "payload": {
                    "uuid": "atlas-source",
                    "title": "Vendor Memo",
                    "origin": "vault",
                    "plane": "vault",
                    "source_role": "vault_note",
                    "zone": "reference",
                    "target_ref": "atlas-active",
                    "evidence_role": "reference",
                },
            },
            {
                "doc_id": "unrelated-garden",
                "source_ref": str(unrelated_note),
                "text": "Garden seedlings and tomato watering notes.",
                "payload": {
                    "uuid": "unrelated-garden",
                    "title": "Seedlings",
                    "origin": "vault",
                    "plane": "vault",
                    "source_role": "vault_note",
                    "zone": "garden",
                    "evidence_role": "reference",
                },
            },
        ]
    )
    ask_route._HYBRID_WARMED = True
    return {"active": active_note, "waiting": waiting_note, "source": source_note, "unrelated": unrelated_note}


def test_human_uat_orientation_classifies_production_indexed_background(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reset_runtime_state(monkeypatch)
    paths = _seed_production_orientation_pack(tmp_path)

    response = TestClient(app).post(
        "/api/ask", json={"question": "Which notes mention the Atlas migration?"}
    )
    assert response.status_code == 200, response.text
    sources = {source["path"]: source for source in response.json()["sources"]}
    assert sources[str(paths["unrelated"])]["orientation"] == "background"
    assert "orientation_role" not in next(
        doc.payload for doc in get_hybrid_store().all() if doc.source_ref == str(paths["unrelated"])
    )


def test_human_uat_orientation_filters_background_before_synthesis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reset_runtime_state(monkeypatch)
    paths = _seed_production_orientation_pack(tmp_path)

    state = run_ask_graph(
        "I am returning to the Atlas migration after interruption. What is next?"
    )
    returned_paths = {hit.path for hit in state.hits}
    assert str(paths["unrelated"]) in returned_paths
    background_index = next(
        index for index, hit in enumerate(state.hits) if hit.path == str(paths["unrelated"])
    )
    assert all(hit.orientation != "background" for hit in state.hits[:background_index])
    if state.synthesis_source_ids:
        assert set(state.synthesis_source_ids) <= {hit.object_id for hit in state.hits}


def test_human_uat_orientation_producer_projection_and_admissibility_are_separate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reset_runtime_state(monkeypatch)
    vault_root = tmp_path / "vault"
    waiting = vault_root / "Projects" / "waiting.md"
    waiting.parent.mkdir(parents=True)
    waiting.write_text(
        "---\n"
        "uuid: 11111111-1111-4111-8111-111111111111\n"
        "zone: workbench\n"
        "commitment_state: waiting\n"
        "target_ref: Projects/active.md\n"
        "evidence_role: reference\n"
        "---\n"
        "Waiting for approval.\n",
        encoding="utf-8",
    )
    summary = run_vault_alpha_ingest_paths(vault_root, [waiting], force=True)
    assert summary.ingested == 1
    row = next(row for row in get_vector_index().all_rows() if row["source_ref"].endswith("waiting.md"))
    payload = row["payload"]
    assert payload["commitment_state"] == "waiting"
    assert payload["zone"] == "workbench"
    assert payload["evidence_role"] == "reference"
    assert "orientation_role" not in payload


def test_human_uat_orientation_intent_requires_resumption_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reset_runtime_state(monkeypatch)
    paths = _seed_production_orientation_pack(tmp_path)
    client = TestClient(app)

    for question in (
        "How do I return to the office?",
        "Can I pick up my prescription?",
        "What is the best way back to the hotel?",
    ):
        response = client.post("/api/ask", json={"question": question})
        assert response.status_code == 200, response.text
        assert str(paths["unrelated"]) in {source["path"] for source in response.json()["sources"]}

    response = client.post(
        "/api/ask", json={"question": "Help me resume the Atlas migration."}
    )
    sources = response.json()["sources"]
    assert sources
    assert sources[0]["path"] != str(paths["unrelated"])
    assert any(source["path"] == str(paths["unrelated"]) for source in sources)


def test_human_uat_orientation_context_limit_and_attribution_are_aligned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reset_runtime_state(monkeypatch)
    paths = _seed_production_orientation_pack(tmp_path)
    from app.agents.ask.utils import AskSettings

    state = run_ask_graph(
        "I am returning to the Atlas migration after interruption. What is next?",
        ask_settings=AskSettings(max_context_docs=2),
    )
    assert len(state.hits) <= 2
    assert str(paths["unrelated"]) not in {hit.path for hit in state.hits}
    if state.synthesis_source_ids:
        assert set(state.synthesis_source_ids) <= {hit.object_id for hit in state.hits}


def test_human_uat_return_after_interruption_orientation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Human-need target from docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md §2.

    This remains non-blocking system-level TDD: it asks for enough surfaced context to restart
    meaningful work after interruption, not just a top-hit retrieval result.
    """
    _reset_runtime_state(monkeypatch)

    paths = _seed_orientation_pack(tmp_path)

    client = TestClient(app)
    resp = client.post(
        "/api/ask",
        json={"question": "I am returning to the Atlas migration after interruption. What was I doing and what is next?"},
    )
    assert resp.status_code == 200, resp.text

    data = resp.json()
    sources = data.get("sources") or []
    source_paths = {src.get("path") for src in sources if src.get("path")}

    assert str(paths["active"]) in source_paths
    assert str(paths["waiting"]) in source_paths
    assert str(paths["source"]) in source_paths
    assert str(paths["unrelated"]) in source_paths
    assert sources[-1]["orientation"] == "background"
    orientation_by_path = {source["path"]: source["orientation"] for source in sources}
    assert orientation_by_path[str(paths["active"])] == "active"
    assert orientation_by_path[str(paths["waiting"])] == "waiting"
    assert orientation_by_path[str(paths["source"])] == "supporting"


def test_human_uat_orientation_preserves_source_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_runtime_state(monkeypatch)
    paths = _seed_orientation_pack(tmp_path)

    response = TestClient(app).post("/api/ask", json={"question": "Help me resume the Atlas migration."})
    assert response.status_code == 200, response.text

    sources_by_path = {source["path"]: source for source in response.json()["sources"]}
    for path in (paths["active"], paths["waiting"], paths["source"]):
        source = sources_by_path[str(path)]
        assert source["uuid"]
        assert source["origin"] == "vault"
        assert source["plane"] == "vault"
        assert source["path"] == str(path)


def test_human_uat_orientation_is_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_runtime_state(monkeypatch)
    _seed_orientation_pack(tmp_path)
    before_objects = get_object_store()._objects.copy()

    response = TestClient(app).post("/api/ask", json={"question": "What was I doing in the Atlas migration?"})

    assert response.status_code == 200, response.text
    assert get_object_store()._objects == before_objects
    assert not list(tmp_path.rglob("*")), "orientation must not materialize vault artifacts"


def test_human_uat_archive_source_reuse_without_note_conversion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Human-need target from docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md §2A.

    The intended behavior is that retained artifacts remain directly retrievable and citeable
    without being rewritten into vault notes first.
    """
    _reset_runtime_state(monkeypatch)

    _object_id, retained_path = _seed_archive_artifact(
        tmp_path,
        filename="quarterly-timeline-report.txt",
        text=(
            "Retained archive report. Vendor timeline states the gateway migration must finish before October "
            "and cites a two-week validation window."
        ),
    )

    client = TestClient(app)
    resp = client.post(
        "/api/ask",
        json={"question": "What does the retained PDF say about the vendor migration timeline?"},
    )
    assert resp.status_code == 200, resp.text

    data = resp.json()
    sources = data.get("sources") or []
    assert sources, "expected retained source to be surfaced"

    top = sources[0]
    assert top.get("origin") == "external_raw"
    assert top.get("plane") == "external"
    assert top.get("path") == retained_path


def test_human_uat_archive_source_reuse_is_non_destructive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Archive retrieval must not create or mutate a warm vault note."""
    _reset_runtime_state(monkeypatch)

    object_id, retained_path = _seed_archive_artifact(
        tmp_path,
        filename="quarterly-timeline-report.txt",
        text="The retained report says the vendor migration finishes before October.",
    )
    before_objects = deepcopy(get_object_store()._objects)
    before_rows = deepcopy(list(get_vector_index().all_rows()))

    response = TestClient(app).post(
        "/api/ask",
        json={"question": "When does the vendor migration finish according to the retained report?"},
    )

    assert response.status_code == 200, response.text
    assert get_object_store()._objects == before_objects
    assert get_vector_index().all_rows() == before_rows
    stored = get_object_store().get(UUID(object_id))
    assert stored is not None
    assert stored["kind"] == "external"
    assert stored["source_ref"] == retained_path


def test_human_uat_archive_source_identity_is_citable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The response must expose the durable source identity needed for citation."""
    _reset_runtime_state(monkeypatch)

    object_id, retained_path = _seed_archive_artifact(
        tmp_path,
        filename="quarterly-timeline-report.txt",
        text="Retained vendor report states the vendor migration timeline and cites a two-week validation window.",
    )

    response = TestClient(app).post(
        "/api/ask",
        json={"question": "What does the retained vendor report say about the vendor migration timeline?"},
    )

    assert response.status_code == 200, response.text
    sources = response.json().get("sources") or []
    assert sources
    top = sources[0]
    assert top["uuid"] == object_id
    assert top["path"] == retained_path
    assert top["origin"] == "external_raw"
    assert top["plane"] == "external"
