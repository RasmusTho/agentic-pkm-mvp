State: Working scenario and acceptance scaffold derived from human flows, user needs, and user stories.
Doc role: Plan
Authority: Scenario-level planning and validation surface for checking whether proposed product work actually serves the intended human needs; subordinate to the concept contracts and human-function docs.

# Scenario Acceptance Matrix

## Purpose

This document turns the human-function documents into scenario-level planning material.

Its purpose is to help answer:
- what real user situation is being supported,
- which user need is at stake,
- what the system must help the user accomplish,
- what successful support would look like,
- and what must not be broken in the process.

This document is not a runtime design spec.
It is a planning and validation surface for keeping product and ontology work grounded in lived use.

## Upstream reading order

Read in this order before treating any scenario here as decision input:
1. `docs/HUMAN-FLOWS.md`
2. `docs/CONCEPTS/USER_NEEDS_MODEL.md`
3. `docs/plans/USER_STORIES_AND_REQUIREMENTS.md`
4. this document

## How to use this document

Use this document when:
- prioritizing feature work,
- checking whether a proposed change supports a real user situation,
- writing acceptance criteria for an increment,
- reviewing whether ontology distinctions preserve actual user value,
- or evaluating whether a runtime behavior is good enough from the user perspective.

Do not use this document to:
- define storage structures,
- define event payloads,
- decide implementation layering directly,
- or substitute synthetic benchmark success for user usefulness.

## Matrix fields

Each scenario below includes:
- scenario,
- user need,
- user outcome,
- system function,
- acceptance signals,
- failure modes to avoid,
- and ontology consequences.

## 1. Capture a fleeting thought before it disappears

### Scenario

The user has a thought, obligation, fragment, or connection while switching contexts and needs to get it out of working memory immediately.

### User need

Not losing what matters.
Being able to think outside the head.

### User outcome

The user can capture the material quickly without having to decide too much up front, and can trust that it will be recoverable later.

### System function

The system should support low-friction capture with minimal upfront classification, while preserving enough continuity that later clarification is possible.

### Acceptance signals

- the user can capture incomplete material without abandoning it,
- captured material remains findable later,
- the capture flow does not force false precision too early,
- and the user does not need to hold the item in memory after capture.

### Failure modes to avoid

- forcing premature typing or classification,
- losing provenance or context for captured sources,
- making quick capture so heavy that the user postpones it,
- or treating all capture as either stable knowledge or task input.

### Ontology consequences

- early capture must allow ambiguous standing,
- fragments, sources, and open loops must remain distinct possibilities,
- and later clarification must be part of the model rather than a workaround.

## 2. Return after interruption and recover orientation

### Scenario

The user returns after hours, days, or weeks and needs to understand what was underway, what matters now, and how to resume without reconstructing everything from scratch.

### User need

Recovering orientation.
Managing commitments without mental overload.

### User outcome

The user can resume work with low restart cost and can distinguish between active work, stalled work, and background context.

### System function

The system should help the user re-orient to current commitments, relevant artifacts, and recent context in a way that restores momentum.

### Acceptance signals

- the user can see what they were doing and why it mattered,
- active and waiting commitments are distinguishable,
- recent context is intelligible without deep digging,
- and restart cost is noticeably reduced.

### Failure modes to avoid

- retrieval that returns fragments without usable orientation,
- flattening all relevant material into an undifferentiated list,
- confusing execution traces with human commitments,
- or requiring the user to reverse-engineer prior context manually.

### Ontology consequences

- commitments and execution artifacts must remain distinct,
- retrieval projections must preserve interpretability,
- and review/posture signals must not replace orientation signals.

## 2A. Work with archive material without forcing it into notes

### Scenario

The user knows a useful PDF, email, media item, or project file exists in the archive and needs to
find, inspect, cite, or reuse it without first rewriting it into a warm note.

### User need

Not losing what matters.
Being able to think outside the head.

### User outcome

The user can use archive material as a legitimate source surface while preserving provenance and
without collapsing the archive into the note space.

