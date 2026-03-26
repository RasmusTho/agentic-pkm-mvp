State: Enabling change plan for v5.x (additive sphere/context seam; not target-state completion).
Doc role: Current implementation-prep note for the first bounded sphere/context enablement wave.
Authority: Describes the additive seam now landed in the current runtime and the explicit limits that keep it below the v6.0 target state.

# Sphere / Context Enablement Prep

## Purpose

This document records the first bounded enablement wave for broader sphere/context representation in
the current v5.x runtime.

This note started as the bounded prep step after state-axis cleanup and now records the first
enablement wave that actually landed.

It exists to answer two narrow questions:
- what is the smallest additive relation/context seam the repo can introduce now,
- and what exactly did this first landed wave change without pretending that `v6.0` is already here.

Read this together with:
- `docs/ARCHITECTURE.md`
- `docs/STATUS.md`
- `docs/PROJECT_KERNEL.md`
- `docs/plans/V60_ARCHITECTURE_TARGET.md`
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md`

## Current posture after state-axis cleanup

The active runtime now has a bounded state-axis posture:
- `maturity` is the canonical standing sink
- `review_state` is the canonical review/mutation posture field
- legacy workflow/status values remain compatibility-only inputs rather than preferred runtime outputs

That means the next meaningful semantic flattening lives more in context modeling than in
artifact-state modeling.

## What is enabled in this wave

- The canonical `RelationIndex` store boundary now supports optional relation memberships in
  addition to directed UUID-to-UUID relations.
- The first intended use is `sphere_membership`.
- A membership record carries:
  - artifact identity (`uuid` / `src_id`)
  - relation kind (`rel`, for example `sphere_membership`)
  - membership value (sphere/context identifier)
  - optional payload metadata
- Multiple memberships for the same artifact are allowed.
- No caller is forced to provide memberships.
- Empty or absent membership data is treated as normal.

## Semantic posture

- `sphere_membership` means broader belonging / participation metadata.
- It is not a permission object.
- It does not replace operational scope.
- It does not replace explicit cross-scope allowance / `bridge` semantics.
- It does not imply that retrieval should cross operational scope boundaries by default.

## What was intentionally not changed

- `ASK_DOMAIN_SCOPE` remains the active conservative retrieval boundary.
- `bridge_domains` remains the compatibility inclusion mechanism for current retrieval.
- Retrieval ranking/filtering is not relation-driven by default.
- Object-store contracts were not made to require sphere/context membership.
- No commitment runtime, schema family, or broader v6.0 context object model was introduced.
- No graph-database-specific architecture was introduced.
- Filesystem/path semantics were not changed.

## Why this seam is safe

- It extends the existing relation-store boundary rather than inventing a parallel subsystem.
- It keeps broader belonging metadata separate from directed semantic relations and from
  operational-scope policy.
- Existing callers that only use `link`, `neighbors`, and `has_any` continue to behave as before.
- Existing retrieval paths do not consult the new seam unless a later wave explicitly integrates it.

## Next likely waves

- Bounded read exposure in selected status/debug/API surfaces where useful.
- Relation-aware retrieval experiments that combine operational scope with broader memberships
  without replacing conservative defaults.
- Later refactors that separate operational scope, broader belonging, and explicit allowances more
  cleanly across retrieval and policy surfaces.
- Commitment/runtime separation work in a later, separate track.

## Non-goals for this wave

- Full relation-first context runtime
- Scope replacement
- Permission or policy semantics inside membership records
- Commitment modeling
- Retrieval redesign
- Final v6.0 vocabulary migration across the whole codebase
