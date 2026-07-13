---
name: Privacy, Security, and Data Ownership
description: Define the threat/data-flow model and minimum control baseline for conversation research.
task_id: ACI-PRIVACY
source_anchor: docs/AI_CONVERSATION_INTELLIGENCE/README.md :: Remaining research tasks and execution order
parent_capability: AI Conversation Intelligence research roadmap
prerequisites: [ACI-INPUTS, ACI-DATA-MODEL, ACI-TAXONOMY]
depends_on: [../research/AI_CONVERSATION_INTELLIGENCE_INPUT_SOURCES.md, ../research/AI_CONVERSATION_INTELLIGENCE_DATA_MODEL.md, ../research/AI_CONVERSATION_INTELLIGENCE_KNOWLEDGE_TAXONOMY.md]
can_parallelize_with: []
---

# Privacy, Security, and Data Ownership

## Purpose

Establish the admissibility and control baseline that every later acquisition or experiment must
obey. The result is research and risk analysis, not legal advice or runtime policy.

## What This Task Does

Produce `docs/research/AI_CONVERSATION_INTELLIGENCE_PRIVACY_SECURITY_AND_DATA_OWNERSHIP.md` with a
threat/data-flow model, sensitivity and trust-boundary analysis, risk/control matrix, prohibited or
deferred acquisition paths, privacy baseline, residual risk, open questions, and bounded follow-ups.

## Concretely

Trace selection, export, capture, import, transformation, review, retention, redaction, deletion,
and portability across provider/account/workspace/scope boundaries. Distinguish regulatory facts,
provider requirements, repo risk analysis, and recommendations, using current primary sources.

## Why This Matters

Conversation histories can contain third-party identity, secrets, attachments, citations, work
product, and derived copies. An adapter design without this baseline would optimize extraction while
leaving consent, ownership, cross-scope exposure, or incomplete deletion unresolved.

## Acceptance Criteria

- [ ] The artifact models data flows and trust boundaries from acquisition through review and deletion.
  - Verify: doc writeback at `docs/research/AI_CONVERSATION_INTELLIGENCE_PRIVACY_SECURITY_AND_DATA_OWNERSHIP.md :: Threat and data-flow model`
- [ ] It classifies sensitivity and covers consent/control, account/workspace scope, ownership/rights, local-vs-external processing, secrets, attachments, citations, identity, logs, receipts, and provenance.
  - Verify: doc writeback at `docs/research/AI_CONVERSATION_INTELLIGENCE_PRIVACY_SECURITY_AND_DATA_OWNERSHIP.md :: Data categories, rights, and control baseline`
- [ ] A risk/control matrix covers cross-scope exposure, failure, partial deletion, derived-copy risk, provider policy/API/export constraints, and residual risk.
  - Verify: doc writeback at `docs/research/AI_CONVERSATION_INTELLIGENCE_PRIVACY_SECURITY_AND_DATA_OWNERSHIP.md :: Risk and control matrix`
- [ ] Prohibited/deferred paths, the recommended privacy baseline, open questions, and bounded follow-ups are explicit and separated from legal advice.
  - Verify: doc writeback at `docs/research/AI_CONVERSATION_INTELLIGENCE_PRIVACY_SECURITY_AND_DATA_OWNERSHIP.md :: Recommendation, residual risk, and follow-ups`
- [ ] Mutable external claims use current primary sources with access dates, and the artifact is indexed.
  - Verify: doc writeback at `docs/research/AI_CONVERSATION_INTELLIGENCE_PRIVACY_SECURITY_AND_DATA_OWNERSHIP.md :: Source register`, plus `docs/DOCS_INDEX.md` registration

## How to Verify (Pre-Merge)

- Run `python3 scripts/docs_guard.py --check` and `git diff --check`.
- Resolve all required headings with `rg` and inspect each external claim against its source register.
- Confirm the diff contains no runtime code, policy implementation, personal data, or provider payload.

## Out of Scope

- Legal advice, compliance certification, DPIA completion, or approval to process a real export.
- Runtime ingestion, privacy-policy enforcement, deletion implementation, or secrets tooling.
- Choosing an adapter or model provider.

## Related Docs

- `docs/research/AI_CONVERSATION_INTELLIGENCE_INPUT_SOURCES.md`
- `docs/research/AI_CONVERSATION_INTELLIGENCE_DATA_MODEL.md`
- `docs/boundaries/EBF.md`
- `docs/boundaries/GOV.md`
- `docs/boundaries/WSP.md`
- `docs/boundaries/HKA.md`

## Related GitHub Issues

Parent #3194; bounded child #3595.