### System function

The system should support archive retrieval, preview, citation, and controlled reuse as first-class
functions.

### Acceptance signals

- archive material can be found and inspected without forced note conversion,
- provenance remains visible,
- the user can reuse or cite archive material in later work,
- and archive use does not require flattening everything into the warm writing surface.

### Failure modes to avoid

- treating archive material as a dumping ground rather than a usable brain,
- forcing unnecessary materialization into notes,
- losing provenance during archive-to-work transitions,
- or making archived sources effectively invisible unless manually rewritten.

### Ontology consequences

- cold/archive artifacts remain first-class,
- source artifacts may remain source artifacts without becoming notes,
- and archive exposure belongs to product function, not only implementation detail.

## 3. Move from source material to durable understanding

### Scenario

The user reads, studies, or researches something difficult and needs to turn source material into understanding that can be revisited, revised, and reused later.

### User need

Learning in a way that compounds.
Being able to think outside the head.

### User outcome

The user can connect sources to evolving understanding, retain what was learned, and return later without starting over from zero.

### System function

The system should support source-grounded interpretation, concept development, revisiting confusion, and gradual stabilization of knowledge.

### Acceptance signals

- the user can keep sources linked to interpretations,
- partial understanding remains representable,
- durable notes can emerge gradually rather than all at once,
- and the user can revisit what they did not fully understand.

### Failure modes to avoid

- separating understanding from source provenance,
- turning uncertain interpretations into settled truth too early,
- losing the path from reading to concept formation,
- or assuming that storage alone equals learning.

### Ontology consequences

- source artifacts, reflective artifacts, and durable knowledge artifacts must remain distinct,
- `maturity` and `review_state` must remain separable,
- and promotion must remain a transition rather than a substitute for understanding.

## 4. Keep commitments trustworthy over time

### Scenario

The user has multiple projects, open loops, blocked items, and next actions and needs the system to reduce stress without reducing all meaningful work to generic task lists.

### User need

Managing commitments without mental overload.
Preserving authorship and control.

### User outcome

The user can trust that obligations are represented clearly enough to review, renegotiate, act on, or defer without carrying them all mentally.

### System function

The system should help clarify commitments, preserve actionability, keep waiting states visible, and support review as a trust-restoring practice.

### Acceptance signals

- projects and next actions are distinguishable,
- waiting states do not disappear,
- review cycles restore confidence in the commitment landscape,
- and the user can renegotiate or defer explicitly.

### Failure modes to avoid

- collapsing projects, concerns, and actions into one undifferentiated type,
- silently rewriting user commitments,
- replacing human commitments with planner-internal execution structures,
- or forcing all open loops into immediate action format.

### Ontology consequences

- project, commitment, next action, waiting, and review cycle must remain first-class,
- execution plan must remain downstream and non-substitutive,
- and accountability around commitment changes matters.

## 5. Develop a creative fragment without premature closure

### Scenario

The user has a fragment, motif, scene, outline, design idea, or speculative concept that is valuable precisely because it is not yet finished.

### User need

Creating without premature closure.
Not losing what matters.

### User outcome

The user can preserve and revisit fragile creative material without forcing it into finished-note or task form before it is ready.

### System function

The system should support gradual creative development, recombination, and return to unfinished material while protecting exploratory ambiguity.

### Acceptance signals

- fragments can be saved without over-structuring,
- exploratory material remains easy to revisit,
- the system supports development over time rather than one-shot capture only,
- and creative material is not automatically treated as settled knowledge.

### Failure modes to avoid

- flattening creative work into task or evergreen knowledge structures,
- over-optimizing for cleanliness at the expense of emergence,
- losing half-formed relationships between ideas,
- or making creative material invisible because it is not fully formalized.

### Ontology consequences

- creative artifacts must remain first-class,
- artifact development must not be reduced to knowledge maturation alone,
- and exploratory standing must remain legitimate.

## 6. Maintain a hobby or RPG world across time

### Scenario

