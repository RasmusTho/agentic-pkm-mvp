"""Closure-derived retrieval salience decay tests (ERE-06, #3181).

Spec: ``docs/EPISODE_RESOLUTION_ENGINE/EMIT_CLOSURE_AND_DERIVE_DECAY.md``;
``docs/adr/ADR-0058-event-horizon-closure-decay.md``.

- AC2 (enforcement): a closed-episode binding derives the salience drop on the PRODUCTION
  ``retrieve()`` call site. Verify: ``test_closed_episode_binding_derives_salience_drop_at_retrieval``
- AC4: closure never touches ``evidence_role``, ``authority_state``, or scope -- ranking only.
  Verify: ``test_closure_affects_ranking_only``
- AC6: re-opening restores full salience with no residue -- proving nothing was persisted.
  Verify: ``test_reopen_restores_salience_no_residue``

The DB-backed closed-episode-id reader (``app.episodes.closure_decay.read_closed_episode_ids``) is
monkeypatched at its own module boundary throughout -- no live Postgres needed, matching every
other ``not pg`` test in this engine.
"""

from __future__ import annotations

import pytest

from app.episodes import closure_decay
from app.episodes.closure_decay import CLOSURE_DECAY_STEP_DOWN_FACTOR
from app.retrieval.capability import RetrievalRequest, retrieve
from app.retrieval.hybrid import get_store, reset_durable_rebuild_state

pytestmark = pytest.mark.not_pg


def _patch_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.retrieval.hybrid.embed_text", lambda text, language=None: [0.2, 0.2, 0.2])
    monkeypatch.setattr(
        "app.retrieval.hybrid.embed_docs", lambda texts: ([[0.2, 0.2, 0.2] for _ in texts], {})
    )
    # This suite runs thousands of tests in one process; an earlier, unrelated test may have left
    # the retrieval store's durable-rebuild-cache flag set (app.retrieval.hybrid module state),
    # which would otherwise make retrieve() revalidate against a real durable index with a
    # different embedding dimension than this file's own 3-dim fake. Force a clean, in-memory-only
    # cache state for every test that seeds the store directly.
    reset_durable_rebuild_state()


def _clear_store() -> None:
    get_store().set_documents([])


# ---------------------------------------------------------------------------
# AC2 (enforcement): closed-episode binding derives the salience drop at retrieve()
# ---------------------------------------------------------------------------


def test_closed_episode_binding_derives_salience_drop_at_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_embeddings(monkeypatch)
    get_store().set_documents(
        [
            {
                "doc_id": "doc-closed",
                "text": "closure decay seam note",
                "source_ref": "vault/doc-closed.md",
                "payload": {"title": "Closed binding", "episode_ref": ["ep-closed-1"]},
            },
            {
                "doc_id": "doc-open",
                "text": "closure decay seam note",
                "source_ref": "vault/doc-open.md",
                "payload": {"title": "Open binding", "episode_ref": ["ep-open-1"]},
            },
        ]
    )
    monkeypatch.setattr(closure_decay, "read_closed_episode_ids", lambda ids: {"ep-closed-1"})

    try:
        response = retrieve(RetrievalRequest(query="closure decay seam", k=2))
    finally:
        _clear_store()

    by_id = {hit.doc_id: hit for hit in response.hits}
    closed_hit = by_id["doc-closed"]
    open_hit = by_id["doc-open"]

    assert closed_hit.signal_payload.salience == {
        "episode_closure": {
            "closed": True,
            "factor": CLOSURE_DECAY_STEP_DOWN_FACTOR,
            "closed_episode_refs": ["ep-closed-1"],
        }
    }
    # An open-episode artifact carries none (AC2, second clause).
    assert open_hit.signal_payload.salience == {}
    # Same raw text/embedding -> identical undamped scores; the closed hit's SERVED score must
    # reflect the step-down factor relative to the open hit's untouched score.
    assert closed_hit.score == pytest.approx(open_hit.score * CLOSURE_DECAY_STEP_DOWN_FACTOR)


