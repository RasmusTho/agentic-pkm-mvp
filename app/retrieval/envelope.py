"""ContextEnvelope assembly for the live ``app/`` retrieval path (KERNEL-10).

The ASK/chat consumption seam must receive a bounded :class:`ContextEnvelope` — not raw ranked
dicts and not raw index access. This module assembles one from a
:class:`app.retrieval.hybrid.ScopedRetrieval`, validated against
``schemas/context-envelope.schema.json``.

It **mirrors the invariant SHAPE** of ``yggdrasil_runtime/context.py::assemble_envelope`` (the
reference implementation) without importing that test-only package: ``access_mode`` is always
``bounded_context_only``; there is NO raw-vault/raw-index field anywhere in the payload; denied
scopes are carried through content-free (class + reason only, no object/scope identity); useful
denied material surfaces as an escalation condition rather than being silently dropped; and the
envelope *composes* (never replaces) a ContextBundle reference marked ``non_authority=True``.

Each retrieved item carries only an embedded metadata bundle (single source of identity) plus its
in-context evidence role, clamped so it never exceeds the item's intrinsic role.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from app.retrieval.hybrid import ScopeDenial, ScopedRetrieval, _intrinsic_evidence_role

_SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas"

# Fields the bounded envelope must never expose — raw vault/index access or storage topology.
_ENVELOPE_FORBIDDEN_BUNDLE_KEYS = frozenset({"vault_id", "vault_root", "raw_index"})

# Conservative defaults for the schema-required MetadataBundle fields the live index rows do not
# carry. An index row is a machine mirror / projection of a vault note, not an authoritative source,
# so its default standing is non-authoritative. Values are valid members of the schema enums
# (schemas/_defs.schema.json). evidence_role is resolved separately via _intrinsic_evidence_role.
_DEFAULT_OBJECT_TYPE = "context_item"
_DEFAULT_SOURCE_ROLE = "machine_mirror"
_DEFAULT_AUTHORITY_STATE = "projection"
_DEFAULT_SENSITIVITY = "internal"
_DEFAULT_CREATED_BY = "app:retrieval"
_DEFAULT_CREATED_AT = "2026-01-01T00:00:00+00:00"

# Only enum members are accepted from payload; anything else falls back to the conservative default
# (never fail the envelope on a dirty payload, but never smuggle an out-of-enum value either).
_SOURCE_ROLE_ENUM = frozenset({
    "human_note", "human_capture", "decision_record", "work_project", "private_note",
    "general_knowledge", "agent_memory", "agent_proposal", "fictional_simulation", "rpg_rule",
    "external_source", "projection", "machine_mirror",
})
_AUTHORITY_STATE_ENUM = frozenset({
    "captured", "draft", "proposed", "working_fiction", "fictional_canon", "accepted", "canonical",
    "noncanonical", "derived", "projection", "deprecated", "retracted",
})
_SENSITIVITY_ENUM = frozenset({"public", "internal", "private", "secret"})


def _enum_or_default(value: Any, allowed: frozenset[str], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def _bundle_from_result(item: dict[str, Any]) -> dict[str, Any]:
    """Project a live retrieval result dict into a schema-valid, bounded MetadataBundle dict.

    Required fields absent from the index payload get conservative, enum-valid defaults; storage /
    raw-access topology (``vault_id`` etc.) is never included, so the bundle is bounded by
    construction. ``object_id`` is the doc id (the single source of identity — no sibling id).
    """
    payload = item.get("payload") or {}
    object_id = str(item.get("doc_id") or item.get("id") or payload.get("uuid") or "") or "artifact:unknown"
    scope_id = str(payload.get("domain") or payload.get("scope_id") or "scope:unscoped")
    # A retrieved context_item is a derived/projected view of the underlying durable index row; it
    # must carry provenance lineage (schema: derived object types require derived_from). The row's
    # object_id is the source it is derived from. object_id stays the doc id so the consumer keys the
    # admitted set on the same identity the retrieval surfaced.
    bundle: dict[str, Any] = {
        "object_id": object_id,
        "object_type": _DEFAULT_OBJECT_TYPE,
        "scope_id": scope_id or "scope:unscoped",
        "derived_from": [object_id],
        "source_role": _enum_or_default(
            payload.get("source_role"), _SOURCE_ROLE_ENUM, _DEFAULT_SOURCE_ROLE
        ),
        "authority_state": _enum_or_default(
            payload.get("authority_state"), _AUTHORITY_STATE_ENUM, _DEFAULT_AUTHORITY_STATE
        ),
        "evidence_role": _intrinsic_evidence_role(payload),
        "sensitivity": _enum_or_default(
            payload.get("sensitivity"), _SENSITIVITY_ENUM, _DEFAULT_SENSITIVITY
        ),
        "suppression_state": "visible",
        "created_by": str(payload.get("created_by") or _DEFAULT_CREATED_BY),
        "created_at": str(payload.get("created_at") or _DEFAULT_CREATED_AT),
        "provenance_event_ids": [f"prov:retrieval:{object_id or uuid4().hex[:12]}"],
    }
    sphere = payload.get("sphere") or payload.get("domain")
    if isinstance(sphere, str) and sphere.strip():
        bundle["sphere"] = sphere.strip()
    # Defense in depth: never let a storage/raw-access field ride along from the payload.
    for forbidden in _ENVELOPE_FORBIDDEN_BUNDLE_KEYS:
        bundle.pop(forbidden, None)
    return bundle


def _retrieved_item(item: dict[str, Any]) -> dict[str, Any]:
    bundle = _bundle_from_result(item)
    # Clamp in-context role to the intrinsic role of THIS bundle (never upgraded toward evidence).
    proposed = item.get("evidence_role_in_context")
    intrinsic = bundle["evidence_role"]
    role = proposed if proposed == intrinsic else intrinsic
    return {
        "metadata_bundle": bundle,
        "evidence_role_in_context": role,
    }


def _escalations_from_denials(denials: Iterable[ScopeDenial]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for d in denials:
        cond: dict[str, Any] = {
            "condition": "relevant material was withheld from this envelope",
            "escalate_to": "governance",
            "reason": d.reason,
        }
        if d.denial_class:
            cond["denial_class"] = d.denial_class
        out.append(cond)
    return out


def assemble_ask_envelope(
    scoped: ScopedRetrieval,
    *,
    active_workspace_id: str,
    active_scope_id: str,
    principal_id: str,
    user_intent: str,
) -> dict[str, Any]:
    """Assemble a schema-valid ContextEnvelope dict from a :class:`ScopedRetrieval`.

    The envelope composes the scoped candidates + content-free denials into the bounded operating
    context an ASK/chat consumer receives. ``access_mode`` is always ``bounded_context_only`` and
    the payload carries no raw-vault/raw-index/storage field. Returns a plain JSON-able dict (ready
    to validate and to hand to a consumer).
    """
    denials = tuple(scoped.denials)
    retrieved_items = [_retrieved_item(item) for item in scoped.results]
    rr_id = f"retrieval:{uuid4().hex[:12]}"
    envelope = {
        "envelope_id": f"envelope:{uuid4().hex[:12]}",
        "access_mode": "bounded_context_only",
        "active_workspace_id": active_workspace_id,
        "active_scope_id": active_scope_id,
        "principal_id": principal_id,
        "user_intent": user_intent,
        "allowed_capabilities": [],  # empty = read/reason only
        "denied_scopes": [d.to_dict() for d in denials],  # content-free, carried straight through
        "cross_scope_flows": [],
        "retrieved_items": retrieved_items,
        "context_bundles": [
            {
                "context_bundle_id": f"context-bundle:{rr_id}",
                "retrieval_result_id": rr_id,
                "non_authority": True,
            }
        ],
        "citation_policy": {
            "citation_required": True,
            "citable_evidence_roles": ["evidence", "background", "reference"],
            "cross_scope_citation_requires_flow": True,
        },
        "memory_policy": {
            "remember_allowed": True,
            "remembered_authority_state": "noncanonical",
            "cross_scope_remember_requires_flow": True,
        },
        "mutation_policy": {"mutation_allowed": False, "requires_authority_transition": True},
        "execution_policy": {"execution_allowed": False, "requires_authorization": True},
        "escalation_conditions": _escalations_from_denials(denials),
        "trace_id": f"trace:{uuid4().hex[:12]}",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return envelope


@lru_cache(maxsize=1)
def _envelope_validator():
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    resources = []
    for path in _SCHEMAS_DIR.glob("*.schema.json"):
        contents = json.loads(path.read_text(encoding="utf-8"))
        schema_id = contents.get("$id")
        if schema_id:
            resources.append((schema_id, Resource.from_contents(contents)))
    registry = Registry().with_resources(resources)
    schema = json.loads((_SCHEMAS_DIR / "context-envelope.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, registry=registry)


def validate_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Validate an assembled envelope against ``schemas/context-envelope.schema.json``.

    Raises ``jsonschema.ValidationError`` on a non-conforming envelope (fail loud — a malformed
    bounded context must never reach a consumer). Returns the envelope on success.
    """
    _envelope_validator().validate(envelope)
    return envelope


def assemble_and_validate_ask_envelope(
    scoped: ScopedRetrieval,
    *,
    active_workspace_id: str,
    active_scope_id: str,
    principal_id: str,
    user_intent: str,
) -> dict[str, Any]:
    """Assemble then validate — the single production entrypoint for the ASK/chat seam."""
    envelope = assemble_ask_envelope(
        scoped,
        active_workspace_id=active_workspace_id,
        active_scope_id=active_scope_id,
        principal_id=principal_id,
        user_intent=user_intent,
    )
    return validate_envelope(envelope)


__all__ = [
    "assemble_ask_envelope",
    "assemble_and_validate_ask_envelope",
    "validate_envelope",
]
