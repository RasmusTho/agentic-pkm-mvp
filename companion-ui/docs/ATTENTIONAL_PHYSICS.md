---
name: Attentional Physics
description: "Interaction-layer rules for attentional weight, the overlay grammar, and the eight interaction invariants that hold across all five cognitive modes. Sourced from the 2026-05-08 Claude Design exploration."
type: design-reference
authority: Design vocabulary for attentional weight and interaction invariants; not an implementation spec
related_docs:
  - companion-ui/docs/EXPERIENTIAL_PATTERNS.md
  - companion-ui/docs/CONTINUITY_AND_DECAY.md
  - companion-ui/docs/TEMPORAL_OVERLAYS.md
  - companion-ui/docs/RESURFACING_HEURISTICS.md
  - companion-ui/docs/ATTENTION_MODEL.md
  - companion-ui/docs/SALIENCE_AND_TENSION.md
  - companion-ui/design_handoff/2026-05-08-cognitive-temporal/Cognitive Modes.html
  - docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md
---

State: Active design vocabulary reference. Sourced from the 2026-05-08 Claude Design exploration (Cognitive Modes.html, interaction invariants section). Does not prescribe layout, components, animation values, or frontend architecture.

# Attentional Physics — Companion UI

This document names the rules governing how elements carry attentional weight and how the overlay grammar works across the five cognitive modes. These are interaction-quality constraints, not layout specifications.

The term "physics" names the felt consistency that makes a surface predictable at low attention — the user develops a tacit model of how things move, recede, and surface without consciously learning it.

---

## Purpose

Define the principles governing how attentional signals are weighted and composed.

## Metaphor boundary

- `Attentional physics` describes interaction principles, not simulation or physical modelling.
- `Weight`, `gravity`, and `pressure` are explanatory metaphors.
- Their architectural meaning is always about attentional behavior, not simulated physics.

## Core terms

- **Attentional weight:** how much attention an object deserves in the current context.
- **Visual weight:** how strongly the interface presents an object perceptually.
- **Salience gradient:** the relative difference in attentional pull across adjacent objects or trajectories.
- **Attentional gravity:** the tendency of an unresolved object or tension to pull attention back over time.
- **Interruption pressure:** the cost imposed when a new signal competes with current focus.
- **Ambient resurfacing:** low-disruption return of relevant material without demanding immediate action.
- **Ambient cognition:** low-pressure cognitive support that stays available without insisting on immediate focus.
- **Non-disruptive salience:** making relevance legible without escalating into alert-like behavior.

## Rules

- Visual weight should usually follow attentional weight, but never replace semantic justification.
- Salience gradients should help the user perceive relative importance without forcing explicit ranking rituals.
- Ambient resurfacing should minimize interruption pressure.
- Attentional gravity should be traceable to tension, dependency, salience, or provenance, not invented urgency.
- Low attentional load is preserved when resurfacing clarifies rather than competes.

## Relations

- Salience influences attentional weight.
- Tension increases attentional gravity.
- Interruption pressure accumulates when multiple overlays compete without clear salience ordering.

---

## The Overlay Grammar

Modes are postures over the same document, expressed as overlays. From the `Cognitive Modes.html` design premise: *"The document is the cognitive anchor. Modes are not screens — they are postures over the same document, expressed as overlays with predictable grammar."*

Each mode answers nine questions: overlay class · density · persistence · provenance · sources · AI visibility · spatial behavior · interruption · transitions out.

The grammar has one rule above all others: **mode changes are overlay swaps, not route changes.** Scroll position, cursor, and selection are never altered when a mode transition occurs. The user's place in the document is sacred.

---

## Eight Interaction Invariants

From the Cognitive Modes design — invariants that hold across all five modes.

**1. Anchor preservation.** Mode changes never alter scroll position, cursor, or selection. The document is the anchor; modes are placed on top of it.

**2. Reversibility.** Every overlay can be dismissed without data loss. No overlay commits the user to a path. Leaving is free.

**3. No hard navigation.** Mode transitions are overlay swaps. They do not navigate to a new route or destroy the current view. The document remains visible behind every overlay.

