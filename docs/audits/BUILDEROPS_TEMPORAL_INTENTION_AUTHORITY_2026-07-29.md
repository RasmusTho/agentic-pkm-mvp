State: Advisory architecture audit snapshot, 2026-07-29. Structural evidence baseline: origin/main at eb441db4ef819bd64818569f98d193cad4047467 (2026-07-29T14:23:05+02:00); live GitHub state sampled 2026-07-29. Subordinate to docs/DOCS_INDEX.md, owner contracts, and accepted ADRs. No runtime authority or implementation Issue is created by this audit.
Doc role: Reference (audit snapshot)
Authority: Evidence-based Builder System / Product-boundary analysis. BuilderOps object semantics remain owned by docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md; Product artifact semantics remain owned by their respective contracts; owner documents win on disagreement.
Owner: BuilderOps governance / Architecture spine
Temporal class: snapshot
Review cadence: event-driven (before feature-breakdown or implementation promotion)

# BuilderOps temporal intention authority audit — 2026-07-29

## 1. Charter and method

This pass asks whether durable temporal/intention observability can be added without creating a second ledger, conflating Builder System evidence with Product truth, or storing private prompt material before retention authority exists. It follows the completed Model Inquiry inq_20260729T095049Z_1a2a2526 as a sequencing input. Its supplied iCloud report path was unreadable from this worktree (Operation not permitted), so claims below are limited to repository and GitHub evidence plus the delegated request's stated outcome.

Three read-only evidence passes covered (1) BuilderOps registry/storage, (2) Product temporal/lifecycle/privacy semantics, and (3) SBS/current-code/backlog reconciliation. No runtime code, vault record, BuilderOps record, or GitHub implementation Issue was created.

### TCD plan

| Field | Result |
| --- | --- |
| Complexity / risk | high / high |
| Recommended capability | architecture-research, Sol / xhigh synthesis; read-only parallel explorers and REST reconciliation |
| Cheapest acceptable path | Evidence-only audit, then gated feature-breakdown only after owner semantics are decided |
| Escalation trigger | Canonical writer, privacy/retention, or lifecycle meaning remains ambiguous |
| Review gate | Tier 1 docs-authoring lane; no implementation authorization |

## 2. Evidence map

### Builder System operational evidence

- ADR-0010 keeps BuilderOps in the building system, repository/product truth in existing authorities, and cross-authority change explicit (docs/adr/ADR-0010-builderops-vault-authority-boundary.md:25-40,121-144).
- The existing BuilderOps envelope already supplies stable id, type, authority/lifecycle/promotion fields, actors/timestamps, provenance, relationships, receipts, and projections (docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md:101-131). Local IDs are type-prefixed; an explicitly supplied ID is retained (app/builderops/models.py:51-60,359-362,394-407).
- Local SQLite serializes one selected database with BEGIN IMMEDIATE, primary-key creation, and idempotency replay, but expressly provides no cross-machine lock (app/builderops/store.py:95-129; docs/builderops/BUILDEROPS_VAULT_STORE.md:32-51,78-81).
- The accepted BuilderOps target is one PostgreSQL operational authority, atomically committing idempotency, guarded mutation, append-only receipt, and outbox intent; no Markdown projection may be sole authority (docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md:81-122). Its BCP-01 kernel is implemented only in the development baseline, not deployed or authoritative (docs/BUILDEROPS_CONTROL_PLANE/POSTGRES_TRANSACTION_KERNEL.md:12-15,89-115).
- Generated BuilderOps Markdown is non-authoritative and non-reproducible across host/time (docs/builderops/BUILDEROPS_VAULT_PROJECTIONS.md:24-42,103-132).

### Product temporal / attention evidence

- A vault-native Moment is a non-authoritative proposal with source-linked references and lifecycle (app/relevance/schema.py:1-8,29-90). The lifecycle is proposed, surfaced, engaged, dismissed, deferred, expired; it contains no done, ignore, or never_show_again (app/relevance/schema.py:29).
- Dismissed/expired Moments remain durable but are excluded from the live now view; deferred stays visible (app/relevance/now_surface.py:23-51). A production-shaped regression proves deferred survives deduplicated rematerialization (tests/relevance/test_deferred_lifecycle_dedup.py:1-15,79-108).
- Existing terms are non-interchangeable: commitments have done (app/domain/commitments.py:15-39), Heimdal attention has attended/skipped (app/heimdal/attention_log.py:70-76,160-180), and the declined-proposal ledger has rebuildable finding suppression that re-enables on loss/corruption (app/proposals/declined_ledger.py:14-50,148-184).
- Temporal Posture is a narrow, read-only derivation with no runtime consumers outside its own module/tests (docs/TEMPORAL_POSTURE/README.md:1-40; app/temporal/posture.py:139-210,229-257). It is not an intention store.

