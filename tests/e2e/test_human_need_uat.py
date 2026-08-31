from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import ask as ask_route
from app.agents.ask.graph import run_ask_graph
from app.ingest.vault_alpha import run_vault_alpha_ingest_paths
from app.retrieval.hybrid import get_store as get_hybrid_store
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
    get_hybrid_store().set_documents([])
    monkeypatch.setattr(ask_route, "_HYBRID_WARMED", False, raising=False)


def _seed_object(*, title: str, source_ref: str, text: str, origin: str = "vault", plane: str | None = None) -> str:
    object_id = uuid4()
    payload = {
        "uuid": str(object_id),
        "title": title,
        "origin": origin,
        "plane": plane or origin,
        "text": text,
        "source_ref": source_ref,
    }
    get_object_store().put(object_id, kind="note", source_ref=source_ref, payload=payload)
    return str(object_id)


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
    assert str(paths["unrelated"]) not in returned_paths
    assert all(hit.orientation != "background" for hit in state.hits)
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
    assert str(paths["unrelated"]) not in {source["path"] for source in response.json()["sources"]}


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
    assert str(paths["unrelated"]) not in source_paths
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


@pytest.mark.xfail(
    reason="Archive retrieval exists in parts, but archive-source reuse is not yet fully established as a release-grade human flow.",
    strict=False,
)
def test_human_uat_archive_source_reuse_without_note_conversion(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Human-need target from docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md §2A.

    The intended behavior is that retained artifacts remain directly retrievable and citeable
    without being rewritten into vault notes first.
    """
    _reset_runtime_state(monkeypatch)

    retained_path = "Archive/Vendor/quarterly-timeline-report.pdf"
    _seed_object(
        title="Quarterly Timeline Report",
        source_ref=retained_path,
        origin="external_raw",
        plane="external",
        text=(
            "Retained PDF report. Vendor timeline states the gateway migration must finish before October "
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
