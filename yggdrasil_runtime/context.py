"""ContextEnvelope assembly — the bounded operating context an agent (CAO) receives.

``assemble_envelope(retrieval_result, *, active_workspace_id, active_scope_id, principal_id, user_intent)``
returns a ContextEnvelope conforming to ``schemas/context-envelope.schema.json``.

- access_mode="bounded_context_only"; NO raw vault/index field (additionalProperties:false ensures it).
- retrieved_items = candidates as EMBEDDED-bundle items (metadata_bundle + evidence_role_in_context);
  no sibling object_id (embedded variant of the oneOf).
- denied_scopes = the RetrievalResult's content-free scope_denials (no identity/content leak).
- escalation_conditions derived from those denials (useful denied material surfaces, not hidden).
- context_bundles = references with non_authority=True (composes, never replaces, ContextBundle).
- citation/memory/mutation/execution policies carry their const guards.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4


@dataclass(frozen=True)
class ComposedBundleRef:
    context_bundle_id: str
    retrieval_result_id: str = ""
    non_authority: bool = True

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "context_bundle_id": self.context_bundle_id,
            "non_authority": True,
        }
        # retrieval_result_id is optional in the schema; omit when absent rather than emit an empty
        # (minLength-violating) id.
        if self.retrieval_result_id:
            out["retrieval_result_id"] = self.retrieval_result_id
        return out


# Storage/raw-access fields that must never appear inside a bounded ContextEnvelope. The bundle
# schema permits vault_id (storage topology), but the envelope contract forbids any raw-access field
# anywhere — so envelope-projected bundles drop them (the source bundle keeps them elsewhere).
_ENVELOPE_FORBIDDEN_BUNDLE_KEYS = frozenset({"vault_id", "vault_root", "raw_index"})


def _plain(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Fresh plain dict from an immutable mapping; inner tuples -> lists for JSON/schema validity."""
    return {k: (list(v) if isinstance(v, tuple) else v) for k, v in mapping.items()}


def sanitize_bundle_for_envelope(bundle: Any) -> Any:
    """Return a bounded-context copy of ``bundle`` with storage/raw-access topology removed.

    The boundary must hold for the envelope VALUE handed to callers, not only its serialization — a
    consumer using the object API must not be able to read ``item.metadata_bundle.vault_id``. The
    optional ``vault_id`` is the only such field on MetadataBundle today; dropping it keeps the bundle
    schema-valid. The source bundle (with full topology) is unchanged.
    """
    if getattr(bundle, "vault_id", None) is None:
        return bundle
    return replace(bundle, vault_id=None)


@dataclass(frozen=True)
class RetrievedItem:
    metadata_bundle: Any
    evidence_role_in_context: str

    def to_dict(self) -> dict[str, Any]:
        # The bundle is already sanitized at construction; the dict-level filter is defense in depth.
        bundle = {
            k: v
            for k, v in self.metadata_bundle.to_dict().items()
            if k not in _ENVELOPE_FORBIDDEN_BUNDLE_KEYS
        }
        return {
            "metadata_bundle": bundle,
            "evidence_role_in_context": self.evidence_role_in_context,
        }


