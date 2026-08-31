---
name: Resolve Minimal Design Packets
description: Select the smallest deterministic set of principle and owner sections for declared change facts.
task_id: DSP-02
github_issue:
source_anchor: "docs/WHOLE_SYSTEM_DESIGN_PRINCIPLES/README.md :: Cross-Task Invariants / Interaction Safety"
parent_capability: Whole-System Design Principle Routing
prerequisites: [DSP-01]
depends_on: [ESTABLISH_PRINCIPLE_KERNEL.md]
can_parallelize_with: []
---

# Resolve Minimal Design Packets

## Purpose

Turn the stable kernel into a deterministic read-only selection result that reduces context cost
without hiding applicable authority.

## What This Task Does

Add one repository-owned resolver that accepts normalized facts such as changed paths, system
classification, write class, persistence class, external effects, and risk triggers. It returns an
ordered packet of principle IDs and exact owner sections, or a typed refusal for ambiguity,
conflict, or stale metadata.

## Concretely

The focused test invokes the production resolver twice with the same facts and repository head and
compares canonical output bytes, then exercises unknown-owner and conflicting-class refusals.

## Why This Matters

Token-efficient routing is useful only if omission is deterministic, inspectable, and fail-loud.

## Acceptance Criteria

- [ ] Equal normalized facts and repository head produce byte-stable ordered packet output with
  exact source sections and the selected kernel version.
  - Verify: `tests/governance/test_design_packet_resolver.py::test_equal_change_facts_produce_canonical_packet`
- [ ] Ambiguous authority, missing owner sections, stale IDs, and contradictory write/persistence
  classifications return typed refusal and no partial packet.
  - Verify: `tests/governance/test_design_packet_resolver.py::test_ambiguous_or_stale_authority_refuses_without_partial_packet`
- [ ] Packet output is explicitly projection-only and contains no mutation, acceptance, ranking, or
  current-state promotion authority.
  - Verify: `tests/governance/test_design_packet_resolver.py::test_packet_is_read_only_projection`

## How To Verify Pre-Merge

- `pytest -q tests/governance/test_design_packet_resolver.py`
- `git diff --check`

## Out Of Scope

- Builder instruction edits, automatic code changes, model/provider selection, or a daemon/service.

## Related Docs

- `docs/WHOLE_SYSTEM_DESIGN_PRINCIPLES/README.md`
- `docs/DESIGN_PRINCIPLES.md`

## Related GitHub Issues

Depends on DSP-01; file only after its terminal receipt.
