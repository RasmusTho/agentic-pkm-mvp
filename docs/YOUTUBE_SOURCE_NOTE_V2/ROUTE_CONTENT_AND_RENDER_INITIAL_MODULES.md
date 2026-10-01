---
name: Route content and render initial modules
description: Classify source content conservatively and compose the initial evidence-bearing modules.
task_id: YSNV2-07
source_anchor: docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Task graph
parent_capability: YouTube Source Note v2
prerequisites: [YSNV2-03, YSNV2-05]
depends_on: [COMPOSE_REVIEW_REQUIRED_PROPOSAL_NOTE.md, PRODUCE_EVIDENCE_ANCHORED_SYNTHESIS_AND_CLAIMS.md]
can_parallelize_with: []
---

# Route Content and Render Initial Modules

## Purpose

Make content-sensitive rendering useful without allowing uncertain classification to invent a false profile or a competing note structure.

## What This Task Does

Adds a conservative multi-label router and the initial `decision_framework` and `documentary_science` module definitions. Routing is an extractor input, not a replacement renderer; uncertain or failed routing falls back to the generic spine.

## Concretely

The router admits at most two profiles only with anchored/inspectable evidence. A module adds bounded sections under the proposals wrapper and can never displace the universal spine. Failure produces a generic, visibly degraded note rather than a dead-lettered candidate.

## Why This Matters

Different source forms need different evidence views, but a wrong confident profile is more misleading than a plain generic note.

## Acceptance Criteria

- [ ] Routing returns at most two ranked profiles with evidence and uses the generic spine when confidence is insufficient or routing fails.
  Verify: `tests/knowledge_acquisition/test_content_router.py::test_router_is_bounded_and_falls_back_to_generic_on_uncertainty_or_failure`.
- [ ] Initial modules render only their evidence-bearing sections beneath the shared proposals wrapper and omit absent sections.
  Verify: `tests/knowledge_acquisition/test_note_modules.py::test_initial_modules_compose_under_shared_proposal_wrapper`.
- [ ] A module failure cannot erase synthesis/claims that already satisfied required-evidence materialization rules.
  Verify: `tests/knowledge_acquisition/test_note_modules.py::test_optional_module_failure_preserves_required_evidence_note`.
- [ ] System-generated module prose follows D6: English unless the source is Swedish-original, with source wording and quotations left in the original language.
  Verify: `tests/knowledge_acquisition/test_note_modules.py::test_module_prose_follows_source_language_policy`.

## How to Verify (Pre-Merge)

- Run the four named focused tests with generic, decision-framework, documentary-science, router-failure, and language-policy fixtures.

## Out of Scope

Ontology, interest overlay, moment selection, and other content profiles.

## Related Docs

- `docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Partial-failure policy introduced by v2`
- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md :: Extraction registry`

## Delivery record

Delivered implementation (#4114):

- `app/knowledge_acquisition/content_router.py` is a deterministic, model-free router over
  normalized transcript segments. A profile is admitted only when its closed English/Swedish cue
  table matches at least three distinct anchorable segments across at least two cue families and
  at least a quarter of the anchorable segments. At most two admitted profiles return, ranked by
  score, each with its anchored evidence. Insufficient evidence yields the generic spine
  (`insufficient_confidence`); any routing exception yields the generic spine with
  `routing_failed`. Routing never raises.
- `app/knowledge_acquisition/note_modules.py` defines the initial `decision_framework` and
  `documentary_science` modules. Each section maps to one cue family and renders only verbatim,
  anchored source excerpts presented as quotations in the original language; sections without
  evidence are omitted. Module titles and the lead line follow D6. An item that would fail the
  renderer's authority lint is dropped, counted in `omitted_module_items`, and reported visibly;
  any other module exception becomes a `ModuleFailure`.
- `candidate_writeback` routes and composes modules at assembly, renders module sections after
  the universal spine (synthesis, claims, evidence gaps) and any ontology proposals inside the one
  proposals wrapper, records `content_route` in frontmatter and the evidence band, and marks routing or
  module failure as `degraded` with a visible degradation section. Spine evidence is unaffected.

Ontology, interest overlay, moment selection, and other content profiles remain out of scope.

## Related GitHub Issues

Issue #4114 (`type:task`, `prio:med`) under parent #4107. SBS class: Product/Runtime.
