"""A skipped self-owned outbox write may not read as a committed event (#4214).

The Heimdal meeting emitters set ``emitted = True`` on a *normal return* from
``write_outbox_event`` rather than on the returned row id, and deliberately so:
their idempotency keys are derived from stable identity, so a deduplicated
``""`` is proof the event was already committed by a prior attempt. Treating
``""`` as failure would refuse such a capture forever.

That reading is only sound while a normal return cannot mean "skipped". The
memory-mode skip branch broke it: with ``STORE_BACKEND=memory`` and a DSN in the
environment the policy returns ``skip``, the write returns ``""`` without
opening a connection, and the emitter reported success for an event no sink
took — including flipping ``POST`` user-note responses from 500 to 200.

Each emitter now guards its DB branch with
``outbox_service.self_owned_write_would_skip()`` — the policy itself, not a
re-derived ``STORE_BACKEND``/DSN predicate.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services import outbox as outbox_service

pytestmark = pytest.mark.not_pg


@pytest.fixture()
def skipping_runtime_with_a_named_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit memory backend + a named database: the policy skips."""
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured.example/app")

    def _must_not_connect(*args: object, **kwargs: object) -> Any:
        raise AssertionError("a skipped self-owned write must not open a connection")

    monkeypatch.setattr(outbox_service, "conn_rw", _must_not_connect)
    assert outbox_service.self_owned_write_would_skip() is True


def _fail_jsonl(monkeypatch: pytest.MonkeyPatch, module: Any) -> None:
    """Fault the compensating sink so only the DB branch could report success."""

    def _unavailable(*args: object, **kwargs: object) -> Any:
        raise OSError("jsonl sink unavailable")

    monkeypatch.setattr(module.outbox_service, "append_jsonl_outbox_event", _unavailable)


def test_media_admission_does_not_report_emitted_when_no_sink_took_it(
    monkeypatch: pytest.MonkeyPatch,
    skipping_runtime_with_a_named_database: None,
) -> None:
    from app.heimdal import media_ingress

    _fail_jsonl(monkeypatch, media_ingress)

    emitted = media_ingress._emit_admission_event(
        {"receipt_id": "r-4214", "content_sha256": "s" * 64},
        trace_id="t-4214",
        receipt_id="r-4214",
        content_sha256="s" * 64,
    )

    assert emitted is False, "reported a committed admission event that no sink took"


def test_meeting_finalization_does_not_report_emitted_when_no_sink_took_it(
    monkeypatch: pytest.MonkeyPatch,
    skipping_runtime_with_a_named_database: None,
) -> None:
    from app.heimdal import meeting_finalization

    _fail_jsonl(monkeypatch, meeting_finalization)

    emitted = meeting_finalization._emit_finalized_event(
        {"session_id": "s-4214", "finalization_state": "finalized"},
        trace_id="t-4214",
    )

    assert emitted is False, "reported a finalized acknowledgement that no sink took"


def test_user_note_event_does_not_report_emitted_when_no_sink_took_it(
    monkeypatch: pytest.MonkeyPatch,
    skipping_runtime_with_a_named_database: None,
) -> None:
    from app.api.routes import heimdal_meeting

    _fail_jsonl(monkeypatch, heimdal_meeting)

    emitted = heimdal_meeting._emit_user_note_event(
        {
            "note_block_id": "nb-4214",
            "revision": 1,
            "content_sha256": "s" * 64,
        },
        trace_id="t-4214",
    )

    assert emitted is False, (
        "reported a persisted user note that no sink took; the route turns this into a 200"
    )
