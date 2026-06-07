State: SoT v5.5 Reality-MVP baseline locked; v5.6 delivery line closed; v6 interaction, finding/reorienting, persistence-surface, and commitment specifications are active planning surfaces; read-only Chat cognition has a shipped scaffold, canvas co-authoring is materially implemented behind `CANVAS_ENABLED`, and hybrid Chat/Panel mutation remains future work.
Doc role: Core SoT
Authority: Canonical user-facing function contract for the system; architecture and implementation changes should remain compatible with this document unless it is updated intentionally.
Owner: Product / human-function SoT
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-07
Last verified against: docs/PROJECT_KERNEL.md, docs/ARCHITECTURE.md, docs/STATUS.md, docs/OPERATIONS.md, docs/SECURITY_ARCHITECTURE.md, docs/SECURITY_TRUST_BOUNDARIES.md, docs/SECURITY_DATA_FLOWS.md, docs/COMPANION_UI_PRODUCT_SPEC.md, docs/COGNITIVE_LOAD_PROJECTION_LAYER.md, docs/research/COGNITIVE_LOAD_REDUCTION_RESEARCH.md, docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md, docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md, companion-ui/docs/WORKSPACE_STATE_CONTRACT.md, companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md, companion-ui/docs/COMPANION_UI_STATE_MAP.md, docs/adr/ADR-0008-leave-point-cursor.md, docs/adr/ADR-0009-orientation-memory-candidate-intent.md, docs/adr/ADR-0011-orientation-push-ambient-resurfacing.md, docs/adr/ADR-0012-orientation-multiagent-reads.md, app/api/routes/companion.py, app/orientation/leave_point_cursor.py, app/agent_memory/posture_projection.py, app/knowledge_compilation/runtime_artifacts.py, app/knowledge_compilation/proposal_builders.py, app/knowledge_compilation/reorientation_packet.py, app/knowledge_compilation/review_admission.py, tests/api/test_companion_workspace_api.py, tests/api/test_companion_orientation_api.py, tests/api/test_leave_point_cursor.py, tests/api/test_companion_vault_browser_queue_review.py, tests/api/test_companion_vault_browser_agent_memory_posture.py, tests/knowledge_compilation/test_runtime_artifacts.py, tests/knowledge_compilation/test_proposal_builders.py, tests/knowledge_compilation/test_reorientation_packet.py, tests/knowledge_compilation/test_review_admission_handoff.py, merged PRs #1448/#1460/#1461/#1463/#1464/#1466/#1475/#1486/#1490/#1525/#1526/#1488/#1487/#1459/#1534/#1535/#1536/#1537/#1538/#1551/#1552/#1586/#1591/#1648/#1649/#1650, and current repo state at 07cc1cb1 on 2026-06-07


# Human Flows — Yggdrasil / agentic-pkm-mvp

> Audience: humans using the system in Obsidian + CLI. Human language is canonical; automation is additive, not authoritative.

This document is about what the system is for.
It describes the human problems the system is meant to help with, the kinds of work it must
support, and the functions it must preserve across implementation changes.

It is not primarily a document about watchers, pipelines, or current internals.
Those matter only insofar as they help or hinder the human functions described here.

For the broader ontology of the system as a second-brain environment, see:
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
- `docs/CONCEPTS/ARCHIVE_BRAIN_CONTRACT.md`
- `docs/CONCEPTS/USER_NEEDS_MODEL.md`
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`
- `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`
- `docs/CONCEPTS/STATE_AXES_CONTRACT.md`
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`
- `docs/plans/ARTIFACT_MODEL_AND_LIFECYCLES.md`
- `docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md`
- `docs/plans/USER_STORIES_AND_REQUIREMENTS.md`
- `docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md`

## 0. Product thesis: cognitive prosthesis, second brain, and agent memory

Yggdrasil is three things at once, held together by design:

- **A cognitive prosthesis for the human.** It supports cognitive functions a human cannot
  reliably do unaided — durable capture, reorientation, retrieval, commitment tracking,
  reflection, source-anchored interpretation — without taking authorship away.
- **A second-brain environment.** Human-authored Markdown artifacts in the vault are the
  primary durable knowledge surface, meant to remain readable and editable directly, with or
  without the system running.
- **A governed memory and runtime substrate for agents.** System agents act as bounded
  delegates over the vault and over supporting machine surfaces (databases, indexes, events,
  receipts), under explicit authority contracts. Their memory and writes are first-class
  inspectable objects, not hidden model state.

Runtime behavior — watchers, indexes, agents, APIs — remains subordinate to human-readable
artifacts and to the authority contracts that govern machine action. When the two come into
tension, the human-authored surface and the authority contract win.

