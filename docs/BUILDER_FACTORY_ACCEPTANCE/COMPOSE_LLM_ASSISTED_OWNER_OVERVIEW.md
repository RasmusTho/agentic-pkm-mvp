---
name: Compose LLM-assisted owner overview
description: compose source-linked LLM overview and next-step proposals
task_id: FCA-03
github_issue: 5402
source_anchor: docs/BUILDER_FACTORY_ACCEPTANCE/README.md :: Capability intent
parent_capability: Builder Factory Acceptance
prerequisites: [FCA-02]
depends_on: [DEFINE_OWNER_FACT_AND_ACTION_CONTRACT.md]
can_parallelize_with: []
---

State: Target-state task specification; not implemented or runtime acceptance.
Doc role: Specification
Authority: Accepted research-to-backlog handoff; existing owner contracts remain binding.

# Compose LLM-assisted owner overview

## Purpose

The owner explicitly accepts an LLM as part of Builder and prioritizes useful overview/control over determinism. Existing DevUI composers and Conversation Port are read-only building blocks; the live Focus adapter is still title-only and empty of execution/receipt context.

## What This Task Does

Add a bounded Builder-owned nonvisual synthesis entrypoint over the existing DevUI source envelopes and selected Issue/PR/run/receipt evidence. Use the configured Builder model/launcher boundary, not Product LLM globals, hard-coded provider IDs or silently billed fallback. Return source-linked plain-language current work, blockers, change since captured evidence and proposed next steps; preserve explicit unknowns, contradictions and timestamps. Production caller supplies addressed repo and bounded source snapshot. Model output is interpretation/proposal, never a verified state or execution instruction. Return the usable source snapshot and an honest model-unavailable state when model access fails. Wire the result into the existing read composition seam; visual rendering follows #4982/design and is outside this child.

## Concretely

A consumer of this task can inspect the named production seam or document and run the exact acceptance targets below. A passing fixture proves that finite contract; runtime and human observations remain on the parent. The expected outcome is compose source-linked LLM overview and next-step proposals.

## Why This Matters

A component or proposal must not be mistaken for a working owner platform. This task closes its named interface while preserving the existing source, action and deployment owners.

## Acceptance Criteria

- [ ] The production synthesis entrypoint carries addressed repo, captured evidence versions and source references through a mocked model response; unreferenced or conflicting completion claims cannot become canonical status.
  - Verify: `tests/builderops/test_devui_owner_synthesis.py::test_production_synthesis_preserves_sources_and_withdraws_unsupported_claims`
- [ ] Prompt injection in Issue/comment evidence and generated action text cannot invoke tools, mutate sources or turn a suggestion into an approved command from the production composition call site.
  - Verify: `tests/builderops/test_devui_owner_synthesis.py::test_untrusted_source_and_model_text_have_no_effect_authority`
- [ ] Missing model access, timeout or malformed output returns readable source facts with explicit model failure and no hidden provider/billing fallback.
  - Verify: `tests/builderops/test_devui_owner_synthesis.py::test_model_failure_preserves_usable_source_view`
- [ ] The production path uses Builder-owned configuration and invocation, and never imports or calls the Product model policy/facade to synthesize this view.
  - Verify: `tests/builderops/test_devui_owner_synthesis.py::test_production_call_uses_builder_model_boundary`

## How to Verify (Pre-Merge)

Run pytest -q tests/builderops/test_devui_owner_synthesis.py plus affected DevUI composition tests, ruff and mypy per baseline. Use model doubles for deterministic authority assertions; semantic usefulness and real-provider observations belong to FCA-07, not a claimed unit-test quality score.

## Out of Scope

No new task/transcript store, model provider layer, source discovery crawler, command execution or visual design. No promise of deterministic language or identical recommendations.

## Restart / Durability Posture

No new parallel authority store is introduced. Source facts and authorized operation receipts retain the durability of their existing owner. LLM text and views are derived; after restart regenerate them from current sources, show any unavailable history explicitly, and never redispatch an ambiguous action from the regenerated text. A previously accepted/tried fact must come from its durable source rather than memory of this view.

## Related Docs

- `docs/BUILDER_FACTORY_ACCEPTANCE/README.md`
- `docs/audits/BUILDER_SYSTEM_VISION_DELIVERY_2026-09-07.md`
- `docs/DEVUI.md`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`

## Related GitHub Issues

- Parent validation hub; see README.

Execution context: `fresh_issue_agent`; issue-local helper budget: 1.
Capability recommendation: Tier 3 external-model/authority boundary; fresh issue agent, configured Codex high reasoning, independent mechanism review; helper budget 1.
The implementation owner re-derives capability/risk at pickup; serial delivery is the default.
