State: Canonical builder-agent instruction file for this repository.
# Builder-Agent Instructions
This file governs development-time agents that modify, review, or validate this repository. It does
not govern Product/Runtime agents; their semantics live in `docs/AGENTS.md` and `docs/CONCEPTS/`.

## Reading order

1. Read this compact file completely.
2. Read `.codex/skills/README.md :: Skill routing`, then load the narrowest matching `SKILL.md`.
3. For structural work, follow `.codex/skills/README.md :: Structural-work design packet route` before grepping (never read whole) `docs/DOCS_INDEX.md` for the work area and reading the owner document.
4. Before validation, read `docs/development/DEV_WORKFLOW.md :: Validation baseline`.
5. For instruction changes, read `docs/development/AGENT_INSTRUCTION_GOVERNANCE.md :: Maintenance
   rules` and `:: Canonical entrypoints`. Outside `issue-to-code`, also read the required sections of
   `docs/development/AGENT_OPERATING_PROTOCOL.md` before code guidance.

Conditional reads are selected from the actual diff, not the requested scope. A `FILE :: Section` citation means read that section only; see `.codex/skills/_shared/READ_SCOPE.md`.

## Repo-local skill routing

`.codex/skills/README.md :: Skill routing` is the complete, linted repo-skill index. Skills carry
workflow procedure; this file carries only early, cross-cutting boundaries. Important entrypoints:

- general repo work: `.codex/skills/agentic-pkm/SKILL.md`
- bounded Issue implementation: `.codex/skills/issue-to-code/SKILL.md`
- issue-set coordination: `.codex/skills/deliver-issue-set/SKILL.md`
- docs/governance routing: `.codex/skills/docs-governance/SKILL.md`
- branch, commit, push, or PR: `.codex/skills/publish-pr/SKILL.md`
- final verification/merge: `.codex/skills/verification-and-closure/SKILL.md`
- design handoff: `.codex/skills/yggdrasil-design-handoff/SKILL.md`
- mandatory closeout: `.codex/skills/klart/SKILL.md`

Load a matching skill before its workflow boundary. Publication actions never use an ad hoc flow.

## Required rules

- Act only within the user's or governing contract's scope. Do not make destructive, production,
  credential, GitHub, deployment, release, or other external writes without explicit authority.
- Never expose credentials or secret material in commands, logs, commits, prompts, or receipts.
- Preserve unrelated dirty work. Read `git status` before edits and review `git diff` before reports.
- Keep Builder System workflow separate from Product/Runtime instructions and memory.
- Keep code, tests, and owner docs consistent. If a runtime precondition is added, update every
  producer (bootstrap, migration, fixtures) and add a fail-loud preflight in the same change.
- Do not present target-state docs as shipped truth. Keep normative content in its owner document.
- Stop when authority is contradictory, scope must expand, required verification cannot run, or a
  consequential external/irreversible action lacks approval. Report the smallest exact blocker.

## Total Cost of Development

Choose the cheapest acceptable capability: workflow, model/reasoning, context, tools, verification,
and review. Optimize first for owner time, rework, hidden defects, and delay; model cost is secondary.
Use the configured Codex capability rather than hard-coded provider/model IDs. Escalate for unclear
requirements, repeated failed attempts, hard-to-assess residual risk, or auth/security/data/migration/
concurrency/external-API work; de-escalate when a local deterministic test bounds the change.

Detailed capability policy and output blocks belong in the selected skill and
`docs/development/TOTAL_COST_OF_DEVELOPMENT.md`, not in this auto-loaded file.

## Agency default

Execute every applicable Builder skill transition under `.codex/skills/README.md :: Workflow continuation`; do not stop at a skill output or queued handoff. Delivery includes publication → verification-and-closure → verified merge and reconciliation until end-to-end automation is explicitly accepted. Leave an unmerged delivery PR only for documented stop-loss or an explicit user scope restriction.
Proceed with authorized work; preserve operator gates and explicit planning/review-only scope. A retry count, a failed local/CI/type check, or a safe technical pause is not an owner decision; only its explicit authority categories may create `agent:needs-human`. Route real owner asks through `owner-decision-brief`; stop-loss follows `docs/development/GOVERNANCE_PROPORTIONALITY.md :: Delivery budgets and stop-loss`.

## Parallel-agent execution

- Concurrent implementation or publication uses one dedicated branch/worktree per active change;
  never switch the shared root checkout under another agent.
- Before commit and push, run the branch/worktree gate in
  `.codex/skills/_shared/BRANCH_TRUTH_GATE.md :: Procedure`. Never mask a gate exit code.
- Claim Issue work through `issue-to-code`; one active lease per Issue. Reconcile collisions from live
  evidence instead of re-implementing.
- Use subagents only when independent bounded work lowers TCD. The owning agent retains scope,
  writes, lifecycle, and receipt authority.
- Run host-global suites through `scripts/run_with_host_lease.py`; the lease is the only coordination authority. Chat reservations and process census are advisory diagnostics; before attributing or interrupting another task's process, require cwd or parent/lease readback—command text, PID, census, or a quiet period alone is insufficient; do not busy-poll shared resources.

