"""KA-06 (#2801) stage-event tests: envelope + deterministic keys, duplicate-delivery
idempotency, and item-scoped dead-letters.

No network, no real DB, no real LLM: the DB outbox insert is driven through the same
in-memory `FakeOutboxConn` PK-conflict emulation `tests/services/test_outbox_idempotency.py`
uses (so `ON CONFLICT (id) DO NOTHING` semantics are exercised exactly), and the `summary`
extractor's completion is stubbed through the `complete=` injection seam
`test_candidate_writeback.py` / `test_summary_extractor.py` use. Every test resets the
extraction registry so a stubbed spec never leaks across modules.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.events.models import Event
from app.knowledge_acquisition.extraction_registry import (
    ExtractorSpec,
    UnknownExtractorError,
    clear_registry,
    register_extractor,
    run_extractor,
)
from app.knowledge_acquisition.extractors import summary_extractor
from app.knowledge_acquisition.extractors.summary_extractor import EXTRACTOR_VERSION
from app.knowledge_acquisition.normalize import normalize
from app.knowledge_acquisition.stage_events import (
    STAGE_COMPLETED_TOPIC,
    STAGE_DEAD_LETTERED_TOPIC,
    STAGE_EVENT_SOURCE,
    emit_stage_completed,
    run_extractors,
    stage_completed_key,
    stage_dead_letter_key,
)

pytestmark = pytest.mark.not_pg

RAW_RECORD_FIXTURE: dict[str, Any] = {
    "source_kind": "youtube_url",
    "item_ref": "dQw4w9WgXcQ",
    "url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
    "content_identity": "sha256:stage-events-fixture-identity",
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
}


class _FakeCursor:
    def __init__(self, rows: list[tuple]):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeOutboxConn:
    """In-memory emulation of the keyed outbox insert with PK-conflict semantics."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def execute(self, sql: str, params: tuple = ()) -> _FakeCursor:
        text = " ".join(sql.lower().split())
        if text.startswith("insert into outbox (id,"):
            assert "on conflict (id) do nothing" in text
            row_id, topic, payload, created_at, attempts = params
            if row_id in self.rows:
                return _FakeCursor([])  # conflict: nothing inserted / returned
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

    def close(self) -> None:  # pragma: no cover - psycopg parity
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