### Privacy, retention, and protected storage evidence

- BuilderOps worklogs must not store secrets/private scratch; ADR-0062 excludes raw client/database/GitHub/model/recovery credentials from PostgreSQL, outbox, receipts, artifacts, logs, WAL, and backups (docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md:276-282; docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md:73-79). Generic local and PostgreSQL payload validation does not classify arbitrary summary/body/payload content (app/builderops/models.py:394-447; app/builderops/control_plane/migrations/0001_transaction_kernel.sql:75-82,92-99).
- source_refs are traceability only; the validator requires non-empty ref_type and ref but defines no host-private reference class (docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md:142-166; app/builderops/models.py:379-387).
- Heimdal raw evidence is the only approved physical-erasure exception: it has guarded hard retention and append-only deletion receipts (app/heimdal/raw_store.py:501-523,601-638; app/heimdal/retention.py:141-169,424-506). That authority does not cover prompt summaries, BuilderOps records, or source references. Complete forgetting remains unshipped (docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md:409-430).
- HMAC has other host-private uses, but no BuilderOps temporal-intention HMAC-key contract (app/agent_memory/ask_provenance_manifest.py:62-86,106-125; app/instance/ownership_ledger.py:893-923,1126-1150). BuilderOps local storage is outside the shared vault and rejects vault-contained DB paths (docs/builderops/BUILDEROPS_VAULT_STORE.md:96-102,114-123; app/builderops/config.py:134-168).

## 3. Research-question resolutions

### RQ1 — Registry, envelope, IDs, privacy classes, and storage

Resolution: extend the existing BuilderOps registry and envelope; do not create a parallel Markdown family. The registry has no temporal/intention record type, privacy-class vocabulary, or validated host-private source-reference type today. A later contract must add one type through the existing authority route, use stable opaque IDs with provenance/receipts, and define privacy class/reference shape explicitly. Canonical operational records belong in protected BuilderOps storage—not the Product vault, iCloud, worktree files, or projections.

### RQ2 — Canonical writer and atomic create-if-absent

Resolution: the present deployed system cannot prove one canonical writer. SQLite provides atomic create-if-absent only per selected local DB; BCP-01 provides the necessary PostgreSQL transaction/fencing substrate but has not cut over. The capability must reject Markdown as a concurrent canonical ledger. Its future writer is one authenticated BuilderOps PostgreSQL API path after BCP deployment/cutover, using transactional identity/idempotency/receipt logic; Markdown is projection only.

### RQ3 — done, ignore, and never_show_again

Resolution: no approved common lifecycle exists. Existing Product terms belong to different artifact and authority models, and the Contextualization lifecycle document is target-state semantics rather than a runtime state machine (docs/CONTEXTUALIZATION_LAYER/ARTIFACT_LIFECYCLE_MODEL.md:1-20). The following is a proposed owner decision, not a shipped mapping:

| Proposed disposition | Proposed meaning | Proposed owner-authorized reversal |
| --- | --- | --- |
| done | The underlying intention is fulfilled/closed; preserve terminal evidence. | Explicit reopen or new intention; never automatic resurfacing. |
| ignore | Suppress this surfacing only for a bounded review window; no completion/preference claim. | Policy expiry or explicit owner re-surface. |
| never_show_again | Durable, scope-bound suppression of this intention/surface; do not delete underlying evidence. | Explicit owner reversal with a new append-only receipt; never heuristic reappearance. |

Until adopted or superseded, implementation may not map existing Product states to these names.

### RQ4 — Retention and physical erasure

Resolution: unresolved for this capability. BuilderOps object semantics expressly leave retention, encryption, and redaction implementation rules out of scope (docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md:1015-1027). No owner document supplies retention, erasure, or key-custody rules for prompt summaries, host-private source references, temporal fingerprints, or a new HMAC key.

The safe first-slice posture is no prompt text, summaries, raw source paths, raw identifiers, fingerprints, or HMAC key material. It may carry only existing approved non-secret opaque IDs/references. Retention and physical erasure require an owner decision before content-bearing collection or fingerprint/HMAC work.

## 4. Divergences and invariant kernel

