State: SoT v5.5 Reality-MVP baseline locked (v5.6 delivered, v6.0 seams shipped at capability-seam level); this document is target-state framing for how new emergent features compose on top of the kernel and extension fabric, and does not claim every emergent behavior described here is implemented today.
Doc role: Core SoT
Authority: Composition spine for emergent features. Owns the rule that new behavior in Yggdrasil emerges from a standard composition pattern (trigger + context bundle + capability composition + policy evaluation + proposal/action + receipt + feedback signal) over the existing kernel and extension fabric, and owns the rule that emergent features must remain observable and must not bypass governance, write guards, provenance, or authority boundaries. Sits below `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` (kernel and extension fabric), `docs/INTEGRATION_FABRIC_CONTRACT.md` (integration classes), `docs/CAPABILITY_CONTRACT_MODEL.md` (capability shape), and `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` and `docs/CONTEXT_BUNDLES/` (context bundle semantic contract and implementation-planning surface), and `docs/AGENT_MEMORY/` (agent memory contracts). Does not replace `docs/ARCHITECTURE.md` (current runtime baseline) or `docs/HUMAN-FLOWS.md` (user-facing behavior contract); it explains how their concerns are composed when new emergent behavior is added.
Owner: Architecture spine
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-05-14
Last verified against: docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md, docs/INTEGRATION_FABRIC_CONTRACT.md, docs/CAPABILITY_CONTRACT_MODEL.md, docs/ARCHITECTURE.md, docs/HUMAN-FLOWS.md, docs/AGENT_MEMORY/README.md, docs/CONTEXT_BUNDLES/README.md, docs/FINDING_AND_REORIENTING/README.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md, docs/DOCS_INDEX.md, parent initiative #877, prerequisite phase issues #878, #879, #880, governing slice issue #881.

# Emergent Features Model

This document defines how new emergent features are added to Yggdrasil without letting them bypass governance, provenance, human authority, or write guards. It is the composition spine: it states the standard composition pattern that any new emergent behavior must follow, the governance and observability rules that bind it, and how it differs from agent sprawl and ad hoc UI behavior.

It is a docs-only artifact. It does not introduce a runtime composition registry, an orchestration engine, a runtime feedback bus, or new tests. It sits on top of the existing kernel and extension fabric so later implementation planning has a stable place to attach.

If this document conflicts with `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`, `docs/INTEGRATION_FABRIC_CONTRACT.md`, `docs/CAPABILITY_CONTRACT_MODEL.md`, `docs/AGENT_MEMORY/`, or `docs/CONTEXT_BUNDLES/` on their respective concerns, those owner docs win. This document should be updated to reflect the resolved boundary, not the other way around.

## Reading rules

- "Emergent feature" in this document means a user-visible behavior that did not previously exist and that is added by composing existing surfaces, capabilities, policies, events, memory, and receipts — not by carving a new authority path through the kernel.
- An emergent feature is not the same thing as a new agent. New agents are an extension-fabric mechanism; emergent features are an outcome that may or may not involve a bounded agent.
- An emergent feature is not the same thing as a new UI affordance. A button, panel, or chat behavior that has no composed contract behind it is ad hoc UI behavior, not an emergent feature.
- Every emergent feature must respect every kernel constraint in `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` (`Kernel and extension fabric`): human-first authority, vault-first durability, provenance/receipts/write guards, local-first operation, event/outbox compatibility, authority separation between subsystems, and the single-user/single-vault baseline.
- Target-state language in this document is distinct from current runtime claims. Worked examples below describe the composed shape an emergent feature must take when it is added; they do not assert that the example is already shipped.

## Composition pattern

The composition pattern is the standard shape an emergent feature must take in Yggdrasil. Every emergent feature must compose from the following seven elements. The elements are not optional decoration; they are the trust contract that distinguishes governed composition from drift.

`Emergent feature = trigger + context bundle + capability composition + policy evaluation + proposal/action + receipt + feedback signal`

The seven elements:

1. **Trigger.** The event, intent, or condition that starts the feature. A trigger is either an event on the common event/outbox envelope (for example a vault change, a watcher signal, a scheduled tick) or an explicit human intent through a governed interaction surface (Panel, Chat/canvas, CLI, HTTP API). Triggers cross subsystem boundaries through the event envelope, not through bespoke side channels. An emergent feature with no nameable trigger is not composable; it is hidden side behavior.

2. **Context bundle.** The inspectable envelope that carries the retrieval, orientation, resurfacing, memory, and provenance material the feature needs in order to act. The semantic contract for context bundles is owned by `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`; the implementation-planning surface lives under `docs/CONTEXT_BUNDLES/`, and agent-memory authority and surfacing are owned by `docs/AGENT_MEMORY/`. The bundle is the bridge between cognition and the durable surface: it makes the feature's inputs legible, it preserves authority flags and provenance, and it is the unit other subsystems can audit. An emergent feature that reaches around the bundle and reads private cognition state is not composable; it has become a hidden source of truth.

