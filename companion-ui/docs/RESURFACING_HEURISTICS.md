---
name: Resurfacing Heuristics
description: "Marginalia field, decay envelope, and resurfacing triggers for the Companion UI. Sourced from the 2026-05-08 Claude Design exploration (temporal-s3.jsx)."
type: design-reference
authority: Design vocabulary for ambient resurfacing; not an implementation spec or ranking algorithm
related_docs:
  - companion-ui/docs/EXPERIENTIAL_PATTERNS.md
  - companion-ui/docs/ATTENTIONAL_PHYSICS.md
  - companion-ui/docs/TEMPORAL_OVERLAYS.md
  - companion-ui/docs/CONTINUITY_AND_DECAY.md
  - companion-ui/docs/SALIENCE_AND_TENSION.md
  - companion-ui/docs/COGNITIVE_TRAJECTORIES.md
  - companion-ui/docs/EPISTEMIC_EVOLUTION.md
  - companion-ui/design_handoff/2026-05-08-cognitive-temporal/temporal-s3.jsx
  - docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md
  - docs/FINDING_AND_REORIENTING/README.md
---

State: Active design vocabulary reference. Sourced from the 2026-05-08 Claude Design exploration (temporal-s3.jsx, Section 3: Temporal resurfacing). Does not prescribe ranking algorithms, salience scores, ML models, or data schemas.

# Resurfacing Heuristics — Companion UI

This document defines the marginalia field, decay envelope, and resurfacing triggers that govern ambient resurfacing in the Companion UI. From `temporal-s3.jsx`.

---

## Purpose

Define when and why dormant material should return to attention.

## Metaphor boundary

- `Heuristic` here means bounded architectural guidance, not hidden ranking machinery or implementation scoring.

## Core rule

- Resurfacing is contextual return, not notification delivery.

## Heuristic signals

- Meaningful salience increase
- Unresolved tension with renewed relevance
- Interruption return to an interrupted trajectory
- New provenance or epistemic change affecting prior understanding
- Downstream dependency on a dormant trajectory

## Negative heuristics

- Do not resurface only because something is old.
- Do not resurface low-provenance material as strong guidance.
- Do not resurface in ways that displace the anchor document.
- Do not convert resurfacing into chat-centric or badge-centric pressure.

## Contextual resurfacing

- Prefer warm trajectories over cold ones when several candidates are relevant.
- Prefer unresolved synthesis over generic historical recap.
- Favor ambient resurfacing when attentional load is already high.

---

## What Resurfacing Is

From `EXPERIENTIAL_PATTERNS.md` and `docs/FINDING_AND_REORIENTING/README.md`:

Resurfacing answers: "this has quietly become relevant again and I would not have thought to ask."

It is not retrieval (user has a query, returns results), and it is not orientation (user has lost place, needs to be led back). It is the surface noticing, and gently making something present, without interruption.

**In the Companion UI, resurfacing is expressed specifically as the marginalia field.** From the design: "Latent knowledge appears as faint marks at the right edge of the document — sized by salience, dimmed by recency, anchored to passages. No popups, no badges, no chime. The user notices only when their eye is ready; that is the correct latency for re-attentioning."

---

## The Marginalia Field

The marginalia field is a narrow rail at the right edge of the document. It holds faint dots (MargDot) anchored to specific passages.

**Size encodes salience.** A highly salient item has a larger dot. A faint, distant item has a smaller dot.

**Opacity encodes recency.** Fresh items are at full opacity. Items that haven't been relevant for longer are progressively dimmer.

**No tooltip until hover.** The dots are visible but not legible until the user directs attention toward them. Hovering reveals the source, label, and state.

**No badge, count, or chime.** The marginalia field never announces itself. There is no counter of how many items are present. The user discovers the field by glancing at the right edge.

**Tension marks pulse once per session entry.** An unresolved tension mark pulses once when the session starts, then settles to static ambient.

