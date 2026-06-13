State: Implemented. All five AGENT-MEMORY slices delivered. Companion-aware handling remains tracked separately if still open.
Doc role: Capability implementation index and delivery record
Authority: Navigates the delivered Agent Memory slices and their verification evidence. Semantic authority remains in `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`; current runtime posture remains in `docs/STATUS.md`.

Final slice (AGENT-MEMORY-05) delivered by PR #1242 (issue #1083, 2026-05-23). Parent feature issue
#900 closed.

# Agent Memory

## Capability Boundary

This directory governs the `agent memory` capability introduced in
`docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`. It began as the implementation-ready
breakdown and is now both a delivery record and a navigation index for the implemented slices.

The capability boundary is:

- memory candidate modeling,
- review queue behavior,
- promote/reject/revise flows,
- recall explanation surfaces,
- and authority guards that prevent unreviewed memory from becoming write authority.

## Shipped Status

All five Agent Memory implementation slices have been delivered:

1. MemoryCandidate model
2. Review queue
3. Promote / reject / revise flow
4. Explainable recall
5. Unreviewed-memory authority guard

These slices implement the bounded capability described by this directory. They do not make agent
memory a hidden source of truth and do not allow unreviewed memory to authorize writes. Delivery
evidence for each slice is recorded under [Relationship to GitHub Issues](#relationship-to-github-issues).

## Relationship to the Contract

`docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` defines what agent memory is, what it is not,
its lifecycle, and its authority limits. It remains the semantic source of truth. This directory
records how that contract was turned into the delivered slices and where their verification evidence
lives.

## Successor Capability

The storage-backend non-goal listed above was deferred, not abandoned. The successor capability
`docs/DURABLE_MEMORY_AND_RECALL/` (parent feature issue #1903, spec PR #1902) closes that gap:
it adds durable persistence of review decisions, startup queue reconciliation, governed vault
materialization of promoted memory, and guarded recall activation. Read that directory for
implementation work that extends this delivered capability.

## Remaining Follow-ups

- Companion-aware handling remains separate if still tracked by #1085 / PR #1216 or successor docs.
- Any broader runtime/product promotion must still be reflected in `docs/STATUS.md` and relevant
  owner docs.

## Non-Goals

- introducing a hidden memory source of truth,
- bypassing human-authored knowledge or write guards,
- defining a specific vector store or storage backend,
- or claiming runtime/product behavior beyond the delivered slices and their recorded evidence.

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
- [x] Review queue, promotion/rejection/revision, recall explanation, and authority guard are each
  specified as independently mergeable tasks.
  Verify: `docs/AGENT_MEMORY/*.md`
  Delivered: PRs #1196, #1215, #1240, #1242 (issues #1080–#1083)
- [x] Every task in this directory includes explicit behavioral or doc-surface `Verify:` targets.
  Verify: `rg -n "Verify:" docs/AGENT_MEMORY/*.md`
- [x] The parent feature draft defines the validation and acceptance path without claiming shipped
  memory behavior.
  Verify: `docs/AGENT_MEMORY/PARENT_FEATURE_ISSUE.md`

## Verification Path

- Task-level verification follows each task file's `How to Verify (Pre-Merge)` section.
- Contract-shape verification for this directory checks frontmatter, required sections, and inline
  `Verify:` targets.
- Each delivered slice resolved its named test targets on the head SHA of its task PR; see the
  delivery records in [Relationship to GitHub Issues](#relationship-to-github-issues).

## Validation / Acceptance Path

- This directory was accepted at the docs/spec layer once the README, parent feature issue, and all
  five task specs were merged and internally consistent.
- All five implementation slices have since been delivered against that contract.
- Broader runtime/product promotion — surfacing memory in current-state owner docs as live product
  behavior — is gated on the conditions in [Owner-Doc Promotion Trigger](#owner-doc-promotion-trigger)
  and on `docs/STATUS.md` reflecting that posture; it is not implied by slice delivery alone.

## Evidence Surface

- Local task specs in this directory define the implementation contract.
- Each delivered slice's PR provides its verification receipt (see Relationship to GitHub Issues).
- The parent feature issue #900 held validation evidence and acceptance tracking before closure.
- Owner docs such as `docs/STATUS.md` and `docs/ARCHITECTURE.md` should change to claim live product
  behavior only when the owner-doc promotion conditions are met.

## Relationship to GitHub Issues

- Parent feature: #900 (closed 2026-05-23)
- AGENT-MEMORY-01 (MemoryCandidate model): issue #1079, PR #1112 (2026-05-19)
- AGENT-MEMORY-02 (Review queue): issue #1080, PR #1196 (2026-05-21)
- AGENT-MEMORY-03 (Promote/reject/revise): issue #1081, PR #1215 (2026-05-22)
- AGENT-MEMORY-04 (Explainable recall): issue #1082, PR #1240 (2026-05-23)
- AGENT-MEMORY-05 (Authority guard): issue #1083, PR #1242 (2026-05-23)
- Artifact metadata compatibility: issue #1084, PR #1214 (2026-05-22)
- Companion-aware handling: issue #1085, PR #1216 (2026-05-22)

The local source for the parent feature issue is
[PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md).

## Owner-Doc Promotion Trigger

Promote current-state owner docs only after implementation receipts show all of the following:

- observed material enters a candidate state rather than truth by default,
- review decisions remain explicit and inspectable,
- promotion preserves provenance and correction paths,
- recall explains why memory was used,
- and unreviewed memory cannot authorize writeback or override human-authored knowledge.
