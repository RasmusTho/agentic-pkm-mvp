State: Target-state product specification. Docs-only. No runtime behavior changes in this PR.
Doc role: Core SoT companion (product specification)
Authority: Defines the Companion UI product model that hosts the canonical interaction surfaces and maps cognitive prosthesis functions to user-facing modes.
Owner: Product / interaction model
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-05-12
Last verified against: docs/COGNITIVE_PROSTHESIS_CHARTER.md, docs/HUMAN-FLOWS.md, docs/HUMAN_FLOW_TO_RUNTIME_MAP.md, docs/COGNITIVE_LOAD_PROJECTION_LAYER.md, docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md, docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/NAME_THE_THREE_INTERACTION_SURFACES.md, docs/FINDING_AND_REORIENTING/README.md, docs/STATUS.md

# Companion UI Product Spec

## Purpose

Define Companion UI as the human-facing product shell for Yggdrasil's cognitive prosthesis
functions.

Companion UI is not a fourth interaction authority surface. It hosts and coordinates the
canonical surfaces:

- Panel
- Chat
- Automation

The authoritative interaction-surface model remains defined in
`docs/INTERACTION_SURFACES_AND_AUTHORITY/NAME_THE_THREE_INTERACTION_SURFACES.md`.

## Product stance

Companion UI is a host/shell/product experience that organizes cognitive work into four user-facing
modes:

1. Find
2. Reorient
3. Resurface
4. Act

These modes are product affordances over existing authority and contract boundaries. They do not
replace authority sources.

## Current-state guardrail

This document uses target-state product language. It does not claim that all described behavior is
currently shipped.

Current shipped runtime truth is owned by:

- `docs/STATUS.md`
- `docs/ARCHITECTURE.md`
- capability owner docs and concept contracts linked below

## Mode Model

### 1) Find

- Human question it answers: "Where is the thing I need, and what is the best source to cite?"
- Cognitive burden it reduces: manual recall, repeated search, and uncertainty about source quality.
- Primary surface(s): Chat and Panel (hosted within Companion UI).
- Supporting runtime capabilities: retrieval capability contract; context-bundle assembly for scoped
  evidence.
- Context bundle usage: assembled bundle should include selected sources, scope/context framing,
  and provenance for why material was returned.
- Agent memory usage: none by default; retrieval output must not silently become memory or knowledge.
- Provenance/receipt expectations: each answer should expose source citations and inspectable
  retrieval basis.
- Authority limits: Find can present and summarize; it cannot promote retrieved material into
  durable knowledge without explicit governed flow.
- Failure modes:
  - irrelevant but plausible results;
  - source laundering (claim without citation);
  - stale retrieval context not labeled stale.
- Target-state UX behavior: user sees candidate sources, citations, and scope; can inspect why each
  source appeared.
- Current-state caveat: retrieval and related diagnostics are partially shipped; exact UX assembly
  varies by current runtime surface and flags.

### 2) Reorient

- Human question it answers: "What was I doing, what changed, and what should I do next?"
- Cognitive burden it reduces: interruption-recovery overhead and reloading situational context from
  scratch.
- Primary surface(s): Chat-first orientation views, with Panel handoff for explicit moves.
- Supporting runtime capabilities: orientation capability contract; context-bundle assembly from
  notes, recent activity, receipts, and allowed memory candidates.
- Context bundle usage: reorientation bundle should separate current frame, recent deltas, open
  loops, and confidence labels.
- Agent memory usage: allowed as candidate support when contract-permitted; memory must be labeled
  as memory-derived and not treated as hidden authority.
- Provenance/receipt expectations: orientation output should distinguish facts, inferences,
  candidate actions, and stale context.
- Authority limits: Reorient can synthesize and propose; it does not execute actions on its own.
- Failure modes:
  - inferred state presented as fact;
  - stale context presented as current;
  - next-action suggestions without basis transparency.
- Target-state UX behavior: user receives an orientation frame with explicit sections for
  facts/inferred/candidates/stale and can jump to sources.
