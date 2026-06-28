"""Runtime conformance tests for ContextEnvelope assembly (#2584 / YRS1-06).

Complement the static skeletons (no-raw-access, bundle-is-not-envelope) by exercising a
runtime-assembled envelope built from a real RetrievalResult over the corpus.

Invariant registry: docs/testing/invariant-tests.md :: context_envelope_has_no_raw_vault_or_index_access,
context_bundle_is_not_context_envelope, denied_scope_does_not_leak_identity
Spec: docs/YGGDRASIL_RUNTIME_SLICE_1/CONTEXT_ENVELOPE_ASSEMBLY.md
"""

from __future__ import annotations

import pytest

from tests.invariants._helpers import assert_validates

from yggdrasil_runtime import capture, context, retrieval

_ALPHA = "scope:work/project-alpha"
# Any raw-access shaped field must never appear anywhere in the envelope payload.
_RAW_ACCESS_KEYS = {"vault_id", "vault_root", "raw_index", "index", "vault", "store", "db"}
_DENIAL_LEAK_KEYS = {"object_id", "scope_id", "metadata_bundle", "content", "text", "provenance_event_ids"}


def _envelope(query: str = "state machine event bus"):
    result = retrieval.retrieve(query=query, active_scope_id=_ALPHA)
    return context.assemble_envelope(
        result, active_workspace_id="ws-1", active_scope_id=_ALPHA,
        principal_id="p-1", user_intent="orient on the state machine",
    )


def test_assembled_envelope_validates_and_is_bounded() -> None:
    env = _envelope()
    assert env.access_mode == "bounded_context_only"
    assert_validates(env.to_dict(), "context-envelope.schema.json")


def test_runtime_envelope_has_no_raw_access() -> None:
    # Recursively assert no raw vault/index access field exists anywhere in the payload.
    payload = _envelope().to_dict()

    def walk(node) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                assert k not in _RAW_ACCESS_KEYS, f"raw-access field leaked into envelope: {k}"
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(payload)


def test_envelope_references_bundle_as_non_authority() -> None:
    env = _envelope()
    assert env.context_bundles, "envelope must compose at least one ContextBundle reference"
    for b in env.context_bundles:
        assert b.non_authority is True
    # Schema-level: composed bundles are references (ids), not inlined/replaced bundles.
    for b in env.to_dict()["context_bundles"]:
        assert b["non_authority"] is True
        assert "context_bundle_id" in b
        assert "metadata_bundle" not in b  # a reference, never an inlined bundle


def test_envelope_strips_vault_id_from_capture_bundles() -> None:
    # Capture-path bundles carry vault_id (storage topology); the bounded envelope must not expose
    # any raw-access/storage field, even nested inside a retrieved item's bundle.
    art = capture.capture(text="a thought", principal_id="p-1")
    assert art.metadata_bundle.vault_id, "precondition: capture bundle carries vault_id"
    cand = retrieval.Candidate(
        metadata_bundle=art.metadata_bundle,
        admissibility_status="admitted",
        evidence_role_in_context=art.metadata_bundle.evidence_role,
    )
    result = retrieval.RetrievalResult(
        candidate_items=(cand,), scope_policy_prefiltered=True,
        active_scope_id=art.metadata_bundle.scope_id, query="x",
    )
    env = context.assemble_envelope(
        result, active_workspace_id="ws-1", active_scope_id=art.metadata_bundle.scope_id,
        principal_id="p-1", user_intent="orient",
    )
    payload = env.to_dict()
    assert_validates(payload, "context-envelope.schema.json")
    assert "vault_id" not in payload["retrieved_items"][0]["metadata_bundle"]


def test_envelope_rejects_scope_mismatch() -> None:
    # A RetrievalResult built for one scope cannot be packaged as a different scope.
    result = retrieval.retrieve(query="state machine", active_scope_id="scope:work/project-beta")
    with pytest.raises(ValueError):
        context.assemble_envelope(
            result, active_workspace_id="ws-1", active_scope_id=_ALPHA,
            principal_id="p-1", user_intent="orient",
        )


def test_runtime_denied_scopes_are_content_free() -> None:
    # Use shared vocab so cross-scope material is found-relevant-but-denied, then surfaced as a
    # content-free denied scope (no object/scope identity, content, or provenance).
    result = retrieval.retrieve(query="system agent rule state event workflow", active_scope_id=_ALPHA)
    env = context.assemble_envelope(
        result, active_workspace_id="ws-1", active_scope_id=_ALPHA,
        principal_id="p-1", user_intent="orient",
    )
    denied = env.to_dict()["denied_scopes"]
    assert denied, "relevant cross-scope material must surface as a content-free denied scope"
    for entry in denied:
        assert _DENIAL_LEAK_KEYS.isdisjoint(entry), f"denied scope leaked identity/content: {set(entry)}"
    # Denied material becomes an escalation condition, not silent inclusion.
    assert env.to_dict()["escalation_conditions"]
