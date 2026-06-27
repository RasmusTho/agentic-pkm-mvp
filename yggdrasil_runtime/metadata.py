"""The shared ``MetadataBundle`` type for the runtime slice.

Single source of truth for the semantic/provenance envelope every usable runtime object carries,
conformant with ``schemas/metadata-bundle.schema.json`` (shared enums in ``schemas/_defs.schema.json``).
Tasks 2-6 all use *this* type — a second, divergent bundle shape anywhere would break
``store_no_naked_vectors`` and candidate-identity single-source (see
``docs/YGGDRASIL_RUNTIME_SLICE_1/README.md`` :: Cross-Task Invariants).

Design rules enforced here:

- ``source_role``, ``authority_state``, and ``evidence_role`` are three separate required fields and
  are never collapsed.
- ``vault_id`` (storage topology) is a distinct optional field and is never equal to ``scope_id``
  (cognitive/policy/provenance frame).
- A bundle always carries at least one provenance event id (the creation/capture event), so a naked
  vector/chunk cannot exist.
- ``derived_from`` is required for derived/rebuildable object types (``segment``, ``projection``,
  ``retrieval_result``, ``context_item``); the DRI stage (#2581) is the call site that supplies it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# Object types whose schema 'if/then' requires a non-empty derived_from.
DERIVED_OBJECT_TYPES = frozenset(
    {"segment", "projection", "retrieval_result", "context_item"}
)

# Authority states that denote durable accepted standing; reaching one requires a governed
# AuthorityTransition + AuthorityReceipt (schema: canonical_authority_state). The schema
# conditionally requires authority_receipt_ref for these, so we enforce it at construction.
CANONICAL_AUTHORITY_STATES = frozenset({"accepted", "canonical"})

# The required core every bundle must carry (mirrors metadata-bundle.schema.json :: required).
_REQUIRED_FIELDS = (
    "object_id",
    "object_type",
    "scope_id",
    "source_role",
    "authority_state",
    "evidence_role",
    "sensitivity",
    "suppression_state",
    "created_by",
    "created_at",
    "provenance_event_ids",
)


@dataclass(frozen=True)
class MetadataBundle:
    """A schema-conformant metadata bundle. Construct via ``capture``/``dri``, not raw vectors.

    Immutable by construction: ``frozen=True`` blocks field reassignment, and the lineage
    collections (``provenance_event_ids``, ``derived_from``) are coerced to tuples so a downstream
    holder cannot mutate lineage in place (e.g. ``bundle.derived_from.clear()``) and recreate a
    naked/no-lineage object after the construction-time guards have run.
    """

    # --- required core ---
    object_id: str
    object_type: str
    scope_id: str
    source_role: str
    authority_state: str
    evidence_role: str
    sensitivity: str
    suppression_state: str
    created_by: str
    created_at: str
    provenance_event_ids: Sequence[str]

    # --- common optionals (omitted from to_dict when unset) ---
    vault_id: str | None = None
    workspace_id: str | None = None
    sphere: str | None = None
    principal_id: str | None = None
    derived_from: Sequence[str] = ()
    content_hash: str | None = None
    authority_receipt_ref: str | None = None

    def __post_init__(self) -> None:
        # Fail loud on construction-time contract violations the schema also enforces, so a bad
        # bundle never silently propagates downstream.
        for name in _REQUIRED_FIELDS:
            value = getattr(self, name)
            if value is None or (isinstance(value, (str, list, tuple)) and len(value) == 0):
                raise ValueError(f"MetadataBundle missing required field: {name}")
        if self.vault_id is not None and self.vault_id == self.scope_id:
            raise ValueError("vault_id must not equal scope_id (storage topology != policy frame)")
        if self.object_type in DERIVED_OBJECT_TYPES and not self.derived_from:
            raise ValueError(
                f"object_type={self.object_type!r} requires a non-empty derived_from (provenance "
                "must survive derivation)"
            )
        if self.authority_state in CANONICAL_AUTHORITY_STATES and not self.authority_receipt_ref:
            raise ValueError(
                f"authority_state={self.authority_state!r} requires an authority_receipt_ref "
                "(canonical standing comes only from a governed AuthorityTransition)"
            )
        if (
            self.object_type == "projection"
            and self.evidence_role == "evidence"
            and not self.authority_receipt_ref
        ):
            raise ValueError(
                "a projection may hold evidence_role='evidence' only via a provenance-backed "
                "promotion receipt (authority_receipt_ref); projection is not evidence by default"
            )
        # Coerce lineage collections to tuples so they cannot be mutated in place by a holder
        # (frozen=True only blocks reassignment). object.__setattr__ is the frozen-dataclass idiom.
        object.__setattr__(self, "provenance_event_ids", tuple(self.provenance_event_ids))
        object.__setattr__(self, "derived_from", tuple(self.derived_from))

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dict for schema validation; prunes unset optionals.

        Pruning keeps the instance compatible with the schema's ``additionalProperties: false`` and
        avoids emitting ``null`` for fields the schema expects to be present-or-absent.
        """
        out: dict[str, Any] = {}
        for name in _REQUIRED_FIELDS:
            value = getattr(self, name)
            # Emit lineage tuples as JSON arrays (jsonschema treats only lists as "array").
            out[name] = list(value) if isinstance(value, tuple) else value
        for name in (
            "vault_id",
            "workspace_id",
            "sphere",
            "principal_id",
            "derived_from",
            "content_hash",
            "authority_receipt_ref",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                if not value:
                    continue
                out[name] = list(value)
            else:
                out[name] = value
        return out
