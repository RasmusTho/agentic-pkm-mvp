"""The ingest path must stamp the embedding identity that will actually serve the
request, not a hardcoded phantom (#4178).

`app/ingest/api.py` used to emit the module constant `"openai/text-embedding-3-large"`
on every `index.embedding.requested` event. No adapter in `PROVIDER_REGISTRY` can serve
that name, so the value was a false provenance claim written into the `meta` of every
outbox row and audit record — exactly the signal mixed-identity detection and reconcile
(CTI-1 / EMBEDREL-06) read as true.

The value is never read back (`app/workers/outbox_worker.py` drops `meta` before the
indexer sees it), so these tests assert on what is *written*, which is where the defect
lives. `docs/EMBEDDINGS.md :: Embedding identity` requires the identity to be attached
to emitted indexing events.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

import app.components.embeddings as embeddings_pkg
import app.components.llm.fabric as fabric
import app.ingest.api as ingest_api
import app.outbox.events as outbox_events
from app.components.embeddings import get_embedding_identity
from app.components.llm.fabric import get_embeddings_client
from app.components.llm.router import LLMTaskIntent
from app.index.artifact_metadata import embedding_identity_provenance


pytestmark = pytest.mark.usefixtures("product_model_access_gateway")

def _capture_requested_events(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Capture envelopes at the outbox boundary.

    Asserting on the real envelope (rather than on the dict handed to
    `emit_index_embedding_requested`) keeps the `meta` routing in
    `app/outbox/events.py` inside the tested path.
    """

    captured: list[Any] = []

    def _write(envelope: Any, **_kwargs: Any) -> str:
        captured.append(envelope)
        return "1"

    monkeypatch.setattr(outbox_events, "write_outbox_event", _write)
    monkeypatch.setattr(outbox_events, "_append_record_best_effort", lambda *a, **k: None)
    return captured


def _requested_meta(captured: list[Any]) -> dict[str, Any]:
    requested = [
        env
        for env in captured
        if getattr(env, "event", None) == outbox_events.INDEX_EMBEDDING_REQUESTED
    ]
    assert requested, "expected an index.embedding.requested envelope"
    meta = dict(getattr(requested[-1], "meta", None) or {})
    return meta


def test_ingest_embedding_requested_carries_resolved_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The emitted event carries the identity the indexer would resolve.

    The consumer resolves identity via `get_embeddings_client` /
    `get_embedding_identity` (`app/indexer/consumer.py`). The request event must
    agree with that resolution rather than announcing a different model.
    """

    captured = _capture_requested_events(monkeypatch)

    ingest_api.ingest_object(
        object_id=None,
        kind="note",
        source_ref="unit-test",
        payload={"title": "Identity provenance"},
        text="Alpha beta gamma",
    )

    meta = _requested_meta(captured)
    identity = get_embedding_identity(
        client=get_embeddings_client(
            LLMTaskIntent(task_kind="embed", strict_identity_required=True)
        )
    )
    expected = embedding_identity_provenance(identity)

    assert meta.get("embedding_identity") == expected, (
        "index.embedding.requested must carry the resolved embedding identity; "
        f"got {meta.get('embedding_identity')!r}, expected {expected!r}"
    )
    # The persisted provenance shape is exactly provider/model/dim/normalize
    # (docs/EMBEDDINGS.md, docs/DB_SCHEMA.md :: store_vector_index). Identity
    # notes such as `no_prefix` must never widen it.
    assert set(expected) == {"provider", "model", "dim", "normalize"}


def test_ingest_resolves_through_the_router_not_the_bare_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pins *which* resolution path ingest uses.

    In the default environment the router path and a bare
    `resolve_embedding_identity()` return the same identity, so a test that
    re-derives the expected value cannot tell them apart — swapping the
    implementation would leave it green. They diverge once a task policy or
    profile is configured, and only the router path matches what the indexer
    consumer resolves.

    Feeding a sentinel through the router and asserting it reaches the event
    pins the decision without depending on settings fixtures.
    """

    captured = _capture_requested_events(monkeypatch)

    class _SentinelIdentity:
        provider = "ollama"
        model = "sentinel-router-model:latest"
        dim = 768
        normalize = True

    class _SentinelClient:
        identity = _SentinelIdentity()

    monkeypatch.setattr(fabric, "get_embeddings_client", lambda _intent: _SentinelClient())

    ingest_api.ingest_object(
        object_id=None,
        kind="note",
        source_ref="unit-test",
        payload={"title": "Router path"},
        text="Alpha beta gamma",
    )

    identity = _requested_meta(captured).get("embedding_identity")
    assert identity == {
        "provider": "ollama",
        "model": "sentinel-router-model:latest",
        "dim": 768,
        "normalize": True,
    }, (
        "ingest must stamp the identity resolved through get_embeddings_client "
        f"(the indexer's path); got {identity!r}"
    )


