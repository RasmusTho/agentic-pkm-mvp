# Companion UI Docs

Foundational documents for cognitive interaction architecture.

## Product architecture and hosting
- `COMPANION_UI_TARGET_ARCHITECTURE.md` — owner doc for Companion UI target architecture: local-first web app served by Yggdrasil, localhost/LAN/Tailscale access model, runtime API as the only vault access path, vault-boundary rules, current shipped state, browser dev server as the next slice, long-term options (PWA, desktop wrapper), non-goals. Governing issue: #1102.
- `LOCAL_ACCESS_MODEL.md` — local access posture for Companion UI: localhost default, LAN/Tailscale opt-in, token/session auth option, CSRF posture, dev/production separation, public internet non-goal.
- `MLP_PRODUCTION_LAUNCH_SAFETY.md` — minimal Companion UI MLP production launch safety runbook: command, port map, localhost default, LAN/Tailscale opt-in, no-public-exposure warning, readiness checks, stop/rollback, and known limitations. Governing issue: #1188.

## Core set
- `SYSTEM_OVERVIEW.md`
- `COGNITIVE_PRINCIPLES.md`
- `INTERACTION_PRINCIPLES.md`
- `COGNITIVE_MODES.md` (canonical term: cognitive postures)
- `OVERLAY_GRAMMAR.md`
- `EVENT_MODEL_SUMMARY.md`
- `UI_RUNTIME_BOUNDARIES.md`
- `FUTURE_RESEARCH.md`
- `DESIGN_BRIEF.md` (preserved source brief)

## Obsidian-compatible note surface
- `OBSIDIAN_COMPATIBILITY_MATRIX.md` — source-of-truth matrix for Obsidian syntax compatibility in Companion UI: compatibility target (Reading View-like), feature-by-feature phase assignments (adopt now / adopt soon / spike / diagnostic only / reject/defer), mutation/governance boundary, stop conditions. Workstream: Companion UI Obsidian-Compatible Note Surface.
- `VAULT_MARKDOWN_RENDERER_CONTRACT.md` — contract for read-only Companion UI rendering of vault Markdown: document model (VaultMarkdownDocument, WikiLinkRef, EmbedRef, etc.), parser/renderer/resolver responsibilities, component boundaries (VaultMarkdownRenderer, ObsidianCalloutRenderer, MermaidBlockRenderer, etc.), security model, governance boundary, test contract, editor-adapter boundary. Workstream: Companion UI Obsidian-Compatible Note Surface.

## Surface contracts and feature implementation specs
- `WORKSPACE_STATE_CONTRACT.md` — read-side aggregate contract for `GET /api/companion/workspace`, combining artifact, runtime, Canvas, Panel, suggestion, and guard state without creating a new authority surface. Governing issue: #1122.
- `CANVAS_BROWSER_EDITOR_DECISION.md` — decision record choosing `textarea` as the interim Canvas browser editor primitive and preserving full-body replacement semantics. Governing issue: #1126.
- `PANEL_STATE_DISCOVERY_DELTA.md` — Panel browser discovery gap analysis; confirms the workspace aggregate is sufficient for the current slice. Governing issue: #1127.
- `CANVAS_AGENT_MVP_CONTRACT.md` — normalized Canvas Agent MVP surface contract: co-authoring posture, session lifecycle, user-present authority, direct in-place editing, undo/rollback, `.chats/` provenance, governance-bearing escape hatch, distinction from Panel and from Canvas bounded suggestion flow. Governing issue: #1021.
- `CANVAS_SUGGESTION_FLOW.md` — normalized implementation spec for the Canvas Suggestion Flow: state machine, component inventory, intent vocabulary, backend mapping, invariants. Derived from design handoff `companion-ui/design_handoff/2026-05-11-canvas-suggestion-flow/`. Implementation contracts for #868–#874.

## Cognitive architecture consolidation set
- `TEMPORAL_COGNITION.md`
- `COGNITIVE_TRAJECTORIES.md`
- `COGNITIVE_FAILURE_MODES.md`
- `ATTENTION_MODEL.md`
- `ATTENTIONAL_PHYSICS.md`
- `POSTURE_TRANSITIONS.md`
- `SALIENCE_AND_TENSION.md`
- `TENSION_PATTERNS.md`
- `CONTINUITY_AND_DECAY.md`
- `RESURFACING_HEURISTICS.md`
- `TEMPORAL_OVERLAYS.md`
- `EPISTEMIC_EVOLUTION.md`
- `COGNITIVE_OBJECTS.md`
- `TEMPORAL_PROVENANCE.md`

## Conceptual hierarchy
- `SYSTEM_OVERVIEW.md` defines overall architectural posture and invariants.
- `TEMPORAL_COGNITION.md`, `ATTENTION_MODEL.md`, and `SALIENCE_AND_TENSION.md` define the top-level semantic frame.
- `COGNITIVE_TRAJECTORIES.md`, `CONTINUITY_AND_DECAY.md`, `ATTENTIONAL_PHYSICS.md`, `TENSION_PATTERNS.md`, `RESURFACING_HEURISTICS.md`, `TEMPORAL_OVERLAYS.md`, and `EPISTEMIC_EVOLUTION.md` own the newer temporal vocabulary.
- `COGNITIVE_OBJECTS.md`, `TEMPORAL_PROVENANCE.md`, and `POSTURE_TRANSITIONS.md` define object, lineage, and transition relationships across that frame.

## Lightweight glossary (canonical terminology)
- **Cognitive posture:** a temporary emphasis of cognition (orientation, exploration, synthesis, review, recovery), not a locked UI mode.
- **Cognitive trajectory:** a continuity-bearing line of thought across time, interruption, and resurfacing.
- **Overlay:** a continuity surface layered on the active document, never a hidden semantic store.
- **Temporal overlay:** an overlay whose purpose is temporal continuity rather than navigation chrome.
- **Resurfacing:** contextual return of latent material based on relevance, salience, and provenance.
- **Resurfacing heuristic:** a bounded rule for when dormant material should return without becoming notification pressure.
- **Provenance:** traceable lineage of why content is shown, suggested, or resurfaced.
- **Epistemic evolution:** change in understanding, confidence, framing, or interpretation over time.
- **Interruption recovery:** explicit re-entry support that restores trajectory without synthetic recap drift.
- **Continuity payload:** the minimal context package required for low-cost cognitive re-entry.
- **Latency ladder:** the ordered increase in reconstruction effort as a trajectory cools or decays.
- **Salience:** evolving attentional relevance, not a static priority flag.
- **Salience gradient:** relative difference in attentional pull across nearby cognitive objects.
- **Attentional weight:** how much attention an object meaningfully deserves in context.
- **Attentional gravity:** the tendency of some objects or tensions to pull attention back over time.
- **Cognitive tension:** unresolved pressure (question, contradiction, decision debt) that should remain visible until resolved.
- **Dormant pressure:** unresolved tension that is not focal now but still capable of resurfacing later.
- **Decay:** loss of continuity, retrievability, or interpretive clarity over time.
- **Cognitive object:** a meaning-bearing unit (thread, proposal, provenance card, tension marker) that can be reasoned about across time.

## Terminology boundary
- Terms such as `gravity`, `payload`, `ladder`, and `temperature` may be used as helpful metaphors, but the architecture remains defined by explicit semantics, not by metaphor alone.