3. **Capability composition.** The reusable capabilities the feature invokes — for example retrieval, orientation, resurfacing, context building, citation checking, memory candidate extraction, note patch proposal, archive exposure, and commitment surfacing, as named in `docs/CAPABILITY_CONTRACT_MODEL.md`. Capabilities are reusable, composable, and testable; agents and orchestration layers invoke capabilities through explicit planning and state transitions. An emergent feature must compose existing capabilities where one already exists. New capabilities are allowed, but they must be added through the capability contract model, not through ad hoc helpers behind a UI surface.

4. **Policy evaluation.** The governance check that decides whether the proposed action is admissible, in what trust tier, and under what write-safety constraints. Policy evaluation is owned by the Governance/Authority subsystem and binds: idempotency, optimistic write guards, per-note opt-outs, governed APPLY paths, and authority separation between subsystems. Policy evaluation is the place where "this feature wants to act" meets "the human and the kernel decide whether that is allowed." An emergent feature that does not pass through policy evaluation is not composable; it is bypass behavior.

5. **Proposal or action.** The output the feature produces. Proposals are surfaced for human decision (the SUGGEST/APPLY pattern in the existing trust semantics); actions are executed only through governed APPLY paths after policy admits them. The split between proposal and action is what keeps human-first authority intact: cognition proposes, execution does not invent intent, and integration does not decide meaning. An emergent feature must name which of its outputs are proposals and which are actions, and it must route actions through the governed event/outbox path, not through direct durable-state writes.

6. **Receipt.** The human-legible artifact that records what the feature did or proposed, with provenance and trust-tier metadata. Receipts are a kernel contract: every system-originated change to the durable surface must carry provenance, must produce a human-legible receipt, and must respect write-safety gates. Receipts are first-class and are distinct from traces, mirrors, or runtime logs. An emergent feature that mutates durable state without producing a receipt is not composable; it is invisible authority.

7. **Feedback signal.** The observable signal the feature emits back into the system after a proposal or action — for example acceptance, rejection, dwell, follow-up edits, downstream resurfacing, or operator override. Feedback signals are what make emergence legible: they let the system observe whether composed behavior is helping, drifting, or degrading. An emergent feature that emits no feedback signal is not observable, and unobservable emergence is drift.

Composition direction: the elements are listed in the order they typically appear in a single feature loop (`trigger → bundle → capabilities → policy → proposal/action → receipt → feedback`), but the pattern is not a rigid pipeline. A given emergent feature may loop, defer, or short-circuit elements (for example, a feature may produce a proposal that is never executed and still emit a feedback signal). The requirement is that every element is named and governed, not that every element is invoked on every pass.

## Governance and observability rules

These rules bind every emergent feature, regardless of which subsystem it composes over. They are restatements and applications of the kernel constraints in `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`; they are listed here so the composition surface is legible without re-reading the spine.

- **No bypass of governance.** Every emergent feature must pass through policy evaluation before producing an action against the durable surface. Cognition that proposes without checking policy is allowed; execution that writes without policy is not.
- **No bypass of write guards.** Every action against the durable surface must respect idempotency, optimistic write guards, per-note opt-outs, and the governed APPLY path. Bulk or composed actions do not get a relaxed write-safety contract because they came out of a composed feature.
- **No bypass of provenance.** Every proposal and every action must carry provenance: which trigger, which capabilities, which bundle, which policy decision, which trust tier. Composed behavior that loses its provenance chain is indistinguishable from drift and must be treated as such.
- **No bypass of human authority.** The human (or a human-authorized rule) remains the final authority over meaning and over durable state. An emergent feature may propose; it may execute only through governed APPLY paths. Authority lives with the human and with explicit governance, not with the most recently composed feature.
- **No bypass of authority separation.** Cognition does not directly mutate notes. Execution does not invent intent. Integration does not decide meaning. Governance owns admissibility and audit. An emergent feature that quietly collapses two of these into one is not composable; it has become a kernel change and must be argued for at the kernel level.
- **Observable by construction.** Every emergent feature must be observable through its context bundle, its receipt, and its feedback signal. Without these three, the feature has no audit trail and no calibration loop, and emergence becomes drift. Observability is not an optional follow-up; it is part of what makes the feature composed.
- **Legible degradation.** Extension-fabric components that fail or are unavailable must degrade legibly. An emergent feature whose capability, integration, or memory dependency is unavailable must surface the degradation, not silently take over authority or hide the failure from the human.

## Examples

