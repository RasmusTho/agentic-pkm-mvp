"""The ASK/chat consumption seam receives a bounded ContextEnvelope, not raw dicts (KERNEL-10, #2772).

Binds AC4: the production seam consumed by ``app.api.routes.ask`` /
``app.activation.ask_synthesis.build_retrieval_candidates`` receives a schema-valid ContextEnvelope
that carries no raw-vault/raw-index/storage field.

Reference for the invariant SHAPE: ``yggdrasil_runtime/context.py::assemble_envelope`` (consumed,
not imported).
"""

from __future__ import annotations

from app.activation.ask_synthesis import build_retrieval_candidates_from_envelope
from app.agents.ask import graph as ask_graph
from app.agents.ask.graph import build_ask_envelope, run_ask_graph
from app.agents.ask.state import AgentState, RetrievedHit
from app.retrieval.envelope import (
    assemble_and_validate_ask_envelope,
    validate_envelope,
)
from app.retrieval.hybrid import ScopedRetrieval

# Any raw-access / storage-topology shaped field must never appear anywhere in the envelope payload.
_RAW_ACCESS_KEYS = {"vault_id", "vault_root", "raw_index", "index", "vault", "store", "db"}


def _no_recall(*_args, **_kwargs):
    return []


def _walk_assert_no_raw_access(node) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            assert k not in _RAW_ACCESS_KEYS, f"raw-access field leaked into envelope: {k}"
            _walk_assert_no_raw_access(v)
    elif isinstance(node, list):
        for v in node:
            _walk_assert_no_raw_access(v)