Security controls are in service of the same human contract. Use `docs/SECURITY_ARCHITECTURE.md`
for threat-model tiers, security invariants, and review routing when a change affects exposure,
tool/provider execution, data flows, or mutation authority; security hardening must preserve
authorship, accountability, and local-first artifact control rather than replacing them.

The full product-level statement of this thesis, including the failure modes that would
violate it, lives in `docs/COGNITIVE_PROSTHESIS_CHARTER.md`. The bridge from these human flows
to the runtime substrate lives in `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`.

### Cognitive-load reduction as prosthetic function

Reducing cognitive load is a central human-first function, not an accessibility side topic. The
system should carry externalizable burdens that otherwise sit in working memory: remembering where
the human left off, keeping source and proposal together, preserving pending decision state,
separating facts from interpretation, and making receipts visible after action.

The rule is: reduce friction, not intelligence. The system should remove mechanical costs around
decoding, parsing, spelling, text production, source comparison, and resumption without flattening
the content, hiding uncertainty, or treating the human's slowest channel as the human's reasoning
capacity.

This function must not reduce load by hiding consequences, replacing source review with agent
summary, or making the system's recommendation behave like approval. Reading-support and
accessibility techniques can help implement the function, but the owning product category is
authority-preserving cognitive offloading. The projection boundary for this work is
`docs/COGNITIVE_LOAD_PROJECTION_LAYER.md`.

## 1. What the system is meant to do

The system is meant to function as a human-first cognitive work environment.

Its job is to help a human:
- capture what should not be lost,
- externalize thought so it can be worked on,
- find and reuse what matters later,
- develop knowledge over time,
- support projects and commitments without keeping everything in working memory,
- aid learning and reflection,
- support creative work, hobby work, and world-building,
- preserve contextual integrity across different life spheres, contexts, and role identities,
- remain evolvable as the user's needs change over time,
- work across multiple devices without abandoning local-first principles,
- keep central human artifacts understandable even if the current system changes or dies,
- and let assistance happen without losing authorship, accountability, or trust.

It should therefore be usable not only for "knowledge management" in a narrow sense, but for
ongoing cognitive life across overlapping spheres and contexts:
- knowledge work,
- writing,
- learning,
- planning,
- reflection,
- creative exploration,
- hobby practices such as roleplaying,
- and GTD-like commitment handling.

## 2. The human problems being solved

The system exists because unaided cognition is limited.

In lived practice, the human faces recurring problems such as:
- too much to keep in working memory at once,
- ideas that disappear unless captured quickly,
- sources that become hard to relocate or trust later,
- projects that fragment across notes, materials, and time,
- open loops that continue to occupy attention without being clarified,
- difficulty turning vague intentions into actionable next steps,
- difficulty maintaining learning momentum and reflective continuity,
- difficulty moving between different life contexts without cognitive contamination,
- fear that important material may become trapped in one system's implementation,
- and creative/hobby material that does not fit cleanly into "task" or "knowledge" categories but
  still needs to be held, developed, and revisited.

The system should reduce those burdens without pretending to replace judgment, memory, or meaning.

The system also exists in a longer arc of use:
- the user does not know all future needs in advance,
- the system must be able to evolve without breaking its human purpose,
- and access may be distributed across devices that do not always have identical state or capability.

## 3. Core human functions

The following functions are primary.
They define what the system must continue to support even as implementation details change.

Automation is additive to these human functions. When the runtime is allowed to act on the user's behalf, it must still preserve authorship, provenance, and a visible receipt trail so the human can tell what happened and why.

### Canonical human loops

These loops are compact recurring patterns, not a claim that all work must follow one rigid workflow.
They summarize the kinds of cycles the system should keep legible and support across changing runtime implementations.

- Capture -> clarify -> place
- Retrieve -> orient -> act
- Source -> interpret -> stabilize
- Intent -> propose -> decide -> execute -> receipt
- Review -> reclassify -> promote/archive

Validation note:
- these loops and the everyday scenarios below are the product-level acceptance source for system-level UAT
- they are intentionally broader than the currently locked runtime baseline
- when implementation lags the human contract, the scenario should still be kept as a non-blocking acceptance target rather than rewritten to fit today's internals
- use `docs/TESTING.md` and `docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md` to classify whether a scenario is a baseline gate, a partial/non-blocking acceptance target, or a future release gate