def _normalized_dict(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    return normalize(dict(raw if raw is not None else RAW_RECORD_FIXTURE)).as_dict()


# ---------------------------------------------------------------------------
# AC1: every stage transition emits exactly one standard-envelope outbox event
# with a deterministic idempotency key, asserted at the production emit site.
# ---------------------------------------------------------------------------


def test_envelope_and_deterministic_idempotency_key() -> None:
    conn = FakeOutboxConn()
    content_identity = RAW_RECORD_FIXTURE["content_identity"]

    # Production emit site for the `normalize` stage transition.
    key = emit_stage_completed(
        stage="normalize",
        stage_version=1,
        content_identity=content_identity,
        trace_id="trace-1",
        conn=conn,
    )

    # Exactly one row, keyed by the deterministic idempotency key (row id == key).
    assert len(conn.rows) == 1
    (row,) = conn.rows.values()
    assert row["id"] == key
    assert row["topic"] == STAGE_COMPLETED_TOPIC

    # The key is deterministic: independently derived from (stage, version, identity).
    assert key == stage_completed_key(
        stage="normalize", stage_version=1, content_identity=content_identity
    )

    # The persisted payload is a standard envelope (Event shape, docs/EVENTS.md fields).
    envelope = Event.model_validate_json(row["payload"])
    assert envelope.event_type == STAGE_COMPLETED_TOPIC
    assert envelope.source == STAGE_EVENT_SOURCE
    assert envelope.event_id  # unique event id present
    assert envelope.created_at  # ISO-8601 emission time present
    assert envelope.payload["stage"] == "normalize"
    assert envelope.payload["stage_version"] == 1
    assert envelope.payload["content_identity"] == content_identity


def test_extractor_run_emits_one_event_per_extractor_at_the_emit_site() -> None:
    """Each extractor run through the production orchestration emit site emits exactly one
    stage.completed event, keyed distinctly per (extractor_id, version, content_identity)."""
    conn = FakeOutboxConn()
    report = run_extractors(
        _normalized_dict(), extractor_ids=["summary"], trace_id="trace-x", conn=conn
    )

    assert len(report.successes) == 1
    completed = conn.rows_for(STAGE_COMPLETED_TOPIC)
    assert len(completed) == 1
    envelope = Event.model_validate_json(completed[0]["payload"])
    assert envelope.payload["stage"] == "extracted"
    assert envelope.payload["extractor_id"] == "summary"
    assert envelope.payload["stage_version"] == EXTRACTOR_VERSION
    # Lineage: model identity is carried in the extractor's completion event.
    assert "model_identity" in envelope.payload


def test_stage_version_bump_is_a_distinct_key() -> None:
    """A stage improvement (version bump) re-runs the stage and must be a DISTINCT lineage
    event — never swallowed against the old version's row (contract § Lineage and replay)."""
    identity = RAW_RECORD_FIXTURE["content_identity"]
    v1 = stage_completed_key(stage="normalize", stage_version=1, content_identity=identity)
    v2 = stage_completed_key(stage="normalize", stage_version=2, content_identity=identity)
    assert v1 != v2

    conn = FakeOutboxConn()
    emit_stage_completed(stage="normalize", stage_version=1, content_identity=identity, conn=conn)
    emit_stage_completed(stage="normalize", stage_version=2, content_identity=identity, conn=conn)
    assert len(conn.rows) == 2  # bumped version is a genuinely new row


def test_two_extractors_same_content_do_not_collide() -> None:
    """Different extractors over the same content identity are distinct lineage events."""
    identity = RAW_RECORD_FIXTURE["content_identity"]
    a = stage_completed_key(
        stage="extracted", stage_version=1, content_identity=identity, extractor_id="summary"
    )
    b = stage_completed_key(
        stage="extracted", stage_version=1, content_identity=identity, extractor_id="claims"
    )
    assert a != b


# ---------------------------------------------------------------------------
# AC2: duplicate event delivery does not duplicate stage effects.
# ---------------------------------------------------------------------------


def test_duplicate_delivery_idempotent() -> None:
    conn = FakeOutboxConn()
    content_identity = RAW_RECORD_FIXTURE["content_identity"]

    # (a) Event-row dedup: emitting the same stage transition twice yields ONE row; the
    # first call returns a truthy row id, the second returns "" (ON CONFLICT DO NOTHING).
    first = emit_stage_completed(
        stage="normalize", stage_version=1, content_identity=content_identity, conn=conn
    )
    second = emit_stage_completed(
        stage="normalize", stage_version=1, content_identity=content_identity, conn=conn
    )
    assert first  # first emission inserted a row
    assert second == ""  # duplicate delivery swallowed
    assert len(conn.rows_for(STAGE_COMPLETED_TOPIC)) == 1

    # (b) Underlying stage effect is not duplicated on a second invocation of the
    # emit-wrapped extractor stage: run_extractor caches its result (replayed=True on the
    # second run), so the LLM is not re-invoked and no second extraction artifact is made.
    normalized = _normalized_dict()
    run_a = run_extractors(normalized, extractor_ids=["summary"], conn=conn)
    run_b = run_extractors(normalized, extractor_ids=["summary"], conn=conn)

    assert run_a.successes[0].replayed is False
    assert run_b.successes[0].replayed is True  # served from cache, no duplicate effect
    # The extractor output is identical across the duplicate delivery.
    assert run_a.successes[0].output == run_b.successes[0].output
    # And the extractor's stage.completed event deduped to a single row (same key).
    assert len(conn.rows_for(STAGE_COMPLETED_TOPIC)) == 2  # normalize (a) + summary (one)


def test_cached_extraction_self_heals_missing_completed_event() -> None:
    """A crash after derived extraction but before event emission heals on replay."""
    normalized = _normalized_dict()
    precomputed = run_extractor("summary", normalized)
    assert precomputed.replayed is False
    conn = FakeOutboxConn()

    report = run_extractors(normalized, extractor_ids=["summary"], conn=conn)

    assert report.successes[0].replayed is True
    rows = conn.rows_for(STAGE_COMPLETED_TOPIC)
    assert len(rows) == 1
    envelope = Event.model_validate_json(rows[0]["payload"])
    assert envelope.payload["stage_version"] == EXTRACTOR_VERSION


# ---------------------------------------------------------------------------
# AC3: a failing stage dead-letters THAT item at THAT stage, loudly; sibling
# items / extractors are unaffected.
# ---------------------------------------------------------------------------


def _failing_spec(extractor_id: str) -> ExtractorSpec:
    def _run(_normalized):
        raise RuntimeError("boom: injected extractor failure")

    return ExtractorSpec(
        extractor_id=extractor_id,
        version=1,
        input_content_type="transcript",
        output_schema_ref="test.failing.v1",
        run=_run,
        model_identity=lambda: {"provider": "test", "model": "test"},
    )


def test_item_scoped_dead_letter() -> None:
    conn = FakeOutboxConn()
    content_identity = RAW_RECORD_FIXTURE["content_identity"]
    normalized = _normalized_dict()

    # Register a failing sibling extractor alongside the working `summary`.
    register_extractor(_failing_spec("always_fails"))

    report = run_extractors(
        normalized, extractor_ids=["always_fails", "summary"], conn=conn
    )

    # The failing extractor is dead-lettered (loud, structured, item-scoped) ...
    dead = report.dead_lettered
    assert len(dead) == 1
    assert dead[0].extractor_id == "always_fails"
    assert dead[0].status == "dead_lettered"
    assert dead[0].error  # loud: the reason is preserved, not swallowed

    # ... and a durable dead-letter audit event was written for THAT item at THAT stage.
    dl_rows = conn.rows_for(STAGE_DEAD_LETTERED_TOPIC)
    assert len(dl_rows) == 1
    dl_env = Event.model_validate_json(dl_rows[0]["payload"])
    assert dl_env.payload["stage"] == "extracted"
    assert dl_env.payload["extractor_id"] == "always_fails"
    assert dl_env.payload["content_identity"] == content_identity
    assert dl_env.payload["reason"] == "extraction_failed"

    # The SIBLING extractor still completed successfully, unaffected by the failure.
    assert len(report.successes) == 1
    assert report.successes[0].extractor_id == "summary"
    completed = conn.rows_for(STAGE_COMPLETED_TOPIC)
    assert len(completed) == 1
    assert Event.model_validate_json(completed[0]["payload"]).payload["extractor_id"] == "summary"


def _make_counting_spec(extractor_id: str, calls: list[str]) -> ExtractorSpec:
    def _run(_normalized):
        calls.append(extractor_id)
        return {"ok": True}

    return ExtractorSpec(
        extractor_id=extractor_id,
        version=1,
        input_content_type="transcript",
        output_schema_ref="test.counting.v1",
        run=_run,
        model_identity=lambda: {"provider": "test", "model": "test"},
    )


def test_unknown_extractor_is_resolved_before_any_sibling_effect() -> None:
    calls: list[str] = []
    register_extractor(_make_counting_spec("would_run", calls))

    with pytest.raises(UnknownExtractorError):
        run_extractors(
            _normalized_dict(),
            extractor_ids=["would_run", "not_registered"],
            conn=FakeOutboxConn(),
        )

    assert calls == []


def test_model_identity_failure_becomes_required_dead_letter() -> None:
    register_extractor(
        ExtractorSpec(
            extractor_id="identity_fails",
            version=1,
            input_content_type="transcript",
            output_schema_ref="test.identity-fails.v1",
            run=lambda _normalized: {"ok": True},
            model_identity=lambda: (_ for _ in ()).throw(RuntimeError("identity down")),
        )
    )
    conn = FakeOutboxConn()

    report = run_extractors(
        _normalized_dict(), extractor_ids=["identity_fails"], conn=conn
    )

    assert report.successes == ()
    assert [item.extractor_id for item in report.required_dead_lettered] == [
        "identity_fails"
    ]
    assert len(conn.rows_for(STAGE_DEAD_LETTERED_TOPIC)) == 1


def test_extraction_persistence_failure_becomes_required_dead_letter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.knowledge_acquisition.extraction_persistence as persistence

    register_extractor(_make_counting_spec("persist_fails", []))
    monkeypatch.setattr(
        persistence,
        "persist_extraction_result",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("store down")),
    )
    conn = FakeOutboxConn()

    report = run_extractors(
        _normalized_dict(),
        extractor_ids=["persist_fails"],
        raw_record_id="raw-1",
        normalized_artifact_id="normalized-1",
        conn=conn,
    )

    assert report.successes == ()
    assert [item.extractor_id for item in report.required_dead_lettered] == [
        "persist_fails"
    ]
    assert len(conn.rows_for(STAGE_DEAD_LETTERED_TOPIC)) == 1


