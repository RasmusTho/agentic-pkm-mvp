---
name: Continuity and Decay
description: "Trajectory states and latency ladder for the Companion UI: how thought continuity degrades over time and what re-entry support the surface offers per gap. Sourced from the 2026-05-08 Claude Design exploration."
type: design-reference
authority: Design vocabulary for continuity modeling; not an implementation spec or data model
related_docs:
  - companion-ui/docs/EXPERIENTIAL_PATTERNS.md
  - companion-ui/docs/ATTENTIONAL_PHYSICS.md
  - companion-ui/docs/TEMPORAL_OVERLAYS.md
  - companion-ui/docs/RESURFACING_HEURISTICS.md
  - companion-ui/docs/COGNITIVE_TRAJECTORIES.md
  - companion-ui/docs/TEMPORAL_COGNITION.md
  - companion-ui/design_handoff/2026-05-08-cognitive-temporal/temporal-s1.jsx
  - companion-ui/design_handoff/2026-05-08-cognitive-temporal/temporal-s2.jsx
  - docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md
  - docs/FINDING_AND_REORIENTING/README.md
---

State: Active design vocabulary reference. Sourced from the 2026-05-08 Claude Design exploration (temporal-s1.jsx, temporal-s2.jsx). Does not prescribe session schemas, decay algorithms, or storage formats.

# Continuity and Decay — Companion UI

This document defines trajectory states, the continuity payload, and the latency ladder that governs what re-entry support the surface provides per gap length.

---

## Purpose

Define what must be preserved for low-cost re-entry and how that preservation weakens over time.

## Metaphor boundary

- `Decay` here means loss of continuity, retrievability, or interpretive clarity, not data deletion.
- `Latency ladder` is a named sequence of re-entry shapes, not a background timing service.

## Core terms

- **Continuity payload:** the minimal context package required for low-cost cognitive re-entry.
- **Cognitive re-entry:** restoring enough context to resume a trajectory without requiring full reconstruction from scratch.
- **Interruption cost:** the attentional and cognitive effort required to resume a trajectory after a gap.
- **Temporal context reconstruction:** assembling a usable picture of prior state from preserved signals.
- **Unresolved synthesis preservation:** maintaining visibility of open cognitive tensions across session gaps so they remain addressable.
- **Latency ladder:** the ordered increase in reconstruction effort as a trajectory cools or decays.

## Decay rules

- The longer the gap, the higher the re-entry cost.
- Re-entry cost should be offset proportionally by the surface — not minimized at all gaps, but calibrated.
- Cold trajectories (>7 days — beyond the leave-point cursor TTL, ADR-0008) receive no re-entry overlay. Re-entry is through the vault and search.
- Tension does not decay on the standard curve. Open synthesis and conflicting sources hold ambient visibility until resolved.

## Architectural constraints

- Continuity payload is derived automatically. The user never declares a trajectory state.
- State transitions (Active → Warm → Dormant → Cold) are time-driven.
- The surface must never claim to reconstruct full continuity for cold trajectories.

---

## Trajectory States

Every thought-in-progress occupies one of four states. The system derives state from time and interaction; the user never declares it. From `temporal-s1.jsx` (Section 1: Interrupted trajectories).

| State | Time since last interaction | Surface expression |
|---|---|---|
| **Active** | < 90 seconds | Cursor pulse · live caret · breath animation |
| **Warm** | 90s – 2 hours | Gold spine · open-loop chip · momentum trail |
| **Dormant** | 2 hours – 7 days | Faint marginalia · decay arc · tension halo if pressured |
| **Cold** | > 7 days | No surface trace · vault-canonical only · re-entry through search |

**Invariant:** State transitions are derived, never declared. The user never marks something dormant; the system never asks. Time does the work.

Cold trajectories have no re-entry overlay. The document is ambient context only.

---

## Continuity Payload

When the user steps away, the surface captures a structured snapshot keyed to the active document. This is volatile cognitive scaffolding — not vault state — and informs re-entry reconstruction.

| Payload item | What it captures |
|---|---|
| Cursor + selection | Last caret line:col and selection range, per file |
| Scroll trail | Last ~40 viewport positions (sparse); reveals what the user lingered on |
| Open loops | Sentences ending in question, "TODO", "?", or unresolved bracket; auto-detected |
| Last query | Most recent question to the agent; lives in the trajectory, not only chat history |
| Adjacent canvas | Branches, even unsaved; cached locally with last-touched timestamp |
| Staged proposals | Pending review-mode blocks remain in place; amber treatment persists |
| Reading thread | Sequence of notes opened in this session; order matters for reconstruction |
| Tension graph | Which passages had unresolved synthesis or conflicting sources |