Scope note:
- `Intent -> propose -> decide -> execute -> receipt` is a canonical loop for mutation-capable interaction surfaces, especially AI-panel and action-driven flows.
- **For artifact-local interaction, Panel is the primary surface for this loop.** Its distinctive function is to make likely artifact intentions visible before they are fully formed as user commands. The agent may propose what the user likely wants to do with the active artifact; the user recognizes, corrects, or confirms; only confirmed intent enters governed execution; a receipt is written near the artifact.
- New emergent features (for example resume my thinking, suggest next action, memory candidate, research pack, dormant project resurfacing, agent learns my workflow) compose this loop together with context bundles, reusable capabilities, policy evaluation, and feedback signals; see `docs/EMERGENT_FEATURES_MODEL.md` for the composition pattern and the rule that emergent features must not bypass governance, write guards, provenance, or authority boundaries.
- It is not a blanket requirement that every runtime interaction must pass through a human approval step before the system can propose or execute low-risk work.
- The runtime should reduce cognitive load by generating autonomous proposals where the action is low-risk and the artifact value is not threatened, while reserving harder guardrails for writes or transitions that could damage artifact integrity, provenance, or user trust.
- Suggested actions may surface as proposed checkbox items in an AI panel when the system has enough context to help but not enough certainty or authority to mutate directly.

### Capture

The system must let the human get material out of fragile working memory and into a durable external
surface quickly enough that important thoughts, tasks, fragments, and source references are not
lost.
Capture must work for:
- notes,
- source material,
- fleeting thoughts,
- project fragments,
- creative fragments,
- roleplaying/hobby material,
- and open loops that are not yet clarified.

### Externalize and work on thought

The system must support thinking by making thought manipulable outside the head.

This includes:
- drafting,
- sketching,
- comparing,
- linking,
- restructuring,
- questioning,
- and revising.

The point is not only storage.
The point is to let external representations help produce understanding.

### Retrieve and re-orient

The system must help the human recover relevant material when needed.

This includes:
- finding the right note, source, or artifact,
- recalling what a project was about,
- recovering context after interruption,
- and re-orienting to what matters now.

Retrieval is therefore not only question-answering.
It is also orientation, rediscovery, and return-to-context.

### Develop knowledge

The system must help ideas move from raw capture toward clearer, more durable understanding.

This includes:
- collecting source-backed material,
- refining interpretations,
- stabilizing concepts,
- and making some material reusable over time.

Knowledge development is one function among several.
It must not erase the existence of creative, reflective, or commitment-oriented material.

### Compile and curate memory

The system should help the human compile and curate memory by weaving together `Source -> interpret -> stabilize`, `Capture -> clarify -> place`, `Review -> reclassify -> promote/archive`, and `Retrieve -> orient -> act`.
Compilation should reduce cognitive load while preserving human authorship, provenance, uncertainty, and review posture across the resulting working artifacts.
Generated compiled artifacts are not automatically canonical truth; they remain reviewable outputs until the human decides what to keep, promote, revise, or archive.

### Support commitments and action

The system must help the human manage open loops, commitments, projects, waiting states, and next
actions without relying on memory alone.

This includes GTD-like functions such as:
- clarifying what something is,
- deciding whether it is actionable,
- identifying the next concrete action,
- tracking what is waiting,
- revisiting commitments in review cycles,
- and closing, deferring, or renegotiating commitments explicitly.

The system should reduce the cognitive cost of staying responsible over time.

### Support learning

The system must support learning as an active process, not only archiving information.

This includes:
- linking source material to understanding,
- turning reading into working representations,
- consolidating concepts,
- revisiting prior understanding,
- and making it easier to see what has or has not yet been learned.

Learning support must remain compatible with self-regulation:
- setting goals,
- monitoring understanding,
- noticing gaps,
- and returning for review or correction.

### Support reflection and calibration

The system must help the human examine:
- what is understood,
- what is uncertain,
- what remains open,
- what is being neglected,
- and whether the system is still trustworthy as a guide to work and memory.

This is why reflection, weekly review, after-action notes, and other review practices matter.
They are not decorative add-ons.
They are part of keeping the system useful and believable.

### Support creative and hobby work

The system must explicitly support forms of work that are not reducible to stable knowledge or
task execution.

This includes:
- idea generation,
- motifs,
- fragments,
- draft scenes,
- speculative structures,
- world-building,
- campaign planning,
- character material,
- setting notes,
- rule interpretations,
- and other hobby/RPG artifacts.

The point is not to force these materials into the same mold as factual notes or action lists.
The point is to let them remain generative, revisitable, and developable over time.

### Support context-specific role identities and controlled overlap

The system must support the fact that the same human operates in different contexts with different
role identities, responsibilities, tones, and cognitive expectations.

This means:
- work, private, creative, and RPG contexts must remain distinguishable,
- the purpose of domain separation is contextual integrity rather than total isolation,
- overlap between contexts may be normal and useful,
- but that overlap must remain explicit, bounded, and intelligible rather than accidental.