def test_dead_letter_across_sibling_items_unaffected() -> None:
    """A failing stage for ONE raw item does not block a SIBLING raw item's pipeline.

    Two items, each with its own content_identity: item A's extractor fails and
    dead-letters; item B's extractor completes. B's success and its stage.completed event
    are present and correct."""
    conn = FakeOutboxConn()
    register_extractor(_failing_spec("always_fails"))

    raw_a = dict(RAW_RECORD_FIXTURE, content_identity="sha256:item-a")
    raw_b = dict(RAW_RECORD_FIXTURE, content_identity="sha256:item-b")
    norm_a = _normalized_dict(raw_a)
    norm_b = _normalized_dict(raw_b)

    report_a = run_extractors(norm_a, extractor_ids=["always_fails"], conn=conn)
    report_b = run_extractors(norm_b, extractor_ids=["summary"], conn=conn)

    # Item A dead-lettered; item B succeeded — sibling item unaffected.
    assert [o.status for o in report_a.outcomes] == ["dead_lettered"]
    assert [o.status for o in report_b.outcomes] == ["ok"]

    dl_rows = conn.rows_for(STAGE_DEAD_LETTERED_TOPIC)
    assert len(dl_rows) == 1
    assert Event.model_validate_json(dl_rows[0]["payload"]).payload["content_identity"] == "sha256:item-a"

    completed = conn.rows_for(STAGE_COMPLETED_TOPIC)
    assert len(completed) == 1
    assert Event.model_validate_json(completed[0]["payload"]).payload["content_identity"] == "sha256:item-b"