The user maintains a campaign, setting, lore base, character web, or scenario collection that evolves across sessions and mixes settled material with speculative ideas.

### User need

Supporting hobby and world-based work.
Recovering orientation.

### User outcome

The user can move between inspiration, preparation, reference, and active material without losing continuity or confusing settled world facts with exploratory content.

### System function

The system should support long-running world continuity while preserving the difference between canonical, provisional, and exploratory material.

### Acceptance signals

- lore and preparation remain navigable together,
- settled and exploratory content are distinguishable,
- session or scenario preparation can reuse existing world material,
- and the user can return after time away without losing the thread.

### Failure modes to avoid

- assuming hobby material is less important than work material,
- collapsing world-building into generic notes,
- losing continuity between inspiration and playable/reference material,
- or forcing all material into factual-note semantics.

### Ontology consequences

- hobby/RPG structures must be treated as first-class legitimate use,
- creative, reference, and project-like materials must coexist without collapsing,
- and domain sensitivity matters.

## 7. Understand what the system did and whether to trust it

### Scenario

The system makes a suggestion, changes a surface, or produces a result, and the user needs to know what happened, what it means, and whether it should be accepted.

### User need

Being able to trust system action.
Preserving authorship and control.

### User outcome

The user can inspect system action, distinguish suggestion from accepted change, and correct or reject results without fear of hidden damage.

### System function

The system should make assistance legible, bounded, and reviewable, especially when it affects meaning, commitments, or durable artifacts.

### Acceptance signals

- the user can tell what the system did,
- the user can tell why it acted or suggested something,
- uncertain outputs default toward visibility and reversibility,
- and authorship boundaries remain intelligible.

### Failure modes to avoid

- silent meaning-changing writes,
- hiding uncertainty behind confident presentation,
- conflating machine action with human decision,
- or making receipts so weak that correction becomes guesswork.

### Ontology consequences

- receipt remains first-class,
- authority boundaries and delegation remain first-class,
- and mirror and receipt must remain distinguishable.

## 8. Use the system across multiple domains without losing meaning

### Scenario

The user moves between work, private life, learning, creativity, and hobby domains and needs continuity without flattening them into one generic workflow.

### User need

Supporting multiple work modes.
Preserving authorship and control.

### User outcome

The user can use one environment across domains while preserving meaningful differences in pace, responsibility, sensitivity, and structure.

### System function

The system should support cross-domain continuity while protecting domain-sensitive distinctions and expectations.

### Acceptance signals

- the user can keep different domains legible without running separate systems,
- recurring overlap can be supported intentionally,
- commitments do not erase creative material,
- creative material does not erase commitments,
- and domain boundaries remain understandable when needed.

### Failure modes to avoid

- forcing one ontology path to dominate all domains,
- treating all important material as either task or knowledge,
- destroying privacy or contextual meaning through over-merging,
- making legitimate overlap so awkward that the user avoids it,
- or confusing one domain's review rhythm with another's.

### Ontology consequences

- multiple artifact and commitment forms must coexist,
- domain-sensitive interpretation matters,
- and the ontology must preserve plural modes of use rather than a single canonical workflow.

## 9. Evolve the system without getting trapped by early decisions

### Scenario

The user's practice changes over time and they want to improve memory support, retrieval behavior, or other major capabilities without abandoning prior artifacts or redesigning the whole system.

### User need

Being able to evolve the system over time.
Keeping major capabilities modular rather than locked to one solution.

### User outcome

The user can keep developing the system as needs become clearer, while preserving continuity of use and meaning.

### System function

The system should allow important capability areas to change or mature without breaking the user's trust, artifacts, or working practices.

### Acceptance signals

- earlier artifacts remain usable after capability changes,
- major capability areas can improve without forcing total migration of meaning,
- transitional states remain usable,
- and the user does not feel trapped by an early design bet.

### Failure modes to avoid

- locking human functions to one current technical mechanism,
- forcing unnecessary rewrites when one subsystem changes,
- making the system brittle during transition periods,
- or treating module boundaries as if they were the human domain itself.

