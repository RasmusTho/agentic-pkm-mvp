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

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class ComposedBundleRef:
    context_bundle_id: str
    retrieval_result_id: str
    non_authority: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_bundle_id": self.context_bundle_id,
            "retrieval_result_id": self.retrieval_result_id,
            "non_authority": True,
        }


@dataclass(frozen=True)
class RetrievedItem:
    metadata_bundle: Any
    evidence_role_in_context: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata_bundle": self.metadata_bundle.to_dict(),
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
    citation_policy: dict[str, Any]
    memory_policy: dict[str, Any]
    mutation_policy: dict[str, Any]
    execution_policy: dict[str, Any]
    escalation_conditions: tuple[dict[str, Any], ...]
    trace_id: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope_id": self.envelope_id,
            "access_mode": self.access_mode,
            "active_workspace_id": self.active_workspace_id,
            "active_scope_id": self.active_scope_id,
            "principal_id": self.principal_id,
            "user_intent": self.user_intent,
            "allowed_capabilities": list(self.allowed_capabilities),
            "denied_scopes": [d.to_dict() for d in self.denied_scopes],
            "cross_scope_flows": list(self.cross_scope_flows),
            "retrieved_items": [i.to_dict() for i in self.retrieved_items],
            "context_bundles": [b.to_dict() for b in self.context_bundles],
            "citation_policy": self.citation_policy,
            "memory_policy": self.memory_policy,
            "mutation_policy": self.mutation_policy,
            "execution_policy": self.execution_policy,
            "escalation_conditions": list(self.escalation_conditions),
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
    denials = tuple(retrieval_result.denied_or_escalated_candidates)
    items = tuple(
        RetrievedItem(
            metadata_bundle=c.metadata_bundle,
            evidence_role_in_context=c.evidence_role_in_context,
        )
        for c in retrieval_result.candidate_items
    )
    # Reference (never inline) the RCA ContextBundle this envelope composes; non_authority always true.
    bundles = (
        ComposedBundleRef(
            context_bundle_id=f"context-bundle:{retrieval_result.retrieval_id}",
            retrieval_result_id=retrieval_result.retrieval_id,
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
        citation_policy={
            "citation_required": True,
            "citable_evidence_roles": ["evidence", "background", "reference"],
            "cross_scope_citation_requires_flow": True,
        },
        memory_policy={
            "remember_allowed": True,
            "remembered_authority_state": "noncanonical",
            "cross_scope_remember_requires_flow": True,
        },
        mutation_policy={"mutation_allowed": False, "requires_authority_transition": True},
        execution_policy={"execution_allowed": False, "requires_authorization": True},
        escalation_conditions=_escalations_from_denials(denials),
        trace_id=f"trace:{uuid4().hex[:12]}",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
