---
name: Adapter Architecture Options
description: Compare provider-neutral acquisition seams without selecting or implementing an adapter.
task_id: ACI-ADAPTERS
source_anchor: docs/AI_CONVERSATION_INTELLIGENCE/README.md :: Remaining research tasks and execution order
parent_capability: AI Conversation Intelligence research roadmap
prerequisites: [ACI-PRIVACY]
depends_on: [PRIVACY_SECURITY_AND_DATA_OWNERSHIP.md]
can_parallelize_with: []
---

# Adapter Architecture Options

## Purpose

Define a provider-neutral architecture recommendation after privacy and ownership constraints are
known, without creating an adapter, port, schema, migration, event, or service.

## What This Task Does

Produce `docs/research/AI_CONVERSATION_INTELLIGENCE_ADAPTER_ARCHITECTURE_OPTIONS.md` comparing
human-selected input, official exports, caller-side API capture, machine-readable CLI capture,
enterprise/compliance feeds, portability APIs, and rejected scraping/private-cache seams.

## Concretely

Map EBF/SIP/HKA/MEM/GOV ownership; compare raw preservation, normalized projection, derivation
receipts, capability/version drift, pagination, branching, edits, tool calls, attachments,
citations, retries, replay, idempotency, deduplication, partial failure, rate limits, auth/secrets,
deletion/redaction propagation, test fixtures, and conformance.

## Why This Matters

Provider formats and access rights change independently. A safe architecture must isolate that
drift while preserving source truth, lineage, deletion semantics, and legible failure.

## Acceptance Criteria

- [ ] An option matrix compares all required acquisition classes and explains why scraping/private caches are not normal paths.
  - Verify: doc writeback at `docs/research/AI_CONVERSATION_INTELLIGENCE_ADAPTER_ARCHITECTURE_OPTIONS.md :: Option matrix`
- [ ] Boundary ownership and provider-neutral/provider-specific responsibilities are explicit across EBF/SIP/HKA/MEM/GOV.
  - Verify: doc writeback at `docs/research/AI_CONVERSATION_INTELLIGENCE_ADAPTER_ARCHITECTURE_OPTIONS.md :: Boundary and responsibility model`
- [ ] The design analysis covers raw/normalized/derived layers, drift discovery, complex conversation features, replay/idempotency/deduplication, partial failure, rate limits, auth/secrets, and deletion propagation.
  - Verify: doc writeback at `docs/research/AI_CONVERSATION_INTELLIGENCE_ADAPTER_ARCHITECTURE_OPTIONS.md :: Adapter lifecycle and failure semantics`
- [ ] Test-fixture/conformance strategy, recommendation, deferred alternatives, open questions, and bounded follow-ups are explicit.
  - Verify: doc writeback at `docs/research/AI_CONVERSATION_INTELLIGENCE_ADAPTER_ARCHITECTURE_OPTIONS.md :: Recommendation, conformance, and follow-ups`
- [ ] Mutable external claims use current primary sources with access dates, and the artifact is indexed.
  - Verify: doc writeback at `docs/research/AI_CONVERSATION_INTELLIGENCE_ADAPTER_ARCHITECTURE_OPTIONS.md :: Source register`, plus `docs/DOCS_INDEX.md` registration

## How to Verify (Pre-Merge)

- Run `python3 scripts/docs_guard.py --check` and `git diff --check`.
- Resolve required headings and inspect provider facts against the source register.
- Confirm no runtime or provider-specific contract is enacted.

## Out of Scope

- Adapter/port/schema/event/API/service implementation.
- Provider selection, credentials, real exports, migrations, or production rate-limit handling.
- Normative EBF/SIP/HKA/MEM/GOV contract changes.

## Related Docs

- `docs/research/AI_CONVERSATION_INTELLIGENCE_INPUT_SOURCES.md`
- `docs/research/AI_CONVERSATION_INTELLIGENCE_DATA_MODEL.md`
- `docs/AI_CONVERSATION_INTELLIGENCE/PRIVACY_SECURITY_AND_DATA_OWNERSHIP.md`
- `docs/boundaries/EBF.md`
- `docs/boundaries/SIP.md`

## Related GitHub Issues

Parent #3194; bounded child #3596, blocked on #3595.