The snapshot is local, ~6kb, written every ~4 seconds when dirty, and purged at 30 days.

---

## Latency Ladder

The latency ladder governs which re-entry shape the surface uses per gap. From `temporal-s2.jsx` (Section 2: Re-entry ergonomics).

| Gap | Stage name | Re-entry shape |
|---|---|---|
| < 90s | **No mist** | Active state. Cursor still pulsing. Returning is identity. |
| 90s – 15m | **Thread fade** | Conversation pane fades a fraction. No card. Trajectory implicit. |
| 15m – 2h | **Soft mist** | 1-line card: "where you stopped" sentence + cursor jump. No metadata. |
| 2h – 3d | **Full mist** | All four questions answered. This is the canonical re-entry shape. |
| 3d – 7d | **Long mist** | Card + delta strip: what changed in vault, agent-found context, decayed branches. |
| > 7d | **Cold start** | No overlay. Document is ambient context only. User searches. (Leave-point cursor TTL is hard-capped at 7d, ADR-0008; re-entry beyond this window is through the vault.) |

---

## The Four Re-entry Questions

The full-mist card answers exactly four questions. No more. The shape of each answer is fixed, not negotiable per session.

1. **"What was I doing?"** — Reconstructed from edit pulses + last query + active selection. One sentence summary, never analytical. Always present.

2. **"Where did momentum stop?"** — Cursor position + last 30 seconds of edits expressed as a verbatim quoted fragment. Resume button jumps to exact caret position.

3. **"What remains unresolved?"** — Open loops + staged proposals + tension halos. Counts only, not enumerated. Click expands to inline list.

4. **"What changed since last engagement?"** — Vault diffs touching this trajectory, agent-found context, decayed items. Delta summary only, never a timeline from zero.

---

## Re-entry Mist Shape Per Gap

From `reentry-analysis.jsx`, the settled composite recommendation.

**2h – 3d:** Variant C alone — atmospheric recall. Warm tint over the document, corner glyphs glow once, gravity well at lower margin. Zero text added. The four questions are answered atmospherically, not structurally.

**3d – 7d:** Variant C + Variant B's ghost sentence, but only when the stop-state was mid-text (unfinished sentence at cursor). If the user paused on a thought without an unfinished sentence, C alone is sufficient.

**> 7d (cold — leave-point TTL expired):** No re-entry overlay. The leave-point cursor TTL is hard-capped at 7d (ADR-0008); the system does not promise recoverable re-entry beyond this boundary. Re-entry is through the vault and search.

**Invariant (from the design):** No card ever centers on the document. Re-entry is felt at the periphery. Cognition returns to the document, not to the system.

---

## What Decays vs What Stays Stable

Not everything about a trajectory decays at the same rate.

**Stays stable indefinitely:**
- The vault document and its content
- The session transcript (if persisted to vault as markdown)
- Committed decisions and explicitly captured material

**Decays at the trajectory state transitions:**
- Active → Warm (90s): The live caret pulse transitions to a gold-spine warm marker
- Warm → Dormant (2h): The open-loop chips and momentum trail contract to faint marginalia
- Dormant → Cold (7d): Surface trace disappears entirely; vault-canonical only (leave-point cursor TTL, ADR-0008)

**Tension does not decay on the standard curve.** An unresolved synthesis or conflicting source holds a mark at ambient visibility until the tension is resolved. See `RESURFACING_HEURISTICS.md` for the decay envelope model.

---

## Ambient Persistence After Re-entry

After the mist dissolves (on first keystroke or interaction), a residual ambient layer persists. Each re-entry variant leaves a different trace:

**After Variant A (whisper):** Marginalia dots remain at every prior whisper position. Caret echo (a small gold tick) marks where the user stopped. Whisper text is gone.

**After Variant B (breath):** A faint underline at the sentence-anchor remains as a resume jump target. Three faint dots in the lower-left margin. The ghost sentence is gone.

**After Variant C (atmospheric):** The warm tint persists at reduced intensity (~60% of entry level). The gravity well persists at 20% opacity if the loop is still open. Corner glyphs disappear. The caret continues its breath animation at the last-stopped line.