**4. Proposal duality.** Any object shown in the agent rail appears identically in the document with the same actions. A suggestion card in the margin and the inline staged block in the document are the same object — same amber treatment, same label, same apply/discard actions. The user should feel they are acting on one thing, not two representations.

**5. Vault-canonical.** Persisted state lives in the vault as markdown and receipts. App-local state (canvas branches, trajectory snapshots, re-entry mist data) is recoverable if deleted. Nothing critical lives only in UI state.

**6. Agent voice is one of many.** Agent contributions are visually distinguished but never structurally privileged. The agent does not own a pane, a primary surface, or a dominant position. Its presence is visible; its contributions are offers.

**7. Low attention default.** Resurfacing and orientation never produce notifications. Salience expresses itself through visual weight — dot size, opacity, border weight — not through alerts, badges, or sounds.

**8. Portrait equivalence.** The bottom sheet on mobile preserves the same cognitive semantics as the margin rail on desktop. Same content, different geometry. Orientation mode, dialogue, suggestion flow, and resurfacing are all available on portrait without degradation.

---

## Attentional Weight

Every visible element carries implicit attentional weight: the claim it makes on focus simply by being present.

**Weight should match function.** The document carries the most weight. Agent contributions and contextual signals carry less. System state and navigation carry least. When weight is inverted, the surface fights the user's actual task.

**Cumulative weight is real.** Many light elements accumulate weight. A surface with few heavy elements but many peripheral signals can become cognitively demanding. Total attentional load must be managed, not just per-element salience.

**Colour discipline is an attentional physics principle.** At any given moment, only the single most actionable element carries a saturated colour. Everything else is monochrome. This makes colour a reliable state signal rather than decoration, which is itself a low-attentional-load technique.

| Moment | Coloured element |
|---|---|
| Focus (reading) | Vault dot only |
| Dialogue | Vault dot + Send button (cyan) |
| Suggestion | Vault dot + Apply + amber tints |
| Vault unreachable | Destructive banner dot |

---

## Peripheral Presence

Peripheral presence describes the state of elements that are visible but not focal.

**Peripheral does not mean hidden.** A peripheral element is available; it is not absent. Reading it requires a minimal attention shift, not a navigation action.

**Periphery is not a notification zone.** Peripheral elements do not animate, pulse, count, or signal urgency at rest. They are available without demanding. The one exception: tension marks pulse once per session entry, then settle.

**Peripheral legibility degrades gracefully.** A marginalia dot is partially readable at low attention (size/colour conveys rough salience) and fully readable at moderate attention (hover reveals label and state). It does not require full focus to parse at the first level.

---

## Focal vs. Ambient Modes

The surface supports two cognitive postures without an explicit mode toggle.

**Focal mode:** the user is composing, reading, or directly engaging with content. Peripheral elements should recede. The document fills available attention. Agent contributions arriving during focal mode appear in the margin at ambient weight — they do not reposition layout or demand acknowledgment.

**Ambient mode:** the user is paused, thinking, or reading at low intensity. Peripheral elements are more present. Contextual signals, trajectory marks, and marginalia are more legible.

The transition between these postures should be driven by user behavior (typing, scrolling speed, pause duration) rather than an explicit toggle. The surface adapts; the user does not switch.

---

## AI Presence and Attentional Weight

**Agent contributions should not interrupt focal mode.** A response arriving while the user is composing does not reposition layout, demand acknowledgment, or pull focus. It becomes available in the margin.

**Agent presence should be readable, not announced.** The user can tell whether the system is active, idle, or recently responded without the system drawing attention to its state.

**Agent contributions decay in peripheral weight over time.** An unengaged response gradually moves toward the far periphery. It remains available but does not compete for attention indefinitely.

---

## Non-Goals

- Component names, animation durations, or specific layout behavior — those belong to design specifications
- Salience scores, ranking algorithms, or runtime attention models — those belong to `ATTENTION_MODEL.md` and `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`
- Which elements appear in which surface states — that belongs to per-surface interaction design specifications
- Accessibility requirements — governed separately
