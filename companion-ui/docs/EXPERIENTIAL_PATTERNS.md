---
name: Experiential Patterns
description: "Phenomenological interaction vocabulary for the Companion UI: attentional feel, continuity restoration, and ambient cognition. Distinguishes experiential metaphors from architectural semantics."
type: design-reference
authority: Design vocabulary for Companion UI interaction quality; not an implementation specification
related_docs:
  - companion-ui/DESIGN_BRIEF.md
  - companion-ui/docs/ATTENTIONAL_PHYSICS.md (planned)
  - companion-ui/docs/TEMPORAL_OVERLAYS.md (planned)
  - companion-ui/docs/CONTINUITY_AND_DECAY.md (planned)
  - companion-ui/docs/RESURFACING_HEURISTICS.md (planned)
  - docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md
  - docs/FINDING_AND_REORIENTING/README.md
---

State: Active design vocabulary reference. Documents phenomenological insights from interaction exploration; does not prescribe implementation, UI components, or runtime behavior.

# Experiential Patterns — Companion UI

This document records the interaction-quality vocabulary that emerged from design exploration around interruption, continuity, and ambient cognition. Its purpose is to preserve phenomenological precision while keeping these concepts clearly distinct from architectural semantics, implementation contracts, and feature specifications.

Nothing in this document is a feature. These are attentional qualities and interaction goals that should inform how the surface *feels*, not what it *does*.

---

## Vocabulary Disambiguation

Four layers of language appear in Companion UI design work. Conflating them produces drift.

| Layer | What it names | Examples |
|---|---|---|
| **Architectural semantics** | Durable system concepts with runtime consequences | document, overlay, salience, resurfacing, continuity |
| **Interaction patterns** | Repeatable design moves with observable UX shape | ambient reveal, progressive disclosure, context anchoring |
| **Experiential metaphors** | Phenomenological descriptions of attentional feel | atmospheric recall, resumption breath, margin whisper |
| **Exploration terminology** | Provisional language from design investigation | dormant trajectory presence, continuity gradients |

Architectural semantics live in `docs/CONCEPTS/` and the companion architecture docs. They carry invariants.

Interaction patterns describe *how* the surface moves and behaves. They are design decisions.

Experiential metaphors describe *what the interaction should feel like*. They guide design judgment without specifying implementation.

Exploration terminology is provisional. Some of it crystallizes into one of the three layers above; the rest dissolves once its insight is captured.

---

## Experiential Goals

The Companion UI exists as a thinking surface, not a dashboard. The following experiential goals describe the intended attentional register across all states.

**Low attentional load.** The surface should not compete for the user's attention. It should receive attention when offered and recede when not needed. Nothing demands acknowledgment.

**Document-centered cognition.** The document — the vault artifact — is the primary cognitive object. The UI's job is to make the document easy to inhabit. Agent contributions, temporal context, and navigation are secondary.

**AI as ambient presence.** The system should feel like a contextually aware collaborator, not a tool being wielded. Its contributions arrive; they do not interrupt.

**Continuity over freshness.** The interaction should favor the experience of returning to familiar ground over the experience of encountering new information. Sessions are resumed, not restarted.

**No notification-centric interaction.** Nothing in the surface should organize the user's attention around alerts, counters, or urgency signals. The rhythm is set by the user.

---

## Attentional Feel

These describe the *quality of attention* the surface should cultivate.

**Attentional softness.** The surface should accommodate diffuse, peripheral attention, not only focal engagement. A user glancing at the UI while thinking should receive ambient orientation without being pulled into a task. This is distinct from attention management as a feature — it is a felt property of the design.

**Peripheral legibility.** Context, thread state, and agent presence should be readable at low attention cost. Information that requires focus to parse belongs in a detail layer, not in the ambient view.

**Interruptibility without cost.** The user should be able to leave mid-thought and return without penalty. The surface does not punish pauses. It holds state legibly without drawing attention to the gap.

---

## Interaction Atmosphere

The interaction atmosphere is the overall register in which the surface operates.

**Contemplative, not reactive.** The surface is built for sustained, exploratory thinking. It should not feel like a messaging app or a task manager. Response latency and visual tempo should reinforce this.

**Spatial continuity.** Elements should feel positioned, not floating. A user returning to the surface after time away should find the same spatial structure they left. Predictable layout reduces re-orientation cost.

**Quiet legibility.** Typography, contrast, and density should favor reading and composition over scanning. The surface is for thinking, not information triage.

---

## Continuity Restoration Principles

Continuity restoration describes what happens when a user returns after interruption — whether that interruption is five minutes or five days. These principles describe the *experiential shape* of good re-entry, not the mechanism.

**The session should be findable, not reconstructed.** The user should feel that their thread is still present and locatable, not that they must rebuild it from evidence. The surface holds the thread; the user retrieves it.

**Re-entry should breathe.** There is a moment when a user returns to a session and orients. Good design creates space for that moment rather than filling it immediately with information. The surface does not rush the user back to work.

