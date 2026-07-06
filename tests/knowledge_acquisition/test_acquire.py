"""Tests for the acquisition entrypoint (#3106): fetch a NEW YouTube URL end-to-end.

All source egress is stubbed (`yt_dlp_extract_info` / `fetch_caption_body` monkeypatched, per
the same pattern `test_youtube_fetch.py` uses) and the LLM extractor is stubbed via the
`summary_extractor.register(complete=...)` injection seam (per `test_replay.py`). The outbox
is a fake in-memory connection (`FakeOutboxConn`), so no real Postgres is required for these
`not_pg` tests — but `DATABASE_URL`/`DB_DSN` must still be set in the environment for the
entrypoint's own DB-required guard to pass (the guard only checks presence of the env var, not
reachability of the DSN behind it, since these tests inject `conn=` directly).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app import objects as object_store_module
from app.knowledge_acquisition import youtube_plugin as plugin
from app.knowledge_acquisition.acquire import (
    AcquisitionError,
    DatabaseNotConfiguredError,
    acquire_youtube,
    require_configured_database_url,
)
from app.knowledge_acquisition.extraction_registry import clear_registry
from app.knowledge_acquisition.extractors import summary_extractor
from app.knowledge_acquisition.stage_events import (
    STAGE_COMPLETED_TOPIC,
    STAGE_DEAD_LETTERED_TOPIC,
)
from app.stores import reset_store_backends
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg

FAKE_URL = "https://www.youtube.com/watch?v=abcdefghijk"
VIDEO_ID = "abcdefghijk"


class _FakeCursor:
    def __init__(self, rows: list[tuple]):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeOutboxConn:
    """In-memory outbox emulating the PK-conflict dedup the real outbox does (per test_replay.py)."""

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
def _memory_store(monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()
    object_store_module._MEMORY_STORE.clear()
    yield
    reset_store_backends()
    object_store_module._MEMORY_STORE.clear()


@pytest.fixture(autouse=True)
def _configured_db_env(monkeypatch):
    """The entrypoint's DB-required guard needs the env var present; tests inject a fake
    conn= directly so no real Postgres connection is ever attempted."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/app_test")
    yield


def _base_info(**overrides):
    info = {
        "id": VIDEO_ID,
        "title": "A Test Video",
        "channel": "Test Channel",
        "channel_id": "UC123",
        "upload_date": "20260101",
        "duration": 600,
        "description": "desc",
        "chapters": [],
        "tags": ["a", "b"],
        "language": "en",
        "thumbnail": "https://example.com/thumb.jpg",
        "subtitles": {"en": [{"ext": "vtt", "url": "https://example.com/manual.vtt"}]},
        "automatic_captions": {},
    }
    info.update(overrides)
    return info


_CAPTION_BODY = (
    "WEBVTT\n\n"
    "00:00:00.000 --> 00:00:02.000\n"
    "Hello world\n\n"
    "00:00:02.000 --> 00:00:04.000\n"
    "This is a transcript about testing.\n"
)


def _stub_caption_fetch(monkeypatch, *, info: dict[str, Any] | None = None, body: str = _CAPTION_BODY):
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info or _base_info())

    def fake_caption_body(url: str) -> str:
        return body

    monkeypatch.setattr(plugin, "fetch_caption_body", fake_caption_body)


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


# ---------------------------------------------------------------------------
# AC1: end-to-end new-URL acquisition — fetch -> persist raw -> normalize ->
# extract(summary) -> candidate note written, one stage event per transition.
# ---------------------------------------------------------------------------


def test_acquire_youtube_end_to_end_writes_candidate_and_emits_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_caption_fetch(monkeypatch)
    conn = FakeOutboxConn()
    vault = _vault(tmp_path / "vault")

    receipt = acquire_youtube(
        FAKE_URL, vault_context=vault, write_guard=_allowing_guard(), conn=conn
    )

    assert receipt.ok is True
    assert receipt.source_kind == "youtube_url"
    assert receipt.item_ref == VIDEO_ID
    assert receipt.is_new_raw is True

    stage_names = [s.stage for s in receipt.stages]
    assert stage_names == ["raw", "normalize", "extracted", "candidate"]

    candidate_stage = next(s for s in receipt.stages if s.stage == "candidate")
    assert candidate_stage.status == "written"
    assert candidate_stage.artifact_path

    notes = list((tmp_path / "vault").rglob("*.md"))
    assert len(notes) == 1
    assert notes[0].read_text(encoding="utf-8")  # candidate note has content

    # One stage.completed event per real transition (normalize, extracted, candidate).
    completed = conn.rows_for(STAGE_COMPLETED_TOPIC)
    stages_seen = {json.loads(r["payload"])["payload"]["stage"] for r in completed}
    assert stages_seen == {"normalize", "extracted", "candidate"}
    assert len(completed) == 3  # exactly one per transition, no duplicates