def test_dead_letter_duplicate_delivery_dedups() -> None:
    """A duplicate delivery of the same stage failure dedups to one audit row."""
    conn = FakeOutboxConn()
    register_extractor(_failing_spec("always_fails"))
    normalized = _normalized_dict()

    run_extractors(normalized, extractor_ids=["always_fails"], conn=conn)
    run_extractors(normalized, extractor_ids=["always_fails"], conn=conn)

    assert len(conn.rows_for(STAGE_DEAD_LETTERED_TOPIC)) == 1


def test_summary_v2_non_finite_confidence_dead_letter_has_v2_identity() -> None:
    """The v2 finite-confidence boundary owns a distinct durable failure lineage."""
    summary_extractor.register(
        complete=_stub_completion(
            json.dumps({"summary": "invalid confidence", "confidence": float("nan")})
        )
    )
    conn = FakeOutboxConn()
    normalized = _normalized_dict()

    report = run_extractors(normalized, extractor_ids=["summary"], conn=conn)

    assert report.successes == ()
    assert len(report.dead_lettered) == 1
    rows = conn.rows_for(STAGE_DEAD_LETTERED_TOPIC)
    assert len(rows) == 1
    envelope = Event.model_validate_json(rows[0]["payload"])
    assert envelope.payload["stage_version"] == EXTRACTOR_VERSION
    assert rows[0]["id"] == stage_dead_letter_key(
        stage="extracted",
        stage_version=EXTRACTOR_VERSION,
        content_identity=normalized["source_content_identity"],
        extractor_id="summary",
        failure_scope="required",
    )