def test_unbound_and_dangling_refs_carry_no_salience_drop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Structurally immune (unbound) and fail-open (dangling/unresolved id) cases carry none."""
    _patch_embeddings(monkeypatch)
    get_store().set_documents(
        [
            {
                "doc_id": "doc-unbound",
                "text": "closure decay seam note",
                "source_ref": "vault/doc-unbound.md",
                "payload": {"episode_ref": "unbound"},
            },
            {
                "doc_id": "doc-dangling",
                "text": "closure decay seam note",
                "source_ref": "vault/doc-dangling.md",
                "payload": {"episode_ref": ["ep-does-not-exist"]},
            },
        ]
    )
    monkeypatch.setattr(closure_decay, "read_closed_episode_ids", lambda ids: set())

    try:
        response = retrieve(RetrievalRequest(query="closure decay seam", k=2))
    finally:
        _clear_store()

    for hit in response.hits:
        assert hit.signal_payload.salience == {}


# ---------------------------------------------------------------------------
# AC4: ranking-only -- never evidence_role / authority_state / scope
# ---------------------------------------------------------------------------


def test_closure_affects_ranking_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_embeddings(monkeypatch)
    get_store().set_documents(
        [
            {
                "doc_id": "doc-closed",
                "text": "ranking only seam note",
                "source_ref": "vault/doc-closed.md",
                "payload": {
                    "episode_ref": ["ep-closed-2"],
                    "evidence_role": "evidence",
                    "authority_state": "accepted",
                    "domain": "work",
                },
            },
            {
                "doc_id": "doc-open",
                "text": "ranking only seam note",
                "source_ref": "vault/doc-open.md",
                "payload": {
                    "episode_ref": "unbound",
                    "evidence_role": "evidence",
                    "authority_state": "accepted",
                    "domain": "work",
                },
            },
        ]
    )
    monkeypatch.setattr(closure_decay, "read_closed_episode_ids", lambda ids: {"ep-closed-2"})

    try:
        response = retrieve(RetrievalRequest(query="ranking only seam", k=2))
    finally:
        _clear_store()

    # Identical raw text -> tied undamped scores; dampening must re-order the open one to the top.
    assert [hit.doc_id for hit in response.hits] == ["doc-open", "doc-closed"]

    for hit in response.hits:
        # Ranking-only guarantee: closure never touches admissibility-shaped fields.
        assert hit.payload["evidence_role"] == "evidence"
        assert hit.payload["authority_state"] == "accepted"
        assert hit.payload["domain"] == "work"


# ---------------------------------------------------------------------------
# AC6: re-open restores full salience with no residue (nothing persisted)
# ---------------------------------------------------------------------------


def test_reopen_restores_salience_no_residue(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_embeddings(monkeypatch)
    original_payload = {"episode_ref": ["ep-recut-1"]}
    get_store().set_documents(
        [
            {
                "doc_id": "doc-recut",
                "text": "reopen residue seam note",
                "source_ref": "vault/doc-recut.md",
                "payload": dict(original_payload),
            }
        ]
    )

    try:
        # Baseline: no closure signal at all.
        monkeypatch.setattr(closure_decay, "read_closed_episode_ids", lambda ids: set())
        baseline_score = retrieve(RetrievalRequest(query="reopen residue seam", k=1)).hits[0].score

        # Closed: the episode resolves as closed -> dampened.
        monkeypatch.setattr(closure_decay, "read_closed_episode_ids", lambda ids: {"ep-recut-1"})
        closed_hit = retrieve(RetrievalRequest(query="reopen residue seam", k=1)).hits[0]
        assert closed_hit.signal_payload.salience != {}
        assert closed_hit.score == pytest.approx(baseline_score * CLOSURE_DECAY_STEP_DOWN_FACTOR)

        # Re-open (human re-cut): the SAME episode id no longer resolves as closed. Nothing about
        # the prior call's derived salience persisted anywhere -- the very next retrieve() must
        # come back to full strength with no trace of the prior dampening.
        monkeypatch.setattr(closure_decay, "read_closed_episode_ids", lambda ids: set())
        reopened_hit = retrieve(RetrievalRequest(query="reopen residue seam", k=1)).hits[0]

        # The store's own persisted payload was never touched by any of the three calls above --
        # derived-only, proven by re-reading the durable store directly.
        stored_payload = get_store().all()[0].payload
    finally:
        _clear_store()

    assert reopened_hit.signal_payload.salience == {}
    assert reopened_hit.score == pytest.approx(baseline_score)
    assert stored_payload == original_payload
