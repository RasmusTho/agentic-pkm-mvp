from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.indexer import consumer
from app.outbox.events import INDEX_EMBEDDING_REQUESTED
from app.workers import outbox_worker


def _missing_object_event(*, object_id: str, trace_id: str = "trace-missing") -> dict:
    return {
        "event": INDEX_EMBEDDING_REQUESTED,
        "payload": {"object_id": object_id},
        "trace_id": trace_id,
    }


def test_missing_object_embedding_request_is_dropped_without_worker_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    acked: list[str] = []
    dropped: list[dict] = []

    monkeypatch.setattr(consumer.ObjectStore, "get_object", lambda self, _object_id, strict_backend=False: None)
    monkeypatch.setattr(
        consumer.outbox_events,
        "emit_index_embedding_failed",
        lambda **kwargs: dropped.append(kwargs),
    )
    monkeypatch.setattr(outbox_worker, "bootstrap", lambda: None)
    monkeypatch.setattr(outbox_worker, "write_worker_heartbeat", lambda **_: None)
    monkeypatch.setattr(outbox_worker, "ack_outbox", lambda msg_id: acked.append(str(msg_id)) or True)
    # run() idles when no vault is selected (#2407); pin one so the embedding
    # request is actually dispatched through the worker loop.
    monkeypatch.setattr(
        outbox_worker, "_resolve_optional_vault_root", lambda *_a, **_k: Path("/tmp/vault")
    )

    messages = [
        {
            "id": "embed-missing-1",
            "topic": INDEX_EMBEDDING_REQUESTED,
            "payload": {"object_id": str(uuid4()), "trace_id": "trace-missing-1"},
        }
    ]

    def fake_poll():
        if messages:
            return messages.pop(0)
        return None

    monkeypatch.setattr(outbox_worker, "poll_outbox_one", fake_poll)
    monkeypatch.setenv("WORKER_HEARTBEAT_INTERVAL", "9999")

    outbox_worker.run(interval=0.0, heartbeat_interval=9999, log_heartbeat_interval=None, stop_after_ticks=2)

    assert acked == ["embed-missing-1"]
    assert dropped


def test_missing_object_embedding_request_records_drop_receipt(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    dropped: list[dict] = []
    object_id = str(uuid4())
    trace_id = "trace-missing-record"

    monkeypatch.setattr(consumer.ObjectStore, "get_object", lambda self, _object_id, strict_backend=False: None)
    monkeypatch.setattr(
        consumer.outbox_events,
        "emit_index_embedding_failed",
        lambda **kwargs: dropped.append(kwargs),
    )

    caplog.set_level(logging.WARNING, logger="app.indexer.consumer")

    consumer.process_event(_missing_object_event(object_id=object_id, trace_id=trace_id))

    assert dropped == [
        {
            "object_id": object_id,
            "trace_id": trace_id,
            "error": f"missing object for embedding request: {object_id}",
        }
    ]
    assert any("missing object" in record.getMessage() for record in caplog.records)


def test_transient_embedding_failure_still_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    object_id = str(uuid4())
    trace_id = "trace-transient"
    target = SimpleNamespace(
        uuid=object_id,
        kind="note",
        payload={"content": "hello world"},
        source_ref="Inbox/hello.md",
    )

    class FakeEmbedder:
        def embed_text(self, _text: str) -> list[float]:
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(consumer.ObjectStore, "get_object", lambda self, _object_id, strict_backend=False: target)
    monkeypatch.setattr(consumer, "get_embeddings_client", lambda _intent: FakeEmbedder())

    with pytest.raises(RuntimeError, match="provider unavailable"):
        consumer.process_event(_missing_object_event(object_id=object_id, trace_id=trace_id))


def test_transient_embedding_exhaustion_dead_letters_for_worker_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exhausted embedding request emits a failed event and returns cleanly.

    Fallback orchestration owns provider recovery. When no viable fallback is
    configured, the consumer dead-letters the request so the outbox worker can
    acknowledge it instead of retrying the same exhausted provider forever.
    """
    object_id = str(uuid4())
    target = SimpleNamespace(
        uuid=object_id,
        kind="note",
        payload={"content": "hello world"},
        source_ref="Inbox/hello.md",
    )

    calls: list[int] = []

    class FlakyEmbedder:
        def embed_text(self, _text: str) -> list[float]:
            calls.append(1)
            raise ConnectionError("ollama briefly unreachable")

    failures: list[dict] = []
    monkeypatch.setattr(consumer.ObjectStore, "get_object", lambda self, _object_id, strict_backend=False: target)
    monkeypatch.setattr(consumer, "get_embeddings_client", lambda _intent: FlakyEmbedder())
    monkeypatch.setattr(consumer.outbox_events, "emit_index_embedding_failed", lambda **kwargs: failures.append(kwargs))
    monkeypatch.delenv("EMBED_FALLBACK_PROVIDER", raising=False)
    monkeypatch.setenv("EMBED_DIM", "8")
    monkeypatch.setenv("EMBED_RETRY_MAX", "2")
    monkeypatch.setenv("EMBED_RETRY_BASE_BACKOFF_S", "0")

    consumer.process_event(_missing_object_event(object_id=object_id))

    assert len(calls) == 2  # retried EMBED_RETRY_MAX times before dead-lettering
    assert failures == [
        {
            "object_id": UUID(object_id),
            "trace_id": "trace-missing",
            "source_ref": "Inbox/hello.md",
            "provider": "mock",
            "model": "mock-embedding",
            "expected_dim": 8,
            "error": "embed exhausted after 2 attempts (transient): ollama briefly unreachable; "
            "fallback gate=NO_FALLBACK_CONFIGURED",
        }
    ]


def test_transient_object_store_failure_bubbles_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    object_id = str(uuid4())

    def fail_lookup(self, _object_id, strict_backend=False):
        raise ConnectionError("db unavailable")

    dropped: list[dict] = []
    monkeypatch.setattr(consumer.ObjectStore, "get_object", fail_lookup)
    monkeypatch.setattr(
        consumer.outbox_events,
        "emit_index_embedding_failed",
        lambda **kwargs: dropped.append(kwargs),
    )

    with pytest.raises(RuntimeError, match="transient object-store lookup failure"):
        consumer.process_event(_missing_object_event(object_id=object_id))

    assert dropped == []