The following worked examples show the composed shape that each emergent feature must take. They are target-state framings, not claims that the example is shipped. Each example names the seven elements explicitly so the composition surface is legible.

### Resume my thinking

The human returns after an interruption (an hour, a day, a week) and wants the system to help them pick up where they left off without spending thirty minutes reconstructing context.

- **Trigger.** Explicit human intent on a governed interaction surface (Panel command "resume", Chat/canvas open, or a vault-open signal on the event envelope).
- **Context bundle.** A resume bundle composed of recent edits, open commitments, recently active notes, last orientation state, and any companion-note continuity markers. Bundle carries provenance and authority flags.
- **Capability composition.** Retrieval (recent and relevant material), orientation (where the human was), resurfacing (what has become relevant again), and commitment surfacing.
- **Policy evaluation.** Read-only by default; no APPLY path is required for a resume proposal. Policy admits the bundle as a proposal to display, not as a write.
- **Proposal or action.** A proposal surfaced in the interaction surface: "here is where you were, here is what changed, here is what looks open." No durable-state mutation.
- **Receipt.** A receipt of the resume proposal (what was shown, from which bundle, at which time) so the human can audit what the system thought "resume" meant.
- **Feedback signal.** Acceptance signals (did the human follow one of the surfaced threads), rejection signals (did the human ignore the proposal), and downstream signals (did the resumed work produce edits that confirm the proposal was useful).

### Suggest next action

The human has too many open loops and wants the system to surface a next concrete step rather than a full task list.

- **Trigger.** Explicit human intent ("what next") or a scheduled tick during focused work.
- **Context bundle.** An open-loop bundle composed of surfaced commitments, recent dwell, blocked items, and salience signals (recency, relations, usage); salience is derived, not stored.
- **Capability composition.** Commitment surfacing, orientation, and resurfacing.
- **Policy evaluation.** Read-only by default. If the suggestion includes a state change (mark a commitment active, add a follow-up), policy admits that as a SUGGEST that the human must confirm before any APPLY.
- **Proposal or action.** A proposal: "the next thing that looks ready is X, because Y, derived from Z." Optional follow-up actions remain proposals until human confirms.
- **Receipt.** A receipt of the suggestion, its provenance, and any confirmed action.
- **Feedback signal.** Did the human take the suggested next action, ignore it, or pick a different open loop; downstream commitment movement.

### Memory candidate

The human is doing creative or learning work and produces material that may deserve to be promoted into durable memory.

- **Trigger.** A vault-change event, a Chat/canvas turn, or an explicit "remember this" intent on the event envelope.
- **Context bundle.** A memory-candidate bundle composed of the candidate fragment, its surrounding context, similar existing notes, and authority flags about what kind of memory it would become.
- **Capability composition.** Memory candidate extraction, retrieval (to find adjacent existing memory), and citation checking.
- **Policy evaluation.** Memory promotion is gated. Policy decides whether the candidate is admissible as a SUGGEST for the human, and never auto-APPLYs into durable memory without explicit human authority.
- **Proposal or action.** A proposal: "this fragment looks like memory worth keeping, here is where it would attach, here is what it would shadow." Action (the actual promotion) only after human confirms through a governed APPLY path.
- **Receipt.** A receipt that records the candidate, the proposed promotion site, the human decision, and the resulting memory artifact (if any).
- **Feedback signal.** Was the candidate accepted, rejected, edited before acceptance, or revisited later; downstream resurfacing of the promoted memory.

### Research pack

The human is writing or producing an output and wants the system to gather relevant material with preserved provenance.

- **Trigger.** Explicit human intent (Panel/Chat "research pack" command) anchored to a note, topic, or open commitment.
- **Context bundle.** A research bundle composed of retrieved candidates, orientation around the topic, archive material exposed through governed adapters, and provenance for every item.
- **Capability composition.** Retrieval, orientation, archive exposure, citation checking, and context building.
- **Policy evaluation.** Read-only by default. If the pack would produce a durable companion note, policy admits the write through the governed APPLY path; otherwise the pack is a proposal only.
- **Proposal or action.** A proposal: an inspectable pack of material with provenance. The optional action is writing the pack into a system-owned companion note.
- **Receipt.** A receipt covering the pack composition, sources cited, and any durable artifact produced.
- **Feedback signal.** Did the human use items from the pack, prune items, add their own sources, or discard the pack; downstream edits that cite the pack.

### Dormant project resurfacing

A project the human has not touched in a long time has quietly become relevant again, and the system should surface it without becoming noisy.