The system should therefore support both:
- protected separation when contexts should stay apart,
- and explicit, reusable overlap when the human wants stable participation across contexts.

### Support safe operator enablement

When the system exposes automated watcher behavior, the operator must be able to decide whether it is safe to enable without reading implementation code.

The system should make the following questions answerable from `settings-explain`, `status`, and the runbook:
- what the effective watcher auto-exec mode is,
- which actions are allowlisted,
- whether the allowlist matches the loaded panel actions,
- whether provenance and write-guard metadata are present,
- and whether recent watcher ticks show only expected skips and receipts.

The operator decision should not depend on a single environment variable alone.

### Support long-term evolution of the system itself

The system must remain compatible with the fact that the user's needs, practices, and preferred workflows will change.

This means the system should:
- allow important capability areas to evolve over time,
- avoid locking core human functions to one premature technical solution,
- support incremental refinement rather than requiring total redesign,
- and preserve continuity even when some modules are more mature than others.

This is a human need, not only an architecture preference.
The user needs to be able to grow the system without being trapped by early design choices.

### Support local-first multi-device use

The system must support use across multiple devices while keeping local artifacts primary.

This means:
- a person should be able to use the system from different devices,
- not every device needs to behave identically at all times,
- synchronization may be eventual rather than instantaneous,
- and satellite-like setups are legitimate if they preserve continuity, intelligibility, and ownership.

The goal is not perfect sameness across all devices.
The goal is reliable continued use across contexts without abandoning the local-file principle.

Core functions should remain available even on narrower devices or partial satellites:
- capture,
- reading central artifacts,
- basic orientation,
- and other minimum continuity functions.

Richer assistance may vary by device role as long as that asymmetry is understandable and does not threaten trust in the underlying artifacts.

Current operational examples the system should remain compatible with:
- a Mac mini acting as the richer home/master runtime node,
- an iPad reading and lightly editing through iCloud-backed file sync,
- and a laptop/satellite node using Git-backed synchronization with narrower or delayed local capability.

The human contract is not that every device behaves identically.
The contract is that the important artifacts remain understandable, recoverable, and usable.

### Preserve long-lived artifacts beyond the current system

<!-- vault-first-human-surface -->

The system must treat the human's central artifacts as longer-lived than any current stack, runtime, or implementation choice.

The vault is the primary durable human cognitive surface. Human writing, decisions, and standing meaning live in vault notes (with companion notes as the system-owned continuity pair). Runtime substrate — LangGraph orchestration state, any future Deep Agents harness, the Orchestrator, the event/outbox layer, derived indexes — is operational and rebuildable. It carries bounded execution under governance; it does not own canonical cognition. The corresponding architectural framing lives in `docs/ARCHITECTURE.md :: layered cognitive/runtime architecture` and `docs/ARCHITECTURE.md :: runtime state vs canonical cognition`.

This means:
- central notes and core artifacts should remain directly comprehensible without the current system,
- local files and primary artifacts should not depend on hidden runtime state to make sense,
- metadata, projections, and machine-side connections may evolve more freely,
- but they must not become the only way to recover the meaning of core human artifacts.

The working assumption should be that the system may evolve, split, or die over decades while the human material remains.

## 4. Types of work the system must support

The system must support several major kinds of work without collapsing them into one narrow model.

### Knowledge work

Examples:
- research,
- note-making,
- synthesis,
- writing support,
- reference management,
- source-grounded recall.

### Archive and source work

Examples:
- PDFs,
- media,
- emails,
- project files,
- reference collections,
- archive retrieval,
- source citation without forced note-conversion.

### Commitment and execution support

Examples:
- projects,
- next actions,
- waiting states,
- planning horizons,
- checklists,
- review cycles,
- operational follow-through.

### Creative work

Examples:
- drafts,
- partial ideas,
- forms,
- exploratory structures,
- themes,
- narrative fragments,
- concept generation.

### Hobby and roleplaying work

Examples:
- campaign material,
- world-building,
- lore,
- session prep,
- character arcs,
- scenario ideas,
- house rules,
- inspiration capture.

### Reflective and personal development work

Examples:
- journaling,
- learning logs,
- after-action reflection,
- weekly review,
- self-observation,
- value clarification.

These forms of work may overlap.
The system should help coordinate them without assuming they are the same thing.

### Cross-device and evolving use

Examples:
- a home machine with richer local capabilities,
- a work device with narrower access,
- a travel device with delayed synchronization,
- a satellite setup with partial functionality,
- and a system that gains new memory, sync, or retrieval capabilities over time without abandoning prior artifacts.

## 5. Human rhythms and recurring use

The system should support recurring human rhythms, not only isolated interactions.

### In the moment

