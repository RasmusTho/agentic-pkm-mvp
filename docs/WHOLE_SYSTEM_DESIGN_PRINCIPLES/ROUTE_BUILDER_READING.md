---
name: Route Builder Reading
description: Use the design packet resolver at Builder workflow boundaries without making Builder System the design authority.
task_id: DSP-03
github_issue:
source_anchor: "AGENTS.md :: Reading order"
parent_capability: Whole-System Design Principle Routing
prerequisites: [DSP-02]
depends_on: [RESOLVE_MINIMAL_DESIGN_PACKETS.md]
can_parallelize_with: []
---

# Route Builder Reading

## Purpose

Make relevant whole-system principles available at the moment a Builder change is classified while
preserving the existing narrow-skill and owner-document reading model.

## What This Task Does

Amend canonical Builder routing instructions and the narrowest owning skills to request a packet
from declared change facts, then read the exact returned owner sections. The workflow refuses when
the resolver cannot select safely and falls back to the existing explicit owner-doc route when the
resolver is unavailable.

## Concretely

Governance tests exercise Product, Builder, Platform/Ops, and boundary classifications and prove
that Builder instructions contain pointers and fallback rules rather than copied Product authority.

## Why This Matters

The principles must influence changes without becoming an expensive blanket read or an accidental
Builder-owned architecture layer.

## Acceptance Criteria

- [ ] Canonical Builder entrypoints invoke change-specific packet selection before structural
  guidance and read only returned owner sections plus independently mandatory workflow contracts.
  - Verify: `tests/governance/test_builder_instruction_routing.py::test_structural_changes_use_minimal_design_packet`
- [ ] Resolver unavailability or refusal preserves the explicit owner-doc fallback and cannot waive
  a mandatory read or invent authority.
  - Verify: `tests/governance/test_builder_instruction_routing.py::test_packet_refusal_falls_back_to_explicit_authority_route`
- [ ] Builder instructions do not copy, redefine, or claim ownership of Product/Runtime principles.
  - Verify: `tests/governance/test_builder_instruction_routing.py::test_builder_route_points_to_product_authority_without_absorbing_it`

## How To Verify Pre-Merge

- `pytest -q tests/governance/test_builder_instruction_routing.py`
- Run the instruction-governance validation required by `docs/development/AGENT_INSTRUCTION_GOVERNANCE.md`.

## Out Of Scope

- Product runtime-agent instructions, automated issue creation, or changing model/provider policy.

## Related Docs

- `AGENTS.md`
- `.codex/skills/README.md`
- `docs/development/AGENT_INSTRUCTION_GOVERNANCE.md`

## Related GitHub Issues

Issue #5203 remains independent Model Inquiry transport work.
