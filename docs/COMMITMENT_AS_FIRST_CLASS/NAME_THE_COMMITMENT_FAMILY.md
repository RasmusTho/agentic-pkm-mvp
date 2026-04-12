---
name: Name the Commitment Family
description: Name Commitment, Project, Next Action, Waiting, and Review Cycle as a distinct semantic family in the v6.0 architecture and state what it is separate from
task_id: COMMITMENT-FIRST-CLASS-01
source_anchor: docs/plans/V60_ARCHITECTURE_TARGET.md :: Pillar 5 "Commitments remain a distinct semantic family"
parent_capability: Commitments as a first-class semantic family
prerequisites: none
depends_on: []
can_parallelize_with: [DEFINE_COMMITMENT_VS_NOTE_STATE, DEFINE_COMMITMENT_VS_EXECUTION_PLAN, DEFINE_COMMITMENT_STATE_TRANSITIONS, DEFINE_COMMITMENT_RECEIPT_REQUIREMENT]
---

State: Specification for the naming anchor of the v6.0 commitment-first-class capability. Docs-only.

# Name the Commitment Family

## Purpose

This task establishes the core naming contract for the v6.0 capability: the five commitment-oriented structures the architecture must carry as their own semantic family, separate from artifact lifecycle, generic note state, and execution-plan vocabulary. Without this anchor, later tasks have nothing stable to refer to. It exists so the user's act of externalizing "what I owe, what I'm waiting on, what's next" lands in a recognizably commitment-shaped place in the system rather than being silently converted into note metadata or planner step vocabulary.

## What This Task Does

Write a short, direct section in this file that:

1. Names the five commitment kinds the v6.0 architecture carries as a distinct semantic family:
   - `Commitment` (the umbrella — something the user experiences as requiring attention, maintenance, progress, decision, follow-up, or closure)
   - `Project` (a commitment that requires multiple steps over time)
   - `Next Action` (the next concrete step that can advance a commitment or project)
   - `Waiting` (a commitment state where progress depends on another actor, event, or future condition)
   - `Review Cycle` (a recurring re-orientation practice that restores trust in the commitment landscape)
2. States, for each, what it is NOT:
   - Not an artifact lifecycle label (`draft`, `provisional`, `reviewed`, `protected`, `archived`).
   - Not a maturity label (`raw`, `draft`, `developing`, `stable`, `evergreen`).
   - Not a planner/orchestrator execution step.
   - Not a tool-call action catalog entry.
   - Not merely a note or a tag on a note.
3. States that this naming is upstream of runtime — no storage or schema is being defined here.
4. Cross-references the concept SoT (`COMMITMENT_LAYER_CONTRACT.md`) as the underlying semantics, and `V60_ARCHITECTURE_TARGET.md` Pillar 5 / Delta 5 as the architectural placement.

## Concretely

When this task is complete, this file contains a named section "## The commitment family" that reads, in substance:

> The v6.0 architecture carries Commitment, Project, Next Action, Waiting, and Review Cycle as a distinct semantic family. These names belong to the commitment layer. They are not synonyms for `review_state`, `maturity`, `kind`, artifact lifecycle, planner `Plan`, or any execution-artifact vocabulary. A note may represent a commitment, but the note is not the commitment. A planner step may support a next action, but the planner step is not the next action.

And a second section "## What this family is separate from" that lists the non-memberships explicitly:

- Not `review_state` values.
- Not `maturity` values.
- Not `kind = "note"` or any artifact `kind`.
- Not `Plan`, `Subplan`, `Step`, or any execution-artifact language.
- Not tool-call catalogs or agent action names.
- Not folder placement, tag presence, or path family.

## Why This Matters

If the architecture does not name this family cleanly, everything downstream gets harder. The v5.6 commitment runtime slice loses its target. The user's experience collapses: they declare "I owe this" and the system silently stores a `review_state = draft` note, losing the commitment meaning. The user cannot trust that GTD-like cognitive offloading is actually happening, because there is no name for the thing being offloaded.

The cognitive-prosthetic value of the system depends on this naming being recognizable. If the user cannot point to "my commitments" as a thing the system holds distinctly, the system is not acting as a prosthetic — it is acting as a filing cabinet.

## Acceptance Criteria

