---
name: Temporal Overlays
description: "Temporal cognition design vocabulary for the Companion UI: cognitive tension, temporal provenance, and how time-aware context is incorporated without producing timeline UIs. Sourced from the 2026-05-08 Claude Design exploration."
type: design-reference
authority: Design vocabulary for temporal context surfacing; not an implementation spec
related_docs:
  - companion-ui/docs/EXPERIENTIAL_PATTERNS.md
  - companion-ui/docs/ATTENTIONAL_PHYSICS.md
  - companion-ui/docs/CONTINUITY_AND_DECAY.md
  - companion-ui/docs/RESURFACING_HEURISTICS.md
  - companion-ui/docs/OVERLAY_GRAMMAR.md
  - companion-ui/docs/TEMPORAL_PROVENANCE.md
  - companion-ui/docs/TEMPORAL_COGNITION.md
  - companion-ui/design_handoff/2026-05-08-cognitive-temporal/Temporal Cognition.html
  - companion-ui/design_handoff/2026-05-08-cognitive-temporal/temporal-s4.jsx
  - companion-ui/design_handoff/2026-05-08-cognitive-temporal/temporal-s5.jsx
  - docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md
  - docs/FINDING_AND_REORIENTING/README.md
---

State: Active design vocabulary reference. Sourced from the 2026-05-08 Claude Design exploration (Temporal Cognition.html, temporal-s4.jsx, temporal-s5.jsx). Does not prescribe data models, event schemas, or frontend components.

# Temporal Overlays — Companion UI

This document defines how temporal context is expressed in the Companion UI. The design frames this as **temporal cognition** — a broader concern than simply showing timestamps or activity recency. It covers: trajectory states, re-entry ergonomics, temporal resurfacing (covered in depth in companion docs), cognitive tension, and temporal provenance.

The organizing principle from the design: *"continuity of thought across interruption · ambient, document-anchored, non-disruptive."*

---

## Purpose

Define overlays whose role is preserving continuity across time rather than simply exposing controls.

## Metaphor boundary

- `Temporal overlay` is an architectural classification.
- It does not imply background automation, notification feeds, or hidden timing state.

## Canonical temporal overlay functions

- Re-entry cueing
- Continuity payload exposure
- Provenance glanceability
- Resurfacing without route replacement
- Decay mitigation through compact context reconstruction

## Rules

- Temporal overlays must preserve the document as anchor.
- Temporal overlays must be dismissible without semantic loss.
- Temporal overlays must reduce interruption cost, not amplify it.
- Temporal overlays must not become notification-centric or dashboard-like.
- Temporal overlays must not hide meaning-bearing state from the vault.

## Examples of temporal overlay roles

- Recovery strip showing prior intent and unresolved tension
- Provenance peek explaining why something resurfaced now
- Compact continuity card for warm trajectory re-entry

---

## What Temporal Overlays Are Not

**Not a timeline.** A timeline makes time the primary navigation axis. Temporal overlays are contextual signals subordinate to the document.

**Not an activity feed.** An activity feed presents events as content to be consumed in reverse-chronological order. Temporal overlays exist as background to the document, not as content.

**Not a notification layer.** Temporal overlays do not alert, pulse, badge, or count. They express state through visual weight.

**Not timestamps on every element.** Stamping times on all visible content makes time a constant low-level noise. Temporal context surfaces only where it changes the user's interpretation.

---

## Temporal Context Scope

The temporal cognition design covers five areas. The first three are documented in depth in companion docs; the last two are documented here.

1. **Interrupted trajectories** — trajectory states (Active/Warm/Dormant/Cold) and the continuity payload. See `CONTINUITY_AND_DECAY.md`.
2. **Re-entry ergonomics** — the mist variants, latency ladder, and the four re-entry questions. See `CONTINUITY_AND_DECAY.md` and `EXPERIENTIAL_PATTERNS.md`.
3. **Temporal resurfacing** — the marginalia field, decay envelope, and six triggers. See `RESURFACING_HEURISTICS.md`.
4. **Cognitive tension** — unresolvedness, conflict, incomplete synthesis. Documented here.
5. **Temporal provenance** — how understanding evolved, what changed, where uncertainty moved. Documented here.

---

## Cognitive Tension

Cognitive tension is the design vocabulary for unresolvedness that persists across sessions. From `temporal-s4.jsx` (Section 4: Cognitive tension). The design's framing: *"Tension is not a number. It has a shape. The shape determines the visual."*

