from __future__ import annotations

from app.episodes import closure_decay
from app.episodes.closure_decay import CLOSURE_DECAY_STEP_DOWN_FACTOR
from app.retrieval.capability import RetrievalRequest, RetrievalSignalPayload, retrieve
from app.retrieval.hybrid import get_store, reset_durable_rebuild_state


def _patch_embeddings(monkeypatch) -> None:
    monkeypatch.setattr("app.retrieval.hybrid.embed_text", lambda text, language=None: [0.2, 0.2, 0.2])
    monkeypatch.setattr("app.retrieval.hybrid.embed_docs", lambda texts: ([[0.2, 0.2, 0.2] for _ in texts], {}))
    # ERE-06 (#3181): this suite runs thousands of tests in one process; an earlier, unrelated
    # test may have left the retrieval store's durable-rebuild-cache flag set (app.retrieval.hybrid
    # module state), which would otherwise make retrieve() revalidate against a real durable index
    # with a different embedding dimension than this file's own 3-dim fake. Force a clean,
    # in-memory-only cache state for every test that seeds the store directly.
    reset_durable_rebuild_state()


def _seed_store() -> None:
    get_store().set_documents(
        [
            {
                "doc_id": "signal-a",
                "text": "signal seam note",
                "source_ref": "vault/signal-a.md",
                "payload": {
                    "title": "Signal A",
                    "origin": "vault",
                    "salience": "persisted-hot",
                    "staleness": "persisted-stale",
                    # NON-exempt state axes (provisional / draft) so the closure-decay path below
                    # actually dampens this doc -- an evergreen/reviewed/protected note is exempt
                    # from closure decay (ADR-0058 §2, app.episodes.closure_decay.is_exempt_note_class)
                    # and would carry NO drop, which the exempt-class test covers separately.
                    "review_state": "provisional",
                    "maturity": "draft",
                    # ERE-06 (#3181): a real episode binding, so the closure-decay derivation path
                    # actually has something to compute against below.
                    "episode_ref": ["ep-signal-closed-1"],
                },
            }
        ]
    )


def test_salience_signals_are_derived_not_persisted(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    _seed_store()
    # ERE-06 (#3181) extension: the seeded doc's episode binding resolves as closed.
    monkeypatch.setattr(closure_decay, "read_closed_episode_ids", lambda ids: {"ep-signal-closed-1"})
    try:
        response = retrieve(
            RetrievalRequest(
                query="signal seam",
                k=1,
                include_signal_payload=True,
                signal_payload=RetrievalSignalPayload(
                    salience={"tier": "active", "reason": "runtime-derivation"},
                    staleness={"state": "fresh", "reason": "status-heartbeat"},
                    source="runtime",
                ),
            )
        )

        assert response.diagnostics["signal_payload"] == {
            "salience": {"tier": "active", "reason": "runtime-derivation"},
            "staleness": {"state": "fresh", "reason": "status-heartbeat"},
            "source": "runtime",
        }
        assert response.hits[0].payload["salience"] == "persisted-hot"
        assert response.hits[0].payload["staleness"] == "persisted-stale"

        # ERE-06 (#3181) enforcement: the closure-derived drop shows up on the PER-HIT
        # `signal_payload.salience` field (the new, dedicated carrier) computed fresh by
        # `retrieve()` itself -- it is NOT the same channel as the caller-supplied
        # `diagnostics["signal_payload"]` above, and it never overwrote the persisted string
        # labels asserted just above either.
        hit = response.hits[0]
        assert hit.signal_payload.salience == {
            "episode_closure": {
                "closed": True,
                "factor": CLOSURE_DECAY_STEP_DOWN_FACTOR,
                "closed_episode_refs": ["ep-signal-closed-1"],
            }
        }

        # AC3 -- no persisted artifact field, bundle field, or index column changes on closure:
        # the durable store's own payload dict is untouched by the derivation above. Neither the
        # hit's own `.payload` (a copy taken at retrieve() time) nor the store's live row grew a
        # "decay"/"salience_drop"/etc. key, and `episode_ref` itself is unchanged.
        assert set(hit.payload) == {
            "title",
            "origin",
            "salience",
            "staleness",
            "review_state",
            "maturity",
            "episode_ref",
        }
        assert hit.payload["episode_ref"] == ["ep-signal-closed-1"]
        stored_payload = get_store().all()[0].payload
        assert stored_payload["episode_ref"] == ["ep-signal-closed-1"]
        assert "decay" not in stored_payload and "episode_closure" not in stored_payload
    finally:
        get_store().set_documents([])


def test_staleness_not_sourced_from_state_axes_labels(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    _seed_store()
    # ERE-06 (#3181): the shared fixture now carries a real episode_ref (see
    # test_salience_signals_are_derived_not_persisted above) -- stub the closure-decay DB reader
    # so this unrelated test never needs a live Postgres either. No closed episodes here.
    monkeypatch.setattr(closure_decay, "read_closed_episode_ids", lambda ids: set())
    try:
        response = retrieve(RetrievalRequest(query="signal seam", k=1))

        assert "signal_payload" not in response.diagnostics
        assert response.hits[0].payload["review_state"] == "provisional"
        assert response.hits[0].payload["maturity"] == "draft"
    finally:
        get_store().set_documents([])