- [ ] This file contains a "## The commitment family" section that names all five commitment kinds.
- [ ] This file contains a "## What this family is separate from" section that explicitly lists `review_state`, `maturity`, artifact `kind`, execution-plan vocabulary, tool-call catalogs, and path/tag/folder assumptions as NOT being commitment semantics.
- [ ] This file cites `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md` as the concept SoT and `docs/plans/V60_ARCHITECTURE_TARGET.md` §Pillar 5 / §Delta 5 as the architectural anchor.
- [ ] This file does not propose schema, tables, event names, or runtime changes.
- [ ] This file does not rewrite or redefine `COMMITMENT_LAYER_CONTRACT.md`.
- [ ] The cognitive-prosthetic framing (externalization + trust) is preserved in the Why This Matters section.

## How to Verify (Pre-Merge)

Docs-only verification:

- Read the completed file. Confirm the five kinds appear by name and each is explicitly separated from state-axis / execution-plan vocabulary.
- Grep-check: open `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md` and confirm nothing in this file contradicts the Primary Concepts section there.
- Grep-check: open `docs/plans/V60_ARCHITECTURE_TARGET.md` Pillar 5 and confirm the wording here is compatible with "commitments remain a distinct semantic family rather than generic note state".
- Confirm no files outside `docs/COMMITMENT_AS_FIRST_CLASS/` have been touched.

## The commitment family

The v6.0 architecture carries **Commitment**, **Project**, **Next Action**, **Waiting**, and **Review Cycle** as a distinct semantic family. These names belong to the commitment layer. They are not synonyms for `review_state`, `maturity`, `kind`, artifact lifecycle, planner `Plan`, or any execution-artifact vocabulary. A note may represent a commitment, but the note is not the commitment. A planner step may support a next action, but the planner step is not the next action.

- **Commitment**: something the human experiences as requiring attention, maintenance, progress, decision, follow-up, or closure. It may be active, deferred, blocked, delegated, or closed. It is not a single task, and it is not a note.
- **Project**: a commitment that requires multiple steps over time to reach a meaningful outcome. It is not an execution graph, and it is not a planner `Plan`.
- **Next Action**: the next concrete step that can advance a commitment or project. It is not a tool-call action catalog entry, and it is not a planner `Step`.
- **Waiting**: a commitment state where progress depends on another actor, event, or future condition. It is not generic inactivity, and it is not a simple defer state.
- **Review Cycle**: a recurring re-orientation practice that restores trust in the commitment landscape. It is not the same as content approval, and it is not a `review_state` value.

The naming is upstream of runtime. No storage, schema, or event design is being defined here.

## What this family is separate from

The commitment family is explicitly NOT any of the following:

- Not `review_state` values (`draft`, `provisional`, `reviewed`, `protected`, `archived`).
- Not `maturity` values (`raw`, `draft`, `developing`, `stable`, `evergreen`).
- Not artifact `kind` values or artifact lifecycle categories.
- Not `Plan`, `Subplan`, `Step`, or any execution-artifact language.
- Not tool-call catalogs or agent action names.
- Not folder placement, tag presence, path family, or any storage convention.

## Authority sources

This naming is grounded in:

- **Concept SoT**: `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md` § "Core rule" and "Primary concepts" define the semantic boundaries and problem-solving purpose of each commitment kind.
- **Architecture anchor**: `docs/plans/V60_ARCHITECTURE_TARGET.md` § Pillar 5 ("Commitments remain a distinct semantic family rather than generic note state") establishes the architectural commitment to this separation.

## Out of Scope

- Defining transitions between commitment states (see `DEFINE_COMMITMENT_STATE_TRANSITIONS.md`).
- Defining the commitment vs note-state boundary in depth (see `DEFINE_COMMITMENT_VS_NOTE_STATE.md`).
- Defining the commitment vs execution-plan boundary in depth (see `DEFINE_COMMITMENT_VS_EXECUTION_PLAN.md`).
- Defining receipts for commitment transitions (see `DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md`).
- Any runtime, schema, or storage design.
- Any change to the v5.6 commitment runtime slice.

## Related Docs

- `docs/COMMITMENT_AS_FIRST_CLASS/README.md`
- `docs/COMMITMENT_AS_FIRST_CLASS/PARENT_FEATURE_ISSUE.md`
- `docs/plans/V60_ARCHITECTURE_TARGET.md` (Pillar 5, Delta 5)
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`
- `docs/CONCEPTS/STATE_AXES_CONTRACT.md`

## Related GitHub Issues

When this task is later turned into issues, reference: "Implements COMMITMENT_AS_FIRST_CLASS/NAME_THE_COMMITMENT_FAMILY". Use the acceptance criteria above as the issue contract.
