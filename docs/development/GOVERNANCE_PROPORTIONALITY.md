State: Development reference. Governance proportionality contract.
Doc role: Governance contract
Authority: Defines how much governance machinery each risk tier requires. Skills and CI reference this contract instead of carrying uniform requirements.
Owner: Builder-agent governance
Temporal class: durable

# Governance Proportionality

This repository is intentionally single-operator. Every gate, receipt, and report section is paid for twice: once by an agent burning context to produce it, once by one human reading it. The governing goal is cost-effectiveness — keep the safety properties (fail-closed promotion, truthful lifecycle state, delivery traceability) while cutting per-change overhead for low-risk work.

Proportionality applies to *reporting and PR-body machinery* **and to delivery-chain depth** — the independent review gate, merge mechanics, and repair budgets (`AGENTS.md :: Proportional delivery`). It never applies to authoritative lifecycle truth: Issue labels, Issue/PR state, CI, and merge evidence must stay truthful at every tier. Project Status is optional projection repair.

## Risk tiers

Three tiers. When in doubt, classify up. A PR that mixes tiers takes the highest tier it touches.

### Tier 1 — low risk

**Classification:** docs-only changes; skill/governance text under `.codex/skills/**`, `AGENTS.md`, and `.github` governance surfaces; comment-level fixes. No product/runtime behavior, contracts, or shipped reality change.

**Deterministic CI classifier:** the PR body carries `- [x] Docs authoring lane` or `- [x] Governance lane`. The existing lane checkboxes double as the tier declaration — no new labels, tokens, or attestation mechanisms.

**Required machinery:**

- lane classifier in the PR body (the checkbox above)
- truthful authoritative lifecycle state (labels, Issue/PR state, CI) — mandatory at every tier
- `## BuilderOps Routing` may be omitted entirely when nothing was routed: **absence means "none"**. A present-but-unfilled section (template placeholders) still fails CI — claiming the section means filling it.
- output format: a short human summary (2–4 sentences) plus a receipt line; no multi-section report
- validation: lightweight docs/governance checks appropriate to the touched surfaces; no full code/test smoke by default
- delivery depth: light path — declare `Final-Review-Rounds: 0` and merge plainly on green required checks; no independent review round, no verified-merge ceremony (single-issue or issue-free; a multi-issue PR escalates to the full path like any other)

### Tier 2 — standard

**Classification:** bounded code slices, tests, owner-doc writeback — the everyday implementation lane.

**Required machinery (the current contract):**

- exactly one `Governing-Issue: #<id>` plus at least one closing-keyword line for fully delivered
  work (the identities match in the normal single-Issue case)
- `## BuilderOps Routing` section with concrete `Records/projections/receipts:` and `Reason:` lines
- every Acceptance Criterion's `Verify:` target resolved before merge
- standard receipts (delivery receipt, post-merge owner-doc check)
- repo-standard validation gates (`ruff check app tests` and the relevant test suites when `app/` or `tests/` changed)
- delivery depth (single-issue default): light path — declare `Final-Review-Rounds: 0`, self-verify
  every `Verify:` target on the head SHA, wait for required checks green, then merge plainly with
  the normal closing keywords; GitHub-native closure closes the single governing issue and is
  verified after merge. No independent review round and no verified-merge neutralization/
  phase-ledger sequence. Delivery depth escalates to the full path when the PR is multi-issue,
  touches a TCD high-risk escalation surface (`AGENTS.md :: Total Cost of Development`), or a
  review round is explicitly requested

### Tier 3 — high risk

**Classification:** migrations, release channels, prod mutations, `stable` pointer moves, Core Runtime <-> Agentic Lab boundary moves.

**Required machinery:** the full current machinery — fail-closed checks, promotion plans, operator acknowledgment, verification receipts. **Unchanged by this contract.** Delivery depth is the full path: the independent local review gate with `Final-Review-Rounds: 1` or `2` plus the verified-merge sequence in `verification-and-closure`. The release-channel promotion chain (`promote-to-test`, `promote-test-to-prod`, `prepare-promotion`, `execute-promotion`, `verify-promotion`, `rollback-promotion`) keeps every existing gate.

