from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.agent_memory.ask_provenance_manifest import (
    AuthorizationSnapshot,
    capture_ask_provenance,
    compare_manifests,
    prune_expired_manifests,
    schedule_ask_provenance_capture,
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
    if "runtime" not in {part.casefold() for part in path.parts}:
        path = path.parent / "runtime" / path.name
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
                    payload={
                        "provenance": {
                            "content_hash": "hash-a",
                            "chunk_policy_version": "chunk-v1",
                            "pipeline_version": "pipeline-v1",
                        },
                        "domain": "work",
                    },
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
    monkeypatch.setenv("ASK_PROVENANCE_RUNTIME_ROOT", str(tmp_path / "runtime"))
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
        deadline = time.monotonic() + 1
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert path.exists()
        record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert record["ordered_evidence"][0]["canonical_source_hash"] == {
            "status": "available",
            "value": "hash-a",
        }
        assert record["authorization"]["principal_hash"] is None
        assert (
            record["authorization"]["principal_unavailable_reason"]
            == "caller_principal_not_observed"
        )
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
    assert manifest["answer_hash"] != hashlib.sha256(b"Grounded answer").hexdigest()
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

    malformed = json.loads(json.dumps(left))
    malformed["identities"]["canonical_index"] = {"status": "available"}
    assert compare_manifests(
        malformed,
        left,
        current_authorization=_snapshot(),
        privacy_key=b"test-only-key",
    ) == {"classification": "indeterminate", "reason": "manifest_invalid"}


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

    path = tmp_path / "runtime" / "manifest.jsonl"
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
    expired["captured_at"] = "2019-01-01T00:00:00Z"
    expired["expires_at"] = "2020-01-01T00:00:00Z"
    fresh["expires_at"] = "2030-01-01T00:00:00Z"
    path.write_text(
        "\n".join(json.dumps(item) for item in (expired, fresh)) + "\n", encoding="utf-8"
    )

    assert prune_expired_manifests(path, now="2029-01-01T00:00:00Z") == 1
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert records == [fresh]
    assert not (tmp_path / "vault").exists()

    expired_for_comparison = json.loads(json.dumps(fresh))
    expired_for_comparison["captured_at"] = "2019-01-01T00:00:00Z"
    expired_for_comparison["expires_at"] = "2020-01-01T00:00:00Z"
    assert compare_manifests(
        expired_for_comparison,
        fresh,
        current_authorization=_snapshot(),
        privacy_key=b"test-only-key",
    ) == {"classification": "indeterminate", "reason": "manifest_expired"}


def test_manifest_path_rejects_runtime_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "Yggdrasil"
    outside.mkdir()
    runtime_link = tmp_path / "runtime"
    runtime_link.symlink_to(outside, target_is_directory=True)

    result = capture_ask_provenance(
        answer="answer",
        query="q",
        evidence=[],
        authorization=_snapshot(),
        path=runtime_link / "manifest.jsonl",
        privacy_key=b"test-only-key",
    )

    assert result is None
    assert not (outside / "manifest.jsonl").exists()


def test_shadow_capture_respects_latency_budget(tmp_path: Path, monkeypatch) -> None:
    from app.agent_memory import ask_provenance_manifest as module

    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def slow_append(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        entered.set()
        release.wait(timeout=1)
        finished.set()

    monkeypatch.setattr(module, "_append_manifest", slow_append)
    started = time.monotonic()
    schedule_ask_provenance_capture(
        answer="answer",
        query="q",
        evidence=[],
        authorization=_snapshot(),
        path=tmp_path / "runtime" / "manifest.jsonl",
        privacy_key=b"test-only-key",
    )
    elapsed = time.monotonic() - started

    assert entered.wait(timeout=1)
    assert elapsed < 0.1
    release.set()
    assert finished.wait(timeout=1)


def test_concurrent_capture_does_not_drop_records(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "manifests.jsonl"

    def capture(position: int) -> None:
        result = capture_ask_provenance(
            answer=f"answer-{position}",
            query="q",
            evidence=[],
            authorization=_snapshot(),
            path=path,
            privacy_key=b"test-only-key",
        )
        assert result is not None

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(capture, range(16)))

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 16
    assert len({record["manifest_id"] for record in records}) == 16