# ---------------------------------------------------------------------------
# AC2: idempotent re-run — dedup no-op on content_identity, no re-download,
# candidate stays byte-identical (first-write-wins).
# ---------------------------------------------------------------------------


def test_acquire_youtube_rerun_is_idempotent_dedup_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetch_calls = {"count": 0}

    def counting_caption_body(url: str) -> str:
        fetch_calls["count"] += 1
        return _CAPTION_BODY

    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: _base_info())
    monkeypatch.setattr(plugin, "fetch_caption_body", counting_caption_body)

    conn = FakeOutboxConn()
    vault = _vault(tmp_path / "vault")

    first = acquire_youtube(FAKE_URL, vault_context=vault, write_guard=_allowing_guard(), conn=conn)
    assert first.is_new_raw is True
    assert fetch_calls["count"] == 1

    note_path = tmp_path / "vault" / next(
        s.artifact_path for s in first.stages if s.stage == "candidate"
    )
    bytes_first = note_path.read_bytes()

    second = acquire_youtube(FAKE_URL, vault_context=vault, write_guard=_allowing_guard(), conn=conn)

    # Caption path re-fetches the (cheap) metadata/caption body every call (the plugin's
    # dedup identity is the caption body's hash), but this proves the DOWNSTREAM pipeline is
    # a traced no-op: raw dedups, and the candidate note is byte-identical, never rewritten.
    assert second.content_identity == first.content_identity
    assert second.is_new_raw is False
    raw_stage = next(s for s in second.stages if s.stage == "raw")
    assert raw_stage.status == "dedup_noop"
    assert raw_stage.idempotent is True

    candidate_stage = next(s for s in second.stages if s.stage == "candidate")
    assert candidate_stage.status == "already_exists"
    assert note_path.read_bytes() == bytes_first

    notes = list((tmp_path / "vault").rglob("*.md"))
    assert len(notes) == 1  # no duplicate note written

    # Stage-completed events deduped: re-running an unchanged item does not mint new rows.
    completed = conn.rows_for(STAGE_COMPLETED_TOPIC)
    assert len(completed) == 3  # still exactly 3: normalize + extracted + candidate, deduped