| ID | Evidence-backed divergence | Consequence |
| --- | --- | --- |
| TIA-F1 | SQLite is single-host; PostgreSQL is not yet authoritative. | Markdown/local files would create duplicate or split truth. |
| TIA-F2 | Product disposition vocabulary has no common owner. | Reusing done, dismissed, decline, or skip would silently change semantics. |
| TIA-F3 | BuilderOps has secret exclusions but no temporal privacy/retention policy. | Content or key material would lack an approved lifecycle. |
| TIA-F4 | PostgreSQL records use state/payload/envelope rather than the initial local authority/lifecycle/promotion fields (app/builderops/control_plane/migrations/0001_transaction_kernel.sql:75-82; docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md:101-131). | A new record type needs an explicit envelope mapping. |

These are proposed future invariants; this audit does not extend docs/testing/invariant-tests.md or claim enforcement.

| ID | Class | Invariant |
| --- | --- | --- |
| TIA-INV-01 | MUST | Exactly one canonical writer admits a temporal/intention transition; Markdown is never canonical concurrent state. |
| TIA-INV-02 | MUST | Admission atomically creates or replays one identity, records disposition, and appends immutable lifecycle evidence. |
| TIA-INV-03 | MUST | Product artifact semantics and BuilderOps delivery/PKM/bug projections remain separate; a projection grants no authority. |
| TIA-INV-04 | MUST | No content, raw host reference, fingerprint input, or HMAC key is admitted before approved classification/retention/erasure rules. |
| TIA-INV-05 | GATE | A concurrent create/replay test proves first-write/replay and append-only receipt history on the actual canonical writer. |
| TIA-INV-06 | GATE | Rebuilding an attention projection leaves canonical state and owner disposition unchanged. |
| TIA-INV-07 | DOCTOR | Read-only reconciliation finds a projection without canonical record, receipt gap, disallowed content class, or unmapped disposition. |

The minimal correctness kernel is TIA-INV-01 through TIA-INV-04.

## 5. SBS and backlog reconciliation

- Conforms: BuilderOps is an enabling Builder System, while HIX owns human intent/review and Product PDM/MEM/DRI retain their own concerns (docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1336-1352; docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md:1-13).
- Extends: a future BuilderOps-only record/projection may extend operational evidence when it uses existing transactional authority. It does not reshape Product Moment/commitment ownership, attention UI, or runtime lifecycle.
- Existing work retained: #3788/#3793 remain the blocked deployment/cutover gate; completed development-kernel #3792 is reusable but not deployment proof. #4132 is a separate Product first-write-wins bug. #3325, #3351, and #3331 own existing Product temporal/review surfaces. No open Issue found by title search owns a canonical temporal-intention authority hub.
- Deferred: collectors, cross-host sync, migration, prompt/summarization capture, fingerprint/HMAC derivation, and cockpit projections are not dependencies of the safe first slice.

## 6. Recommendation and handoff

Evidence authorizes conditional feature-breakdown, not implementation-Issue filing. The breakdown must first record the owner decisions below and keep all implementation blocked until the PostgreSQL writer is deployed/cut over. It must reuse the BCP-01 port/receipt kernel, never introduce a parallel ledger.

After those gates, the smallest first slice is admit opaque temporal-intention lifecycle evidence through the canonical BuilderOps transaction:

1. add one registry-backed non-content record shape plus explicit PostgreSQL envelope mapping;
2. admit/replay a stable opaque identity in one transaction with append-only receipt;
3. encode only owner-approved dispositions and reversal receipt; and
4. generate a rebuildable read-only projection, proven by concurrent create/replay and rebuild-dedupe tests.

It excludes collectors, Product UI/cockpit, cross-host sync beyond the API, migration, prompt/summary capture, fingerprint/HMAC derivation, and physical-erasure work.

## 7. Owner decisions required before implementation

1. Adopt, replace, or reject the distinct disposition/reversal table in RQ3, including its artifact scope.
2. Select privacy class plus retention/erasure rules for each future payload category; until then the no-content posture is mandatory.
3. Confirm that the first writer waits for BCP deployment/cutover rather than using local SQLite or Markdown as temporary canonical state.

## 8. Docs governance decision

Docs Governance Decision:
- Artifact role: audit snapshot
- Owner: BuilderOps governance / Architecture spine; subordinate to named owner contracts
- Action: publish this advisory audit and its DOCS_INDEX snapshot row only
- Traceability: baseline SHA, file:line evidence, and live GitHub reconciliation in sections 1-5
- DOCS_INDEX impact: add one audit-snapshot row
- SBS/interface ownership: Builder System extension analysis; Product/runtime ownership unaffected
- Next skill or no-change receipt: feature-breakdown only after section 7 decisions; otherwise no implementation action
- Human Exception: none; unresolved semantics are recorded as owner decisions rather than silently enacted
