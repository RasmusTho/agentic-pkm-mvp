"""Invariant skeletons: agent memory is noncanonical and never real-world evidence.

Invariant registry: docs/testing/invariant-tests.md
  :: memory_item_authority_is_noncanonical, memory_item_cannot_be_real_world_evidence,
     remember_not_canonical
Issues: #2550 (registry), #2552 (skeletons). Contract: docs/architecture/memory-model.md (#2546).
"""

from __future__ import annotations

from tests.invariants._helpers import load_schema, value_family


def test_memory_item_authority_is_noncanonical() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: memory_item_authority_is_noncanonical
    # Static (schema_enforced): authority_state is a const noncanonical; source_role a const agent_memory.
    mi = load_schema("memory-item.schema.json")["properties"]
    assert mi["authority_state"].get("const") == "noncanonical"
    assert mi["source_role"].get("const") == "agent_memory"


def test_memory_item_cannot_be_real_world_evidence() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: memory_item_cannot_be_real_world_evidence
    # Static (schema_enforced): evidence_role is restricted to the non-authoritative family, which
    # excludes real-world `evidence`.
    non_authoritative = set(value_family("non_authoritative_evidence_role"))
    assert "evidence" not in non_authoritative
    mi = load_schema("memory-item.schema.json")["properties"]
    ev = mi["evidence_role"]
    # The memory schema references the non-authoritative family by $ref.
    assert "non_authoritative_evidence_role" in ev.get("$ref", "")


def test_remember_not_canonical() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: remember_not_canonical
    # Static (schema_enforced): material retained by `remember` is a memory item, and a memory item
    # can never hold canonical authority — so remembering cross-scope material never confers standing.
    mi = load_schema("memory-item.schema.json")["properties"]
    assert mi["authority_state"].get("const") == "noncanonical"
    # And `noncanonical` is distinct from the canonical authority family.
    assert "noncanonical" not in set(value_family("canonical_authority_state"))