def test_acquire_youtube_asr_dedup_skips_reacquisition(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The ASR (captionless) path pre-checks dedup BEFORE running ASR — the plugin's own
    `find_raw_record` short-circuit (`youtube_plugin.fetch`). A known captionless item's
    re-run must not re-invoke ASR."""
    asr_calls = {"count": 0}

    def fake_asr(item_ref_or_url: str):
        asr_calls["count"] += 1
        return {
            "payload": {
                "text": "asr transcript text here",
                "segments": [{"start": 0.0, "end": 2.0, "text": "asr transcript text here"}],
                "language": "en",
            }
        }

    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: _base_info(subtitles={}, automatic_captions={}))
    monkeypatch.setattr(plugin, "transcribe_source", fake_asr)

    conn = FakeOutboxConn()
    vault = _vault(tmp_path / "vault")

    first = acquire_youtube(FAKE_URL, vault_context=vault, write_guard=_allowing_guard(), conn=conn)
    assert first.is_new_raw is True
    assert asr_calls["count"] == 1

    second = acquire_youtube(FAKE_URL, vault_context=vault, write_guard=_allowing_guard(), conn=conn)
    assert second.is_new_raw is False
    assert asr_calls["count"] == 1  # ASR never re-invoked on the dedup hit


# ---------------------------------------------------------------------------
# AC3: loud, item-scoped failure — no fabricated raw record, no partial
# candidate.
# ---------------------------------------------------------------------------


def test_acquire_youtube_fetch_failure_is_loud_no_raw_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ASR-chain failure on a captionless item: fetch() itself returns ok=False; the
    entrypoint must raise AcquisitionError with no raw record persisted and no candidate note."""
    monkeypatch.setattr(
        plugin, "yt_dlp_extract_info", lambda url: _base_info(subtitles={}, automatic_captions={})
    )

    def failing_asr(item_ref_or_url: str):
        raise RuntimeError("faster-whisper boom")

    monkeypatch.setattr(plugin, "transcribe_source", failing_asr)

    conn = FakeOutboxConn()
    vault = _vault(tmp_path / "vault")

    with pytest.raises(AcquisitionError):
        acquire_youtube(FAKE_URL, vault_context=vault, write_guard=_allowing_guard(), conn=conn)

    assert list((tmp_path / "vault").rglob("*.md")) == []
    # No raw record was persisted: a subsequent fetch (were it to succeed) starts fresh.
    from app.knowledge_acquisition.raw_record import find_raw_record

    existing = find_raw_record(
        source_kind="youtube_url",
        item_ref=VIDEO_ID,
        content_identity=plugin.compute_content_identity(
            metadata={
                "title": "A Test Video",
                "description": "desc",
                "duration": 600,
            },
            caption=plugin.CaptionSelection(available=False),
            asr_fallback=True,
        ),
    )
    assert existing is None
    assert conn.rows_for(STAGE_DEAD_LETTERED_TOPIC) == []  # no KA-06 stage reached; nothing to dead-letter there


def test_acquire_youtube_extractor_dead_letter_skips_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dead-lettered extractor must not produce a partial candidate note."""
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

    _stub_caption_fetch(monkeypatch)
    conn = FakeOutboxConn()
    vault = _vault(tmp_path / "vault")

    receipt = acquire_youtube(
        FAKE_URL,
        vault_context=vault,
        extractor_ids=("summary", "always_fails"),
        write_guard=_allowing_guard(),
        conn=conn,
    )

    assert receipt.ok is False
    assert receipt.dead_lettered == ("always_fails",)
    candidate_stage = next(s for s in receipt.stages if s.stage == "candidate")
    assert candidate_stage.status == "skipped_upstream_dead_letter"
    assert list((tmp_path / "vault").rglob("*.md")) == []

    dl_rows = conn.rows_for(STAGE_DEAD_LETTERED_TOPIC)
    assert len(dl_rows) == 1
    payload = json.loads(dl_rows[0]["payload"])["payload"]
    assert payload["stage"] == "extracted"
    assert payload["extractor_id"] == "always_fails"


def test_acquire_youtube_normalize_failure_dead_letters_and_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A normalize() failure dead-letters the item at the normalize stage and raises loudly,
    with no candidate note written."""
    # An empty caption body with no ASR segments makes normalize() fail (no parseable cues).
    _stub_caption_fetch(monkeypatch, body="WEBVTT\n\n")
    conn = FakeOutboxConn()
    vault = _vault(tmp_path / "vault")

    with pytest.raises(AcquisitionError):
        acquire_youtube(FAKE_URL, vault_context=vault, write_guard=_allowing_guard(), conn=conn)

    assert list((tmp_path / "vault").rglob("*.md")) == []
    dl_rows = conn.rows_for(STAGE_DEAD_LETTERED_TOPIC)
    assert len(dl_rows) == 1
    payload = json.loads(dl_rows[0]["payload"])["payload"]
    assert payload["stage"] == "normalize"
    assert payload["reason"] == "normalize_failed"
    assert payload["error"]


# ---------------------------------------------------------------------------
# AC4: DB-required guard — fails loud when DATABASE_URL/DB_DSN is unset,
# never silently skips stage-event emission.
# ---------------------------------------------------------------------------


def test_require_configured_database_url_raises_when_unset() -> None:
    with pytest.raises(DatabaseNotConfiguredError):
        require_configured_database_url(env={})


def test_require_configured_database_url_accepts_db_dsn() -> None:
    assert require_configured_database_url(env={"DB_DSN": "postgresql://x/y"}) == "postgresql://x/y"


def test_acquire_youtube_fails_loud_without_database_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard fires before any source egress: fetch/caption seams are deliberately left
    unstubbed here (raising if reached) to prove the DB check happens first."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    def _forbidden(*_a, **_k):
        raise AssertionError("fetch must not run before the DB-required guard fires")

    monkeypatch.setattr(plugin, "yt_dlp_extract_info", _forbidden)
    monkeypatch.setattr(plugin, "fetch_caption_body", _forbidden)

    vault = _vault(tmp_path / "vault")

    with pytest.raises(DatabaseNotConfiguredError):
        acquire_youtube(FAKE_URL, vault_context=vault, write_guard=_allowing_guard(), env={})

    assert list((tmp_path / "vault").rglob("*.md")) == []