Colour of marginalia dots:
- `--vault` (green): related notes, decayed items, adjacent vault edits
- `--amber`: unresolved tension, conflicting sources, synthesis drift
- `--cyan`: returning questions, recurrent echoes, decayed adjacent canvas
- `--accent` (gold): open loops anchored to the user's own prior writing

---

## Six Resurfacing Triggers

From the design, six conditions can cause a latent item to gain a marginalia mark. None produce a notification. All resolve to a visual weight on something already on screen.

| Trigger | When it fires | Surface expression |
|---|---|---|
| **Contextual proximity** | User reads a passage; vault has neighbors within k=3 hops | Faint vault dot at line; dims until eye lingers >2 seconds |
| **Temporal echo** | Today's date matches a prior session anniversary or recurring date frame | Cyan recurrent mark; surfaces once per matching day |
| **Unresolved tension** | Open loop or conflicting source persists across sessions | Amber tension halo; pulses once per session entry |
| **Synthesis drift** | A vault edit elsewhere contradicts a claim in the current draft | Amber margin mark + provenance fleck on the affected paragraph |
| **Self-trace** | Returning to a passage the user last edited mid-thought | Gold momentum trail under the paragraph for one session |
| **Decayed adjacent** | An old exploration branch touches the current cursor topic | Faint cyan dot; clicking reanimates the branch |

---

## Decay Envelope

Marginalia opacity follows a curve, not a clock. Three decay curves compose the final opacity. From `temporal-s3.jsx` (Decay envelope artboard).

**Curve 1 — Recency only:** Pure exponential. ~50% opacity at 7 days, ~10% at 30 days.

**Curve 2 — Salience-weighted:** Half-life doubles per uniqueness tier. Evergreen items persist longer; ephemeral ones fade faster.

**Curve 3 — Tension-bound:** No decay until resolved. An unresolved synthesis or conflicting source stays at ambient visibility regardless of recency. Tension never lets a mark go fully dark while a loop is open.

**Composition rule:** `final_opacity = min(recency, salience) · tension_bonus`

Tension bonus prevents the floor from reaching zero while an open loop exists.

---

## Optional Resurface Tray

From the Cognitive Modes design: the marginalia field has an optional companion, the **Resurface tray** — a ~200px sidebar listing latent items with their reason for surfacing. It is always optional and always dismissible. It is a depth layer, not the primary resurfacing surface.

The tray exists for when the user wants to engage explicitly with what the marginalia field is showing. It does not replace the ambient behavior; it supplements it for users who want to understand the full resurfacing pool.

---

## Attentional Cost Discipline

Calmness above density. The constraints held throughout the design exploration were: no dashboards, no badges, no notifications, no productivity chrome, no chat surface.

**False positives are expensive.** A dot that surfaces for an item the user finds irrelevant costs attention to register and dismiss. Repeated false positives train the user to ignore the marginalia field entirely.

**Cumulative load is real.** Many low-opacity dots still accumulate attentional weight. The design limits concurrent marks and uses opacity to signal which are most worth attention now.

**Hover is the interaction gate.** The user must direct attention to a dot to read it. This is the deliberate gate — the marginalia field should never force its content on the user.

---

## What Resurfacing Is Not

**Not a notification system.** No sound, no badge, no counter, no banner. Resurfacing is silent.

**Not retrieval.** The user did not ask a question. The surface is acting on the user's behalf, not answering a query.

**Not a timeline.** The marginalia field is not organized chronologically. It is organized spatially — anchored to the passages it relates to.

**Not a queue to be processed.** Marginalia marks are not tasks. The user is not expected to act on them. They are ambient availability, not pending items.

**Not system-generated operational artifacts.** Receipts, logs, intermediate projections, and agent-internal traces do not enter the resurfacing pool. Only vault-native human-authored material and companion notes belong there.

---

## Non-Goals

- Defining salience scores, ranking weights, or ML model specifications — those belong to implementation and `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`
- Specifying vault queries for resurfacing candidate generation — implementation concern
- Prescribing UI components for tray layout — design decisions per surface
- Managing notification or alert delivery — resurfacing is explicitly not a notification system