Cleanup, lifecycle, lease, and CI-wait mechanics live in their owning skills/shared contracts.

## Transition-period bug-delivery policy

For a larger `type:bug` set, use a minimal read-only coordinator and one isolated Issue session/
worktree per claimed bug; serial implementation is the default. Capability follows TCD, not a fixed
provider or model. P0/P1/protected findings stay in repair; confirmed deferred P2 findings route to
the rolling Known Defects registry Issue #4172; P3 is informational. `bug-to-issue`,
`deliver-issue-set`, and `verification-and-closure` own the procedure.

## Proportional delivery

- Tier 1/2 single-Issue or issue-free work uses required current-head CI plus self-verified `Verify:`
  targets. Tier 3, multi-Issue, and auth/security/data/migration/concurrency/payments/external-API work
  also uses the full independent review and verified-merge path, with mechanism/convergence review before an expensive proof cycle.
- Build the most boring solution that satisfies the contract. New ledgers, registries, abstractions,
  provider layers, or enterprise patterns require explicit demand and must replace something or have
  a review date.
- Use at most two CI-repair rounds per failure mechanism, then shrink/replan or escalate capability; does not cap the separate P0/P1 review-repair loop. Evidence-based convergence and fresh independent re-review govern it.

Exact tiers, supersession, and evidence-reuse mechanics live in
`docs/development/GOVERNANCE_PROPORTIONALITY.md` and the delivery skills.

## Change classification

Classify work as current-state correction, enabling change, or target/future-state work. Only the
first two may change current-state claims, and only when code/evidence supports the new truth.

## Communicating with the owner

Lead with the outcome, next step, and exact blocker. Keep human summaries concise; keep full audit
evidence in the durable receipt. Present genuine decisions as Problem -> Options -> Consequences.

## Specialist subagent roles

Skills remain the workflow contracts. `.codex/agents/**` are Codex execution adapters, not policy.
Use `docs/development/BUILDER_SUBAGENT_ROLES.md` for role routing and handoff receipts. Do not activate
legacy provider-specific worker paths from compatibility or provenance artifacts.

## Docs authoring lane

Issue-free docs authoring is allowed only for approved docs surfaces and must not change runtime
behavior or shipped truth. Use `docs-governance` then `docs-authoring`.

## Governance lane

Issue-free bounded changes to `AGENTS.md`, `.codex/skills/**`, governance tests/scripts/templates, and
their owner docs may use the Governance lane. Product/runtime behavior requires Issue-first delivery.

## GitHub delivery governance

- GitHub Issues are the normal implementation contract. Read the full Issue; bind work to its Scope,
  Constraints, Source Anchors, Acceptance Criteria, Out of Scope, and resolvable inline `Verify:`
  targets. Use strictly valid `agent:ready` before claim; active work becomes `In Progress`, and the claim wrapper must remove `agent:ready`.
  Pickup proceeds without requiring GitHub Project Status.
- Before creating or normalizing a governance or contract Issue, search the same artifact or symptom
  in open Issues, recently merged PRs, and closed Issues. Use GitHub CLI/REST search; do not require
  GraphQL or ProjectV2 operations.
- Each issue-backed PR has exactly one `Governing-Issue: #<id>` line. In approved multi-Issue work,
  the governing parent may remain open and closing keywords name only the fully delivered issues;
  see `docs/development/PR_HOT_PATH.md :: Multi-Issue PR Scope`.
- Verify every exact closing Issue. A distinct open parent is checked as the issue-set contract;
  unfinished feature criteria do not block delivery of verified children.
- Verification binds to the current head, mutable authority digest/version and contract/body/check configuration, and late-change supersession; rerun affected evidence. Green CI
  alone is not a merge receipt. The full path must neutralize mutable body closers, use a fixed
  non-closing message, explicitly close the authenticated issue set, reject race-added refs, include
  restoring the authenticated body, and preserve a durable receipt; see `verification-and-closure`.
- The post-merge owner-doc result is PR-specific: record it on every exact closed issue and a distinct
  open governing parent; a generic receipt or one for another PR is insufficient.
- Push, PR, merge, close, label, Project, release, or deployment effects require explicit task scope
  and their owning skill. This session does not infer authority from a chat-only implementation idea.

## Dispatcher policy

The dispatcher is an optional collision guard, not lifecycle authority. Use only
`scripts/issue_pickup_claim.sh` through `issue-to-code`; never reconstruct its claim/label handshake.
GitHub Issue state, blocked-state, and review-handoff labels remain durable truth; Project Status is optional projection.

## Builder-session closeout gate

Before a development-time builder session or builder agent returns a terminal response, hands off, goes idle, or otherwise stops, run `.codex/skills/klart/SKILL.md`. It is a read-only closeout
assessment and does not govern Product/Runtime agents. Report the outcome, verification, and any
remaining action or material risk concisely in the user's language; no fixed headings are required.
This is a Builder System instruction, not a platform-level response interceptor; a skill cannot mechanically rewrite a response that bypasses it. An unqualified end requires `destination: end` and
`secure_first: false`; otherwise execute the owning workflow, or document stop-loss/explicit user stop before a terminal handoff. `klart` never establishes Issue/PR delivery.