def test_ingest_embedding_requested_never_names_an_unservable_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whatever identity is stamped must be servable by a registered adapter."""

    from app.llm.embeddings import PROVIDER_REGISTRY

    captured = _capture_requested_events(monkeypatch)

    ingest_api.ingest_object(
        object_id=None,
        kind="note",
        source_ref="unit-test",
        payload={"title": "Servable provider"},
        text="Alpha beta gamma",
    )

    identity = _requested_meta(captured).get("embedding_identity")
    assert isinstance(identity, dict), "embedding_identity must be a provenance dict"
    provider = identity.get("provider")
    # `deterministic` is served by _DeterministicEmbeddingClient before dispatch
    # ever reaches PROVIDER_REGISTRY (app/components/embeddings/legacy.py).
    assert provider in set(PROVIDER_REGISTRY) | {"deterministic"}, (
        f"ingest stamped provider {provider!r}, which no adapter can serve"
    )


def test_ingest_embedding_requested_fails_loud_when_identity_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Identity resolution failure propagates; no event is emitted with a substitute.

    Swallowing the failure and stamping a default literal is the defect being
    fixed here — a silent fallback reintroduces it under a different name.
    """

    captured = _capture_requested_events(monkeypatch)

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("embedding identity unavailable")

    # Patched at the source module, not on ingest_api: the resolver imports these
    # function-locally (so `import app.ingest` stays cheap), so there is no
    # module attribute to shadow — this also keeps the real import path under test.
    monkeypatch.setattr(fabric, "get_embeddings_client", _boom)

    with pytest.raises(RuntimeError, match="embedding identity unavailable"):
        ingest_api.ingest_object(
            object_id=None,
            kind="note",
            source_ref="unit-test",
            payload={"title": "Fail loud"},
            text="Alpha beta gamma",
        )

    requested = [
        env
        for env in captured
        if getattr(env, "event", None) == outbox_events.INDEX_EMBEDDING_REQUESTED
    ]
    assert not requested, (
        "no index.embedding.requested event may be emitted when identity "
        "resolution failed"
    )