@dataclass(frozen=True)
class ContextEnvelope:
    envelope_id: str
    access_mode: str
    active_workspace_id: str
    active_scope_id: str
    principal_id: str
    user_intent: str
    allowed_capabilities: tuple[Any, ...]
    denied_scopes: tuple[Any, ...]
    cross_scope_flows: tuple[Any, ...]
    retrieved_items: tuple[RetrievedItem, ...]
    context_bundles: tuple[ComposedBundleRef, ...]
    citation_policy: Mapping[str, Any]
    memory_policy: Mapping[str, Any]
    mutation_policy: Mapping[str, Any]
    execution_policy: Mapping[str, Any]
    escalation_conditions: tuple[Mapping[str, Any], ...]
    trace_id: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        # Rebuild fresh, plain, JSON-able structures from the immutable sources. jsonschema treats
        # only `list`/`dict` as array/object (not tuple/mappingproxy), and rebuilding means a caller
        # mutating the returned payload can never reach back into the frozen envelope's guards.
        return {
            "envelope_id": self.envelope_id,
            "access_mode": self.access_mode,
            "active_workspace_id": self.active_workspace_id,
            "active_scope_id": self.active_scope_id,
            "principal_id": self.principal_id,
            "user_intent": self.user_intent,
            "allowed_capabilities": [dict(c) for c in self.allowed_capabilities],
            "denied_scopes": [d.to_dict() for d in self.denied_scopes],
            "cross_scope_flows": [dict(f) for f in self.cross_scope_flows],
            "retrieved_items": [i.to_dict() for i in self.retrieved_items],
            "context_bundles": [b.to_dict() for b in self.context_bundles],
            "citation_policy": _plain(self.citation_policy),
            "memory_policy": _plain(self.memory_policy),
            "mutation_policy": _plain(self.mutation_policy),
            "execution_policy": _plain(self.execution_policy),
            "escalation_conditions": [_plain(c) for c in self.escalation_conditions],
            "trace_id": self.trace_id,
            "created_at": self.created_at,
        }


def _escalations_from_denials(denials) -> tuple[dict[str, Any], ...]:
    out = []
    for d in denials:
        cond = {
            "condition": "relevant material was withheld from this envelope",
            "escalate_to": "governance",
            "reason": d.reason,
        }
        if getattr(d, "denial_class", None):
            cond["denial_class"] = d.denial_class
        out.append(cond)
    return tuple(out)


def assemble_envelope(
    retrieval_result,
    *,
    active_workspace_id: str,
    active_scope_id: str,
    principal_id: str,
    user_intent: str,
) -> ContextEnvelope:
    # Fail loud on a scope mismatch: re-stamping a result built for one scope as another scope would
    # smuggle the original scope's bundles into this envelope, bypassing the prefilter's premise.
    if retrieval_result.active_scope_id != active_scope_id:
        raise ValueError(
            "active_scope_id mismatch: RetrievalResult was built for "
            f"{retrieval_result.active_scope_id!r}, cannot package it as {active_scope_id!r}"
        )
    denials = tuple(retrieval_result.denied_or_escalated_candidates)
    items = tuple(
        RetrievedItem(
            metadata_bundle=sanitize_bundle_for_envelope(c.metadata_bundle),
            evidence_role_in_context=c.evidence_role_in_context,
        )
        for c in retrieval_result.candidate_items
    )
    # Reference (never inline) the RCA ContextBundle this envelope composes; non_authority always true.
    rr_id = retrieval_result.retrieval_id or ""
    bundle_key = rr_id or uuid4().hex[:12]
    bundles = (
        ComposedBundleRef(
            context_bundle_id=f"context-bundle:{bundle_key}",
            retrieval_result_id=rr_id,
        ),
    )
    return ContextEnvelope(
        envelope_id=f"envelope:{uuid4().hex[:12]}",
        access_mode="bounded_context_only",
        active_workspace_id=active_workspace_id,
        active_scope_id=active_scope_id,
        principal_id=principal_id,
        user_intent=user_intent,
        allowed_capabilities=(),  # empty = read/reason only
        denied_scopes=denials,  # content-free scope_denials, carried straight through
        cross_scope_flows=(),
        retrieved_items=items,
        context_bundles=bundles,
        # Policy guards are immutable on the object API too (MappingProxyType + tuple), so a consumer
        # holding the envelope value cannot flip a guard in place.
        citation_policy=MappingProxyType({
            "citation_required": True,
            "citable_evidence_roles": ("evidence", "background", "reference"),
            "cross_scope_citation_requires_flow": True,
        }),
        memory_policy=MappingProxyType({
            "remember_allowed": True,
            "remembered_authority_state": "noncanonical",
            "cross_scope_remember_requires_flow": True,
        }),
        mutation_policy=MappingProxyType({"mutation_allowed": False, "requires_authority_transition": True}),
        execution_policy=MappingProxyType({"execution_allowed": False, "requires_authorization": True}),
        escalation_conditions=tuple(MappingProxyType(c) for c in _escalations_from_denials(denials)),
        trace_id=f"trace:{uuid4().hex[:12]}",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