When something appears, the human should be able to:
- capture it quickly,
- mark or infer enough context that it can be found again,
- and continue working without needing to fully classify everything immediately.

### During focused work

When the human is actively working, the system should help by:
- resurfacing the most relevant material,
- preserving context around a project or line of thought,
- keeping source material available,
- and reducing the need to remember supporting details manually.

### When interrupted

After interruption, the system should help the human return by making it easy to see:
- what this work was,
- what mattered,
- what was next,
- and what remains unresolved.

### In review

At daily/weekly or other recurring review moments, the system should help the human:
- re-open the right commitments,
- notice what has drifted,
- detect waiting states and neglected loops,
- and restore trust that the external system still reflects reality well enough.

### Over longer time

Across weeks and months, the system should help the human:
- develop durable knowledge,
- preserve continuity in projects and learning,
- carry creative/hobby worlds forward,
- and maintain a usable memory of prior thought and prior action.

## 6. Choosing the right representation

A user-facing system like this should help the human distinguish not only *content*, but *what kind
of thing this currently is*.

The system should make it increasingly clear whether something is primarily:
- a note to think in,
- a source to rely on or cite,
- a project that requires multiple steps,
- a next action,
- a waiting item,
- a creative fragment,
- a reflective artifact,
- a companion note or other system-surface continuity artifact,
- or a system receipt/status surface.

The human should not need to force everything into one representation too early.

Good support means:
- vague things can begin vague,
- commitments can become clearer over time,
- creative fragments can remain exploratory,
- and sources can remain sources rather than being prematurely absorbed into personal claims.

## 7. What the user should be able to rely on

From the human point of view, the following expectations matter:

- captured material should not disappear silently,
- important source/provenance context should remain inspectable,
- the system should not silently rewrite meaning-bearing content,
- suggestions should be distinguishable from accepted truth,
- commitments should remain recoverable across time,
- creative and hobby material should remain usable without being downgraded to second-class status,
- central artifacts should remain understandable without the current runtime,
- narrower devices should still preserve minimum continuity functions,
- and meaningful automated action should leave inspectable receipts.

Just as important is what the user should *not* be asked to rely on:
- opaque hidden reasoning,
- silent classification changes,
- unexplained cross-domain leakage,
- hidden dependency on one implementation for understanding core artifacts,
- or the assumption that current runtime mechanics are the same thing as the domain model.

## 8. Everyday scenarios and user needs

The system should be understandable not only in abstract principles, but in ordinary lived cases.

### Case: a fleeting idea appears

User need:
- "I need to get this out of my head before it disappears."

The system should help the user:
- capture the idea quickly,
- avoid demanding premature classification,
- and make it easy to come back later and decide whether it is:
  - a note,
  - a project seed,
  - a creative fragment,
  - or nothing important after all.

### Case: I am trying to learn something difficult

User need:
- "I need to move from reading and collecting to actual understanding."

The system should help the user:
- keep source material attached to evolving understanding,
- let partial understanding remain visible,
- support revision and consolidation over time,
- and make it easy to revisit prior thinking instead of starting from zero.

### Case: I know the material exists, but it is not in my active notes

User need:
- "I need to find and use archived source material without first rewriting it into notes."

The system should help the user:
- retrieve retained source material as a first-class source surface,
- preserve provenance and domain boundaries,
- support citation, preview, and controlled reuse,
- and avoid forcing every useful retained artifact into the writing surface.

### Case: I have too many open loops

User need:
- "I know many things need attention, but I cannot hold them all in mind."

The system should help the user:
- externalize open loops,
- clarify what each one is,
- identify what is actionable,
- separate projects from next actions,
- preserve waiting states,
- and support recurring review so the whole landscape becomes trustworthy again.

### Case: I am returning after interruption

User need:
- "I do not want to spend thirty minutes reconstructing what I was doing."

The system should help the user:
- recover the relevant note, project, or source,
- restore the local context of the work,
- show what mattered and what was next,
- and reduce the restart cost after context loss.

### Case: I am writing or producing an output

User need:
- "I need to turn notes, sources, and thought into something shippable."

The system should help the user:
- gather relevant material,
- preserve provenance,
- keep draft work separable from settled claims,
- and support movement from exploration to output without laundering uncertain material into false certainty.

### Case: I am doing creative work

User need:
- "I need a place where fragments, motifs, half-ideas, and strange connections can stay alive."

The system should help the user:
- hold fragments without forcing closure,
- let ideas be revisited and recombined,
- support emergence rather than only classification,
- and protect exploratory material from being prematurely treated as finalized knowledge.

### Case: I am running a hobby or RPG world

User need:
- "I need to keep lore, scenarios, character ideas, rules, and plans coherent over time."

