---
name: Companion UI Cognitive-Load Operating Model
description: Spine document for the cognitive-load capability — the human-first organizing model, authority-class vocabulary, and RQ-9 simplification-vs-authority gate that govern Companion UI load-reduction work
doc_role: Owner model / organizing reference
authority: Non-normative organizing model. Behavior authority for each surface stays with its owner contract (Panel, Workspace State, Workspace Orientation, Vault Browser, UI Runtime Boundaries) and shipped runtime truth in docs/STATUS.md. This document names and reconciles; it defines no new authority semantics and adds no APIs. Where it disagrees with an owner contract, the owner contract wins.
owner: Companion UI / product architecture
last_reviewed: 2026-06-07
source_contracts:
  - docs/COMPANION_UI_PRODUCT_SPEC.md
  - docs/PANEL_AGENT.md
  - docs/HUMAN-FLOWS.md
  - docs/ARCHITECTURE.md
  - companion-ui/docs/COMPANION_UI_STATE_MAP.md
  - companion-ui/docs/WORKSPACE_STATE_CONTRACT.md
  - companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md
  - docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md
  - docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md
governing_issue: "#1638"
implementation_state: model_normalized_from_design_handoff
---
State: Normalized organizing model derived from the cognitive-load design handoff. Reconciliation/reference doc, not a runtime contract. Captures the model as of 2026-06-07.

# Companion UI Cognitive-Load Operating Model

## Purpose

