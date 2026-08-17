"""KA-06 (#2801) replay test: full replay from `raw` reproduces equivalent derived
artifacts with ZERO source egress.

The slice's proof-of-architecture. No network, no real DB, no real LLM:

- the raw record is persisted through the real `persist_raw_record` into the memory object
  store (`STORE_BACKEND=memory`, the `not pg` default), so `get_raw_record` reads it back
  without a DB;
- the outbox insert is driven through the in-memory `FakeOutboxConn` PK-conflict emulation;
- the `summary` extractor's completion is stubbed via the `complete=` injection seam;
- zero source egress is asserted by the context-local runtime policy at every canonical
  YouTube/ASR seam, including overlap/restoration and concurrent-acquisition coverage.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import threading
from typing import Any

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.knowledge_acquisition import youtube_plugin
from app.knowledge_acquisition.candidate_writeback import (
    assemble_candidate,
    write_candidate_note,
)
from app.knowledge_acquisition.extraction_registry import clear_registry
from app.knowledge_acquisition.extractors import summary_extractor
from app.knowledge_acquisition.normalize import normalize
from app.knowledge_acquisition.raw_record import (
    persist_raw_record,
    raw_record_object_id,
)
from app.knowledge_acquisition.replay import (
    ReplayError,
    ReplayReceipt,
    SourceEgressBlockedError,
    StageReplayReceipt,
    run_replay,
)
from app.knowledge_acquisition.stage_events import (
    STAGE_COMPLETED_TOPIC,
)
from app.objects import DomainObject, ObjectStore
from app.source_egress import (
    assert_source_egress_allowed,
    block_source_egress,
)
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg

RAW_PAYLOAD: dict[str, Any] = {
    "source_kind": "youtube_url",
    "item_ref": "dQw4w9WgXcQ",
    "url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
    "content_identity": "sha256:replay-fixture-identity",
    "acquisition_method": "captions_manual",
    "caption_language": "en",
    "caption_body": (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "Hello world\n\n"
        "00:00:02.000 --> 00:00:04.000\n"
        "This is a transcript about testing.\n"
    ),
    "metadata": {"title": "A Test Video", "channel": "Test Channel", "publish_date": "20260101"},
    "provenance": {
        "source_kind": "youtube_url",
        "url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
        "creator": "Test Channel",
        "published": "20260101",
        "acquisition_method": "captions_manual",
    },
}


class _FakeCursor:
    def __init__(self, rows: list[tuple]):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeOutboxConn:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def execute(self, sql: str, params: tuple = ()) -> _FakeCursor:
        text = " ".join(sql.lower().split())
        if text.startswith("insert into outbox (id,"):
            assert "on conflict (id) do nothing" in text
            row_id, topic, payload, created_at, attempts, legacy_key, vault_binding_id, *_ = params
            if row_id in self.rows:
                return _FakeCursor([])
            self.rows[row_id] = {
                "id": row_id,
                "topic": topic,
                "payload": payload,
                "created_at": created_at,
                "delivered_at": None,
                "attempts": attempts,
                "legacy_key": legacy_key,
                "vault_binding_id": vault_binding_id,
            }
            return _FakeCursor([(row_id,)])
        raise AssertionError(f"unexpected SQL shape reached the outbox: {text!r}")

    def close(self) -> None:  # pragma: no cover
        pass

    def rows_for(self, topic: str) -> list[dict[str, Any]]:
        return [r for r in self.rows.values() if r["topic"] == topic]


def _stub_completion(raw: str):
    def complete(*, system: str, user: str, trace_id=None, max_tokens=None) -> str:
        return raw

    return complete


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_registry()
    summary_extractor.register(
        complete=_stub_completion(
            json.dumps({"summary": "A deterministic test summary.", "confidence": 0.75})
        )
    )
    yield
    clear_registry()
    summary_extractor.register()


def _vault(root: Path) -> VaultContext:
    root.mkdir(parents=True, exist_ok=True)
    return VaultContext(
        status="selected",
        active_vault_id="vault-test",
        active_vault_name="Vault Test",
        active_vault_path=str(root),
    )


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _persist_raw() -> str:
    result = persist_raw_record(
        source_kind=RAW_PAYLOAD["source_kind"],
        item_ref=RAW_PAYLOAD["item_ref"],
        content_identity=RAW_PAYLOAD["content_identity"],
        payload=dict(RAW_PAYLOAD),
        source_ref="test:replay",
    )
    return str(result.object_id)


# ---------------------------------------------------------------------------
# AC4: full replay from `raw` reproduces equivalent derived artifacts with zero
# source egress.
# ---------------------------------------------------------------------------


def test_replay_fresh_write_not_equivalent_then_preserved(tmp_path: Path) -> None:
    conn = FakeOutboxConn()
    vault = _vault(tmp_path / "vault")
    raw_id = _persist_raw()

    # First materialization: writes the candidate note (empty vault).
    first = run_replay(
        raw_id,
        vault_context=vault,
        write_guard=_allowing_guard(),
        conn=conn,
    )
    assert first.source_egress == 0
    assert first.equivalent is False

    # Replay again: derived levels re-run, candidate is first-write-wins preserved.
    second = run_replay(
        raw_id,
        vault_context=vault,
        write_guard=_allowing_guard(),
        conn=conn,
    )
    assert second.source_egress == 0
    assert second.equivalent is True

    stages = {s.stage: s for s in second.stages}

    # normalize: byte-identical equivalence, asserted deterministic.
    assert stages["normalize"].equivalence == "byte_identical"
    assert stages["normalize"].idempotent is True
    # And really byte-identical: the receipt's determinism check backs the class.
    n1 = normalize(dict(RAW_PAYLOAD)).as_dict()
    n2 = normalize(dict(RAW_PAYLOAD)).as_dict()
    assert n1 == n2

    # extracted: schema + lineage equivalence (NOT byte-identical text).
    assert stages["extracted"].equivalence == "schema_and_lineage"
    assert stages["extracted"].extractor_id == "summary"
    assert stages["extracted"].extractor_version == 2

    # candidate: first-write-wins, with the fresh re-extraction surfaced as a companion proposal.
    assert stages["candidate"].status == "proposal_written"
    assert stages["candidate"].equivalence == "versioned_proposal_original_preserved"

    # The original candidate plus one proposal companion and its derived transcript exist;
    # the candidate is untouched.
    notes = list((tmp_path / "vault").rglob("*.md"))
    assert len(notes) == 3
    assert len([path for path in notes if path.name.endswith(".meta.md")]) == 1

    # Stage events were emitted on the outbox for normalize + extracted + candidate.
    completed = conn.rows_for(STAGE_COMPLETED_TOPIC)
    stages_seen = {json.loads(r["payload"])["payload"]["stage"] for r in completed}
    assert stages_seen == {"normalize", "extracted", "candidate"}


def test_candidate_byte_identical_across_replay(tmp_path: Path) -> None:
    """The written candidate note is byte-identical after a replay (first-write-wins)."""
    conn = FakeOutboxConn()
    vault = _vault(tmp_path / "vault")
    raw_id = _persist_raw()

    first = run_replay(raw_id, vault_context=vault, write_guard=_allowing_guard(), conn=conn)
    note_path = tmp_path / "vault" / _candidate_stage_path(first)
    bytes_first = note_path.read_bytes()

    run_replay(raw_id, vault_context=vault, write_guard=_allowing_guard(), conn=conn)
    assert note_path.read_bytes() == bytes_first


def test_candidate_write_self_heals_missing_completed_event(tmp_path: Path) -> None:
    """A crash after note creation but before event emission heals on raw replay."""
    conn = FakeOutboxConn()
    vault = _vault(tmp_path / "vault")
    raw_id = _persist_raw()
    candidate = assemble_candidate(RAW_PAYLOAD)
    direct_write = write_candidate_note(
        candidate,
        vault_context=vault,
        write_guard=_allowing_guard(),
    )
    assert direct_write.status == "written"
    assert conn.rows == {}

    receipt = run_replay(
        raw_id,
        vault_context=vault,
        write_guard=_allowing_guard(),
        conn=conn,
    )

    candidate_stage = next(stage for stage in receipt.stages if stage.stage == "candidate")
    assert candidate_stage.status == "proposal_written"
    assert candidate_stage.equivalence == "versioned_proposal_original_preserved"
    candidate_events = [
        row
        for row in conn.rows_for(STAGE_COMPLETED_TOPIC)
        if json.loads(row["payload"])["payload"]["stage"] == "candidate"
    ]
    assert len(candidate_events) == 1


def test_fresh_candidate_write_does_not_claim_byte_identity(tmp_path: Path) -> None:
    """A replay that freshly writes the candidate note is not byte-comparable.

    The candidate renderer includes current timestamps. Until the note exists and
    first-write-wins can preserve its bytes, the receipt must not claim byte identity.
    """
    conn = FakeOutboxConn()
    vault = _vault(tmp_path / "vault")
    raw_id = _persist_raw()

    receipt = run_replay(raw_id, vault_context=vault, write_guard=_allowing_guard(), conn=conn)

    candidate = next(stage for stage in receipt.stages if stage.stage == "candidate")
    assert candidate.status == "written"
    assert candidate.equivalence == "fresh_write_not_byte_comparable"
    assert receipt.equivalent is False


def test_replay_valid_empty_asr_blocks_candidate_when_summary_is_required(
    tmp_path: Path,
) -> None:
    empty_asr = {
        **RAW_PAYLOAD,
        "content_identity": "sha256:replay-empty-asr",
        "acquisition_method": "asr",
        "caption_body": "",
        "asr_segments": [],
    }
    persisted = persist_raw_record(
        source_kind=empty_asr["source_kind"],
        item_ref=empty_asr["item_ref"],
        content_identity=empty_asr["content_identity"],
        payload=empty_asr,
        source_ref="test:replay-empty-asr",
    )

    def _unexpected_completion(**_kwargs) -> str:
        raise AssertionError("valid empty ASR must bypass transcript extraction")

    summary_extractor.register(complete=_unexpected_completion)
    conn = FakeOutboxConn()
    vault = _vault(tmp_path / "vault")

    receipt = run_replay(
        str(persisted.object_id),
        vault_context=vault,
        write_guard=_allowing_guard(),
        conn=conn,
    )

    assert [stage.stage for stage in receipt.stages] == [
        "normalize",
        "extracted",
        "candidate",
    ]
    candidate = receipt.stages[-1]
    assert candidate.status == "skipped_upstream_dead_letter"
    assert receipt.required_dead_lettered == ("summary",)
    assert list((tmp_path / "vault").rglob("*.md")) == []
    completed_stages = {
        json.loads(row["payload"])["payload"]["stage"]
        for row in conn.rows_for(STAGE_COMPLETED_TOPIC)
    }
    assert completed_stages == {"normalize"}


def test_replay_valid_empty_asr_materializes_degraded_when_summary_is_optional(
    tmp_path: Path,
) -> None:
    empty_asr = {
        **RAW_PAYLOAD,
        "content_identity": "sha256:replay-empty-asr-optional",
        "acquisition_method": "asr",
        "caption_body": "",
        "asr_segments": [],
    }
    persisted = persist_raw_record(
        source_kind=empty_asr["source_kind"],
        item_ref=empty_asr["item_ref"],
        content_identity=empty_asr["content_identity"],
        payload=empty_asr,
        source_ref="test:replay-empty-asr-optional",
    )

    receipt = run_replay(
        persisted.object_id,
        vault_context=_vault(tmp_path / "vault"),
        extractor_requirements={"summary": "optional_for_materialization"},
        write_guard=_allowing_guard(),
        conn=FakeOutboxConn(),
    )

    assert receipt.optional_dead_lettered == ("summary",)
    assert receipt.required_dead_lettered == ()
    candidate = receipt.stages[-1]
    assert candidate.status == "written_degraded"
    assert candidate.artifact_path is not None
    note = (tmp_path / "vault" / candidate.artifact_path).read_text(encoding="utf-8")
    assert "transcript_available: false" in note


def test_replay_rejects_non_raw_object_at_deterministic_raw_identity(tmp_path: Path) -> None:
    object_id = raw_record_object_id(
        source_kind=RAW_PAYLOAD["source_kind"],
        item_ref=RAW_PAYLOAD["item_ref"],
        content_identity="sha256:replay-not-raw",
    )
    ObjectStore().save_object(
        DomainObject(
            uuid=str(object_id),
            kind="knowledge_acquisition.normalized_transcript",
            payload={**RAW_PAYLOAD, "content_identity": "sha256:replay-not-raw"},
            source_ref="test:replay-not-raw",
            created_at=datetime.now(timezone.utc),
        ),
        emit_outbox=False,
    )

    with pytest.raises(ReplayError, match="not immutable raw evidence"):
        run_replay(
            object_id,
            vault_context=_vault(tmp_path / "vault"),
            write_guard=_allowing_guard(),
            conn=FakeOutboxConn(),
        )


def test_replay_malformed_asr_evidence_dead_letters_before_extraction(
    tmp_path: Path,
) -> None:
    from app.knowledge_acquisition.stage_events import STAGE_DEAD_LETTERED_TOPIC

    malformed_asr = {
        **RAW_PAYLOAD,
        "content_identity": "sha256:replay-malformed-asr",
        "acquisition_method": "asr",
        "caption_body": "",
        "asr_segments": [{"start": 2.0, "end": 1.0, "text": "reversed"}],
    }
    persisted = persist_raw_record(
        source_kind=malformed_asr["source_kind"],
        item_ref=malformed_asr["item_ref"],
        content_identity=malformed_asr["content_identity"],
        payload=malformed_asr,
        source_ref="test:replay-malformed-asr",
    )
    conn = FakeOutboxConn()

    with pytest.raises(ReplayError):
        run_replay(
            str(persisted.object_id),
            vault_context=_vault(tmp_path / "vault"),
            write_guard=_allowing_guard(),
            conn=conn,
        )

    dead_letters = conn.rows_for(STAGE_DEAD_LETTERED_TOPIC)
    assert len(dead_letters) == 1
    payload = json.loads(dead_letters[0]["payload"])["payload"]
    assert payload["stage"] == "normalize"
    assert payload["content_identity"] == "sha256:replay-malformed-asr"
    assert list((tmp_path / "vault").rglob("*.md")) == []


def test_acquire_replay_fresh_materialization_reports_successful_non_equivalence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The CLI succeeds when a fresh candidate write is non-byte-comparable."""
    fresh_receipt = ReplayReceipt(
        raw_record_id="raw-id",
        content_identity="sha256:fresh",
        source_egress=0,
        stages=(
            StageReplayReceipt(
                stage="normalize", status="ok", equivalence="byte_identical"
            ),
            StageReplayReceipt(
                stage="extracted",
                status="ok",
                equivalence="schema_and_lineage",
                extractor_id="summary",
                extractor_version=2,
            ),
            StageReplayReceipt(
                stage="candidate",
                status="written",
                equivalence="fresh_write_not_byte_comparable",
            ),
        ),
        equivalent=False,
    )
    import app.knowledge_acquisition.replay as replay_mod

    monkeypatch.setattr(replay_mod, "run_replay", lambda *_args, **_kwargs: fresh_receipt)

    result = CliRunner().invoke(
        cli,
        ["acquire-replay", "raw-id", "--vault-root", str(tmp_path / "vault")],
    )

    assert result.exit_code == 0, result.output
    assert "fresh materialization succeeded" in result.output.lower()
    assert "equivalent=false" in result.output

    failed_receipt = ReplayReceipt(
        raw_record_id="raw-id",
        content_identity="sha256:blocked",
        source_egress=0,
        stages=(
            StageReplayReceipt(
                stage="normalize", status="ok", equivalence="byte_identical"
            ),
            StageReplayReceipt(stage="candidate", status="blocked", equivalence="none"),
        ),
        equivalent=False,
    )
    monkeypatch.setattr(replay_mod, "run_replay", lambda *_args, **_kwargs: failed_receipt)

    failed = CliRunner().invoke(
        cli,
        ["acquire-replay", "raw-id", "--vault-root", str(tmp_path / "vault")],
    )
    assert failed.exit_code == 1