## Delivery budgets and stop-loss

Every delivery carries a default budget of **2 CI-repair rounds per failure mechanism** (the full
path keeps the 2+2 capability-escalated repair budget owned by `verification-and-closure`). When
the budget is spent, stop grinding: ship the smallest passing subset of the change, or hand the
work back with a one-paragraph stop report and a `LearningSignal` naming the artifact that made it
expensive. Budgets are never rebound to a new mechanism key to reset accounting. Light (Tier 1/2)
deliveries run without sub-agent fan-out. Repeated failure on a bounded change is evidence the
solution is too big — shrink the solution before escalating capability.

## Post-validation base-drift evidence reuse

Branch freshness does not make byte-identical validation evidence false. When `origin/main`
advances after expensive local validation but before the first push, rebase as required by the
branch-truth gate and carry that evidence forward only when every condition below is proven:

- the rebased delivery patch has the same stable patch ID as the validated patch;
- every delivery-owned file blob is byte-identical to the validated patch;
- the incoming base commits do not overlap delivery-owned paths and a changed-surface review finds
  no semantic effect on dependencies, contracts, runtime configuration, schemas, migrations,
  generated inputs, test selection, CI/build tooling, or the validation command itself;
- no repair, scope change, conflict resolution, or delivery-owned edit occurred during the rebase;
- the rebased head passes the bounded `Verify:` targets and cheap integration/contract checks that
  can detect interaction with the incoming base; and
- the publication receipt records the validated SHA, rebased SHA, stable patch ID, incoming commit
  range, overlap result, checks rerun, and the expensive validation carried forward.

Any unresolved relevance question fails closed and reruns the affected validation. A code,
dependency, configuration, schema, migration, test-selection, CI/build-tooling, or contract change
that can affect the delivery is relevant even when filenames do not overlap.

This rule replaces unconditional full-suite repetition for irrelevant base-only SHA changes. It
does not carry forward GitHub CI, live-environment proof, mergeability, or a required final review:
those remain bound to the current PR head. It also never carries evidence across a repair commit,
scope change, conflict resolution, or changed delivery blob.

## Right-size default

The default solution is the most boring one that satisfies the acceptance criteria. A new gate,
receipt, ledger, registry, config surface, abstraction layer, or enterprise-grade pattern (high
availability, multi-tenancy, pluggable providers, defense-in-depth beyond the single-operator
trust model) requires an explicit demand in the governing contract — never default posture. "A
simpler mechanism satisfies the contract" is a valid blocking review finding at any tier. A new
permanent governance mechanism must name what it replaces or carry an explicit review-by date.
Product-side scale posture is owned by `docs/DESIGN_PRINCIPLES.md`.

## What proportionality never relaxes

- Lifecycle truth: labels and Issue/PR state stay accurate at every tier; Project projection repair is optional and cold-path.
- The fail-closed release-channel promotion chain.
- `Verify:` targets on issue-backed acceptance criteria.
- Branch-truth gates at the publication boundary.
- Required CI checks green on the current head SHA before any merge, at every tier.
- Required final reviews run on the current head SHA; only eligible pre-publication expensive
  validation may use the base-drift evidence-reuse rule above.

## CI enforcement

`.github/workflows/issue-pr-governance.yml` (`pr-contract` job) implements the Tier 1 relaxation deterministically: when the PR body carries a docs-authoring or governance lane checkbox, a missing `## BuilderOps Routing` section is treated as "none"; for all other PRs the section remains required with concrete values. The same job accepts `Final-Review-Rounds: 0` (light path), `1`, or `2`; the value's delivery-depth meaning is defined by this contract, not by CI.

## Output formats

The everyday skills (`publish-pr`, `issue-to-code`, `verification-and-closure`, `deliver-issue-set`, `issue-maintenance-change-control`) lead their reports with a **Summary for the human** — 2–4 sentences covering what was done, what remains, and what needs a decision — before any receipt blocks, and include further sections only when they have content.