def test_ask_consumes_envelope(tmp_path, monkeypatch) -> None:
    """The ASK graph assembles + validates a ContextEnvelope at the synthesis seam, and the gate's
    admitted set is derived from the envelope's embedded metadata bundles — not raw ranked dicts."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv(
        "ASK_SYNTHESIS_RECEIPTS_PATH",
        str(tmp_path / "runtime" / "activation" / "ask_synthesis_receipts.jsonl"),
    )

    from app.retrieval.capability import RetrievalHit, RetrievalResponse

    def _fake_retrieve(request):
        return RetrievalResponse(
            query=request.query,
            trace_id="trace-envelope",
            hits=[
                RetrievalHit(
                    object_id="env-src-1",
                    doc_id="env-src-1",
                    text="stateful workflow engine body",
                    score=0.9,
                    snippet="stateful workflow engine body",
                    source_ref="vault/source.md",
                    # vault_id in the payload must NOT survive into the bounded envelope.
                    payload={"title": "Src", "origin": "vault", "vault_id": "vault:secret-topology"},
                )
            ],
        )

    def _fake_llm_answer(question, context, ask_settings):
        return "Synthesized over the envelope.", {"provider": "mock"}

    captured: dict[str, dict] = {}
    original_assemble = ask_graph.assemble_and_validate_ask_envelope

    def _spy_assemble(scoped, **kwargs):
        env = original_assemble(scoped, **kwargs)
        captured["envelope"] = env
        return env

    monkeypatch.setattr(ask_graph, "retrieve", _fake_retrieve)
    monkeypatch.setattr(ask_graph, "retrieve_relevant_promoted", _no_recall)
    monkeypatch.setattr(ask_graph, "llm_answer", _fake_llm_answer)
    monkeypatch.setattr(ask_graph, "assemble_and_validate_ask_envelope", _spy_assemble)

    state = run_ask_graph("what does the source say?", trace_id="trace-envelope")

    # A schema-valid envelope was assembled at the seam.
    assert "envelope" in captured, "the ASK seam must assemble a ContextEnvelope"
    envelope = captured["envelope"]
    assert envelope["access_mode"] == "bounded_context_only"
    validate_envelope(envelope)  # re-validate: fail loud if the seam ever emits a non-conforming one

    # No raw vault/index/storage field anywhere — including the vault_id planted in the payload.
    _walk_assert_no_raw_access(envelope)

    # The gate's admitted set was derived from the envelope's embedded bundle identity.
    assert state.synthesis_source_ids == ["env-src-1"]
    assert state.answer == "Synthesized over the envelope."

    # build_retrieval_candidates consumes the envelope (embedded object_id), not raw dicts.
    candidates = build_retrieval_candidates_from_envelope(envelope)
    assert [c.artifact_id for c in candidates] == ["env-src-1"]


def test_build_ask_envelope_is_schema_valid_and_bounded() -> None:
    """``build_ask_envelope`` over live-shaped hits produces a bounded, schema-valid envelope."""
    state = AgentState(
        trace_id="t",
        query="state machine",
        hits=[
            RetrievedHit(
                object_id="doc-1",
                score=0.8,
                snippet="a snippet",
                text="a longer body",
                path="vault/a.md",
                payload={"title": "A", "vault_id": "vault:topology"},
                evidence_role_in_context="background",
            )
        ],
    )
    envelope = build_ask_envelope(state)
    validate_envelope(envelope)
    assert envelope["access_mode"] == "bounded_context_only"
    _walk_assert_no_raw_access(envelope)
    # Bundle-is-not-envelope: composed bundles are references, never inlined bundles.
    for b in envelope["context_bundles"]:
        assert b["non_authority"] is True
        assert "metadata_bundle" not in b


def test_envelope_denials_surface_as_escalation_conditions() -> None:
    """Content-free denials carried on the scoped result surface as escalation conditions, so useful
    denied material is not silently dropped."""
    from app.retrieval.hybrid import ScopeDenial

    scoped = ScopedRetrieval(
        results=[
            {
                "id": "doc-1",
                "doc_id": "doc-1",
                "text": "body",
                "score": 0.5,
                "snippet": "body",
                "source_ref": "vault/a.md",
                "payload": {"domain": "work"},
                "evidence_role_in_context": "background",
            }
        ],
        denials=(
            ScopeDenial(
                reason="relevant material outside the active scope was excluded",
                denial_class="cross_scope_no_flow",
            ),
        ),
        active_scope="work",
    )
    envelope = assemble_and_validate_ask_envelope(
        scoped,
        active_workspace_id="workspace:ask",
        active_scope_id="scope:work",
        principal_id="principal:ask",
        user_intent="orient",
    )
    assert envelope["denied_scopes"], "denials must be carried on the envelope"
    assert envelope["escalation_conditions"], "denied material must surface as an escalation condition"
    for cond in envelope["escalation_conditions"]:
        assert cond["denial_class"] == "cross_scope_no_flow"


def test_ask_seam_envelope_carries_real_denials_end_to_end(tmp_path, monkeypatch) -> None:
    """PRODUCTION-SEAM denial threading (review F1): with an active scope and relevant out-of-scope
    material in the real store, the envelope assembled by the ASK graph carries non-empty,
    content-free ``denied_scopes`` and a matching escalation condition — denials survive the
    retrieve -> rerank -> answer path (they are scope-level, not per-hit)."""
    from app.retrieval.hybrid import get_store

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("ASK_DOMAIN_SCOPE", "work")
    monkeypatch.setenv(
        "ASK_SYNTHESIS_RECEIPTS_PATH",
        str(tmp_path / "runtime" / "activation" / "ask_synthesis_receipts.jsonl"),
    )

    store = get_store()
    store.set_documents([])
    store.add_document(
        doc_id="work-in-scope",
        text="stateful workflow engine reconciliation notes",
        source_ref="work/notes.md",
        payload={"domain": "work"},
    )
    store.add_document(
        doc_id="rpg-out-of-scope",
        # Shares query vocabulary so it is RELEVANT — and must become a denial, not vanish.
        text="stateful workflow engine ritual of the aether",
        source_ref="rpg/ritual.md",
        payload={"domain": "rpg"},
    )

    def _fake_llm_answer(question, context, ask_settings):
        return "Synthesized in scope.", {"provider": "mock"}

    captured: dict[str, dict] = {}
    original_assemble = ask_graph.assemble_and_validate_ask_envelope

    def _spy_assemble(scoped, **kwargs):
        env = original_assemble(scoped, **kwargs)
        captured["envelope"] = env
        return env

    monkeypatch.setattr(ask_graph, "retrieve_relevant_promoted", _no_recall)
    monkeypatch.setattr(ask_graph, "llm_answer", _fake_llm_answer)
    monkeypatch.setattr(ask_graph, "assemble_and_validate_ask_envelope", _spy_assemble)

    try:
        state = run_ask_graph("stateful workflow engine", trace_id="trace-denials")
    finally:
        store.set_documents([])

    # Retrieval surfaced only the in-scope doc; the graph ran to an answer.
    assert [h.object_id for h in state.hits] == ["work-in-scope"]
    assert "envelope" in captured, "the ASK seam must assemble a ContextEnvelope"
    envelope = captured["envelope"]
    validate_envelope(envelope)

    # The real prefilter denial reached the envelope: non-empty and class-matched.
    assert envelope["denied_scopes"], (
        "relevant out-of-scope material must surface as a denial on the production envelope"
    )
    assert any(d["denial_class"] == "cross_scope_no_flow" for d in envelope["denied_scopes"])
    # ...with a matching escalation condition (useful denied material is surfaced, not hidden).
    assert any(
        c.get("denial_class") == "cross_scope_no_flow" for c in envelope["escalation_conditions"]
    ), "a denial must surface as an escalation condition"

    # Content-free: the denial and escalation records leak no identity/content of the denied doc.
    import json as _json

    denial_blob = _json.dumps(
        {"denied": envelope["denied_scopes"], "escalations": envelope["escalation_conditions"]}
    ).lower()
    for leaked in ("rpg", "ritual", "aether", "rpg-out-of-scope", "rpg/ritual.md"):
        assert leaked not in denial_blob, f"denial leaked identifying content: {leaked!r}"

    # And the state carries them scope-level, unaffected by hit truncation in the rerank node.
    assert state.denials and state.denials[0]["denial_class"] == "cross_scope_no_flow"


def test_envelope_honors_proposed_role_downgrade() -> None:
    """Review F2: a legitimate proposed DOWNGRADE of the in-context role is honored (not silently
    reset to intrinsic); a proposed upgrade is still clamped to intrinsic."""
    scoped = ScopedRetrieval(
        results=[
            {
                "id": "doc-down",
                "doc_id": "doc-down",
                "text": "body",
                "score": 0.5,
                "snippet": "body",
                "source_ref": "vault/a.md",
                # Intrinsic evidence, proposed downgrade to background -> honored.
                "payload": {"domain": "work", "evidence_role": "evidence"},
                "evidence_role_in_context": "background",
            },
            {
                "id": "doc-up",
                "doc_id": "doc-up",
                "text": "body",
                "score": 0.4,
                "snippet": "body",
                "source_ref": "vault/b.md",
                # Intrinsic background, proposed upgrade to evidence -> clamped to background.
                "payload": {"domain": "work", "evidence_role": "background"},
                "evidence_role_in_context": "evidence",
            },
        ],
        denials=(),
        active_scope="work",
    )
    envelope = assemble_and_validate_ask_envelope(
        scoped,
        active_workspace_id="workspace:ask",
        active_scope_id="scope:work",
        principal_id="principal:ask",
        user_intent="orient",
    )
    roles = {
        item["metadata_bundle"]["object_id"]: item["evidence_role_in_context"]
        for item in envelope["retrieved_items"]
    }
    assert roles["doc-down"] == "background", "a proposed downgrade must be honored"
    assert roles["doc-up"] == "background", "a proposed upgrade must be clamped to intrinsic"