- Current-state caveat: bounded orientation runtime seams exist, but full target-state orientation UX
  assembly is not yet baseline.

### 3) Resurface

- Human question it answers: "What quietly important thing should return to attention now?"
- Cognitive burden it reduces: missed follow-up, forgotten relevance, and re-orientation effort
  after attention drift.
- Primary surface(s): Companion orientation/resurface areas across Chat/Panel host context. The
  baseline posture is pull/snapshot/read-only; ambient refresh is bounded foreground refresh only
  where ADR-0011 or a successor owner decision admits it.
- Supporting runtime capabilities: resurfacing capability contract; relevance-change signals;
  context-bundle support for explanation.
- Context bundle usage: resurfacing bundle should carry why-now signals, linked artifacts, and
  relation context.
- Agent memory usage: optional contextual hinting; memory contribution must be explicit and
  reviewable.
- Provenance/receipt expectations: resurfacing should explain "why now" with short
  pointer/provenance-first signals and keep semantic relatedness distinct from priority, trust,
  authority, and actionability.
- Authority limits: Resurface can suggest; it must not escalate to urgent-task semantics unless
  explicitly promoted/escalated. Resurfacing presence must not become approval, urgency, memory
  promotion, or write authority.
- Failure modes:
  - semantic similarity mistaken for urgency;
  - suggestion pressure that feels mandatory;
  - hidden ranking logic with no explanation.
- Target-state UX behavior: scarce, low-pressure, source-linked suggestions with clear actions:
  inspect, dismiss, snooze, or pin when those actions are explicitly scoped. No alert, badge,
  notification inbox, focus stealing, or persistent monitoring stream is implied by this mode.
- Current-state caveat: minimal resurfacing runtime seams exist; full product-surface suggestion
  orchestration remains target-state. The read-only card surface carries the "scarce glance, not a
  feed" treatment (Claude-Design pass): scarce bordered cards capped to a server-declared scarce
  count, pinned cards sorted to the top with a cool "pinned" tag, provenance-first why-now, a single
  cool relation glyph, source pointer, receded disabled actions, a settled-green "at rest" empty
  that is unmistakable from the amber "can't say" degraded state, and a withheld line that signals
  "more was held below the line" without any count or badge. The resurfacing runtime declares
  `scarce_count` and `more_held_back` and tags each candidate with a read-only `pinned` flag (always
  false until pin persistence lands). With today's ≤3-signal evaluator the surfaced set never exceeds
  the scarce count, so `more_held_back` stays false in practice and the withheld line and scarce cap
  remain dormant until a richer relevance source surfaces more candidates than the cap; likewise the
  pinned sort/tag does not fire while `pinned` is always false. The dismiss/snooze/pin actions remain
  disabled pending persistence, and the underlying suggestion/ranking orchestration is still
  target-state.

### 4) Act

- Human question it answers: "How do I turn intent into a governed, completed change?"
- Cognitive burden it reduces: coordination overhead between deciding, executing, and documenting
  outcomes.
- Primary surface(s): Panel as command-oriented authority surface; Chat for proposal/clarification;
  Automation for governed background execution where applicable.
- Supporting runtime capabilities: trust semantics, governance router, write guards, receipt
  generation, event/intent contracts.
- Context bundle usage: action bundle provides intent context, affected artifacts, proposal basis,
  and execution constraints.
- Agent memory usage: optional assistive recall; never a substitute for explicit authority.
- Provenance/receipt expectations: action flow must preserve `intent -> propose -> decide -> execute
  -> receipt` and produce inspectable receipts.
- Authority limits: Act must not bypass write guards; must distinguish propose, stage, apply, and
  log.
- Failure modes:
  - applying changes from proposal context without explicit decision;
  - stage/apply boundaries blurred;
  - missing or incomplete receipts.
- Target-state UX behavior: explicit proposal review, staged actions, guarded apply, and durable
  receipt visibility.
- Current-state caveat: parts of this flow are shipped across Panel/runtime contracts; broader
  unified Companion UX remains target-state.

## Companion UI Principles