Four shapes of cognitive tension, each with a distinct visual treatment:

### Open Loop

*"One question waits for an answer."*

A single thread that is explicitly unfinished. Shape: a dotted trajectory line with a gold dot at the open end.

Surface expression: an open-loop chip (`OpenLoop` component from `temporal-primitives.jsx`) anchored to the passage it belongs to. Shows the loop text and its age. Persists in the marginalia field until resolved.

The tension halo (radial amber glow) scales with pressure intensity — how long the loop has been open and how many other sessions touched it without resolving it.

### Conflict

*"Two interpretations, refused merge."*

Sources or claims actively disagree. The draft cannot proceed by picking one silently. Shape: an X — two lines crossing, endpoints marked.

Surface expression: an amber break in the draft where the two sides diverge, both sides preserved with provenance. No merge is forced. The conflict stays legible until the user resolves it deliberately.

### Incomplete Synthesis

*"Multiple sources drawn in; draft incomplete."*

Several sources are in play, draft is partially assembled, but the synthesis has not landed. Shape: a triangle with one side open.

Surface expression: a green-bordered synthesis block showing source count, conflict count, and draft completion percentage. Persists until the synthesis either closes or is abandoned.

### Dormant Pressure

*"Something is pulling without being named."*

Not a specific question or conflict — a diffuse sense that a body of material has unresolved weight. Often the result of several smaller tensions that were never individually surfaced.

Surface expression: the gravity well in Variant C of the re-entry mist — a radial pressure indicator in the lower margin, present whenever dormant pressure is above threshold.

---

## Tension Does Not Decay

Tension marks in the marginalia field do not follow the standard recency curve. From the design: *"Tension never lets a mark go fully dark while a loop is open."*

The decay composition rule: `final_opacity = min(recency, salience) · tension_bonus`. The tension bonus prevents the mark from reaching zero until the tension is explicitly resolved.

This is what makes tension visually distinct from ordinary resurfacing marks: tension marks stay bright even when old.

---

## Temporal Provenance

Temporal provenance is the design vocabulary for the evolution of understanding over time. From `temporal-s5.jsx` (Section 5: Temporal provenance): *"how understanding evolved · what changed · where uncertainty moved."*

The design presents provenance as a **paragraph genealogy**: a single paragraph's evolution across revisions, each revision state named and attributed.

From the design's example, a paragraph can move through states:
- **Seed** — first capture, often from an agent suggestion or rough phrase
- **Expanded** — user revision, elaboration
- **Contested** — a conflict introduced from a new source, both sides preserved
- **Synthesized** — user reframing that resolves the conflict, often by elision or reframing
- **Active** — current state, possibly with an open loop if the synthesis is still incomplete

Each state is attributed: user revision, agent suggestion, source citation, conflict introduced by which note.

### What Provenance Enables

Provenance allows the user to answer:
- *How did I arrive at this claim?*
- *What was I uncertain about here, and did I resolve it?*
- *This looks odd — when did I change this, and why?*
- *What would I lose if I accepted Hugin's suggestion here?*

### Provenance in the Surface

The design shows two provenance interaction forms:

**Genealogy strip:** A depth-layer view of a paragraph's revision history. Not ambient — accessed deliberately. Shows the temporal spine, revision states, text at each state, and attributions.

**Diff lens:** A focused comparison between two states — what changed, what was preserved, what provenance tags moved. Also a depth-layer view, not ambient.

**Provenance flecks:** Small marks on the current paragraph that signal it has provenance depth available. Visible in the ambient view; tapping opens the genealogy.

### What Provenance Is Not

Provenance is not a version control UI. The user is not expected to review diffs as a workflow. Provenance is available when the user wants to understand the history of a claim; it does not announce itself or demand engagement.

---

## Temporal Language

The surface should use natural temporal language rather than exact timestamps in the ambient view.

Exact timestamps belong in detail layers. Ambient temporal language ("4 days ago," "last month," "2 hours idle") provides orientation without requiring arithmetic.

Temporal language should be consistent across the surface: "3 days ago" not "72 hours ago" for the same item. The design uses natural time spans throughout.

---

## Non-Goals

- Designing a version control or audit log UI
- Specifying timestamp schemas, event models, or how the runtime tracks session timing
- Real-time synchronization indicators or live-update patterns
- Animation or transition behavior for temporal context arrival — those are implementation decisions
