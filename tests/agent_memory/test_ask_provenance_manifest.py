from __future__ import annotations

import json
from pathlib import Path

from app.agent_memory.ask_provenance_manifest import (
    AuthorizationSnapshot,
    capture_ask_provenance,
    compare_manifests,
    prune_expired_manifests,
)


def _snapshot(*, scope: str = "work", principal: str = "owner") -> AuthorizationSnapshot:
    return AuthorizationSnapshot(
        scope_id=scope,
        principal_id=principal,
        authorization_context={"access_mode": "bounded_context_only"},
        policy={"citation_required": True, "mutation_allowed": False},
        authorized_source_ids=("source-1",),
    )


def _capture(
    path: Path, *, source_hash: str = "hash-a", index_identity: str | None = "index-a"
) -> dict:
    manifest = capture_ask_provenance(
        answer="Grounded answer",
        query="private question",
        evidence=[{"source_id": "source-1", "canonical_source_hash": source_hash}],
        authorization=_snapshot(),
        retrieval_identity=index_identity,
        synthesis_identity={"provider": "mock", "model": "mock-1"},
        path=path,
        privacy_key=b"test-only-key",
    )
    assert manifest is not None
    return manifest


def test_shadow_capture_preserves_ask_response_and_side_effects(
    tmp_path: Path, monkeypatch
) -> None:
    from fastapi.testclient import TestClient

    from app.agents.ask import graph as ask_graph
    from app.api.app import app
    from app.api.routes import ask as ask_module
    from app.retrieval.capability import RetrievalHit, RetrievalResponse
    from app.retrieval.hybrid import get_store

    def fake_retrieve(request):  # type: ignore[no-untyped-def]
        return RetrievalResponse(
            query=request.query,
            trace_id="trace",
            metadata={"canonical_index_identity": "index-a"},
            hits=[
                RetrievalHit(
                    object_id="source-1",
                    doc_id="source-1",
                    text="literal",
                    score=1.0,
                    snippet="literal",
                    source_ref="vault/private.md",
                    payload={"content_hash": "hash-a", "domain": "work"},
                )
            ],
        )

    monkeypatch.setattr(ask_graph, "retrieve", fake_retrieve)
    monkeypatch.setattr(ask_graph, "retrieve_relevant_promoted", lambda *_a, **_k: [])
    monkeypatch.setattr(
        ask_graph,
        "llm_answer",
        lambda *_a, **_k: ("same answer", {"provider": "mock", "model": "mock-1"}),
    )
    monkeypatch.setenv("ASK_PROVENANCE_PRIVACY_KEY", "test-only-key")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "ASK_SYNTHESIS_RECEIPTS_PATH",
        str(tmp_path / "runtime" / "activation" / "ask_synthesis_receipts.jsonl"),
    )
    path = tmp_path / "runtime" / "ask_provenance.jsonl"
    monkeypatch.setenv("ASK_PROVENANCE_MANIFEST_PATH", str(path))
    monkeypatch.setattr("app.api.routes.ask._ensure_hybrid_store_loaded", lambda: None)
    ask_module._HYBRID_WARMED = True
    client = TestClient(app)

    try:
        monkeypatch.delenv("ASK_PROVENANCE_MANIFEST_ENABLED", raising=False)
        disabled = client.post("/api/ask", json={"question": "private question"})
        assert not path.exists()

        monkeypatch.setenv("ASK_PROVENANCE_MANIFEST_ENABLED", "1")
        enabled = client.post("/api/ask", json={"question": "private question"})

        assert enabled.status_code == disabled.status_code == 200
        assert enabled.json()["answer"] == disabled.json()["answer"] == "same answer"
        assert enabled.json()["sources"] == disabled.json()["sources"]
        assert enabled.json()["synthesis_source_ids"] == disabled.json()["synthesis_source_ids"]
        assert path.exists()
        assert not (tmp_path / "vault").exists()
        assert not (tmp_path / "index").exists()
    finally:
        ask_module._HYBRID_WARMED = False
        get_store().set_documents([])


def test_manifest_is_minimal_and_privacy_safe(tmp_path: Path) -> None:
    manifest = _capture(tmp_path / "runtime" / "manifests.jsonl")
    encoded = json.dumps(manifest, sort_keys=True)

    assert manifest["schema"] == "ask_provenance_manifest.v1"
    assert manifest["answer_hash"]
    assert manifest["query_hash"]
    assert manifest["authorization"]["scope_id"] == "work"
    assert [item["position"] for item in manifest["ordered_evidence"]] == [0]
    assert manifest["ordered_evidence"][0]["canonical_source_hash"]["status"] == "available"
    assert manifest["identities"]["canonical_index"]["status"] == "available"
    for forbidden in ("Grounded answer", "private question", "vault/private.md", "owner"):
        assert forbidden not in encoded
    assert "answer" not in manifest
    assert "query" not in manifest