**Continuity is graduated, not binary.** A user who was away for ten minutes needs different re-entry support than one who returns after two weeks. The surface should be sensitive to this without asking the user to declare which case they are in.

**The document anchors re-entry.** On return, the document itself — its content, state, and recent activity — is the primary orientation surface. System-level context (thread state, agent contributions) supports the document rather than replacing it.

---

## Ambient Cognition Patterns

These describe how the surface supports cognition that does not require direct engagement.

**Atmospheric recall.** The surface should evoke the cognitive atmosphere of a previous session, not merely display its data. A user returning should feel the context of where they were, not only see a log of what happened. This is a quality of presentation, not a data requirement.

**Ambient resurfacing.** Material that has become relevant again should be able to surface without active querying. The surface should occasionally make something visible at the periphery rather than waiting for the user to search. This is a presence quality — the system makes gentle, non-intrusive contact with material the user has not explicitly asked for.

**Margin whisper.** Soft contextual signals — related threads, dormant artifacts, nearby material — belong at the periphery of the working surface, not in the center. They should be visible without being legible at low attention; readable when the user shifts focus toward them.

**Dormant trajectory presence.** An abandoned or paused thread should feel present in the surface even when not active. This is not a UI state indicator. It is the felt quality of the system holding the thread — a sense that the work is still there, waiting.

---

## Re-entry Ergonomics

Re-entry ergonomics covers the interaction cost of resuming work after an interruption. These are design quality criteria, not feature requirements.

**Resumption breath.** The moment of return should be a moment of orientation, not immediate engagement pressure. Design decisions that reduce this space — immediate focus trapping, autoplay on load, aggressive information density — should be avoided. Good re-entry design creates the breath; it does not skip past it.

**Progressive context reveal.** On re-entry, orient before elaborating. Show the user where they are before showing them everything that happened while they were away. Temporal context, agent activity, and related material should be available but not foregrounded at the moment of arrival.

**Low cost abandonment.** The user should be able to leave a session at any point without cleanup, without a decision to make, without a form to complete. The surface manages its own state. Leaving is free.

**Legible thread state.** A user should be able to read the thread state — active, paused, complete, abandoned — at a glance without investigation. This is not a status badge; it is a design responsibility.

---

## Environmental Cognition Concepts

Environmental cognition describes thinking that uses the surface as extended mind — where the UI holds structure, state, and context that the user does not need to carry internally.

**The surface as memory prosthetic.** The surface should hold thread state, context, and history so the user does not have to. This is not about persistence as a feature; it is about the designed experience of cognitive offloading being reliable and legible.

**Contextual re-entry.** The surface should know where the user was and make that information available at re-entry without requiring the user to find it. The environment restores context; the user does not reconstruct it.

**The vault as cognitive ground.** All artifacts visible in the surface are, or derive from, vault documents. The vault is the stable cognitive substrate beneath the interaction. This grounds the environmental metaphor: the surface is not an ephemeral app state — it is a window into durable personal knowledge.

**Interruption ergonomics.** The full shape of interruption — from cognitive load at interruption time, through the gap, to re-entry — is a design unit. The surface should be designed for this whole arc, not only for the active-engagement moment.

---

## Architectural Invariants

These experiential patterns must remain consistent with the following architectural positions. Nothing in this document is intended to modify or override them.

- **The document is the primary cognitive anchor.** Agent contributions, overlays, and contextual material are always secondary to the vault artifact itself.
- **Overlays preserve continuity.** Temporal overlays, contextual signals, and resurfacing cues reinforce the user's thread; they do not fragment it.
- **AI remains ambient and contextual.** The system does not initiate, demand, or redirect. Its presence is felt; its interventions are offered.
- **Avoid dashboard UX.** No part of the surface should organize the user's attention around metrics, counters, statuses, or alerts.
- **Avoid notification-centric interaction.** The user sets the rhythm. The surface does not interrupt.
- **Preserve low attentional load.** Complexity lives in depth layers, not in the ambient view.

For architectural salience semantics, see `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`.

For the capability contracts governing orientation, resurfacing, and retrieval, see `docs/FINDING_AND_REORIENTING/README.md`.

---

## Planned Companion Documents

These documents are not yet authored. They are the anticipated specification surfaces for the more precise design contracts that this vocabulary anticipates.

- `companion-ui/docs/ATTENTIONAL_PHYSICS.md` — interaction-layer rules for attentional weight, peripheral presence, and focus transitions
- `companion-ui/docs/TEMPORAL_OVERLAYS.md` — design contracts for time-aware contextual signals and how temporal context is surfaced without becoming a timeline UI
- `companion-ui/docs/CONTINUITY_AND_DECAY.md` — design contracts for how thread continuity degrades over time and how the surface responds to different gap lengths
- `companion-ui/docs/RESURFACING_HEURISTICS.md` — design heuristics for ambient resurfacing decisions: when, how soft, at what cost to ambient legibility

This document should be read before authoring any of the above. It establishes the vocabulary those documents will use and the architectural invariants they must preserve.
