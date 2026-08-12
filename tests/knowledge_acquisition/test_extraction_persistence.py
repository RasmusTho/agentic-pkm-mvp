"""YSNV2-04 durable transcript/extraction and proposal-companion tests."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app import objects as object_store_module
from app.knowledge_acquisition.candidate_writeback import candidate_note_path
from app.knowledge_acquisition.extraction_persistence import (
    EXTRACTION_ARTIFACT_KIND,
    load_latest_extraction,
    load_persisted_transcript,
    persist_normalized_transcript,
)
from app.knowledge_acquisition.extraction_registry import (
    ExtractionResult,
    clear_extraction_results,
    clear_registry,
    run_extractor,
)
from app.knowledge_acquisition.extractors import summary_extractor
from app.knowledge_acquisition.normalize import normalize
from app.knowledge_acquisition.raw_record import persist_raw_record
from app.knowledge_acquisition.replay import run_replay
from app.stores import reset_store_backends
from app.objects import DomainObject, ObjectStore
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard
from tests.knowledge_acquisition.test_replay import FakeOutboxConn, RAW_PAYLOAD
from tests.invariants._helpers import assert_validates

pytestmark = pytest.mark.not_pg


def _completion(payload: dict[str, object]):
    def complete(*, system: str, user: str, trace_id=None, max_tokens=None) -> str:
        return json.dumps(payload)

    return complete


@pytest.fixture(autouse=True)
def _isolated_runtime(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()
    object_store_module._MEMORY_STORE.clear()
    clear_registry()
    summary_extractor.register(
        complete=_completion({"summary": "Durable summary.", "confidence": 0.8})
    )
    yield
    clear_registry()
    summary_extractor.register()
    object_store_module._MEMORY_STORE.clear()
    reset_store_backends()


def _persist_raw() -> tuple[str, dict[str, object]]:
    result = persist_raw_record(
        source_kind=str(RAW_PAYLOAD["source_kind"]),
        item_ref=str(RAW_PAYLOAD["item_ref"]),
        content_identity=str(RAW_PAYLOAD["content_identity"]),
        payload=dict(RAW_PAYLOAD),
        source_ref="test:ysnv2-persistence",
    )
    return str(result.object_id), result.record


def _persist_raw_item(item_ref: str) -> tuple[str, dict[str, object]]:
    raw = {
        **RAW_PAYLOAD,
        "item_ref": item_ref,
        "url": f"https://youtube.com/watch?v={item_ref}",
    }
    result = persist_raw_record(
        source_kind=str(raw["source_kind"]),
        item_ref=item_ref,
        content_identity=str(raw["content_identity"]),
        payload=raw,
        source_ref=f"test:ysnv2-persistence:{item_ref}",
    )
    return str(result.object_id), result.record


def _vault(root: Path) -> VaultContext:
    root.mkdir(parents=True, exist_ok=True)
    return VaultContext(
        status="selected",
        active_vault_id="vault-test",
        active_vault_name="Vault Test",
        active_vault_path=str(root),
    )


def _guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def test_persisted_extraction_preserves_anchor_and_lineage_across_restart() -> None:
    raw_record_id, raw = _persist_raw()
    normalized = normalize(dict(raw))
    transcript = persist_normalized_transcript(
        raw_record_id=raw_record_id,
        raw_record=raw,
        normalized=normalized,
    )
    first = run_extractor(
        "summary",
        normalized.as_dict(),
        raw_record_id=raw_record_id,
        normalized_artifact_id=transcript.object_id,
    )

    # Fresh-process posture: process caches/registration disappear while ObjectStore survives.
    clear_extraction_results()
    clear_registry()

    def _must_not_rerun(**_kwargs) -> str:
        raise AssertionError("a same-version persisted extraction should survive restart")

    summary_extractor.register(complete=_must_not_rerun)
    restored = run_extractor(
        "summary",
        normalized.as_dict(),
        raw_record_id=raw_record_id,
        normalized_artifact_id=transcript.object_id,
    )
    persisted_transcript = load_persisted_transcript(
        raw_record_id=raw_record_id,
        content_identity=str(raw["content_identity"]),
        stage_version=normalized.stage_version,
    )
    persisted_extraction = load_latest_extraction(
        raw_record_id=raw_record_id,
        content_identity=str(raw["content_identity"]),
        extractor_id="summary",
        extractor_version=first.extractor_version,
    )

    assert restored.replayed is True
    assert restored.output == first.output
    assert restored.model_identity == first.model_identity
    assert persisted_transcript is not None
    transcript_payload = persisted_transcript.extensions
    anchors = transcript_payload["segments"]
    assert [segment["anchor"] for segment in anchors] == [
        "t000000000-t000002000-s0000",
        "t000002000-t000004000-s0001",
    ]
    assert persisted_transcript.derived_from == (raw_record_id,)
    assert persisted_extraction is not None
    assert persisted_extraction.raw_record_id == raw_record_id
    assert persisted_extraction.normalized_artifact_id == transcript.object_id
    assert persisted_extraction.input_anchors == tuple(
        segment["anchor"] for segment in anchors
    )
    assert persisted_extraction.result.source_content_identity == raw["content_identity"]
    assert_validates(
        persisted_transcript.metadata_bundle, "metadata-bundle.schema.json"
    )
    assert_validates(
        persisted_extraction.metadata_bundle, "metadata-bundle.schema.json"
    )


def test_bound_episode_ref_persists_with_lineage_across_restart() -> None:
    episode_ref = ["episode:test-bound-source"]
    raw_payload = {
        **RAW_PAYLOAD,
        "item_ref": "boundsource",
        "episode_ref": episode_ref,
    }
    persisted_raw = persist_raw_record(
        source_kind=str(raw_payload["source_kind"]),
        item_ref=str(raw_payload["item_ref"]),
        content_identity=str(raw_payload["content_identity"]),
        payload=raw_payload,
        source_ref="test:ysnv2-persistence:bound-episode",
    )
    raw_record_id = str(persisted_raw.object_id)
    assert persisted_raw.record["episode_ref"] == episode_ref

    normalized = normalize(dict(persisted_raw.record))
    transcript = persist_normalized_transcript(
        raw_record_id=raw_record_id,
        raw_record=persisted_raw.record,
        normalized=normalized,
    )
    extracted = run_extractor(
        "summary",
        normalized.as_dict(),
        raw_record_id=raw_record_id,
        normalized_artifact_id=transcript.object_id,
    )

    clear_extraction_results()
    clear_registry()
    restored_transcript = load_persisted_transcript(
        raw_record_id=raw_record_id,
        content_identity=str(raw_payload["content_identity"]),
        stage_version=normalized.stage_version,
    )
    restored_extraction = load_latest_extraction(
        raw_record_id=raw_record_id,
        content_identity=str(raw_payload["content_identity"]),
        extractor_id="summary",
        extractor_version=extracted.extractor_version,
    )

    assert restored_transcript is not None
    assert restored_transcript.metadata_bundle["episode_ref"] == episode_ref
    assert restored_transcript.derived_from == (raw_record_id,)
    assert restored_extraction is not None
    assert restored_extraction.metadata_bundle["episode_ref"] == episode_ref
    assert restored_extraction.raw_record_id == raw_record_id


def test_reextraction_writes_versioned_proposal_companion_without_overwriting_candidate(
    tmp_path: Path,
) -> None:
    raw_record_id, _raw = _persist_raw()
    vault = _vault(tmp_path / "vault")
    conn = FakeOutboxConn()

    first = run_replay(
        raw_record_id,
        vault_context=vault,
        write_guard=_guard(),
        conn=conn,
    )
    initial_candidate = next(stage for stage in first.stages if stage.stage == "candidate")
    assert initial_candidate.status == "written"
    assert initial_candidate.artifact_path is not None
    candidate = Path(vault.active_vault_path) / initial_candidate.artifact_path
    owner_bytes = candidate.read_bytes() + b"\nOWNER AUTHORED BYTES\n"
    candidate.write_bytes(owner_bytes)

    second = run_replay(
        raw_record_id,
        vault_context=vault,
        write_guard=_guard(),
        conn=conn,
    )

    assert candidate.read_bytes() == owner_bytes
    candidate_stage = next(stage for stage in second.stages if stage.stage == "candidate")
    assert candidate_stage.status == "proposal_written"
    assert candidate_stage.artifact_path is not None
    first_proposal = Path(vault.active_vault_path) / candidate_stage.artifact_path
    assert "Durable summary." in first_proposal.read_text(encoding="utf-8")

    assert candidate_stage.artifact_path is not None
    proposal = Path(vault.active_vault_path) / candidate_stage.artifact_path
    assert proposal != candidate
    assert proposal.name.endswith(".meta.md")
    assert proposal.exists()
    body = proposal.read_text(encoding="utf-8")
    assert f"predecessor_ref: {candidate_note_path.__name__}" not in body
    assert initial_candidate.artifact_path in body
    assert str(RAW_PAYLOAD["content_identity"]) in body
    assert "proposal_reference:" in body
    assert "write_receipt:" in body

    third = run_replay(
        raw_record_id,
        vault_context=vault,
        write_guard=_guard(),
        conn=conn,
    )
    third_candidate = next(stage for stage in third.stages if stage.stage == "candidate")
    assert candidate.read_bytes() == owner_bytes
    assert third_candidate.status == "proposal_written"
    assert third_candidate.artifact_path not in {
        initial_candidate.artifact_path,
        candidate_stage.artifact_path,
    }
    assert len(list(candidate.parent.glob("*.meta.md"))) == 2


def test_latest_extraction_lookup_is_complete_beyond_one_thousand_objects() -> None:
    raw_record_id, raw = _persist_raw()
    normalized = normalize(dict(raw))
    transcript = persist_normalized_transcript(
        raw_record_id=raw_record_id,
        raw_record=raw,
        normalized=normalized,
    )
    expected = run_extractor(
        "summary",
        normalized.as_dict(),
        raw_record_id=raw_record_id,
        normalized_artifact_id=transcript.object_id,
    )
    store = ObjectStore()
    for index in range(1001):
        object_id = str(uuid4())
        store.save_object(
            DomainObject(
                uuid=object_id,
                kind=EXTRACTION_ARTIFACT_KIND,
                payload={
                    "object_id": object_id,
                    "extensions": {
                        "artifact_kind": "unrelated",
                        "sequence": index,
                    },
                },
                source_ref="test:unrelated",
                created_at=datetime.now(timezone.utc),
            ),
            emit_outbox=False,
        )

    restored = load_latest_extraction(
        raw_record_id=raw_record_id,
        content_identity=str(raw["content_identity"]),
        extractor_id="summary",
        extractor_version=expected.extractor_version,
    )

    assert restored is not None
    assert restored.object_id == expected.artifact_id


def test_identical_content_from_distinct_raw_authorities_keeps_separate_lineage() -> None:
    artifacts = []
    for item_ref in ("aaaaaaaaaaa", "bbbbbbbbbbb"):
        raw_record_id, raw = _persist_raw_item(item_ref)
        normalized = normalize(dict(raw))
        transcript = persist_normalized_transcript(
            raw_record_id=raw_record_id,
            raw_record=raw,
            normalized=normalized,
        )
        extraction = run_extractor(
            "summary",
            normalized.as_dict(),
            raw_record_id=raw_record_id,
            normalized_artifact_id=transcript.object_id,
        )
        artifacts.append((raw_record_id, transcript, extraction))

    assert artifacts[0][0] != artifacts[1][0]
    assert artifacts[0][1].object_id != artifacts[1][1].object_id
    assert artifacts[0][2].artifact_id != artifacts[1][2].artifact_id
    assert artifacts[0][1].derived_from == (artifacts[0][0],)
    assert artifacts[1][1].derived_from == (artifacts[1][0],)
    assert artifacts[0][2].raw_record_id == artifacts[0][0]
    assert artifacts[1][2].raw_record_id == artifacts[1][0]


def test_concurrent_identical_content_raw_authorities_never_borrow_lineage() -> None:
    barrier = threading.Barrier(2)

    def materialize(item_ref: str):
        raw_record_id, raw = _persist_raw_item(item_ref)
        normalized = normalize(dict(raw))
        transcript = persist_normalized_transcript(
            raw_record_id=raw_record_id,
            raw_record=raw,
            normalized=normalized,
        )
        barrier.wait(timeout=5)
        extraction = run_extractor(
            "summary",
            normalized.as_dict(),
            raw_record_id=raw_record_id,
            normalized_artifact_id=transcript.object_id,
        )
        return raw_record_id, transcript, extraction

    with ThreadPoolExecutor(max_workers=2) as executor:
        artifacts = list(executor.map(materialize, ("ccccccccccc", "ddddddddddd")))

    assert artifacts[0][1].object_id != artifacts[1][1].object_id
    assert artifacts[0][2].artifact_id != artifacts[1][2].artifact_id
    for raw_record_id, transcript, extraction in artifacts:
        assert transcript.derived_from == (raw_record_id,)
        assert extraction.raw_record_id == raw_record_id
        assert extraction.normalized_artifact_id == transcript.object_id


def test_concurrent_ordinary_extraction_converges_on_one_durable_artifact() -> None:
    raw_record_id, raw = _persist_raw()
    normalized = normalize(dict(raw))
    transcript = persist_normalized_transcript(
        raw_record_id=raw_record_id,
        raw_record=raw,
        normalized=normalized,
    )
    clear_extraction_results()
    barrier = threading.Barrier(2)

    def run_once(_index: int) -> ExtractionResult:
        clear_extraction_results()
        barrier.wait(timeout=5)
        return run_extractor(
            "summary",
            normalized.as_dict(),
            raw_record_id=raw_record_id,
            normalized_artifact_id=transcript.object_id,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run_once, range(2)))

    assert results[0].artifact_id == results[1].artifact_id
    persisted = [
        item
        for item in ObjectStore().list_objects(
            kind=EXTRACTION_ARTIFACT_KIND,
            limit=ObjectStore().count_objects(kind=EXTRACTION_ARTIFACT_KIND),
        )
        if item.payload.get("extensions", {}).get("extractor_id") == "summary"
    ]
    assert len(persisted) == 1
