from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import ask as ask_route
from app.retrieval.hybrid import get_store as get_hybrid_store
from app.stores import get_object_store, reset_store_backends


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


@pytest.mark.xfail(
    reason="Current baseline supports retrieval, but not a strong orientation surface for active/waiting/background restart flows.",
    strict=False,
)
def test_human_uat_return_after_interruption_orientation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Human-need target from docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md §2.

    This remains non-blocking system-level TDD: it asks for enough surfaced context to restart
    meaningful work after interruption, not just a top-hit retrieval result.
    """
    _reset_runtime_state(monkeypatch)

    active_note = tmp_path / "Projects" / "atlas-migration.md"
    waiting_note = tmp_path / "Projects" / "atlas-waiting.md"
    source_note = tmp_path / "Sources" / "vendor-memo.md"
    unrelated_note = tmp_path / "Garden" / "seedlings.md"

    _seed_object(
        title="Atlas Migration",
        source_ref=str(active_note),
        text=(
            "Atlas migration is the active project. Current focus: migrate the API gateway. "
            "Next step: draft the migration checklist and schedule the rollout review."
        ),
    )
    _seed_object(
        title="Atlas Waiting",
        source_ref=str(waiting_note),
        text=(
            "Atlas migration waiting item. Blocked pending finance approval and vendor confirmation. "
            "Do not treat this as the next action."
        ),
    )
    _seed_object(
        title="Vendor Memo",
        source_ref=str(source_note),
        text=(
            "Vendor migration memo for Atlas. Confirms gateway deprecation window and required cutover steps."
        ),
    )
    _seed_object(
        title="Seedlings",
        source_ref=str(unrelated_note),
        text="Garden seedlings note about watering tomatoes and spring soil temperature.",
    )

    client = TestClient(app)
    resp = client.post(
        "/api/ask",
        json={"question": "I am returning to the Atlas migration after interruption. What was I doing and what is next?"},
    )
    assert resp.status_code == 200, resp.text

    data = resp.json()
    sources = data.get("sources") or []
    source_paths = {src.get("path") for src in sources if src.get("path")}

    assert str(active_note) in source_paths
    assert str(waiting_note) in source_paths
    assert str(source_note) in source_paths
    assert str(unrelated_note) not in source_paths


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