- **Trigger.** A scheduled tick combined with derived salience signals (recency, relations, usage) on existing artifacts; or a vault-change event that creates a relation back into the dormant project.
- **Context bundle.** A resurfacing bundle composed of the dormant project's most recent state, the relation that revived it, current open loops it now touches, and salience metadata.
- **Capability composition.** Resurfacing, retrieval, relation traversal, and orientation.
- **Policy evaluation.** Resurfacing is read-only and gated for noise. Policy decides whether the resurfacing crosses the threshold to surface to the human, and at which trust tier.
- **Proposal or action.** A proposal: "this dormant project has quietly become relevant again, here is the relation that revived it." No durable-state mutation by default.
- **Receipt.** A receipt of the resurfacing event, its salience reasoning, and whether the human engaged.
- **Feedback signal.** Did the human reopen the project, edit related notes, dismiss the resurfacing, or mark it as not relevant; downstream changes to the project's recency/relation/usage signals.

### Agent learns my workflow

Over time, the system should refine its proposals and orientation in ways that reflect how the human actually works, without taking authority away from the human.

- **Trigger.** Accumulated feedback signals across many features (acceptance, rejection, dwell, edits, overrides) plus an explicit human intent ("calibrate" / "review what you have learned") on a governed surface.
- **Context bundle.** A calibration bundle composed of the human's interaction history with proposals, the receipts those proposals produced, and the feedback signals attached to them.
- **Capability composition.** Memory candidate extraction (for inferred preferences), orientation (over the human's workflow), and citation checking (to keep inferred preferences anchored to evidence).
- **Policy evaluation.** Learning is gated. Policy admits inferred preferences as SUGGEST artifacts only; durable changes to agent memory or to default behavior require explicit human confirmation through a governed APPLY path. The human (or a human-authorized rule) remains the final authority over what the agent learns.
- **Proposal or action.** A proposal: "here is what I think you prefer, here is the evidence, here is what changing this would affect." Action only after the human confirms.
- **Receipt.** A receipt for every inferred preference: source signals, proposed change, human decision, resulting durable change (if any).
- **Feedback signal.** Did the inferred preference hold up over the next interactions, or did the human revert it; downstream calibration drift.

## What this model is not

Emergent feature composition is a specific shape with a specific contract. It is not the same as the patterns it is most often confused with. Naming the difference is part of the contract.

- **Not agent sprawl.** Adding a new bounded agent is an extension-fabric move; it is allowed when an agent is the right shape, but it is not the same thing as adding an emergent feature. An emergent feature may use an agent, may use a deterministic pipeline, or may use neither. The composition pattern, not the agent, is what makes the feature emergent. New agents whose only justification is "we needed somewhere to put this behavior" are sprawl, not composition.
- **Not ad hoc UI behavior.** A button, panel command, or chat affordance that has no composed contract behind it — no nameable trigger, no inspectable bundle, no policy evaluation, no receipt, no feedback signal — is ad hoc UI behavior. It may still be useful, but it is not an emergent feature in the sense this document governs, and it must not be relied on as if it were composed.
- **Not hidden side effects.** Behavior that quietly mutates durable state without a trigger, a policy decision, a proposal/action split, and a receipt is not an emergent feature. It is a write that escaped governance, and it must be repaired, not formalized as emergence.
- **Not a runtime composition engine.** This document does not introduce, require, or imply a runtime composition registry, an orchestration framework, or a new event bus. The composition pattern is a docs-level contract that any implementation of an emergent feature must satisfy; how a specific feature is wired is a runtime decision owned by the relevant subsystem's owner docs.
- **Not a substitute for owner docs.** This document does not own the durable surface, the context bundle contract, the capability contract, the integration fabric, the agent memory contract, or the policy and write-guard semantics. It composes them. Each emergent feature's authoritative contract surfaces remain owned by those owner docs.

## Source anchors

- `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` :: Kernel and extension fabric; subsystem map; authority separation.
- `docs/INTEGRATION_FABRIC_CONTRACT.md` :: Integration classes; contract fields; authority rule for external components.
- `docs/CAPABILITY_CONTRACT_MODEL.md` :: Capability definition; canonical capabilities; capability contract shape.
- `docs/AGENT_MEMORY/README.md` :: Agent memory contract and authority guards.
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` :: Context bundle semantic contract (authority, fields, provenance).
- `docs/CONTEXT_BUNDLES/README.md` :: Context bundle implementation-planning surface; bridge between cognition and durable surface.
- `docs/ARCHITECTURE.md` :: Current runtime baseline; current-vs-planned status; capability model.
- `docs/HUMAN-FLOWS.md` :: User-facing behavior contract; canonical human loops; everyday scenarios and user needs.
- `docs/FINDING_AND_REORIENTING/README.md` :: Retrieval, orientation, resurfacing as distinct capabilities; salience as derived.
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md` :: Capability-level acceptance criteria; gated execution authority; interaction surfaces and authority boundaries.
- `docs/DOCS_INDEX.md` :: Documentation review index; doc role and review status map.