def test_ingest_embedding_requested_fails_loud_on_incomplete_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resolver that returns an identity without provider/model fails loud.

    `resolve_embedding_identity` normalizes rather than raises, so "no identity
    could be resolved" surfaces as a blank field, not an exception. Emitting a
    half-empty provenance claim is the same defect in a quieter form.
    """

    captured = _capture_requested_events(monkeypatch)

    class _BlankIdentity:
        provider = ""
        model = ""
        dim = 768
        normalize = True

    monkeypatch.setattr(
        embeddings_pkg, "get_embedding_identity", lambda **_kwargs: _BlankIdentity()
    )

    with pytest.raises(RuntimeError, match="embedding identity"):
        ingest_api.ingest_object(
            object_id=None,
            kind="note",
            source_ref="unit-test",
            payload={"title": "Blank identity"},
            text="Alpha beta gamma",
        )

    requested = [
        env
        for env in captured
        if getattr(env, "event", None) == outbox_events.INDEX_EMBEDDING_REQUESTED
    ]
    assert not requested


def test_ingest_api_carries_no_hardcoded_embedding_model() -> None:
    """No phantom model literal and no dead `app.config.agent` import guard.

    The original constant sat behind `try: from app.config.agent import settings`,
    which reads like a live config override but is not: `app.config.agent` exports
    no `settings` symbol, so the `except` branch always ran and the literal was
    unconditional.
    """

    source = Path(ingest_api.__file__).read_text(encoding="utf-8")

    assert "text-embedding-3-large" not in source, (
        "app/ingest/api.py must not hardcode an embedding model literal"
    )
    assert not hasattr(ingest_api, "_EMBED_MODEL"), (
        "the _EMBED_MODEL phantom constant must be gone, not renamed"
    )
    assert "app.config.agent" not in source, (
        "the dead app.config.agent settings guard must be removed"
    )


def test_indexer_rejects_unservable_selected_embedding_route_after_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An invalid selected route is loud before inference/index effects on replay."""
    from app.components.embeddings import legacy
    from app.services import indexer

    stored: dict[str, Any] = {}
    saves: list[dict[str, Any]] = []

    class _ObjectStore:
        def get_object(self, object_id):
            return stored.get(str(object_id))

        def save_object(self, domain, **kwargs):
            stored[str(domain.uuid)] = domain
            saves.append(kwargs)

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("invalid admission must precede client or index access")

    monkeypatch.setattr(legacy, "get_settings_bundle", lambda: None)
    monkeypatch.setattr(indexer, "ObjectStore", _ObjectStore)
    monkeypatch.setattr(indexer, "resolve_canonical_object_id", lambda value: value)
    monkeypatch.setattr(indexer, "embed_with_fallback", _unexpected)
    monkeypatch.setattr(indexer, "get_vector_index", _unexpected)
    monkeypatch.setattr(indexer, "emit_index_embedding_failed", _unexpected)
    monkeypatch.setenv("LLM_FORCE_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FORCE_MODEL", "nomic-embed-text:latest")
    monkeypatch.setenv("EMBED_PRIMARY_PROVIDER", "mock")
    event = {
        "object_id": str(UUID(int=5882)),
        "content": "must not become a mock vector",
        "source_ref": "unit-test-admission",
        "trace_id": "trace-admission",
        "payload": {},
    }

    for _ in range(2):
        with pytest.raises(ValueError, match=r"openai.*override_provider"):
            indexer.handle_ingest_object_created(event)

    assert stored[event["object_id"]].payload["content"] == event["content"]
    assert len(stored) == 1
    assert saves == [{"emit_outbox": False, "trace_id": "trace-admission"}] * 2


def test_indexer_valid_synthetic_ingest_preserves_selected_identity_and_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stronger explicit route retains precedence over an inactive legacy value."""
    from app.components.embeddings import legacy
    from app.objects import ObjectStore
    from app.services import indexer

    monkeypatch.setattr(legacy, "get_settings_bundle", lambda: None)
    monkeypatch.setenv("EMBED_PRIMARY_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FORCE_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "4")
    monkeypatch.delenv("EMBED_FALLBACK_PROVIDER", raising=False)
    monkeypatch.setattr(indexer, "resolve_canonical_object_id", lambda value: value)

    class _Index:
        def __init__(self):
            self.rows: dict[UUID, dict[str, Any]] = {}
            self.purges: list[UUID] = []

        def purge_vectors(self, object_id, *, view):
            self.purges.append(object_id)
            return int(self.rows.pop(object_id, None) is not None)

        def upsert(self, object_id, **kwargs):
            self.rows[object_id] = kwargs

    vector_index = _Index()
    created: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    monkeypatch.setattr(indexer, "get_vector_index", lambda: vector_index)
    monkeypatch.setattr(indexer, "emit_index_object_embedded", lambda **kwargs: created.append(kwargs))
    monkeypatch.setattr(indexer, "emit_index_embedding_failed", lambda **kwargs: failed.append(kwargs))
    object_id = str(UUID(int=58820))
    event = {
        "object_id": object_id,
        "kind": "note",
        "content": "valid synthetic body",
        "source_ref": "unit-test-valid-admission",
        "trace_id": "trace-valid-admission",
        "payload": {},
    }

    for _ in range(2):
        indexer.handle_ingest_object_created(event)

    stored = ObjectStore().get_object(object_id)
    assert stored is not None
    assert stored.payload["content"] == event["content"]
    assert "embedding_identity" not in stored.payload
    assert len(vector_index.rows) == 1
    row = vector_index.rows[UUID(object_id)]
    expected = {"provider": "mock", "model": "mock-embedding", "dim": 4, "normalize": True}
    assert embedding_identity_provenance(row["identity"]) == expected
    assert row["payload"]["provenance"]["embedding_identity"] == expected
    assert len(row["embedding"]) == 4
    assert vector_index.purges == []
    assert failed == []
    assert created == [{
        "object_id": object_id,
        "trace_id": event["trace_id"],
        "source_ref": event["source_ref"],
        "provider": "mock",
        "model": "mock-embedding",
        "dim": 4,
        "meta": None,
    }] * 2