def test_comparison_classifies_only_supported_drift(tmp_path: Path) -> None:
    left = _capture(tmp_path / "left.jsonl", source_hash="hash-a")
    right = _capture(tmp_path / "right.jsonl", source_hash="hash-b")
    comparison = compare_manifests(
        left, right, current_authorization=_snapshot(), privacy_key=b"test-only-key"
    )
    assert comparison == {"classification": "source_drift"}

    right["identities"]["canonical_index"] = {"status": "unavailable", "reason": "not_observed"}
    comparison = compare_manifests(
        left, right, current_authorization=_snapshot(), privacy_key=b"test-only-key"
    )
    assert comparison == {
        "classification": "indeterminate",
        "reason": "canonical_index_identity_unavailable",
    }


def test_scope_mismatch_redacts_evidence_details(tmp_path: Path) -> None:
    left = _capture(tmp_path / "left.jsonl")
    right = _capture(tmp_path / "right.jsonl")
    comparison = compare_manifests(
        left,
        right,
        current_authorization=_snapshot(scope="personal"),
        privacy_key=b"test-only-key",
    )

    assert comparison["classification"] == "scope_mismatch"
    assert comparison["mismatch_axes"] == ["scope"]
    assert "evidence" not in json.dumps(comparison)
    assert "source-1" not in json.dumps(comparison)

    mismatch_snapshots = (
        AuthorizationSnapshot(
            "work",
            "someone-else",
            {"access_mode": "bounded_context_only"},
            {"citation_required": True, "mutation_allowed": False},
            ("source-1",),
        ),
        AuthorizationSnapshot(
            "work",
            "owner",
            {"access_mode": "different"},
            {"citation_required": True, "mutation_allowed": False},
            ("source-1",),
        ),
        AuthorizationSnapshot(
            "work",
            "owner",
            {"access_mode": "bounded_context_only"},
            {"citation_required": False, "mutation_allowed": False},
            ("source-1",),
        ),
        AuthorizationSnapshot(
            "work",
            "owner",
            {"access_mode": "bounded_context_only"},
            {"citation_required": True, "mutation_allowed": False},
            (),
        ),
    )
    expected_axes = ("principal", "authorization_context", "policy", "authorization")
    for snapshot, expected_axis in zip(mismatch_snapshots, expected_axes):
        redacted = compare_manifests(
            left, right, current_authorization=snapshot, privacy_key=b"test-only-key"
        )
        assert redacted == {"classification": "scope_mismatch", "mismatch_axes": [expected_axis]}


def test_capture_failure_isolated_from_ask(tmp_path: Path, monkeypatch) -> None:
    from app.agent_memory import ask_provenance_manifest as module

    path = tmp_path / "manifest.jsonl"
    monkeypatch.setattr(
        module, "_append_manifest", lambda *_a, **_k: (_ for _ in ()).throw(OSError("disk full"))
    )
    result = capture_ask_provenance(
        answer="still succeeds",
        query="q",
        evidence=[],
        authorization=_snapshot(),
        path=path,
        privacy_key=b"test-only-key",
    )
    assert result is None
    assert not path.exists()


def test_manifest_retention_is_local_and_bounded(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "manifests.jsonl"
    expired = _capture(path)
    fresh = _capture(path)
    expired["expires_at"] = "2020-01-01T00:00:00Z"
    fresh["expires_at"] = "2030-01-01T00:00:00Z"
    path.write_text(
        "\n".join(json.dumps(item) for item in (expired, fresh)) + "\n", encoding="utf-8"
    )

    assert prune_expired_manifests(path, now="2029-01-01T00:00:00Z") == 1
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert records == [fresh]
    assert not (tmp_path / "vault").exists()


def test_shadow_capture_respects_latency_budget(tmp_path: Path) -> None:
    ticks = iter((0.0, 0.050))
    result = capture_ask_provenance(
        answer="answer",
        query="q",
        evidence=[],
        authorization=_snapshot(),
        path=tmp_path / "manifest.jsonl",
        privacy_key=b"test-only-key",
        latency_budget_ms=10,
        clock=lambda: next(ticks),
    )
    assert result is None
    assert not (tmp_path / "manifest.jsonl").exists()
