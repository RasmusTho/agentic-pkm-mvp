State: Advisory architecture audit snapshot, 2026-08-09. Evidence baseline: `origin/main` at `6f4fb5e2cdd1c05b8905f55b25b671c583c76a7e`. Subordinate to owner docs, ADRs, and live delivery authority. Executable governance handoff: `.codex/skills/builder-vault-deliberation/`, `.codex/skills/builder-vault-review/`, and `.codex/skills/_shared/BUILDER_VAULT_DELIBERATION_CONTRACT.md`.
Doc role: Reference (audit snapshot)
Authority: Evidence-based structural analysis only. ADR-0010 and ADR-0062 own BuilderOps authority; repo/GitHub/CI/review/merge/dispatcher/approval/receipt surfaces retain their existing authority.
Owner: BuilderOps governance
Temporal class: Point-in-time audit; refresh live-state claims rather than treating this snapshot as current.

# Builder Vault deliberation boundary review — 2026-08-09

## Question And Method

Can Codex and Claude Code agents on separate builder hosts share durable asynchronous BuilderOps
deliberation without creating a second task, decision, promotion, or delivery authority?

Three independent read-only evidence passes covered BuilderOps authority/storage, the Mimer client
boundary, and skill/discovery conventions. The coordinator reconciled them against current owner
docs, current `origin/main`, and live GitHub overlap. The accepted external design intent was staged
as BuilderOps `PromotionIntent` `prom_20260809122910_7ec86c98`; that record is proposal/provenance
only and does not enact this repo change.

## Verdict

**Proceed with a governance-only skill slice.** The existing external BuilderOps artifact vault is
an accepted Builder System surface, and the Model Inquiry path already proves the compatible
file-first precedent. Deliberation remains safe only when immutable entries are the source,
manifests/projections are derived, iCloud is never treated as a lock, and every authority crossing
uses an existing owner workflow.

No runtime, database, distributed writer, object type, dispatcher, backlog, automation service, or
devUI change is justified by the evidence.

## Authority Baseline

- ADR-0010 makes BuilderOps the building-system operating plane while repo docs/code/tests remain
  repo authority and generated views remain projections
  (`docs/adr/ADR-0010-builderops-vault-authority-boundary.md:25-72`).
- Skills and `AGENTS.md` are repo-governed BuilderOps surfaces and still require the PR gate
  (`docs/adr/ADR-0010-builderops-vault-authority-boundary.md:74-94`).
- ADR-0062 keeps Issue, PR SHA, CI, review, protection, and GitHub merge authoritative even when
  BuilderOps coordinates work (`docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md:38-57`).
- The shared `BUILDEROPS_VAULT_ROOT` is already documented as a Markdown artifact root, not a
  database or lock service; SQLite and credentials are excluded and cross-device claims are
  advisory (`docs/builderops/BUILDEROPS_VAULT_STORE.md:262-282`).
- Model Inquiry persists immutable artifacts and receipts in that root, validates hashes and causal
  edges, and fails closed on cross-device conflicts
  (`docs/BUILDEROPS_MODEL_INQUIRY/PRE_TICKET_INQUIRY_RECORDS.md:54-104`).
- Mimer app-agent skills are Product/Runtime client instructions, while BuilderOps records and
  projections are Builder System material (`.codex/skills/README.md:263-276`,
  `docs/architecture/SBS_OPERATING_MODEL.md:70-84`). The repository `vault/` is explicitly a
  fixture (`.codex/skills/mimer-vault-workspace/SKILL.md:1-9`).

## Ranked Boundary Findings

### F1 — Blocking if violated: deliberation can masquerade as delivery authority

Status, approval, claim, review, merge, and promotion prose would create split truth if a consumer
treated it as authoritative. The implementation therefore labels entries non-authoritative and
requires live reads from the owning external surfaces before state-dependent conclusions.

### F2 — Blocking if violated: a mutable shared thread recreates cross-device lost-update risk

iCloud has neither distributed lock nor transactional database semantics. Immutable unique entries,
no-overwrite installation, hash-bound targets, and derived content-addressed manifests avoid a
shared mutable sequence/head. Conflicts remain visible and stop disposition.

### F3 — High: a convenient path can leak into the wrong vault or shared content boundary

The live root, Mimer vaults, and the repo fixture are distinct surfaces. Root validation and
confinement are mandatory, and outputs expose only vault-relative locations. The accepted brief's
content boundary is stricter than generic Model Inquiry: no product code, diffs, private host paths,
credentials, or secrets are copied into deliberation.

### F4 — High: a new resolution flow can become a shadow promotion gateway

Resolution records rationale only. Owner decisions, design, Issues, learning, `PromotionIntent`,
PR publication, and receipts remain owned by their current skills/contracts
(`docs/builderops/BUILDEROPS_PROMOTION_GATEWAY.md:13-45`).

