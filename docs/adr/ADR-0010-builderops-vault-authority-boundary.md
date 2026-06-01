State: Accepted - docs/governance decision for BuilderOps Vault authority. No runtime, store, CLI, schema, API, MCP, or promotion-gateway behavior is implemented.

# ADR-0010: BuilderOps Vault Authority and Promotion Boundary

**Date:** 2026-06-01
**Status:** Accepted - docs/governance decision for #1499

---

## Context

BuilderOps Vault needs an authority decision before any BuilderOps Vault implementation begins. The
vault is intended to become the shared operating plane for builder-agent work, but that operating
plane must not blur into product/runtime truth or silently rewrite repository authority.

The active missing package is now the BuilderOps operating plane. The earlier Contextualization
Layer package is not the active gap for this issue: #1093 through #1098 are completed docs/spec
deliveries, and this ADR must not frame BuilderOps Vault as filling that completed package.

#1495 raised the related raw agent worklog boundary: raw builder-agent work notes need a default
home that does not pollute reviewed repo docs, `$CODEX_HOME`, or local-only ignored state. This ADR
reconciles that boundary at the authority level. It does not implement storage or migrate any
learning-log, roadmap, or docs freshness state.

## Decision

BuilderOps governs the building system.
Repo governs product/runtime truth.
GitHub Issues and skills are BuilderOps surfaces.
Promotion across authority classes is explicit.
No silent authority transfer.

BuilderOps Vault is the BuilderOps operating plane. It may guide work, queue proposals, record
signals, and generate projections. It may not silently change code, tests, runtime contracts,
product ADRs, canonical architecture docs, current-state owner docs, or any other product/runtime
truth surface.

GitHub Issues remain the current executable task-contract surface. Repo-local skills under
`.codex/skills/**` and `AGENTS.md` are BuilderOps-governance artifacts stored in the repo as
bootstrap/executable copies until a future BuilderOps-to-repo export/promotion pipeline exists.

## Authority model

### A. BuilderOps domain

BuilderOps governs the building system.

BuilderOps Vault owns, or will own once implemented, builder-agent worklogs, learning signals,
roadmap execution state, docs freshness state, maintenance queues, promotion intents, and
builder-operation receipts.

BuilderOps may guide work, queue proposals, record signals, and generate projections. Those objects
are operating-plane material unless explicitly promoted across an authority boundary.

### B. Product/runtime domain

Repo governs product/runtime truth.

The repository remains the authority surface for code, tests, product/runtime contracts, ADRs,
canonical architecture docs, and current-state owner docs.

Product/runtime truth changes only through normal repo authority gates. BuilderOps does not bypass
tests, PR review, ADR/doc ownership, contract-governance requirements, or the product/runtime owner
docs that define shipped reality.

### C. Projection/mirror domain

The projection/mirror domain includes generated views, exported summaries, dashboards, GitHub
Project views, external board/tool projections, and generated repo/dashboard views.

Projections are not authority by default. Generated projections must identify themselves as
projections. Projection drift does not change source authority.

## BuilderOps surfaces

The following are BuilderOps surfaces even when stored in GitHub or in the repository:

- GitHub Issues
- `.codex/skills/**`
- `AGENTS.md`

GitHub Issues are BuilderOps artifacts and remain the current executable task-contract surface for
implementation work. They are not product/runtime semantic truth.

Repo-local skills under `.codex/skills/**` are BuilderOps-governance artifacts stored in the repo as
bootstrap/executable copies. They sequence and operationalize builder-agent workflow, but they do
not become product/runtime contracts merely because they live in the repository.

`AGENTS.md` is a BuilderOps-governance surface while stored in the repo. It is the canonical
builder-agent instruction entrypoint, not runtime/system-agent architecture.

Changes to `.codex/skills/**` and `AGENTS.md` still require repo PR until a future
BuilderOps-to-repo export/promotion pipeline exists. Storage in the repo is a bootstrap/executable
mechanic, not an authority-class collapse.

## Product/runtime non-authority boundary

