"""Production orientation bundle consumption tests (#1563, #1592)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.context_bundles.runtime_registry import clear_emitted_bundles, register_emitted_bundle
from app.context_bundles.schema import (
    AuthorityFlags,
    ExcludedItem,
    ItemProvenance,
)
from app.retrieval.bundle_emission import emit_retrieval_bundle
from app.retrieval.capability import RetrievalHit, RetrievalResponse


@pytest.fixture(autouse=True)
def _clear_registry():
    clear_emitted_bundles()
    yield
    clear_emitted_bundles()


def _response() -> RetrievalResponse:
    return RetrievalResponse(
        query="orientation query",
        trace_id="trace-orient",
        hits=[
            RetrievalHit(
                object_id="emitted-artifact",
                doc_id="doc-1",
                text="body",
                score=0.91,
                snippet=None,
                source_ref="vault/emitted-note.md",
                payload={},
            )
        ],
    )


def _register_orientation_bundle(
    bundle_id: str,
    *,
    may_orient: bool = True,
    may_write: bool = False,
    intended_use: list[str] | None = None,
) -> None:
    result = emit_retrieval_bundle(
        _response(),
        selected_ids=["emitted-artifact"],
        bundle_id=bundle_id,
    )
    bundle = result.bundle.model_copy(
        update={
            "intended_use": intended_use or ["orient"],
            "authority": AuthorityFlags(
                may_answer=True,
                may_orient=may_orient,
                may_write=may_write,
            ),
            "excluded": [
                ExcludedItem(
                    artifact_id="excluded-emitted",
                    reason="excluded from emitted retrieval selection",
                    provenance=ItemProvenance(origin="retrieval"),
                )
            ],
        },
        deep=True,
    )
    register_emitted_bundle(bundle)


def test_orientation_path_consumes_emitted_bundle():
    _register_orientation_bundle("ob-1")
    client = TestClient(app)
    resp = client.get("/api/orientation/bundle/ob-1")
    assert resp.status_code == 200
    body = resp.json()

    assert body["bundle_id"] == "ob-1"
    # Exclusions are surfaced for review (part of provenance).
    assert isinstance(body["exclusions"], list)
    assert body["exclusions"], "exclusions must be preserved in the orientation frame"

    # Included items are projected into the frame buckets, with provenance kept.
    segments = body["facts"] + body["inferences"] + body["candidate_actions"]
    assert segments, "bundle included items must be projected into the frame"
    assert any(seg.get("provenance") for seg in segments), "per-item provenance must be preserved"
    assert {seg["artifact_id"] for seg in segments} == {"emitted-artifact"}
    assert "contract-example" not in {seg["artifact_id"] for seg in segments}


def test_orientation_path_consumes_route_emitted_bundle(monkeypatch):
    import app.retrieval.production_bundle as production_bundle

    monkeypatch.setattr(production_bundle, "retrieve", lambda request: _response())

    client = TestClient(app)
    emitted = client.get("/api/context-bundles/ob-route?query=real&intended_use=orient")
    assert emitted.status_code == 200
    assert emitted.json()["authority"]["may_orient"] is True

    resp = client.get("/api/orientation/bundle/ob-route")
    assert resp.status_code == 200
    body = resp.json()
    segments = body["facts"] + body["inferences"] + body["candidate_actions"]
    assert {seg["artifact_id"] for seg in segments} == {"emitted-artifact"}


def test_orientation_path_non_write_authoritative():
    _register_orientation_bundle("ob-2")
    client = TestClient(app)
    body = client.get("/api/orientation/bundle/ob-2").json()
    assert body["may_write"] is False
    assert body["read_only"] is True


def test_orientation_path_rejects_non_orient_bundle():
    _register_orientation_bundle("ob-bad", may_orient=False, intended_use=["answer"])

    client = TestClient(app)
    resp = client.get("/api/orientation/bundle/ob-bad")
    assert resp.status_code == 409


def test_orientation_path_rejects_missing_emitted_bundle():
    client = TestClient(app)
    resp = client.get("/api/orientation/bundle/missing-bundle")
    assert resp.status_code == 404
    assert "not emitted" in resp.json()["detail"]