The system should help the user:
- preserve continuity of the world or campaign,
- keep exploratory and canonical material distinguishable,
- support session prep, inspiration capture, and later reuse,
- and make it possible to move between fragments, references, and structured materials without losing coherence.

### Case: I am switching between work and another life mode

User need:
- "I need these contexts to stay different enough to support me, but not so separate that useful overlap becomes impossible."

The system should help the user:
- preserve contextual integrity between domains,
- make recurring overlap explicit rather than accidental,
- and support bounded cross-context permissions that feel intentional instead of contaminating.

### Case: I need this to remain understandable in the future

User need:
- "I need my central material to still make sense even if this system changes completely."

The system should help the user:
- keep primary artifacts readable and meaningful without hidden machinery,
- avoid putting core understanding only in derived metadata,
- and treat the current implementation as support infrastructure rather than the sole home of meaning.

### Case: I need to know whether I can trust the system right now

User need:
- "I need to know whether this is a suggestion, a source-backed result, an active commitment, or a system action that already happened."

The system should help the user:
- distinguish source from interpretation,
- distinguish suggestion from accepted meaning,
- distinguish commitment from note text,
- and inspect what the system did, under what authority, and with what result.

### Case: I want to think on a note with a writing partner

User need:
- "I have a note that is rough, or partial, or messy, and I want to work on it with assistance that edits the note directly, not in a separate chat window."

The system should help the user:
- open a canvas session on the note where edits apply in place as they are generated, the way a collaborative editor behaves,
- treat the note itself as the surface they are working on, not a conversation transcript,
- keep sessions short and purposeful rather than accumulating a long chat log per note,
- retain the session as a subordinate intent trail so the user can later ask "why did this note become what it is," without that trail growing into a second document that competes with the note,
- keep content edits in the active session authorized by the user's presence, and keep any governance-bearing change (classification, cross-note moves, lifecycle transitions) on the same gated-execution path the Panel already uses,
- and undo any edit the way the user would undo their own typing.

This case is what the canvas-Chat surface exists for. The note remains the artifact; the session log remains the provenance of intent behind it.

## 9. Context-sensitive use

The same human may use the system across multiple life spheres and contexts.

Examples:
- work,
- private life,
- creative work,
- roleplaying/hobby worlds,
- long-term learning,
- reflective/self-development work.

The system should support this without collapsing everything into one undifferentiated pool.

User need:
- "I want continuity across my life, but I do not want all contexts mixed by default."

Therefore the system should:
- preserve operational scope boundaries where they matter,
- support different role identities across contexts,
- allow intentional and even recurring cross-domain use when wanted,
- avoid accidental leakage,
- make stable overlap possible through explicit shared participation and bounded cross-context
  permissions when needed,
- and make it possible for different kinds of work to coexist without forcing the same standards of
  truth, urgency, or structure on all of them.

## 10. What a good experience looks like

Good looks like:
- the human can put something down before it is lost,
- come back later and recognize what it is and why it mattered,
- find relevant prior material without trawling blindly,
- develop knowledge without flattening all work into "facts",
- run projects and commitments without carrying all open loops mentally,
- support creative/hobby domains without treating them as second-class,
- learn through interaction with externalized material,
- move between contexts without losing role integrity,
- rely on central artifacts remaining understandable over time,
- and understand what the system did and why.

Bad looks like:
- the system becoming a pile of notes with no orienting function,
- the human losing track of commitments because they were modeled only as text,
- creative and hobby material being forced into inappropriate taxonomies,
- different life contexts contaminating each other in ways that make the system harder to inhabit,
- central artifacts becoming dependent on hidden system structures to remain intelligible,
- retrieval returning material without intelligible provenance,
- and automation acting in ways the human cannot reconstruct or trust.

## 11. Human-first boundaries

The following boundaries protect the functions above.

### The human remains the bearer of meaning

The system may assist, suggest, structure, and automate bounded work.
It must not silently become the owner of interpretation, commitment, or truth.

### External representations support cognition; they do not replace it

The system should reduce cognitive load, not produce dependence on opaque machine behavior.

Good support helps the human:
- think better,
- remember better,
- act more coherently,
- and learn more reflectively.

### Accountability is part of usefulness

If the system proposes, mutates, classifies, promotes, or executes, the human must be able to see:
- what happened,
- why it happened,
- what authority allowed it,
- and how to inspect or reverse it.

### Different work types must remain distinguishable

The system must not force:
- commitments into note semantics only,
- creative fragments into knowledge semantics only,
- or learning/reflective material into task semantics only.

### Retrieval must preserve provenance

The system should help the human remember and reuse material without laundering uncertain or
external content into uncited truth.

### Assistance should degrade safely

