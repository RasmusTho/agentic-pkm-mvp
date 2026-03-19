State: Proposal / implementation-spec draft on top of active SoT.
Doc role: Design recommendation
Authority: Non-authoritative implementation guide for separating `review_state`, `maturity`, `promotion`, and execution-plan semantics without breaking the active baseline.

# State Axis Separation Spec

## Purpose

This document defines the first concrete implementation step implied by the ontology-alignment work:
separating review posture, maturity/standing, promotion transitions, and execution-plan language in
the active runtime.

It is not a migration by itself.
Its role is to specify:
- what should change first,
- what should remain stable for compatibility,
- and how to stage the work without breaking the v5.5 baseline.

Related documents:
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`
- `docs/plans/RUNTIME_ONTOLOGY_NORMALIZATION.md`
- `docs/CORE_CONTRACT.md`
- `docs/NOTE_KIND_POLICIES.md`
- `docs/EVENTS.md`

## Problem statement

The current runtime compresses several distinct meanings into a small number of fields and action
names:

- `review_state` currently carries:
  - mutation/review posture,
  - some lifecycle markers,
  - and promotion outcomes such as `evergreen`

- `maturity` exists in some payloads and docs, but is not the durable sink for promotion work

- `promotion` exists as:
  - panel action intent
  - event family
  - consumer path
  - frontmatter mutation

- `Plan` currently refers to execution plans, while documentation and intuition may read it as human
  project/commitment planning

Observed in active code:
- `app/services/note_update.py`
- `app/promotion/consumer.py`
- `app/orchestrator/executor.py`
- `app/agents/planner/graph.py`
- `app/agents/planner/agent.py`
- `app/settings/panel_actions.py`
- tests such as `tests/services/test_note_update_promotion.py`

## Canonical target semantics

### `review_state`

Canonical meaning:
- review posture and mutation safety

Question answered:
- what is the current review/protection posture of this artifact?

Examples:
- `draft`
- `provisional`
- `reviewed`
- `protected`
- `archived`

### `maturity`

Canonical meaning:
- development/standing of the artifact in its domain role

Question answered:
- how developed, stabilized, or enduring is this artifact?

Examples:
- `raw`
- `draft`
- `developing`
- `stable`
- `evergreen`

### `promotion`

Canonical meaning:
- transition family that may update maturity, role, placement, or related policy-visible status

Question answered:
- what transition is being requested or executed to change standing/role?

### `Execution Plan`

Canonical meaning:
- generated runtime artifact for orchestration and bounded execution

Question answered:
- what runtime steps should be executed, in what order, against which target?

## Compatibility constraints

The following must remain stable in the first implementation wave:

1. Existing notes with `review_state: evergreen` must keep working.
2. Existing `promote.intent.created` events must continue to be consumable.
3. Existing planner/orchestrator flows must remain runnable without requiring a full schema change.
4. Existing tests should be migrated incrementally, not all at once.
5. The vault remains the human-facing canonical writing surface.

## Recommended staged implementation

## Phase 1: semantic expansion without breaking names

Goal:
- preserve compatibility while creating distinct sinks for meaning

### Changes

1. Extend promotion application to write `maturity` when present.
2. Preserve legacy `review_state` writes for compatibility, but treat them as compatibility mirrors
   rather than the primary semantic sink.
3. Introduce helper functions that centralize the mapping between:
   - requested promotion outcome
   - resulting `maturity`
   - resulting `review_state` compatibility value

### Suggested helper boundary

Add a dedicated state-axis module, for example:
- `app/domain/state_axes.py`

Suggested responsibilities:
- normalize allowed `review_state` values
- normalize allowed `maturity` values
- map promotion outcomes to state-axis updates
- provide backward-compatible mirror rules

### Example compatibility rule

Requested promotion:
- `maturity = evergreen`

Phase-1 writes:
- `maturity = evergreen`
- `review_state = reviewed` or `protected` depending on the chosen policy

Compatibility option during migration:
- also preserve legacy `review_state = evergreen` only if a compatibility flag is enabled

Preferred direction:
- stop producing new `review_state = evergreen` once downstream readers are updated

## Phase 2: planner/orchestrator action normalization

Goal:
- stop treating review mutation and promotion mutation as the same primitive action

### Current problem

Active code currently converges these:
- `update_review_state`
- `set_review_state`
- `promote_to_evergreen`

### Changes

Introduce distinct primitive action names:
- `set_review_state`
- `set_maturity`
- `request_promotion_transition`

Meaning:
- `set_review_state` updates review posture only
- `set_maturity` updates maturity only
- `request_promotion_transition` emits a promotion transition intent rather than mutating fields directly

### PlannerGraph migration rule

In `app/agents/planner/graph.py`:
- keep existing action names working,
- but route them through a normalization layer,
- and stop implementing `promote_to_evergreen` as a disguised `update_review_state`

## Phase 3: promotion event payload normalization

Goal:
- make promotion events carry explicit transition semantics

### Current problem

`promote.intent.created` currently carries:
- note reference
- action reference
- optional `maturity`

This is workable but underspecified.

### Recommended normalized payload

```json
{
  "note": {"uuid": "...", "path": "..."},
  "action": {"id": "promote.evergreen", "label": "Promote to evergreen"},
  "transition": {
    "family": "promotion",
    "target_maturity": "evergreen"
  },
  "instruction": "..."
}
```

Compatibility:
- keep accepting legacy top-level `maturity`
- internally normalize into `transition.target_maturity`

### Consumer rule

`app/promotion/consumer.py` should:
- normalize legacy payloads into the new internal transition shape
- write `maturity` as the primary semantic sink
- write compatibility `review_state` only via explicit mapping rules

## Phase 4: test migration

Goal:
- make tests enforce the new semantics

### Tests to update first

- `tests/services/test_note_update_promotion.py`
- planner/runtime tests that currently assert `review_state == evergreen`
- panel runtime tests that emit promotion intents

### New expected assertions

Instead of only:
- `frontmatter["review_state"] == "evergreen"`

Prefer:
- `frontmatter["maturity"] == "evergreen"`
- `frontmatter["review_state"] == "<review posture>"`

Short transition period:
- tests may allow either the legacy mirror or the normalized pair while migration is in progress

## Source-of-truth decisions required

These decisions must be made before code changes go too far:

1. What are the canonical allowed values for `review_state`?
2. What are the canonical allowed values for `maturity`?
3. Should `review_state = evergreen` remain accepted indefinitely, or only during migration?
4. What review posture should promotion to `evergreen` imply:
   - `reviewed`
   - `protected`
   - something else
5. Should `promote.intent.created` stay as the external event name during the first migration wave?

## Recommended answers

These are my current recommended answers based on the runtime and docs work:

1. `review_state` should be normalized around review posture:
   - `draft`
   - `provisional`
   - `reviewed`
   - `protected`
   - `archived`

2. `maturity` should be normalized around standing:
   - `raw`
   - `draft`
   - `developing`
   - `stable`
   - `evergreen`

3. `review_state = evergreen` should be treated as legacy-compatible, not preferred.

4. Promotion to `evergreen` should imply:
   - `maturity = evergreen`
   - `review_state = reviewed` or `protected`

5. `promote.intent.created` should remain the external event name in the first migration wave, with
   a richer payload and clearer internal normalization.

## Concrete change list

### Wave 1

- Add state-axis normalization helper(s)
- Update promotion apply path to write `maturity`
- Keep compatibility writes for legacy `review_state`
- Update tests to expect `maturity`
- Add explicit comments/docs in affected runtime modules

### Wave 2

- Normalize planner primitive action names
- Normalize promotion payload internals
- Reduce direct reliance on `review_state = evergreen`

### Wave 3

- Consider event-family cleanup (`promotion.*` vs `promote.*`)
- Consider stronger schema/runtime separation for execution plans vs human commitments

## Files likely affected when implementation starts

- `app/services/note_update.py`
- `app/promotion/consumer.py`
- `app/orchestrator/executor.py`
- `app/agents/planner/graph.py`
- `app/agents/planner/agent.py`
- `app/settings/panel_actions.py`
- `tests/services/test_note_update_promotion.py`
- planner/panel runtime tests

## Non-goals

This spec does not propose:
- a full schema migration now,
- immediate renaming of all event families,
- replacing the planner architecture,
- or eliminating all legacy compatibility paths in one step.

## Compact implementation direction

1. Make `maturity` the primary sink for standing.
2. Keep `review_state` for review/mutation posture.
3. Treat promotion as a transition request/execution path, not a field value.
4. Treat current `Plan` as execution-plan language.
5. Migrate tests and runtime in compatibility-preserving waves.