State how Companion UI should reduce cognitive load as a human-first capability without transferring authority from the human to the agent. This document is the spine for the cognitive-load track (#1638). It names the organizing principle, a UI-wide authority-class vocabulary that reconciles existing postures, and the standing RQ-9 gate every load-reduction feature must pass.

Per-surface behavior remains owned by the per-surface contracts. This model points at them and must not be read as a new write path, new memory authority, or shipped-runtime claim.

## Organizing principle

> Reduce friction, not intelligence.

The system should preserve full complexity, nuance, and source fidelity while removing mechanical friction: decoding load, spelling/encoding load, working-memory reload, resumption cost, source-finding cost, option-parsing cost, confirmation ambiguity, and proposal-review overhead.

Content is never simplified merely to save reading effort. Slow reading is not slow thinking.

## Authority-class vocabulary

Companion UI is a host/shell that arranges canonical surfaces. It is not itself an authority. Every surface carries exactly one class. The class is server-declared; the UI never infers governance, memory authority, urgency, salience, or actionability locally.

| Class | Existing posture it names | May mutate canonical | Owner |
|---|---|---|---|
| Canonical | Vault Markdown / frontmatter — the human control surface | is the source | vault; `docs/ARCHITECTURE.md` |
| Projection | Read-only projection | never | Workspace State / Orientation, Vault Browser, UI Runtime Boundaries |
| Proposal | Non-authoritative proposal/clarification | never | `docs/PANEL_AGENT.md` |
| Confirmation | Checked task item / `POST /api/panel/confirm` | via governed path only | `docs/PANEL_AGENT.md`, Panel confirmation |
| Receipt | Durable governed-execution trace | written by runtime | `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` |
| Local UI | UI-only / bounded workspace state | never | `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md` |

Mutation boundary is unchanged: only confirmation through the governed path mutates canonical state, and only through policy, WriteGuard, idempotency, and receipt linkage. Projection, Proposal, and Local UI surfaces cannot mutate canonical Markdown, receipts, provenance, memory, or interpretation.

## RQ-9 gate

Apply this gate before any cognitive-load feature ships. Reducing the cost of a decision is legitimate; reducing the decision itself is not.

- **A — Presentation only.** Re-presents the same options/decision; no semantic transform, re-classification, or summarize-as-replacement. Canonical Markdown is byte-unchanged after any reflow, restyle, or TTS.
- **B — Decision preserved.** The human still makes the same decision; no pre-checking, auto-confirm, or auto-apply. Confirm, Defer, Reject, and Clarify remain reachable and equally salient.
- **C — Consequence legible.** Consequence, risk, and reversibility are visible upfront. Provenance/source is visible, or its absence is stated.
- **D — Authority invariants.** Canonical, receipts, provenance, memory, and interpretation remain unmutated by the projection layer; any real mutation routes through WriteGuard, idempotency, and receipt with id linkage.
- **E — Automation-bias safe.** Not more persuasive without being more verifiable; no explanation-as-trust-signal; no confirm-all over governed actions.
- **F — Cognitive-load fit.** Lowers extraneous load without lowering intrinsic load by hiding the decision; one decision per surface; self-contained labels.

Verdict rule: A-F pass means legitimate load reduction. Any failure in B, C, or D is an authority transfer or semantic transformation and must be rejected or redesigned. Failures in A, E, or F are presentation issues to iterate.

## Operating model

| Area | Goal | Load risk | Authority risk | Forbidden |
|---|---|---|---|---|
| Intake / capture | Capture before loss | Encoding/spelling load | Capture read as authored fact | Silent autocorrect; capture as canonical |
| Reorientation | Recover context | Resumption lag | Re-presented context as new truth | Cold-load with no path forward (#1690) |
| Reading | Full source, low decoding cost | Decoding / crowding | Source replacement | Simplify content; speed-over-comprehension |
| Listening | Route via auditory channel | Forced redundant audio+text | Spoken summary as source | Auto-play; improved narration as source |
| Comprehension | Understand before confirming | Front-loaded reasoning | Persuasion inflates reliance | Explanation-as-trust-signal |
| Source comparison | Check claim vs source cheaply | Split-attention | Provenance lost | Hiding provenance |
| Summary review | Orient without replacing source | Access-load vs false certainty | Confirm-from-summary | Summary replaces source |
| Proposal review | Understand to decide | Density / option count | Options equal to truth | Unbounded options; reasoning upfront |
| Confirm / reject / defer | Exercise authority deliberately | Rubber-stamping | Friction erodes authority | Pre-check; confirm-all |
| Governed execution | See intent take effect safely | Opaque state | Projection treated as execution | Auto-execute; same-pass governed fire |
| Receipt review | Confirm what happened | Hidden outcome | Receipt hidden | Hiding receipt post-execution |
| Resurfacing | Right thing returns | Flood / monitoring burden | Covert re-prioritization | Surface without why-now/provenance |
| Memory / context review | Inspect remembered material | Over-offloading | Salience as memory truth | System-driven over-offloading |
| Text production | Author past spelling | Encoding load | Layer edits meaning/voice | Silent rewrite; autocorrect-on-type |
| Correction review | Accept right fix | Eye-proofreading load | Correction before decision | Silent / meaning-altering correction |
| Local display prefs | Tune to visual system | Display masks load problem | Local state becomes canonical | Writing UI state to vault |

## Information architecture

- **Work surface** — Canonical + Local UI: active note/source body, primary.
- **Source / evidence rail** — Projection: source spans, provenance, comparison.
- **Agent proposal rail** — Proposal -> Confirmation: cards, options, rail.
- **Orientation / resurfacing rail** — Projection: re-entry and scarce why-now cards.
- **Receipt / trace rail** — Receipt: receipts, blocked/stale states, trace.
- **Capture composer** — Proposal -> Confirmation: dictation-as-draft, correction-as-proposal.
- **Local render / listen controls** — Local UI: display prefs, modality, playback.

Authority is preserved spatially: proposals never appear inside the work surface; receipts never appear inside the proposal rail; local-render controls are physically separated and badged local-only.

## Cross-references

- State architecture: `companion-ui/docs/COMPANION_UI_STATE_MAP.md`
- Blocked / stale / missing states: `companion-ui/docs/BLOCKED_AND_STALE_STATE_SPEC.md`
- Local display state: `companion-ui/docs/DISPLAY_PREFERENCE_LOCAL_STATE_CONTRACT.md`
- Proposal / confirmation: `docs/PANEL_AGENT.md`
- Workspace state: `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md`
- Workspace orientation: `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md`

## Non-goals

- No new authority semantics.
- No bypass of WriteGuard, policy, idempotency, or receipts.
- No durable salience fields on artifacts.
- No simplification of content, decisions, or consequences.
- No display/listening preference writes to vault Markdown or frontmatter.