When the system is uncertain, incomplete, or missing context, it should:
- suggest rather than assert,
- ask rather than assume,
- preserve reversibility,
- and leave the human able to continue work without hidden damage.

This matters because trust is lost more by silent overreach than by visible incompleteness.

## 12. Functional implications for ontology

Because of the functions above:
- commitment structures must be first-class,
- creative artifacts must remain first-class,
- source and provenance must remain explicit,
- review posture and maturity must remain distinct,
- execution plans must not replace human project/commitment structure,
- system agents must remain bounded and accountable,
- and receipt/accountability surfaces must not be confused with mirrors or event traces.

These are not arbitrary modeling choices.
They follow from what the system is meant to help the human do.

## 13. Current human-facing surfaces

<!-- vault-first human surface -->

**Vault notes are the primary durable human cognitive surface.** The Obsidian vault is the authoritative writing, reading, capture, and working surface for the human. All runtime state — indexes, stores, execution traces, agent outputs — is derived from and subordinate to the human-authored vault artifacts. Runtime services serve this surface; they do not replace it, redefine it, or become semantically primary over it.

The vault-first principle means:
- vault notes remain readable and meaningful without the current runtime,
- runtime stores and indexes are rebuildable projections from the file-based continuity set (vault notes + companion notes),
- automation and agent behavior must preserve authorship, provenance, and the integrity of vault-first artifacts,
- and no execution substrate (LangGraph, orchestrator, Deep Agent harness) becomes the canonical cognitive record in place of the vault.

The current baseline exposes these main surfaces:
- Obsidian vault: the primary writing, reading, capture, and working surface.
- CLI: operator/developer tooling for ingest, retrieval, watcher control, and diagnostics.
- HTTP API: `/api/ask`, `/api/health`, `/api/status`, and the bounded `/api/canvas/sessions*`
  surface when `CANVAS_ENABLED=1`.
- AI panels + receipts: bounded in-note surfaces for suggestions, explicit actions, and visible
  outcomes.
- Canvas co-authoring: a bounded note-body editing surface with session logs and governance-routing
  for mutation-bearing requests; this is implemented but still explicitly gated behind
  `CANVAS_ENABLED`.

These surfaces are important only insofar as they serve the human functions described above.

The human may also occasionally observe system-surface artifacts such as companion notes.
Those artifacts are not normal authoring surfaces, but their presence should still remain legible
enough that the human is not surprised by them.

A canvas-Chat surface now exists as a bounded human-facing surface for thinking on a note with
assistance — direct in-place editing during an active session, with session logs retained
alongside the note as subordinate intent trails. The shipped surface is intentionally narrow:
session logs, body-only co-authoring, and governance-routing are present, while broader hybrid
Panel/Chat behavior and richer Chat cognition remain separate work. Its authority model and
artifact conventions are specified in
`docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md` so that the co-editing
posture cannot be either over-restricted (reintroducing ASK-shaped turn-taking) or
over-permissive (collapsing the gated-execution invariant) as the surface expands.
Hybrid Panel/Chat behavior remains future work; its docs-only compatibility schema is
`docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md`.

### Satellite and tablet flow

The system should support a practical flow where:
- the Mac mini runs the richer ingest/watch/runtime loop,
- iCloud propagates changed vault files to an iPad for reading and light editing,
- Git propagates tracked files to a laptop or narrower satellite,
- and the runtime reacts to changed files rather than assuming one transport is the only real one.

This means:
- companion notes may travel with the vault's system-owned files,
- runtime DB/index state may differ temporarily across nodes,
- but continuity should still be recoverable from the file-based artifacts.

This section is the authoritative user-facing description of the current operational topology.
Architecture and roadmap docs may reference it, but should not duplicate device-specific narrative
unnecessarily.
## 14. Current baseline realization

The current baseline realizes only part of the broader function set.

### Already materially supported

- vault-first writing and capture
- source-grounded retrieval through ASK
- bounded frontmatter updates and side-channel system metadata
- AI-panel-driven suggestions and visible receipts
- bounded canvas co-authoring with session logs and governance-routed mutation-bearing requests
- early support for promotion / standing changes
- early support for open-loop/project semantics in docs and ontology

### Emerging but not yet fully realized

- explicit commitment-layer support in runtime
- richer review-cycle support
- stronger learning-oriented flows
- clearer creative/hobby-specific support patterns
- fuller receipt artifacts beyond current overlays and operational traces
- hybrid Panel/Chat integration that preserves Panel as primary command surface without making it
  the exclusive authoritative intent source (see
  `docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md`)

This is acceptable as long as the system is developed toward the broader human functions rather than
mistaking current baseline mechanics for the full target.

## 15. Research orientation

