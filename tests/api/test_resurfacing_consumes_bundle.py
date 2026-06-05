"""Production resurfacing bundle consumption tests (#1563, #1592)."""
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
        query="resurfacing query",
        trace_id="trace-resurface",
        hits=[
            RetrievalHit(
                object_id="resurface-artifact",
                doc_id="doc-1",
                text="body",
                score=0.87,
                snippet=None,
                source_ref="vault/resurface-note.md",
                payload={},
            )
        ],
    )


def _register_resurfacing_bundle(
    bundle_id: str,
    *,
    may_resurface: bool = True,
    may_write: bool = False,
    intended_use: list[str] | None = None,
) -> None:
    result = emit_retrieval_bundle(
        _response(),
        selected_ids=["resurface-artifact"],
        bundle_id=bundle_id,
    )
    bundle = result.bundle.model_copy(
        update={
            "intended_use": intended_use or ["resurface"],
            "authority": AuthorityFlags(
                may_answer=True,
                may_resurface=may_resurface,
                may_write=may_write,
            ),
            "excluded": [
                ExcludedItem(
                    artifact_id="excluded-resurface",
                    reason="excluded from emitted retrieval selection",
                    provenance=ItemProvenance(origin="retrieval"),
                )
            ],
        },
        deep=True,
    )
    register_emitted_bundle(bundle)


def test_resurfacing_path_consumes_emitted_bundle():
    _register_resurfacing_bundle("rb-1")
    client = TestClient(app)
    resp = client.get("/api/resurfacing/bundle/rb-1")
    assert resp.status_code == 200
    body = resp.json()

    assert body["bundle_id"] == "rb-1"
    assert body["suggestion_only"] is True
    assert body["may_write"] is False
    # Auditable why-now: a human-readable rationale anchored to a named signal.
    assert body["why_now"].strip()
    assert body["why_now_signal_name"].strip()
    assert {item["artifact_id"] for item in body["surfaced_items"]} == {"resurface-artifact"}
    assert "contract-example" not in {item["artifact_id"] for item in body["surfaced_items"]}


def test_resurfacing_path_consumes_route_emitted_bundle(monkeypatch):
    import app.retrieval.production_bundle as production_bundle

    monkeypatch.setattr(production_bundle, "retrieve", lambda request: _response())

    client = TestClient(app)
    emitted = client.get("/api/context-bundles/rb-route?query=real&intended_use=resurface")
    assert emitted.status_code == 200
    assert emitted.json()["authority"]["may_resurface"] is True

    resp = client.get("/api/resurfacing/bundle/rb-route")
    assert resp.status_code == 200
    assert {item["artifact_id"] for item in resp.json()["surfaced_items"]} == {"resurface-artifact"}


def test_rejects_bundle_not_scoped_for_resurface():
    _register_resurfacing_bundle("rb-bad", may_resurface=False, intended_use=["answer"])

    client = TestClient(app)
    resp = client.get("/api/resurfacing/bundle/rb-bad")
    assert resp.status_code == 409
