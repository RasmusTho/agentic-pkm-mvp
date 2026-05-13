State: Local draft parent feature issue. Not yet filed on GitHub as of 2026-05-13. This file is
the local source for later filing and validation tracking.

# [Feature] Agent Memory

> **Local draft only.** Do not treat this file as a live GitHub issue until it is filed.

## Context

`docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` defines the target-state semantics of agent
memory, knowledge, review, promotion, recall, and authority limits. The contract now exists, but
the repository does not yet have an implementation-ready breakdown for how memory candidates should
be modeled, reviewed, promoted, explained, or prevented from becoming hidden authority.

This feature exists to create that breakdown without claiming shipped runtime behavior. It is a
docs-only capability-preparation slice.

## Scope

- define one specification directory at `docs/AGENT_MEMORY/`,
- break the agent-memory contract into bounded implementation tasks,
- define verification targets for candidate modeling, review queue behavior, promotion and revision,
  recall explanation, and authority guards,
- and define the parent-level validation and acceptance path for later implementation issues.

## Source Anchors

- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Core rule`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Lifecycle`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Authority rules`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Review and promotion rules`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Relation to receipts`
- `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`
- `docs/COMPANION_UI_PRODUCT_SPEC.md`

## Constraints

- Docs-only in this PR. No runtime, schema, or API implementation changes.
- Do not claim that durable memory, review queues, or promotion flows are already shipped unless
  `docs/STATUS.md` already says so.
- Preserve the distinction between human-authored knowledge, runtime state, context bundles, and
  agent memory.
- Preserve the rule that unreviewed memory must not become hidden authority.
- Keep every task independently mergeable and independently verifiable.

## Acceptance Criteria

- [ ] `docs/AGENT_MEMORY/README.md` exists and defines capability boundary, non-goals, task list,
  execution order, verification path, validation path, evidence surface, relationship to GitHub
  issues, and owner-doc promotion trigger.
  Verify: `docs/AGENT_MEMORY/README.md`
- [ ] `docs/AGENT_MEMORY/PARENT_FEATURE_ISSUE.md` exists as a local draft with the full parent
  feature issue contract shape.
  Verify: `docs/AGENT_MEMORY/PARENT_FEATURE_ISSUE.md`
- [ ] The five agent-memory implementation tasks exist with required frontmatter, required
  sections, and explicit `Verify:` targets.
  Verify: `rg -n "^task_id: AGENT-MEMORY-|^## (Purpose|What This Task Does|Concretely|Why This Matters|Acceptance Criteria|How to Verify \\(Pre-Merge\\)|Out of Scope|Related Docs|Related GitHub Issues)$|Verify:" docs/AGENT_MEMORY/*.md`
- [ ] The breakdown preserves the contract boundary that memory starts as candidate material, stays
  reviewable, and does not override human-authored knowledge by default.
  Verify: doc review of `docs/AGENT_MEMORY/README.md` and `docs/AGENT_MEMORY/PREVENT_UNREVIEWED_MEMORY_AUTHORITY.md`

## Out of Scope

- Implementing any durable memory runtime.
- Creating child GitHub implementation issues in this PR.
- Claiming current runtime support in `docs/STATUS.md` beyond docs/spec preparation.
- Defining companion UI rendering beyond the memory implementation contract.

## Suggested Validation

- `rg -n "^task_id: AGENT-MEMORY-|^source_anchor:|^parent_capability: Agent Memory" docs/AGENT_MEMORY/*.md`
- `rg -n "^## (Purpose|What This Task Does|Concretely|Why This Matters|Acceptance Criteria|How to Verify \\(Pre-Merge\\)|Out of Scope|Related Docs|Related GitHub Issues)$" docs/AGENT_MEMORY/*.md`
- `rg -n "Verify:" docs/AGENT_MEMORY/*.md`
- `rg -n "^## (Context|Scope|Source Anchors|Constraints|Acceptance Criteria|Out of Scope|Suggested Validation|Source Docs|Implementation Tasks|Verification Path|Validation / Acceptance Path)$" docs/AGENT_MEMORY/PARENT_FEATURE_ISSUE.md`

## Source Docs

- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`
- `docs/COMPANION_UI_PRODUCT_SPEC.md`
- `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `.codex/skills/feature-breakdown/SKILL.md`

## Implementation Tasks

1. `docs/AGENT_MEMORY/DEFINE_MEMORY_CANDIDATE_MODEL.md`
2. `docs/AGENT_MEMORY/ADD_MEMORY_CANDIDATE_REVIEW_QUEUE.md`
3. `docs/AGENT_MEMORY/PROMOTE_REJECT_AND_REVISE_MEMORY.md`
4. `docs/AGENT_MEMORY/EXPLAIN_MEMORY_RECALL.md`
5. `docs/AGENT_MEMORY/PREVENT_UNREVIEWED_MEMORY_AUTHORITY.md`

## Verification Path

- Each future task PR resolves the named `Verify:` targets in the task spec it implements.
- Candidate and review-queue tasks verify review posture before promotion and recall tasks are
  treated as complete.
- Parent-level verification checks that memory remains inspectable, correctable, and
  non-authoritative by default.

## Validation / Acceptance Path

- File the parent issue when the repository is ready to convert this directory into execution work.
- Create child implementation issues from the task files in dependency order.
- Keep validation evidence on the future parent issue until runtime support is accepted.
- Promote owner-doc truth only after receipts show reviewed memory flows, explainable recall, and
  authority guards in the shipped runtime.
