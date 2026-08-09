---
name: Open External Conversation Port
description: Export or open one immutable subject context pack to Codex or Claude without session authority or storage.
task_id: FCP-03
github_issue: 4696
source_anchor: "docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md :: Conversation Port contract"
parent_capability: devUI Focus + Conversation Port
prerequisites: [FCP-01, FCP-02]
depends_on: [COMPOSE_SUBJECT_CENTRED_FOCUS.md, VALIDATE_FOCUS_CONVERSATION_DESIGN.md]
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
- Adds a pack preview showing purpose, exact includes/excludes, sources, limitations, expiry, and
  hash.
- Adds bounded export/open adapters with explicit available/unavailable/unsupported states.
- Accepts a non-authoritative `ConversationDisposition.v1` with one allowed outcome and optional
  typed-proposal payload.
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
- [ ] Browser acceptance covers the accepted handoff, keyboard flow, exact hash display, no-action,
      unavailable, unsupported, stale, and unlinked states.
  - Verify: `tests/browser/test_devui_conversation_port.py::test_conversation_port_acceptance_matrix`.

## How to Verify (Pre-Merge)

- Run the five named unit/architecture tests and the browser acceptance file.
- Exercise changed-byte, expired, over-broad, unavailable, unsupported, refused, and no-action
  fixtures.
- Inspect network/storage behavior for the absence of session enumeration and transcript/task
  persistence.
- Run `git diff --check`.

## Out of Scope

- Embedded chat or transcript rendering.
- Global provider-session view or reconciliation.
- Command execution; FCP-04 owns the first command.
- Builder System Control implementation.

## Related Docs

- `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md`

## Related GitHub Issues

Filed as blocked child [#4696](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4696) and made
ready only after FCP-01 delivery and FCP-02 handoff acceptance.