def _candidate_stage_path(receipt) -> str:
    for stage in receipt.stages:
        if stage.stage == "candidate":
            assert stage.artifact_path
            return stage.artifact_path
    raise AssertionError("no candidate stage in receipt")


def test_replay_runtime_guard_blocks_egress_seam(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`run_replay`'s own guard turns a source-egress call into a loud SourceEgressBlockedError.

    We wedge a call to an egress seam into the replay by patching `normalize` to reach one;
    the guard installed by `run_replay` must raise `SourceEgressBlockedError` (not a silent
    network call)."""
    vault = _vault(tmp_path / "vault")
    raw_id = _persist_raw()

    import app.knowledge_acquisition.replay as replay_mod

    def _normalize_that_egresses(raw_record):
        # Simulate a regression that reaches acquisition during replay.
        youtube_plugin.yt_dlp_extract_info("https://youtube.com/watch?v=x")
        raise AssertionError("unreachable: guard should have raised")

    monkeypatch.setattr(replay_mod, "normalize", _normalize_that_egresses)

    with pytest.raises(SourceEgressBlockedError):
        run_replay(raw_id, vault_context=vault, write_guard=_allowing_guard())


def test_replay_runtime_guard_stays_on_when_flag_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The compatibility flag cannot relax the KA-06 zero-source-egress guarantee."""
    vault = _vault(tmp_path / "vault")
    raw_id = _persist_raw()

    import app.knowledge_acquisition.replay as replay_mod

    def _normalize_that_egresses(raw_record):
        youtube_plugin.yt_dlp_extract_info("https://youtube.com/watch?v=x")
        raise AssertionError("unreachable: guard should have raised")

    monkeypatch.setattr(replay_mod, "normalize", _normalize_that_egresses)

    with pytest.raises(SourceEgressBlockedError):
        run_replay(
            raw_id,
            vault_context=vault,
            write_guard=_allowing_guard(),
            assert_no_source_egress=False,
        )


def test_overlapping_replay_guards_restore_locally_and_allow_concurrent_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No replay scope mutates another scope or a concurrent acquisition context."""
    entered = threading.Barrier(3)
    release = (threading.Event(), threading.Event())

    def replay_scope(index: int) -> str:
        with block_source_egress():
            entered.wait(timeout=5)
            with pytest.raises(SourceEgressBlockedError):
                assert_source_egress_allowed(f"replay-{index}")
            release[index].wait(timeout=5)
            with pytest.raises(SourceEgressBlockedError):
                assert_source_egress_allowed(f"replay-{index}-still-blocked")
        assert_source_egress_allowed(f"replay-{index}-restored")
        return "restored"

    monkeypatch.setattr(youtube_plugin, "yt_dlp_extract_info", lambda _url: {
        "id": "abcdefghijk",
        "title": "Concurrent acquisition",
        "description": "desc",
        "duration": 1,
        "language": "en",
        "subtitles": {"en": [{"ext": "vtt", "url": "test:vtt"}]},
        "automatic_captions": {},
    })
    monkeypatch.setattr(
        youtube_plugin,
        "fetch_caption_body",
        lambda _url: "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n",
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(replay_scope, index) for index in range(2)]
        entered.wait(timeout=5)
        # The main execution context is an ordinary acquisition while both replay contexts
        # remain blocked. It must reach its source seam and persist normally.
        acquired = youtube_plugin.fetch(
            "https://www.youtube.com/watch?v=abcdefghijk"
        )
        assert acquired.ok is True
        release[0].set()
        assert futures[0].result(timeout=5) == "restored"
        # Scope 1 is still independently blocked; releasing scope 0 did not restore it.
        release[1].set()
        assert futures[1].result(timeout=5) == "restored"

    assert_source_egress_allowed("post-overlap")


def test_replay_context_policy_is_checked_by_every_canonical_egress_seam() -> None:
    import app.media.transcribe as transcribe_mod

    seams = (
        lambda: youtube_plugin.yt_dlp_extract_info("test:blocked"),
        lambda: youtube_plugin.fetch_caption_body("test:blocked"),
        lambda: youtube_plugin.fetch("abcdefghijk"),
        lambda: transcribe_mod.transcribe_source("test:blocked"),
    )
    with block_source_egress():
        for seam in seams:
            with pytest.raises(SourceEgressBlockedError):
                seam()


def test_replay_reads_raw_not_transcript_derivative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A replay re-normalizes immutable raw and bypasses persisted extraction reads."""
    from app.knowledge_acquisition import extraction_persistence
    from app.knowledge_acquisition.extraction_persistence import persist_normalized_transcript

    raw_id = _persist_raw()
    normalized = normalize(dict(RAW_PAYLOAD))
    persisted = persist_normalized_transcript(
        raw_record_id=raw_id,
        raw_record=dict(RAW_PAYLOAD),
        normalized=normalized,
    )
    # A transcript derivative exists. Replay may persist a replacement-equivalent projection,
    # but it must never load that derivative as the source for normalize/extract/candidate.
    assert persisted.extensions["segments"]

    import app.knowledge_acquisition.replay as replay_mod

    original_normalize = replay_mod.normalize
    seen_inputs: list[dict[str, Any]] = []

    def _assert_raw_input(raw_record: dict[str, Any]):
        seen_inputs.append(dict(raw_record))
        assert raw_record["caption_body"] == RAW_PAYLOAD["caption_body"]
        assert "segments" not in raw_record
        return original_normalize(raw_record)

    def _forbid_derivative_load(**_kwargs):
        raise AssertionError("force re-extraction replay must not load a transcript derivative")

    monkeypatch.setattr(replay_mod, "normalize", _assert_raw_input)
    monkeypatch.setattr(extraction_persistence, "load_latest_extraction", _forbid_derivative_load)
    receipt = run_replay(
        raw_id,
        vault_context=_vault(tmp_path / "vault"),
        write_guard=_allowing_guard(),
        conn=FakeOutboxConn(),
    )

    assert receipt.source_egress == 0
    assert seen_inputs
    assert all(item["content_identity"] == RAW_PAYLOAD["content_identity"] for item in seen_inputs)


def test_replay_dead_letters_normalize_failure(tmp_path: Path) -> None:
    """A NormalizeError during replay dead-letters THIS item at the normalize stage
    (durable audit event) and fails the replay loudly — never a silent abort."""
    from app.knowledge_acquisition.stage_events import STAGE_DEAD_LETTERED_TOPIC

    conn = FakeOutboxConn()
    vault = _vault(tmp_path / "vault")
    captionless = dict(RAW_PAYLOAD, acquisition_method="captionless", caption_body=None)
    captionless["content_identity"] = "sha256:replay-captionless-identity"
    result = persist_raw_record(
        source_kind=captionless["source_kind"],
        item_ref=captionless["item_ref"],
        content_identity=captionless["content_identity"],
        payload=captionless,
        source_ref="test:replay-captionless",
    )

    with pytest.raises(ReplayError):
        run_replay(
            str(result.object_id),
            vault_context=vault,
            write_guard=_allowing_guard(),
            conn=conn,
        )

    dl_rows = conn.rows_for(STAGE_DEAD_LETTERED_TOPIC)
    assert len(dl_rows) == 1
    payload = json.loads(dl_rows[0]["payload"])["payload"]
    assert payload["stage"] == "normalize"
    assert payload["content_identity"] == "sha256:replay-captionless-identity"
    assert payload["reason"] == "normalize_failed"
    assert payload["error"]  # loud: the underlying error is preserved


def test_replay_skips_candidate_on_extractor_dead_letter(tmp_path: Path) -> None:
    """A dead-lettered extractor leaves siblings unaffected, and the candidate stage is
    reported skipped (its selected extraction inputs are incomplete) — no partial note."""
    from app.knowledge_acquisition.extraction_registry import ExtractorSpec, register_extractor

    def _boom(_normalized):
        raise RuntimeError("boom: injected extractor failure")

    register_extractor(
        ExtractorSpec(
            extractor_id="always_fails",
            version=1,
            input_content_type="transcript",
            output_schema_ref="test.failing.v1",
            run=_boom,
            model_identity=lambda: {"provider": "test", "model": "test"},
        )
    )

    conn = FakeOutboxConn()
    vault = _vault(tmp_path / "vault")
    raw_id = _persist_raw()

    receipt = run_replay(
        raw_id,
        vault_context=vault,
        extractor_ids=("summary", "always_fails"),
        write_guard=_allowing_guard(),
        conn=conn,
    )

    assert receipt.equivalent is False
    assert receipt.dead_lettered == ("always_fails",)

    by_key = {(s.stage, s.extractor_id): s for s in receipt.stages}
    # The sibling extractor still completed for this item.
    assert by_key[("extracted", "summary")].status == "ok"
    assert by_key[("extracted", "always_fails")].status == "dead_lettered"
    # Candidate did not assemble a partial note; the skip is explicit, never silent.
    candidate = by_key[("candidate", None)]
    assert candidate.status == "skipped_upstream_dead_letter"
    assert "always_fails" in (candidate.detail or "")
    assert list((tmp_path / "vault").rglob("*.md")) == []


def test_replay_missing_raw_record_is_loud(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    with pytest.raises(ReplayError):
        run_replay(
            "00000000-0000-0000-0000-000000000000",
            vault_context=vault,
            write_guard=_allowing_guard(),
        )


def test_replay_invalid_id_is_loud(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    with pytest.raises(ReplayError):
        run_replay("not-a-uuid", vault_context=vault, write_guard=_allowing_guard())
