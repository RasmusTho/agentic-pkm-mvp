State: Delivered capability specification directory. Parent validation hub #1959 closed as completed on 2026-06-15 after child slices #1970-#1972 delivered; GitHub remains the authoritative backlog and validation record.
Doc role: Capability specification
Authority: Specifies the runtime activation of guarded memory recall. Semantic authority for memory remains in `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`; the durable-memory model/boundary remains in `docs/DURABLE_MEMORY_AND_RECALL/` and `docs/AGENT_MEMORY/`; current runtime posture remains in `docs/STATUS.md`.

# Recall Runtime Activation

## Capability Boundary

The closed `docs/DURABLE_MEMORY_AND_RECALL/` capability shipped the memory model, durable review
decisions, governed materialization, the authority guard, recall explanation, and
`app/agent_memory/recall_activation.py::activate_guarded_recall`. At that point those last pieces
had **zero production call sites** ("dormant by design, not by defect"): no path recalled promoted
memory into reasoning. This capability closed exactly that gap: `app/agents/ask/graph.py` now calls
`activate_guarded_recall` from the ASK graph, so guarded recall has a live production call site and
is no longer dormant.

Historical scope (delivered):

- a **retrieval** step that selects the *relevant* promoted memories for a query (not "all promoted
  memory"); scarcity matters — recall must be selective;
- an **ASK-graph integration** that calls `activate_guarded_recall` per selected memory (authority
  guard + recall receipt) and makes the recalled awareness available to the answer step;
- a **surfacing** treatment: when recall participates in an answer, how that is shown and attributed.

Out of scope (unchanged from the durable-memory boundary):

- any memory→mutation path — recall is read-only awareness; the authority guard stays a decision
  contract (#1942);
- archive/forget lifecycle (`docs/AGENT_MEMORY/DEFINE_MEMORY_LIFECYCLE_ARCHIVE_AND_FORGET.md`);
- non-ASK agents (PanelAgent/Planner recall is a later slice once the ASK path is proven).

## Implementation tasks

- [`RETRIEVE_RELEVANT_PROMOTED_MEMORY`](RETRIEVE_RELEVANT_PROMOTED_MEMORY.md) (RECALL_RUNTIME-01) — a reader + relevance selector over promoted memories.
- [`WIRE_RECALL_INTO_ASK`](WIRE_RECALL_INTO_ASK.md) (RECALL_RUNTIME-02) — an ASK-graph node that activates guarded recall and threads it to the answer; flips the anti-dormancy guard green.
- [`SURFACE_RECALL_IN_ANSWER`](SURFACE_RECALL_IN_ANSWER.md) (RECALL_RUNTIME-03) — how recalled memory is shown/attributed in the answer (carries an owner UX decision).

## Execution order

`RETRIEVE_RELEVANT_PROMOTED_MEMORY` → `WIRE_RECALL_INTO_ASK` → `SURFACE_RECALL_IN_ANSWER`. Slice 2
depends on slice 1; slice 3 depends on slice 2 **and** an owner decision on the surfacing treatment.

## Capability-level acceptance

- A real ASK run over a vault with promoted memory recalls the relevant memory via
  `activate_guarded_recall`, with a recall receipt, and the recall is read-only (no mutation).
- `git grep -n activate_guarded_recall app/agents` returns a runtime call site (dormancy closed).
- The recall participates in the answer in the owner-ratified surfacing treatment.

## Relationship to GitHub issues

Parent feature/validation hub: **#1959** (was the original "invoke guarded recall" issue, reshaped
here after a pre-implementation scoping finding). Each child posted a validation receipt to #1959; the
final child (`SURFACE_RECALL_IN_ANSWER`) carried the parent-closure + owner-doc promotion handoff, and
the hub closed as completed on 2026-06-15. Part of the v6.1 delivery hub #1956.