### Ontology consequences

- human needs remain primary over current module layout,
- artifacts remain more stable than supporting mechanisms,
- and implementation modularity must remain downstream of user value.

## 10. Work across devices while keeping local artifacts primary

### Scenario

The user works across home, work, travel, or satellite devices and needs continuity even when different devices have different capabilities or temporarily different state.

### User need

Being able to access the system across devices without abandoning local-first principles.

### User outcome

The user can keep using the system across contexts without requiring every device to be identical or continuously synchronized.

### System function

The system should preserve local artifact ownership and intelligibility while supporting delayed synchronization, partial roles, and satellite-like use.

### Acceptance signals

- the user can work meaningfully on more than one device,
- local files remain a trusted primary surface,
- eventual synchronization is acceptable when immediate sameness is not available,
- and device differences remain understandable rather than surprising.

Core continuity functions remain available on narrower devices.

### Failure modes to avoid

- requiring perfect real-time sameness to make the system usable,
- undermining trust in local artifacts,
- assuming every device must support every capability equally,
- or making cross-device use so fragile that the user avoids it.

### Ontology consequences

- local artifacts remain primary,
- continuity across devices matters more than strict uniformity,
- and satellite-like participation is a legitimate mode rather than an edge case.

## 11. Preserve contextual integrity while allowing real overlap

### Scenario

The user moves between work and other life contexts, such as private or RPG, and needs both
separation and repeated overlap without feeling that one context contaminates another.

### User need

Preserving contextual integrity across role identities and domains.

### User outcome

The user can switch contexts without losing the tone, responsibility structure, or cognitive posture of each one, while still reusing genuinely shared material.

### System function

The system should make separation the default where needed, preserve shared participation where it is real, and make repeated cross-scope reuse available through bounded, intelligible allowances when durable runtime permission is needed.

### Acceptance signals

- different contexts remain distinct enough to support different role identities,
- repeated overlap can be configured or expressed intentionally,
- shared material remains understandable as shared rather than leaked,
- and the user does not feel that one context or sphere is "smearing" over another.

### Failure modes to avoid

- treating all cross-domain reuse as suspicious edge cases,
- allowing accidental bleed-through between contexts,
- collapsing spheres or contexts into one mixed pool,
- or making persistent cross-scope allowances too opaque to trust.

### Ontology consequences

- spheres and contexts describe human distinctions more faithfully than one flat domain model,
- shared participation is the primary overlap relation,
- operational scope and explicit cross-scope allowance remain the narrower runtime/boundary layer,
- and contextual integrity matters alongside exposure control.

## 12. Keep central artifacts understandable if the system changes or dies

### Scenario

The user revisits central material years later, or after a major system change, and needs the artifacts themselves to remain meaningful without depending on the current implementation.

### User need

Ensuring central artifacts outlive the current system.

### User outcome

The user can still read, understand, and use core artifacts even if metadata, indices, or support layers have changed or disappeared.

### System function

The system should preserve primary artifacts as directly intelligible long-lived surfaces while treating richer metadata and system structures as supportive rather than mandatory.

### Acceptance signals

- central artifacts remain readable and understandable on their own,
- loss or replacement of one support layer does not destroy basic meaning,
- the user can distinguish core artifact meaning from derived machine structure,
- and long-term continuity does not depend on one runtime surviving forever.

### Failure modes to avoid

- hiding essential meaning only in system metadata,
- making core artifacts dependent on one stack's internal representations,
- treating portability as mere file survivability instead of intelligibility,
- or letting derived structures quietly become the true source of meaning.

### Ontology consequences

- primary human artifacts remain ontologically prior to support structures,
- mirrors, indexes, and metadata remain derivative,
- and artifact longevity is a first-class product concern rather than a storage accident.

## Next use

This document should next be used to produce one or more of:
- prioritized acceptance criteria for upcoming increments,
- requirement groups tied to concrete scenarios,
- ontology coverage review against real user situations,
- or implementation-track work items that can show which scenario they improve.
