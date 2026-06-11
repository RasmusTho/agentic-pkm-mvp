State: Development reference. Governance proportionality contract.
Doc role: Governance contract
Authority: Defines how much governance machinery each risk tier requires. Skills and CI reference this contract instead of carrying uniform requirements.
Owner: Builder-agent governance
Temporal class: durable

# Governance Proportionality

This repository is intentionally single-operator. Every gate, receipt, and report section is paid for twice: once by an agent burning context to produce it, once by one human reading it. The governing goal is cost-effectiveness — keep the safety properties (fail-closed promotion, truthful lifecycle state, delivery traceability) while cutting per-change overhead for low-risk work.

Proportionality applies to *reporting and PR-body machinery*. It never applies to lifecycle truth: labels and Project Status must stay truthful at every tier — the board must never lie.

## Risk tiers

Three tiers. When in doubt, classify up. A PR that mixes tiers takes the highest tier it touches.

### Tier 1 — low risk

**Classification:** docs-only changes; skill/governance text under `.codex/skills/**`, `AGENTS.md`, and `.github` governance surfaces; comment-level fixes. No product/runtime behavior, contracts, or shipped reality change.

**Deterministic CI classifier:** the PR body carries `- [x] Docs authoring lane` or `- [x] Governance lane`. The existing lane checkboxes double as the tier declaration — no new labels, tokens, or attestation mechanisms.

**Required machinery:**

- lane classifier in the PR body (the checkbox above)
- truthful lifecycle state (labels, Project Status) — mandatory at every tier
- `## BuilderOps Routing` may be omitted entirely when nothing was routed: **absence means "none"**. A present-but-unfilled section (template placeholders) still fails CI — claiming the section means filling it.
- output format: a short human summary (2–4 sentences) plus a receipt line; no multi-section report
- validation: lightweight docs/governance checks appropriate to the touched surfaces; no full code/test smoke by default

### Tier 2 — standard

**Classification:** bounded code slices, tests, owner-doc writeback — the everyday implementation lane.

**Required machinery (the current contract, unchanged):**

- `Fixes #<id>` linking the governing Issue
- `## BuilderOps Routing` section with concrete `Records/projections/receipts:` and `Reason:` lines
- every Acceptance Criterion's `Verify:` target resolved before merge
- standard receipts (delivery receipt, post-merge owner-doc check)
- repo-standard validation gates (`ruff check app tests` and the relevant test suites when `app/` or `tests/` changed)

### Tier 3 — high risk

**Classification:** migrations, release channels, prod mutations, `stable` pointer moves, Core Runtime <-> Agentic Lab boundary moves.

**Required machinery:** the full current machinery — fail-closed checks, promotion plans, operator acknowledgment, verification receipts. **Unchanged by this contract.** The release-channel promotion chain (`promote-to-test`, `promote-test-to-prod`, `prepare-promotion`, `execute-promotion`, `verify-promotion`, `rollback-promotion`) keeps every existing gate.

## What proportionality never relaxes

- Lifecycle truth: labels and Project Status stay accurate at every tier.
- The fail-closed release-channel promotion chain.
- `Verify:` targets on issue-backed acceptance criteria.
- Branch-truth gates at the publication boundary.

## CI enforcement

`.github/workflows/issue-pr-governance.yml` (`pr-contract` job) implements the Tier 1 relaxation deterministically: when the PR body carries a docs-authoring or governance lane checkbox, a missing `## BuilderOps Routing` section is treated as "none"; for all other PRs the section remains required with concrete values.

## Output formats

The everyday skills (`publish-pr`, `issue-to-code`, `verification-and-closure`, `deliver-issue-set`, `issue-maintenance-change-control`) lead their reports with a **Summary for the human** — 2–4 sentences covering what was done, what remains, and what needs a decision — before any receipt blocks, and include further sections only when they have content.
