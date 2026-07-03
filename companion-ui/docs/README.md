# Companion UI Docs

Foundational documents for cognitive interaction architecture.

> Semantic alignment: `SEMANTIC_PROJECTION_ALIGNMENT.md` maps every Companion UI contract onto Layer 7 (UI projection) of `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md` — the shared projection/mutation/authority/runtime-overlay rules these contracts must satisfy. Read it before changing any Companion UI contract.

## Governance and terminology
- `CORE_TERM_MAPPING.md` — normalization reference mapping Claude Design language to Yggdrasil/Companion UI architecture language; the term-mapping authority for design handoffs.
- `DESIGN_HANDOFF_GOVERNANCE.md` — defines the handoff chain by which Claude Design explorations become normalized implementation inputs; governance chain SoT.

## Product architecture and hosting
- `COMPANION_UI_TARGET_ARCHITECTURE.md` — owner doc for Companion UI target architecture: local-first web app served by Yggdrasil, localhost/LAN/Tailscale access model, runtime API as the only vault access path, vault-boundary rules, current shipped state, browser dev server as the next slice, long-term options (PWA, desktop wrapper), non-goals. Governing issue: #1102.
- `LOCAL_ACCESS_MODEL.md` — local access posture for Companion UI: loopback bind default, explicit LAN/Tailscale opt-in, token/session auth option, CSRF posture, dev/production separation, public internet non-goal.
- `MLP_PRODUCTION_LAUNCH_SAFETY.md` — minimal Companion UI MLP production launch safety runbook: command, port map, loopback default, explicit LAN/Tailscale opt-in, no-public-exposure warning, readiness checks, stop/rollback, and known limitations. Governing issue: #1188.
- `PRODUCTION_EXPOSURE_SECURITY_PROFILE.md` — network exposure, auth, CSRF/CORS, rendering, and authority posture for Companion UI production-readiness review; exposure-security companion to `LOCAL_ACCESS_MODEL.md`. Governing issue: #1589.
- `LOCAL_FIRST_TTS_CONTRACT.md` — shipped local-only TTS planning and synthesis boundary for Companion UI read-back; server-side local TTS by default, no cloud fallback in this contract.

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

## Daily-use visibility
- `COMPANION_UI_DAILY_USE_VISIBILITY_CONTRACT.md` — what is always visible vs. behind disclosure vs. suppressed when disabled: dev controls, runtime identity, Panel deduplication, vault browser filtering, read-only body affordance, frontmatter humanization. Governing issue: #1361.
- `BLOCKED_AND_STALE_STATE_SPEC.md` — binding UX/state contract for held-boundary states: WriteGuard-blocked, stale-source, identity mismatch, and idempotent already-confirmed presentation.
- `DISPLAY_PREFERENCE_LOCAL_STATE_CONTRACT.md` — binding contract for local, non-authoritative display/listening preference state and byte-unchanged canonical Markdown. Governing issues: #1643, #1675.
- `COMPANION_UI_VISUAL_ALIGNMENT_GUIDE.md` — non-normative token and component guidance for aligning the live Python/Jinja2 + Tailwind Companion UI with the cognitive-load handoff.

## Surface contracts and feature implementation specs
- `WORKSPACE_STATE_CONTRACT.md` — read-side aggregate contract for `GET /api/companion/workspace`, combining artifact, runtime, Canvas, Panel, suggestion, and guard state without creating a new authority surface. Governing issue: #1122.
- `WORKSPACE_ORIENTATION_CONTRACT.md` — shipped read-only contract for `GET /api/companion/orientation`, including the structured leave-point projection admitted by ADR-0008 and bounded MemoryCandidate intent seam admitted by ADR-0009. Governing issues: #1454, #1455, #1457.
- `CANVAS_BROWSER_EDITOR_DECISION.md` — decision record choosing `textarea` as the interim Canvas browser editor primitive and preserving full-body replacement semantics. Governing issue: #1126.
- `PANEL_STATE_DISCOVERY_DELTA.md` — Panel browser discovery gap analysis; confirms the workspace aggregate is sufficient for the current slice. Governing issue: #1127.
- `CANVAS_AGENT_MVP_CONTRACT.md` — normalized Canvas Agent MVP surface contract: co-authoring posture, session lifecycle, user-present authority, direct in-place editing, undo/rollback, `.chats/` provenance, governance-bearing escape hatch, distinction from Panel and from Canvas bounded suggestion flow. Governing issue: #1021.
- `CANVAS_SUGGESTION_FLOW.md` — normalized implementation spec for the Canvas Suggestion Flow: state machine, component inventory, intent vocabulary, backend mapping, invariants. Derived from design handoff `companion-ui/design_handoff/2026-05-11-canvas-suggestion-flow/`. Implementation contracts for #868–#874.
- `SYSTEM_ENTRY_POINT_SPEC.md` — normalized spec for the System Entry Point and unified-shell composition: entry-point state enum (boot / no_vault / cold_start / orienting / shell_active), re-entry shapes per the latency ladder, data-attribute and intent vocabularies, surface composition table (shipped vs new per surface), and resolutions for the package's open questions (Q4–Q9, Q17–Q19; Q15–Q16 parked). Derived from design handoff `companion-ui/design_handoff/2026-06-09-system-entry-point/`. Feature breakdown: `docs/SYSTEM_ENTRY_POINT/`.
- `ADAPTIVE_WORKSPACE_LAYOUT_HANDOFF.md` — design-input handoff for a corrective UI/layout pass on the Companion UI / Vault Browser workspace, subordinate to shipped contracts. Parent issue: #1395; child issues #1396–#1401.
- `COMPANION_UI_STATE_MAP.md` — normalized, non-normative status map of Companion UI product modes and surfaces (shipped/dev-staging vs target-state) ahead of Resurface and Act slicing.
- `VAULT_BROWSER_UI_REQUIREMENTS.md` — binding requirements input for downstream Vault Browser / Workspace UI implementation, derived from user UAT feedback and the Claude Design Vault Browser Foundation handoff. Source issue: #1286.
- `REAL_NOTE_WORKSPACE_DEV_PAGE.md` — dev/staging-only status page documenting the Real-Note Workspace dev page's visual-alignment history; not a production UI contract.
- `MLP_CAPABILITY_MATRIX.md` — current-state classification matrix for visible Companion UI MLP affordances against implementation evidence, foundation for #1177 MLP implementation. Related issues: #1177–#1180.
- `MLP_INTERACTION_DESIGN_HANDOFF.md` — curated, subordinate MLP interaction-design handoff translating Claude Design delivery into implementation-ready slices. Related issues: #1177–#1180.

## Panel contracts
- `PANEL_COMPANION_UI_CONTRACT.md` — SoT surface contract for Panel as the artifact-local intent manifestation and confirmation surface: conceptual model, render states, confirmation write-back, surface boundaries.
- `PANEL_CONFIRMATION_API_CONTRACT.md` — binding API contract for Panel confirmation transport and the runtime-mediated checkbox projection endpoint: request/response schema, source freshness, idempotency, blocked/receipt semantics. Governing issue: #1042.
- `PANEL_DURABLE_PROJECTION_MAPPING.md` — binding mapping from Panel confirmation/execution outcome to vault-visible state: checkbox semantics, receipt callout, event emissions, inverse-action, watcher compatibility, runtime-sole-writer rule. Governing issue: #1043.

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
- `EXPERIENTIAL_PATTERNS.md` — phenomenological interaction vocabulary (attentional feel, continuity restoration, ambient cognition); design vocabulary, distinguished from architectural semantics.

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