- Context must be inspectable.
- Suggestions must be dismissible.
- Writes must be staged before applied unless explicitly authorized by contract.
- Chat is not source of truth.
- Agent memory is not hidden authority.
- Human-readable artifacts remain primary.
- Cognitive-load support is central to the Companion experience: reduce decoding, parsing,
  spelling, review, and resumption friction without simplifying away the human's reasoning task.
- Review surfaces should be verifiability-first: source and consequences stay reachable before an
  agent projection becomes a decision.
- The UI should reveal enough system state to support trust without exposing unnecessary runtime
  machinery.

## Mode Transition Model

Allowed transitions:

- Find -> Reorient
- Reorient -> Act
- Resurface -> Find
- Resurface -> Dismiss / Snooze / Pin
- Act -> Receipt -> Review
- Review -> Memory candidate / Promotion / Archive

Transition intent:

- Find may trigger Reorient when located material indicates the user needs broader situational
  reconstruction.
- Reorient may trigger Act when the user confirms a concrete next move.
- Resurface may trigger Find when the user wants source inspection before deciding significance.
- Review is where memory-candidate handling remains explicit and governed.

## UX States (Target State)

- `idle`
- `searching`
- `context assembled`
- `answer generated`
- `orientation assembled`
- `suggestion available`
- `proposal staged`
- `write blocked`
- `write applied`
- `receipt available`
- `memory candidate pending review`

These are product-facing states and should not be interpreted as current runtime API guarantees.

## Authority And Safety

Companion UI may:

- present suggestions;
- host human decisions;
- display runtime state.

Companion UI must not:

- become a source of authority itself;
- bypass contracts, write guards, or human decisions;
- treat memory, chat output, or UI state as authoritative by default.

Authority comes from:

- contracts;
- events and receipts;
- write guards;
- explicit human decisions;
- owner docs.

## Runtime control actions

The UI transports human intent into the system across multiple interaction origins (UI, CLI, file
edit, and future MCP/API). The authoritative register for which control actions the UI may initiate
and how they route is maintained in `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md :: Control-action
register` and in
`docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_RUNTIME_CONTROL_ACTION_BOUNDARY.md`.

The canonical two-tier classification:

1. **Vault binding (pre-init)** — vault select / init / reload. Routes through app-local / WSP
   binding, not vault-scoped governance. The vault is not yet initialized, so this is the human's
   only surface.

2. **Runtime gating (post-init)** — `enableVaultWatcher` / `enableAutoIndexing`. These are
   authority-bearing: they reconfigure whether the watcher/indexing runtime runs. Writes route
   through the single server-side governed seam: WriteGuard health-gate + actor-tagged
   `SettingsWriteReceipt` (who / surface / when). No human/agent approval loop — a human may
   already flip these via a direct hand-edit of `settings/local.md` (the file-originated door).
   The receipt is wired for the **API/CLI door only** (caller: `app/api/routes/companion.py:826`).
   The file-originated door (watcher-detected delta → `surface='file'`) is NOT yet wired; tracked
   by #2512.

3. **External-boundary enable** — TTS provider enable. EBF applies; not re-decided here
   (`#2086`/`#1699`).

The UI is the **transport** of human intent; it is not itself the authority. The server classifies
the write and applies the deterministic governance gate. The UI never re-derives authority from the
response.

## Safe Onboarding Path

1. Find with citations.
2. Reorient around one project or note.
3. Resurface related material with dismiss/pin controls.
4. Act through propose/stage/apply.
5. Review memory candidate.
6. Inspect receipt.

This sequence is designed to teach trust boundaries before higher-autonomy behaviors.

## Non-Goals

- Not a generic chatbot.
- Not a replacement Obsidian editor.
- Not an autonomous agent control room.
- Not a hidden memory store.
- Not a bypass around write guards.
- Not a new source of truth.

## References

- `docs/COGNITIVE_PROSTHESIS_CHARTER.md`
- `docs/HUMAN-FLOWS.md`
- `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `docs/FINDING_AND_REORIENTING/README.md`
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/NAME_THE_THREE_INTERACTION_SURFACES.md`
- `docs/STATUS.md`
