State: Partial implementation. AGENT-MEMORY-01 (MemoryCandidate model) delivered by PR #1112
(issue #1079, 2026-05-19). Tasks 2–5 remain spec-only; no runtime behavior for those slices yet.

# Agent Memory

## Capability Boundary

This specification directory defines the implementation-ready breakdown for the `agent memory`
capability introduced in `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`.

The capability boundary is:

- memory candidate modeling,
- review queue behavior,
- promote/reject/revise flows,
- recall explanation surfaces,
- and authority guards that prevent unreviewed memory from becoming write authority.

This directory is downstream of the concept contract and upstream of any runtime implementation. It
prepares bounded implementation work; it does not claim that the runtime already has these memory
surfaces.

## Relationship to the Contract

`docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` defines what agent memory is, what it is not,
its lifecycle, and its authority limits. This directory turns that contract into bounded
implementation tasks suitable for later issue filing.

The concept contract remains the semantic source of truth. These task specs are the implementation
planning surface for it.

## Non-Goals

- shipping durable agent memory in this PR,
- introducing a hidden memory source of truth,
- bypassing human-authored knowledge or write guards,
- defining a specific vector store or storage backend,
- or claiming that recall, promotion, or review flows are already shipped.

## Task List

1. [DEFINE_MEMORY_CANDIDATE_MODEL.md](DEFINE_MEMORY_CANDIDATE_MODEL.md)
2. [ADD_MEMORY_CANDIDATE_REVIEW_QUEUE.md](ADD_MEMORY_CANDIDATE_REVIEW_QUEUE.md)
3. [PROMOTE_REJECT_AND_REVISE_MEMORY.md](PROMOTE_REJECT_AND_REVISE_MEMORY.md)
4. [EXPLAIN_MEMORY_RECALL.md](EXPLAIN_MEMORY_RECALL.md)
5. [PREVENT_UNREVIEWED_MEMORY_AUTHORITY.md](PREVENT_UNREVIEWED_MEMORY_AUTHORITY.md)

## Flat Execution Order

1. `DEFINE_MEMORY_CANDIDATE_MODEL.md`
2. `ADD_MEMORY_CANDIDATE_REVIEW_QUEUE.md`
3. `PROMOTE_REJECT_AND_REVISE_MEMORY.md`
4. `EXPLAIN_MEMORY_RECALL.md`
5. `PREVENT_UNREVIEWED_MEMORY_AUTHORITY.md`

## Capability-Level Acceptance Criteria

- [x] The repository contains a bounded memory-candidate model task that preserves provenance and
  review state.
  Verify: `docs/AGENT_MEMORY/DEFINE_MEMORY_CANDIDATE_MODEL.md`
  Delivered: `app/agent_memory/candidate.py` (PR #1112, issue #1079)
- [ ] Review queue, promotion/rejection/revision, recall explanation, and authority guard are each
  specified as independently mergeable tasks.
  Verify: `docs/AGENT_MEMORY/*.md`
- [ ] Every task in this directory includes explicit behavioral or doc-surface `Verify:` targets.
  Verify: `rg -n "Verify:" docs/AGENT_MEMORY/*.md`
- [ ] The parent feature draft defines the validation and acceptance path without claiming shipped
  memory behavior.
  Verify: `docs/AGENT_MEMORY/PARENT_FEATURE_ISSUE.md`

## Verification Path

- Task-level verification follows each task file's `How to Verify (Pre-Merge)` section.
- Contract-shape verification for this directory checks frontmatter, required sections, and inline
  `Verify:` targets.
- PR-level verification for future implementation work must resolve the named test targets on the
  head SHA of each task PR.

## Validation / Acceptance Path

- This directory is accepted at the docs/spec layer when the README, parent feature draft, and all
  five task specs are merged and internally consistent.
- Runtime acceptance remains future work and should be tracked on a future parent feature issue plus
  child implementation issues.
- Owner-doc promotion is gated on implementation evidence that the runtime treats memory as
  inspectable, reviewable, and non-authoritative by default.

## Evidence Surface

- Local task specs in this directory define the implementation contract.
- Future child PRs provide slice verification receipts.
- The parent feature issue, once filed, should hold validation evidence and acceptance tracking.
- Owner docs such as `docs/STATUS.md` and `docs/ARCHITECTURE.md` should change only when runtime
  support is actually delivered.

## Relationship to GitHub Issues

- Parent feature: #900
- AGENT-MEMORY-01 (MemoryCandidate model): implemented by issue #1079, PR #1112 (2026-05-19)
- AGENT-MEMORY-02 through 05: filed as issues #1080–#1085; awaiting execution

The local source for the parent feature issue is
[PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md).

## Owner-Doc Promotion Trigger

Promote current-state owner docs only after implementation receipts show all of the following:

- observed material enters a candidate state rather than truth by default,
- review decisions remain explicit and inspectable,
- promotion preserves provenance and correction paths,
- recall explains why memory was used,
- and unreviewed memory cannot authorize writeback or override human-authored knowledge.