### F5 — Medium: discoverability can become a new mandatory ceremony

Natural hooks improve continuity, but absence of a thread cannot weaken or block an otherwise valid
resume, delivery, review, or closure. Only an existing governing authority contract can make a
specific promoted target required evidence.

## Invariant Kernel

| ID | Category | Invariant | Existing/added enforcement |
| --- | --- | --- | --- |
| BVD-01 | MUST | Deliberation never grants delivery or promotion authority. | Existing ADR-0010/0062; shared contract makes consumers read live authority. |
| BVD-02 | MUST | Every source entry is immutable, attributed, hash-validated, and uniquely identified. | New shared skill contract; conflicts fail closed. |
| BVD-03 | MUST | Repository fixture, Mimer vaults, SQLite, secrets, private paths, and product code are excluded. | Existing vault separation plus new root/content gate. |
| BVD-04 | MUST | Correction, resolution, and archive are additive events with exact target/basis hashes. | New shared contract; no edit/move/delete path. |
| BVD-05 | GATE | Both skills load the same non-invocable contract and remain routed from canonical entrypoints. | Skill-consistency lint and focused governance test. |
| BVD-06 | GATE | Resume, delivery closure, epic closure, and cadence review carry bounded discovery hooks. | Focused governance test over the named workflow files. |
| BVD-07 | DOCTOR | Review detects stale, unanswered, duplicate, promotion-pending, conflicted, changed-after-resolution, and orphaned threads from entries. | `builder-vault-review`; projections remain optional snapshots. |
| BVD-08 | DOCTOR | Saved manifests/projections can be rebuilt from the complete validated entry set. | Content-addressed manifests and entry-first review procedure. |

BVD-01 through BVD-04 are the minimal correctness kernel. This Builder System governance contract
does not extend the Product/Runtime invariant registry in `docs/testing/invariant-tests.md`; doing
so would incorrectly recast builder workflow instructions as runtime fitness rules.

## Research-Question Resolution

### RQ1 — What is durable?

Immutable Markdown entries in the validated external BuilderOps artifact root. Manifests and health
projections are rebuildable snapshots. External Issues, PRs, commits, CI, reviews, dispatchers,
approvals, BuilderOps records, and receipts retain their own durability and authority.

### RQ2 — How do two devices write safely?

They create collision-resistant entry IDs and install one final pathname without overwrite. They do
not coordinate through SQLite, a sequence number, a mutable head, or an iCloud lock. Full-set hash
validation detects synchronized conflicts; it does not silently resolve them.

### RQ3 — How are threads corrected and closed?

By new correction/resolution/archive entries that cite exact target or manifest hashes. Physical
file mutation, thread-directory moves, and deletion are unnecessary.

### RQ4 — How does useful deliberation become work or truth?

Through the existing owner decision, design-handoff, Issue, learning, PromotionIntent, PR, and
receipt paths. A resolution may cite their completed artifacts but cannot perform their transitions.

### RQ5 — Where should discovery run?

At substantial session close, interrupted-work resume, larger delivery review/closure, parent/epic
closure, and a configured weekly/threshold health pass. These are observation points, not new gates.

## SBS Reconciliation

The slice **conforms to** the Builder System boundary in
`docs/architecture/SBS_OPERATING_MODEL.md:102-136` and its repo-local skill artifact map
(`docs/architecture/SBS_OPERATING_MODEL.md:189`). It does not extend or reshape the Product/Runtime
SBS, CES ownership, Mimer client boundary, or control-plane target. No SBS transition-debt row is
needed because the new artifacts remain inside the already-defined external BuilderOps artifact
surface and introduce no claimed runtime state.

The adjacent target-state devUI Focus Conversation Port remains separate: it exports one scoped
provider context and treats dispositions as provenance, while this slice preserves asynchronous
BuilderOps context. This change adds no devUI ingestion, session inventory, durable command,
projection, or UI. A future read-only deliberation projection would require its own governed spec
and would still rebuild from validated entries rather than own their state.

## Implementation Plan And Reconciliation

1. Add one `_shared` non-invocable contract for root confinement, entry layout, hashes, immutable
   writes, derived state, content safety, and promotion routing.
2. Add `builder-vault-deliberation` for create/read/search/reply/correct/resolve/archive.
3. Add `builder-vault-review` for periodic health and evidence-backed disposition.
4. Add bounded discovery references to the existing skill index, root agent routing, resume,
   verification/closure, epic delivery, parent closure, and learning cadence.
5. Enforce discovery/contract linkage with existing skill lint and one focused governance test.

Live GitHub search found no existing deliberation Issue or PR to extend. The capability is one
bounded Tier 3 governance change because its contract governs shared data and concurrent writers;
`feature-breakdown` and new implementation Issues would still add ceremony without improving
acceptance. No backlog handoff is created.
