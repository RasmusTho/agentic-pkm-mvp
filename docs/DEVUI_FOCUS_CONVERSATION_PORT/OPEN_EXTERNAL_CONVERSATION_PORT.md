---
name: Open External Conversation Port
description: Export or open one immutable subject context pack to Codex or Claude without session authority or storage.
task_id: FCP-03
github_issue: 4696
source_anchor: "docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md :: Conversation Port contract"
parent_capability: devUI Focus + Conversation Port
prerequisites: [FCP-01]
depends_on: [COMPOSE_SUBJECT_CENTRED_FOCUS.md]
can_parallelize_with: []
recommended_capability: "Codex Terra / high"
capability_rationale: "Bounded external-adapter and canonical-hash work with provenance, privacy, and no-authority constraints."
---

# Open External Conversation Port

## Purpose

Allow the owner to take one scoped Focus subject into an external Codex or Claude conversation
through immutable context rather than inferred or globally discovered sessions.

## What This Task Does

- Defines canonical serialization and SHA-256 validation for `ConversationContextPack.v1`.
- Binds every material source to a fresh, watermarked read and caps pack expiry at the earliest
  source freshness deadline.
- Defines the read-only pack-preview data needed to show purpose, exact includes/excludes, sources,
  limitations, expiry, and hash without selecting a visual treatment.
- Adds bounded export/open adapters with explicit available/unavailable/unsupported states.
- Accepts a non-authoritative `ConversationDisposition.v1` with one allowed outcome; a non-null
  typed-proposal payload remains refused until FCP-04 owns its complete validator.
- Keeps provider transcript/session/model/usage fields as optional provenance only and persists no
  devUI transcript, session inventory, disposition, task, or effect.

## Concretely

Given one fresh Focus subject, the preview exports canonical pack bytes with hash `H`. A provider
response may return `plan` plus source refs, but nothing changes until a separately validated typed
proposal also binds `H`; selecting `no_action` ends the flow without a durable devUI record.

## Why This Matters

External reasoning is useful only if its context and limits are inspectable. Session discovery or
implicit effect would turn a reasoning port into a competing work and authority system.

## Acceptance Criteria

- [ ] Canonical serialization produces the same hash for the same semantic pack and rejects changed
      bytes, duplicate/ambiguous fields, noncanonical encoding, expired sources, and over-broad scope.
  - Verify: `tests/builderops/test_devui_conversation_port.py::test_context_pack_hash_is_canonical_and_scope_bounded`.
- [ ] Export/open passes the exact previewed artifact and never discovers, enumerates, or claims an
      existing provider session.
  - Verify: `tests/builderops/test_devui_conversation_port.py::test_external_port_has_no_global_session_discovery`.
- [ ] Provider unavailable/unsupported/refused states leave Focus readable and produce no hidden
      fallback or effect.
  - Verify: `tests/builderops/test_devui_conversation_port.py::test_provider_failure_degrades_only_the_port`.
- [ ] Disposition outcomes are restricted to the six specified values and remain non-authoritative;
      prose or transcript content can never invoke a command.
  - Verify: `tests/builderops/test_devui_conversation_port.py::test_disposition_is_provenance_not_command`.
- [ ] No browser/server transcript store, session store, task store, inferred work link, credential
      path, GitHub call, or repository mutation is introduced.
  - Verify: `tests/architecture/test_devui_focus_boundaries.py::test_conversation_port_adds_no_authority_or_store`.
- [ ] The adapter emits complete preview-state fixtures for exact hash, no-action, unavailable,
      unsupported, stale, and unlinked states without prescribing layout or interaction geometry.
  - Verify: `tests/builderops/test_devui_conversation_port.py::test_conversation_port_emits_design_handoff_fixtures`.

## How to Verify (Pre-Merge)

- Run the six named unit/architecture tests.
- Exercise changed-byte, expired, over-broad, unavailable, unsupported, refused, and no-action
  fixtures.
- Inspect network/storage behavior for the absence of session enumeration and transcript/task
  persistence.
- Run `git diff --check`.

## Out of Scope

- Embedded chat or transcript rendering.
- Browser layout, interaction geometry, or visual implementation; FCP-02 owns the governed handoff.
- Global provider-session view or reconciliation.
- Command execution; FCP-04 owns the first command.
- Builder System Control implementation.

## Related Docs

- `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md`

## Related GitHub Issues

Filed as blocked child [#4696](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4696) and made
ready only after FCP-01 delivery. It does not wait for a visual design receipt.
