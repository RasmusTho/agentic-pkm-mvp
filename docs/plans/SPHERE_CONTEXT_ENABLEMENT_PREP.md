State: Proposal / enabling-step prep on top of active SoT.
Doc role: Design recommendation
Authority: Non-authoritative preparation note for the next additive runtime step after state-axis cleanup; current runtime truth remains in `docs/ARCHITECTURE.md` and `docs/STATUS.md`.

# Sphere / Context Enablement Prep

## Purpose

This note defines the next bounded enabling step after state-axis cleanup is complete for active runtime surfaces.

It does **not** redesign the current runtime around the full `v6.0` target architecture.
It exists to answer a narrower question:

- what is the smallest additive relation/context seam the repo can introduce now,
- so the future move from flattened scope assumptions toward relation-first context does not start from zero.

This note should be read together with:
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

That means the next meaningful semantic flattening now lives more in context modeling than in artifact-state modeling.

The main current limitation is:
- operational scope still carries too much of the effective context boundary for runtime filtering and interpretation,
- while broader belonging, overlap, and shared participation remain mostly implicit or concept-only.

## Goal of this enabling step

Introduce the smallest additive runtime/store concept that lets the system say:
- an artifact can belong to more than one broader sphere or context,
- without replacing current operational-scope filtering,
- and without forcing a full retrieval redesign yet.

This step should:
- prepare the path toward relation-first context,
- remain backward-compatible,
- and avoid pretending that `v6.0` context layering is already implemented.

## Non-goals

This step must NOT:
- replace the current operational scope field or scope filters
- redesign ASK retrieval around relation-aware ranking yet
- add commitment tables/runtime
- rename large parts of the architecture into final `v6.0` vocabulary
- force filesystem/path changes
- require a full graph-database migration

## Proposed minimal seam

### 1. Add a bounded relation type for broader belonging

Introduce an additive relation concept equivalent to `sphere_membership`.

Minimal meaning:
- an artifact may participate in one or more broader spheres / contexts,
- while still having one current operational scope for active runtime filtering.

This should be read as:
- broader belonging / participation metadata,
- not as a replacement for current runtime scope,
- and not as a permission object by itself.

### 2. Keep operational scope as the active runtime boundary

During this enabling wave:
- operational scope remains the conservative default runtime boundary,
- retrieval does not become relation-driven by default,
- relation-bearing context remains additive metadata that future runtime steps may use.

### 3. Keep the first write/read path narrow

The first implementation step should likely do only this:
- allow storing and reading the additive relation/context metadata,
- expose it in a bounded runtime/store/API seam,
- but not yet make it a strong ranking or policy driver.

Good first outcomes:
- tests can prove the runtime can represent multi-sphere participation,
- docs can stop speaking as if one scope field is the whole context model,
- later retrieval work can consume the seam when ready.

## Suggested implementation shape

The exact table/store design can remain open, but the first wave should favor the smallest additive shape that fits current boundaries.

Possible low-risk implementation directions:
- add a relation-store entry / relation type such as `sphere_membership`
- or add a narrowly typed context-membership projection that is still stored through existing relation/store boundaries

Constraints:
- no direct DB shortcuts outside store boundaries
- no hidden semantic authority in filesystem path
- no replacement of current `ASK_DOMAIN_SCOPE` / operational-scope filtering during this wave

## Acceptance criteria for the prep-to-implementation handoff

Before implementation starts, the repo should have agreement on these points:

1. `sphere/context membership` is additive, not replacing operational scope in the first wave.
2. It represents broader belonging / participation, not permission by itself.
3. It can be empty with no runtime breakage.
4. Current retrieval defaults remain conservative.
5. New docs must describe this as enablement, not as the full `v6.0` target state.

## Recommended next implementation wave

The next bounded implementation wave should likely be:

### Wave A — store and contract seam only
- define the minimal relation/context membership shape
- store it through current store/relation boundaries
- add tests proving multi-membership can exist without changing current scope behavior
- update docs accordingly

### Wave B — bounded read/exposure use
- expose relation-bearing context in selected APIs or internal projections
- keep retrieval behavior conservative unless explicitly enabled

### Later waves
- relation-aware retrieval
- operational-scope refactoring
- richer context overlap / shared participation reasoning
- commitment/runtime separation work

## Exit condition

This prep note has served its purpose when:
- the repo can implement a small additive relation/context seam,
- without reopening state-axis work,
- and without pretending that the full `v6.0` architecture already exists.
