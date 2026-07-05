"""KA-06 (#2801) replay test: full replay from `raw` reproduces equivalent derived
artifacts with ZERO source egress.

The slice's proof-of-architecture. No network, no real DB, no real LLM:

- the raw record is persisted through the real `persist_raw_record` into the memory object
  store (`STORE_BACKEND=memory`, the `not pg` default), so `get_raw_record` reads it back
  without a DB;
- the outbox insert is driven through the in-memory `FakeOutboxConn` PK-conflict emulation;
- the `summary` extractor's completion is stubbed via the `complete=` injection seam;
- zero source egress is asserted TWO ways: (1) the test monkeypatches the three egress
  seams to raise if called, and the replay still succeeds (proving the code path never
  reaches them), and (2) `run_replay` installs its own runtime guard over the same seams.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.knowledge_acquisition import youtube_plugin
from app.knowledge_acquisition.extraction_registry import clear_registry
from app.knowledge_acquisition.extractors import summary_extractor
from app.knowledge_acquisition.normalize import normalize
from app.knowledge_acquisition.raw_record import persist_raw_record
from app.knowledge_acquisition.replay import (
    ReplayError,
    SourceEgressBlockedError,
    run_replay,
)
from app.knowledge_acquisition.stage_events import (
    STAGE_COMPLETED_TOPIC,
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
            row_id, topic, payload, created_at, attempts = params
            if row_id in self.rows:
                return _FakeCursor([])
            self.rows[row_id] = {
                "id": row_id,
                "topic": topic,
                "payload": payload,
                "created_at": created_at,
                "delivered_at": None,
                "attempts": attempts,
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


@pytest.fixture(autouse=True)
def _block_source_egress(monkeypatch: pytest.MonkeyPatch):
    """Independent egress assertion: fail if replay reaches any source-egress seam.

    Belt-and-suspenders alongside `run_replay`'s own guard — this proves at the TEST level
    that the replay code path never touches acquisition, not merely that the guard was
    installed."""

    def _forbidden(name: str):
        def _raise(*_a: Any, **_k: Any):
            raise AssertionError(f"source egress seam {name!r} was called during replay")

        return _raise

    import app.media.transcribe as transcribe_mod

    monkeypatch.setattr(youtube_plugin, "yt_dlp_extract_info", _forbidden("yt_dlp_extract_info"))
    monkeypatch.setattr(youtube_plugin, "fetch_caption_body", _forbidden("fetch_caption_body"))
    monkeypatch.setattr(youtube_plugin, "fetch", _forbidden("fetch"))
    monkeypatch.setattr(transcribe_mod, "transcribe_source", _forbidden("transcribe_source"))
    monkeypatch.setattr(youtube_plugin, "transcribe_source", _forbidden("transcribe_source"))
    yield


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


def test_replay_from_raw_no_source_egress_equivalent_output(tmp_path: Path) -> None:
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
    assert first.equivalent is True

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
    assert stages["extracted"].extractor_version == 1

    # candidate: byte-identical by first-write-wins preservation on the second replay.
    assert stages["candidate"].status == "already_exists"
    assert stages["candidate"].equivalence == "byte_identical_first_write_preserved"

    # Exactly one candidate note on disk after two replays (idempotent write).
    notes = list((tmp_path / "vault").rglob("*.md"))
    assert len(notes) == 1

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