BuilderOps may propose, queue, route, and record.

BuilderOps may not silently change code, tests, runtime contracts, product ADRs, canonical
architecture docs, or current-state owner docs.

No product/runtime contract changes without the repo authority gate.

If BuilderOps evidence implies a product/runtime change, the output is a proposal, issue, PR,
ADR/decision doc, or owner-doc writeback proposal. It is not silent truth mutation.

## Projection/mirror boundary

Generated views and dashboards are projections.

External tool boards are projections unless the governing repo docs say otherwise.

Projections must preserve provenance back to their source authority.

Projection updates do not imply authority transfer.

Projection drift is corrected by reconciling with the authoritative source, not by treating the
projection as truth.

## Promotion targets

Allowed promotion targets are:

- GitHub Issue
- PR
- ADR/decision doc
- owner-doc writeback proposal
- generated projection
- discard receipt

Promotion mapping:

- BuilderOps operational signal -> GitHub Issue
- BuilderOps decision -> skill/AGENTS proposal
- BuilderOps task -> PR
- BuilderOps finding -> owner-doc writeback proposal
- BuilderOps projection -> generated repo/dashboard view
- BuilderOps obsolete/invalid signal -> discard receipt

A skill/AGENTS proposal is not self-applying. It crosses into repo authority through an explicit
PR, and when appropriate through an owner-doc writeback proposal or ADR/decision doc.

Promotion is an explicit boundary crossing, not automatic synchronization.

## Raw worklog boundary

This section reconciles #1495 at the authority level.

Raw agent worklogs belong in BuilderOps Vault by default.

Raw agent worklogs do not belong in reviewed repo docs by default.

Raw agent worklogs do not belong in `$CODEX_HOME` by default.

Raw agent worklogs do not belong in local-only ignored state by default, except as transient
execution scratch/state.

Raw worklogs may later be promoted into GitHub Issues, owner-doc writeback proposals, learning
summaries, ADR/decision docs, generated projections, or discard receipts through explicit
promotion.

Raw worklog existence is not itself product/runtime truth.

Until BuilderOps Vault storage exists, #1499 does not authorize a new permanent raw-worklog storage
mechanic. `docs/learning-log.md`, where still used, remains a promoted learning-summary surface, not
the default raw worklog store. Storage mechanics and migrations belong to #1500 and later issues.

## Consequences

BuilderOps Vault can become the shared operating plane for builder-agent work.

GitHub Issues remain the current executable task-contract surface for now.

Repo-local skills and `AGENTS.md` remain repo-stored bootstrap/executable copies for now.

A future BuilderOps-to-repo export/promotion pipeline can change storage mechanics later, but not
through #1499.

Product/runtime contracts remain protected by normal repo gates.

Generated projections must be labeled as projections.

## Out of scope for #1499

#1499 does not implement:

- BuilderOps store
- BuilderOps object schemas
- CLI
- API or MCP boundary
- promotion gateway
- migrations
- moving `.codex/skills/**` out of the repo
- replacing GitHub Issues as the current executable task-contract surface
- changing product/runtime contracts
- changing code, tests, or runtime behavior
- migrating learning-log, docs freshness, or roadmap execution state

These belong to #1500 and later issues unless the issue contract is updated.

## Validation

Acceptance criteria are discoverable with:

```bash
rg -n "BuilderOps governs the building system|GitHub Issues and skills are BuilderOps surfaces|Promotion targets|Raw worklog boundary" docs .codex AGENTS.md
git diff --check docs .codex AGENTS.md
python3 scripts/docs_guard.py
```

## References

- #1498 - epic(builderops): create shared BuilderOps Vault operating plane
- #1499 - decision(builderops): define BuilderOps Vault authority and promotion boundary
- #1495 - type:task: decide raw agent worklog persistence boundary
- `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`
- `docs/development/DELIVERY_FEEDBACK_LOOP.md`
- `docs/DOCS_INDEX.md`
- `docs/ROADMAP.md`
- `AGENTS.md`
