---
name: Register Design-Agent Adapters
description: Add exact design-agent registrations above the shared ADR-0064 model-access transport.
task_id: CDH-02
source_anchor: docs/CKM_DESIGN_AGENT_INTEGRATION/README.md :: Authority boundary
parent_capability: CKM Design-Agent Integration Hub
prerequisites: [CDH-01, MAS-PHASE1-ACCEPTED]
depends_on: [DEFINE_DESIGN_RUN_CONTRACTS.md, ../MODEL_ACCESS_SUBSTRATE/README.md]
can_parallelize_with: []
---

# Register Design-Agent Adapters

## Purpose

Keep design-agent capability and availability above one shared model-access transport while
exposing only sanitized descriptors to CKM.

## What This Task Does

After parent #4286 closes with its repo-verifiable Phase 1 acceptance ledger, registers exactly
`codex`, `claude-design-via-claude-code`, and `fable` as design-agent domain profiles. The parent
validation is a filing/pickup prerequisite only; runtime code never reads GitHub or delivery
evidence. Withdrawn provider/bridge receipts and active provider-backed inference are not
prerequisites.

Each profile maps to a neutral role profile (`design.codex`, `design.claude`, `design.fable`) and
constructs a `ModelResolutionRequest` with the provider-free seven-field intent and a design-run-bound
`resolution_group_id`. The production path always calls the shared Builder
`resolve_group(...)` boundary, even for the normal one-adapter/one-request run. Provider/model,
capabilities, effective identity, and resolution-group provenance are outputs. If a typed grouped
request requires `distinct_effective_target`, a colliding resolution refuses before any adapter
call. No second execution protocol, credential resolver, session bridge, HTTP client, subprocess
runner, or provider-bearing role profile is added.

## Concretely

- Descriptors expose stable ID, availability, supported deliverable kinds, provider identity, and
  safe limitation/refusal detail.
- A request chooses one design agent explicitly; there is no order, score, recommendation, retry
  across agents, or fallback.
- CKM imports only the neutral port/descriptor contract.
- Provider/model resolution, credentials, sessions, execution transport, and failures remain owned
  by the shared model-access substrate. Interactive subscription-only routes are reported
  unavailable for headless design runs.

## Why This Matters

A second transport would preserve the exact fragmentation ADR-0064 was accepted to remove.
Provider-specific execution inside CKM would also turn a projection subsystem into an integration
control plane.

## Acceptance Criteria

- [ ] Registry discovery returns exactly the configured supported design-agent descriptors and
  honest headless availability resolved through the shared model-access substrate.
  Verify: `tests/builderops/test_design_agent_adapters.py::test_supported_design_adapters_conform_to_common_contract`
- [ ] Domain adapters declare provider-free model intent and consume `ModelTurnAdapter`; they
  contain no credential/session acquisition, provider transport, retry/fallback decision, or
  competing failure vocabulary.
  Verify: `tests/builderops/test_design_agent_adapters.py::test_design_agents_use_the_shared_model_access_substrate`
- [ ] The production adapter path maps the three domain IDs to the exact neutral role profiles,
  constructs run-bound `ModelResolutionRequest` groups, calls `resolve_group(...)`, preserves
  resolution-group provenance, and refuses a required-distinct collision before every adapter call.
  Verify: `tests/builderops/test_design_agent_adapters.py::test_design_agents_use_grouped_builder_resolution_with_collision_refusal`
- [ ] CKM-facing descriptors contain no credentials, commands, retry policy, raw stderr, or
  host-local launcher paths.
  Verify: `tests/builderops/test_design_agent_adapters.py::test_descriptor_and_failure_surfaces_are_secret_safe`
- [ ] Unknown or unavailable selection fails closed before execution and never falls back.
  Verify: `tests/builderops/test_design_agent_adapters.py::test_unknown_or_unavailable_adapter_never_falls_back`
- [ ] Existing model-inquiry adapters and launcher behavior remain unchanged.
  Verify: `tests/builderops/test_model_inquiry_adapters.py::test_local_command_adapter_is_bounded_and_secret_safe`

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/test_design_agent_adapters.py`
- `python3 -m pytest -q tests/builderops/test_model_inquiry_adapters.py`
- `ruff check app tests`
- `mypy app`

## Out of Scope

Credential/session/transport/resolver implementation, admission/approval, durable run state, CLI command
grammar, cockpit rendering, automatic provider choice, and subscription-session headless bridging.

## Related Docs

- `docs/CKM_DESIGN_AGENT_INTEGRATION/README.md`
- `docs/adr/ADR-0064-model-access-substrate.md`

## Related GitHub Issues

Create one child of #4131 after CDH-01 is terminal and #4286 has terminally accepted the
repo-verifiable Phase 1 ledger.