The direction described here is consistent with research and practice around:
- distributed cognition and external representations,
- epistemic action and thinking-through-manipulation,
- self-regulated learning and reflective monitoring,
- personal knowledge management,
- and workflow/commitment practices such as GTD-like clarification and review.

This document does not attempt to turn those traditions into dogma.
It uses them as orientation for what kinds of human function a system like this should support.

## 16. Current runtime notes

The current runtime remains relevant, but secondary.

- Ingest projects artifacts into runtime stores and rebuildable indexes.
- Companion notes preserve system-side continuity and healing context for tracked vault notes.
- PanelAgent provides bounded suggestion/action surfaces inside notes.
- Promotion flows currently carry only part of the broader artifact/commitment model.
- Watchers and orchestration are implementation conveniences, not the essence of the human
  contract.

If future implementations change these mechanics while preserving the human functions above, this
document should continue to hold.

## References

- `docs/PROJECT_KERNEL.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/USER_NEEDS_MODEL.md`
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`
- `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`
- `docs/CONCEPTS/STATE_AXES_CONTRACT.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- Zhang, J. & Norman, D. A. (1994). [Representations in Distributed Cognitive Tasks](https://pages.ucsd.edu/~scoulson/203/zhang.pdf)
- Kirsh, D. & Maglio, P. (1994). [On Distinguishing Epistemic from Pragmatic Action](https://philpapers.org/archive/KIRODE.pdf)
- Zimmerman, B. J. (2002). [Becoming a Self-Regulated Learner: An Overview](https://mathedseminar.pbworks.com/w/file/fetch/94760840/Zimmerman_-_2002_-_Becoming_a_SelfRegulated_Learner_An_Overview.pdf)

## Companion UI converse handoff update (2026-05-03)

Converse interaction design handoff materials are now available at `companion-ui/design_handoff/2026-05-03-converse/`.
The handoff reinforces the document-first Converse behavior: vault note remains primary, dialogue operates as a secondary rail/sheet, and suggestion moments are staged for explicit user action.
That direction is no longer handoff-only: a bounded implementation now exists in `companion-ui/companion-app/` with rail-state geometry, thread/composer states, the staged suggestion moment (apply/discard intents, mirrored proposal identity cues, and dimmed non-focused region), the session-drawer/portrait-sheet interaction slices, a read-only real-note workspace shell, and confirm-response artifact refresh delivered by PRs #745, #746, #750, #762, #1069, and #1070. The supporting runtime path now exposes `GET /api/artifacts/note` for read-only artifact hydration and `POST /api/panel/confirm` for explicit governed panel confirmation.

## Vault Browser as orientation surface

The Companion UI vault browser is the human-first navigation and orientation surface over the vault for the reorient/find/return-to-context flows. Its long-term capability contract — concepts (`VaultArtifact`, `VaultView`, `VaultQuery`, `VaultRelation`, `VaultActivity`, `VaultHealth`, `VaultAction`, `VaultProposal`, `VaultReceipt`), action-mode boundary, MLP-versus-future scope, and non-goals — is owned by `docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md`. Current shipped behavior is bounded as `Vault Browser MLP v0`: read-only Markdown enumeration with deterministic title/path filtering, active-vault identity, empty/error/identity-unavailable states, and note selection into the Companion workspace. When a browse cap applies, the retained subset is deterministic: lexicographically smallest matching note paths are preserved. The browser is a projection layer; the vault and Markdown/frontmatter remain the human control surface. Per the topology authority decision in `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md` and #1488, current browser `zone` posture is frontmatter-preferred with path-derived fallback over the active vault; topology-derived zones remain deferred projection material until a future issue defines source, provenance, degradation, and visible ranking/filter semantics.

## Companion Niflheim dev UAT workspace update check

For Niflheim dev UAT, Companion workspace update capability must be visible as runtime-declared state before mutation testing proceeds:
- the runtime safety strip must declare workspace update availability as `available` or `disabled`
- disabled state must remain non-mutating in the UI (no active body-update composer)
- workspace update capability is scoped to active-note body updates and must not authorize governance-bearing actions

## Companion Niflheim dev UAT active note body update check

For Niflheim dev UAT, active-note body updates in Companion workspace must stay bounded and guarded:
- entering the active-note body update flow must be explicit and note-local
- update attempts must be scoped to the active note path only
- target paths must resolve to Markdown note files (`.md`) before any write occurs
- successful updates must preserve frontmatter and UUID while changing body content
- blocked updates must show a clear guard reason (for example WriteGuard or capability disabled)
- failed updates must show a clear failure state distinct from blocked
- blocked/failed update attempts must preserve loaded workspace context so the note and status surfaces remain visible
