State: Capability boundary contract for human-facing cognitive-load projections; docs-only, no runtime implementation claim.
Doc role: Cognitive load projection contract
Authority: Binding source-of-truth boundary for Cognitive Load Projection Layer docs and downstream issue contracts. It defines how cognitive-load aids, display preferences, listening surfaces, text-production aids, resurfacing aids, and accessibility techniques may project, render, summarize, structure, or propose changes on human-facing views without mutating canonical artifacts or changing authority. Current runtime truth remains owned by shipped implementation docs and tests.
Owner: Product / Companion UI / interaction authority
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-07
Last verified against: docs/HUMAN-FLOWS.md, docs/COGNITIVE_PROSTHESIS_CHARTER.md, companion-ui/docs/SEMANTIC_PROJECTION_ALIGNMENT.md, companion-ui/docs/VAULT_MARKDOWN_RENDERER_CONTRACT.md, companion-ui/docs/WORKSPACE_STATE_CONTRACT.md, companion-ui/docs/PANEL_CONFIRMATION_API_CONTRACT.md, app/api/routes/ingest.py, docs/research/COGNITIVE_LOAD_REDUCTION_RESEARCH.md

# Cognitive Load Projection Layer

## Purpose

The Cognitive Load Projection Layer is the governed boundary between canonical artifacts and
human-facing cognitive-load projections.

This is not an accessibility sidecar for a subset of users. In Yggdrasil, cognitive-load
reduction is one of the central functions of the cognitive prosthesis: the system helps the human
hold less in working memory, recover context after interruption, compare source and proposal, and
decide without losing authorship or authority. Accessibility techniques are valid tools inside
that function, but they are not the owning category.

Its purpose is to reduce avoidable reading, review, orientation, resurfacing, text-production, and
decision burden while preserving the system's authority spine: canonical Markdown, source
authority, WriteGuard, receipts, provenance, runtime authority, and human confirmation.

Cognitive-load reduction is a workflow capability, not a UI theme. The layer supports the Human
Flow loops `Source -> interpret -> stabilize` and `Intent -> propose -> decide -> execute -> receipt`
by making source material, proposals, risk, uncertainty, choices, and receipts easier to inspect.
It does not make projections authoritative.

The governing design principle is:

> Reduce friction, not intelligence.

The system should remove mechanical friction around decoding, parsing, remembering, spelling,
reviewing, and resuming work. It must not simplify away the human's reasoning task, flatten nuance,
hide consequences, or replace the source with a more persuasive agent projection.

## Capability Taxonomy

This work is filed under cognitive load as a central Human-First capability. Diagnosis-specific
language is useful evidence and calibration, but not the top-level product category.

The active sub-areas are:

- Working-memory load: proposal density, option count, self-contained labels, and holding-in-mind
  cost.
- Reading throughput: TTS/listening, shorter readable columns, spacing, pacing, and
  comprehension-per-effort.
- Text-production / encoding load: spelling, dictation drafts, correction suggestions,
  real-word-error flags, and read-back verification.
- Decision / confirmation load: proposal review, risk-tiering, explicit confirmation, and receipt
  visibility.
- Orientation / resumption load: `leave_point`, open loops, notable changes, and stable re-entry
  after interruption.
- Resurfacing / memory-context load: scarce, justified, non-authoritative return of relevant
  context, with pointer-first provenance and no notification-style monitoring burden.

## Core Rules

Cognitive-load projections are non-authoritative. They are not authority, not a replacement for
source artifacts, and not a hidden route around governed mutation paths.

Every projection in this layer must satisfy these rules:

- It must not mutate canonical Markdown.
- It must not alter receipts, provenance, memory extraction, runtime authority, or agent
  interpretation.
- It must preserve source visibility or explicitly state when source anchors are unavailable.
- It must distinguish source text, agent interpretation, recommendation, uncertainty, and requested
  human action when those concepts are present.
- It must keep local display preferences separate from semantic transformations.
- It must keep resurfacing scarce, source-linked, and explicitly non-authoritative; resurfacing
  presence must not become priority, urgency, or approval.
- It must treat dictation output, spelling correction, and rewriting assistance as draft or
  proposal-class until the human confirms the intended text.
- It must route any authority transfer through the existing governed confirmation or mutation path.

The layer may improve readability, listening, comparison, orientation, resurfacing, text
production, and decision review. It may not decide for the human, silently approve an agent
recommendation, silently rewrite the human's intended meaning, silently re-prioritize the human's
work, or make a summary behave as canonical truth.

## Projection Stack

```mermaid
flowchart TD
    canonical["Canonical Markdown, frontmatter, receipts, provenance"]
    runtime["Runtime and machine mirrors (indexes, aggregates, hashes, guard state)"]
    layer["Cognitive Load Projection Layer"]
    views["Human-facing views: reading, listening, resurfacing, text-production, decision, review"]
    governed["Governed mutation path: server classification, WriteGuard, receipt"]

    canonical --> runtime
    canonical --> layer
    runtime --> layer
    layer --> views
    views -->|"render, listen, compare, review"| views
    views -->|"confirm or mutate only through governed path"| governed
    governed --> canonical
```

The diagram is directional. A view can render or re-present material, but a durable change must go
through the governed mutation path before canonical artifacts change.

## Architecture Placement

This layer sits in the human-facing projection zone, aligned with Companion UI Layer 7 in
`companion-ui/docs/SEMANTIC_PROJECTION_ALIGNMENT.md`. It inherits the shared Companion UI rule that
the UI may project, render, summarize, overlay, stage, queue, and propose, but durable mutation
requires server-side classification, WriteGuard, provenance, and receipt production.

Existing contracts already define important neighbors:

- `companion-ui/docs/VAULT_MARKDOWN_RENDERER_CONTRACT.md` defines the renderer as a read-only
  projection of vault Markdown.
- `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md` defines workspace state as a read-side aggregate,
  not semantic authority.
- `companion-ui/docs/PANEL_CONFIRMATION_API_CONTRACT.md` defines
  `POST /api/panel/checkbox-projection` as the source-backed, runtime-mediated checkbox projection
  path for Panel read-mode confirmation.
- `docs/research/COGNITIVE_LOAD_REDUCTION_RESEARCH.md` supplies evidence grounding and the
  simplification-vs-authority decision test for downstream cognitive-load work.

The Cognitive Load Projection Layer does not replace those contracts. It names the cross-cutting
human-first boundary that downstream reading, listening, display, review, and decision surfaces
must satisfy.

## Display Preferences Vs Semantic Transformations

Display preferences are local, opt-in, render-only UI config. Examples include font family, font
size, line spacing, paragraph spacing, column width, contrast/theme, reduced clutter, focus mode,
optional reading-support font preference, and experimental Bionic-style rendering.

Display preferences remain render-only when they present the same source or proposal without
changing meaning, selection, recommendation, approval, receipt posture, or agent interpretation.
They must not mutate canonical Markdown, frontmatter, receipts, provenance, memory extraction,
runtime authority, agent interpretation, or content hash inputs. Canonical Markdown remains
byte-for-byte unchanged regardless of display settings.

Display preference state belongs in Companion UI workspace/local UI state. It is not canonical
knowledge, artifact metadata, frontmatter, memory input, receipt input, or source interpretation.
Future UI implementation may persist preferences locally for the browser/session, but it must not
introduce a backend API or a durable artifact write just to remember display choices.

Evidence tiers for display preferences:

| Tier | Aid | Posture |
| --- | --- | --- |
| Tier 1 | line length, column width, line spacing, paragraph spacing | Highest-priority render-only defaults and local controls because they are low-risk and user-calibratable. |
| Tier 2 | practical style guidance such as readable sans-serif font family, adequate font size, contrast/theme, ragged-right layout, reduced clutter, and focus mode | Useful local preferences, still subordinate to source review and proposal design. |
| Tier 3 | dyslexia fonts, colored overlays, and Bionic-style rendering | Experimental, optional, reversible, and off by default; never the core cognitive-load intervention. |

Semantic transformations are different. Summaries, simplifications, extracted decisions,
recommendations, risk labels, source comparisons, and reordered proposal fields can help the human,
but they change how material is interpreted. They therefore need explicit review posture:

- source or source-reference visibility;
- separation between source claims and agent interpretation;
- uncertainty and omission warnings where relevant;
- no durable write unless routed through governance;
- no authority transfer by presentation alone.

If a transformation changes what the human is considered to have approved, it is an authority
transfer and must use a governed confirmation path.

## Mode Scope

This contract scopes reading mode, listening mode, resurfacing mode, text-production mode,
decision mode, review mode, and experimental projections as projection behaviors, not
implementation claims.

### Reading mode

Reading mode presents canonical material in a lower-load layout. It may apply display preferences,
structure, spacing, focus layout, source-adjacent labels, and local navigation aids. It must not
mutate source Markdown or encode preference choices into canonical artifacts.

Reading throughput is measured as comprehension per unit effort, not raw words per minute. Shorter
columns, spacing, and similar render-only aids are valid only while they re-present the same source
content and preserve anchors, option identity, and review posture.

RQ-23 personal calibration should measure comprehension-per-effort for display/listening defaults
instead of assuming a generic accessibility preset. A lightweight calibration pass may compare
normal versus short lines, spacing levels, contrast/theme, read-only versus TTS/bimodal review,
subjective effort, time-to-decision, and short comprehension checks. Calibration output is a local
preference aid, not source truth or agent authority.

### Listening mode

Listening mode is a first-class comprehension path for the human-agent loop. It re-presents source
or projection content through text-to-speech or read-aloud ordering as a read-only projection. It
is not authority, not source replacement, and not a mutation path.

Listening must be user-controlled: no autoplay, explicit play/pause, adjustable rate, and clear
scope such as selected text, full artifact, draft, source field, proposal field, or resurfacing
card. A forced simultaneous identical audio/text stream can add load for some review tasks; the
safe contract is to support reading, listening, sequential review, or narration with
source-adjacent highlights without making one modality authoritative.

Source audio and summary audio have different authority posture. Source audio may read canonical
source text or a source-anchored excerpt. Summary audio, clarification audio, and proposal audio
remain subordinate to source review: they may help the human enter the material, but they must not
be presented as the source itself or as sufficient confirmation for governance-bearing actions.

For proposal review, the proposal-review audio order is stable: what this is, what the human needs
to decide, recommendation or option, why this is proposed, risk/uncertainty, source/reference,
available choices, and expected receipt/status. Listening must not read only the recommendation
while skipping risk, uncertainty, source reference, choices, or expected receipt/status.

For text-production, listening is verification. Dictation and correction flows close as
`draft -> TTS read-back -> human confirm -> authorized save/apply path`. Read-back must read the
actual draft or proposal text under review, not a silently cleaned, corrected, summarized, or
normalized version.

### Resurfacing mode

Resurfacing mode returns existing context to attention when the runtime has a source-linked reason
to believe it is relevant again. It is a projection/orientation aid, not a notification system, not
priority authority, and not memory promotion.

Task-support resurfacing and learning resurfacing are different modes. Task-support resurfacing
helps the human resume or orient now; it should attach to `leave_point`, open loops, notable
changes, and bounded why-now signals. Learning resurfacing is spaced retrieval practice and should
not reuse task-orientation timing or present answers as passive re-reading.

Resurfacing must be scarce, justified, non-authoritative, and cheap to consume. The safe posture is
pull-by-default with bounded foreground ambient refresh only where an owner contract admits it; no
alerts, badges, notification inboxes, urgency feeds, or focus stealing. Each surfaced item should
carry a short pointer-first "why now" with source/provenance and should remain TTS-ready.

#### FA-5 resurfacing budget and why-now contract

FA-5 is task-support resurfacing unless a later owner-doc explicitly admits a learning mode.
Task-support resurfacing restores context for action now. Learning resurfacing is spaced retrieval
practice and remains a separate future capability with separate scheduling, success metrics, and
verification. A task-support resurfacing implementation must not reuse a spaced-retrieval timer, and
a learning implementation must not present answers as passive re-reading in the orientation surface.

The contract fields are:

| Field | Contract posture |
| --- | --- |
| `items_per_orientation_moment` | Parametric display budget. The displayed subset must be scarce and may be lower than backend caps; settings may tune the exact value later, but the visible footprint must stay within the human-first working-memory and screen-space budget. |
| `foreground_refresh_frequency` | Parametric refresh budget. Default is manual pull. Any ambient refresh must be client-initiated, foreground-only, default-off, and no more eager than server-declared freshness/staleness; settings may tune cadence later without creating notification pressure. |
| `resurface_salience_threshold` | Parametric relevance threshold. If the relevance/salience signal is weak, show nothing or mark degraded. Do not manufacture a confident reason. |
| `why_now` | One short, structured pointer: trigger, source, relevance basis, and confidence/degraded posture. Prefer provenance over generated rationale. |

Parametric does not mean unbounded. When available screen space, card footprint, reading cost, or
working-memory load constrains the surface, the implementation should choose the smaller
human-first display budget and put overflow behind deliberate expansion rather than asking the owner
to decide a fixed number up front.

Budgeted resurfacing is not a ranking authority. A resurfaced item says "this may help re-orient
you"; it does not say "this is important", "this is urgent", "this is approved", "this should be
acted on", or "this belongs in memory". If filtering or ordering is used, the surface must make the
server-declared basis inspectable through `why_now`, `signal_labels`, and `source_ref`; it must not
silently re-prioritize canonical lists or open loops.

Resurfacing cards must be short, self-contained, pointer-first, source-linked, and TTS-ready. They
should surface where to resume, why this is shown now, and what source backs it. They should not
force re-reading of long note bodies, raw diffs, raw event logs, or generated persuasive rationale.
Any open/read action remains read-only. Any write, review, memory, promotion, lifecycle, or
governance action routes through the owning governed path and receipt semantics.

Audio-ready resurfacing uses the same cognitive-load budget as the visual surface, or a smaller
one when listening cost is higher. It should not turn a scarce card set into a longer audio queue.

### Text-production mode

Text-production mode supports the human while writing into the system. The current shipped surfaces
already include direct note editing, Canvas/body-edit paths, and ingest/capture routes where text
enters the system; this mode defines the boundary for future spelling, dictation, correction, and
read-back support on those surfaces.

Dictation/STT output is draft text. Spelling, grammar, real-word-error, or rewriting assistance is
a suggestion over the draft, not a silent canonical rewrite. Any assistive layer must make changed
text inspectable, preserve the human's intended meaning and voice, and leave the human as the
authority over what is saved. TTS/read-back is the preferred verification companion for
dictation/correction because visual proofreading is not the only review path.

The correction-as-proposal contract is stricter than ordinary display assistance:

- Suggestion, never silent rewrite. No assistive layer edits user-authored text automatically.
  Autocorrect-on-type is prohibited because it acts before the human decides and can silently
  replace the intended word with a wrong real word.
- Transparency of every change. Each proposed change must show the original token and proposed
  token. Anything beyond a pure spelling fix must also show why it is being suggested.
- Canonical content remains untouched until confirmation. Confirmed corrections route through the
  authorized save/apply path for the current surface: direct note save, ingest/capture submission,
  Canvas user-present body-edit with undo/session-log provenance, staged Canvas body suggestion, or
  Panel/governed execution when the operation is governance-bearing. Do not invent a stronger
  receipt claim than the owning surface provides.
- Meaning-affecting changes require more friction than spelling fixes. Orthographic fixes,
  real-word/context flags, and grammar/phrasing rewrites must be visually and procedurally
  distinct.
- Voice and meaning belong to the human. Stylistic smoothing is out of scope unless explicitly
  requested for the current instance and shown as a reviewable proposal.

Correction tiers:

| Tier | Class | Example | Required posture |
| --- | --- | --- | --- |
| 0 | Orthographic | `recieve` -> `receive` | Light confirmation; still not automatic. |
| 1 | Real-word / context flag | `form` possibly `from` | Flag only; never auto-apply because intent is inferred. |
| 2 | Grammar / phrasing / voice | rewriting a sentence | Most explicit confirmation; default is keep the user's text. |

The selection problem is part of the contract. A suggestion list should stay small, offer
read-aloud on focus, include a short meaning cue such as a definition or the word in the user's own
sentence, and always expose a clear "keep mine" path.

Dictation closes through listening: dictate, draft, TTS read-back, then human confirm. Read-back is
required for dictation support because it routes verification through listening rather than forcing
proofreading only by eye.

### Decision mode

Decision mode structures a proposal or choice so the human can understand what is being decided.
It should separate what this is, what the human needs to decide, recommendation or option, why,
risk or uncertainty, source or source reference, available choices, and expected receipt or status.
It must not default governance-bearing choices to approved.

### Review mode

Review mode helps the human compare a projection to its source, inspect uncertainty, recover after
interruption, and audit what happened. It should keep status and receipt feedback visible after a
governed action.

### Experimental projections

Experimental projections include weakly supported or highly user-specific aids such as Bionic-style
rendering or reading-support font presets. They must be opt-in, reversible, render-only where
possible, clearly marked as experimental, and disabled by default unless a later owner-doc update
changes that posture.

## Decision Test

Use this test before implementing or documenting a cognitive-load projection:

| Question | Projection class | Required route |
| --- | --- | --- |
| Does it only change visual or auditory presentation of the same content? | Display preference | Keep local and render-only. |
| Does it summarize, simplify, rank, filter, recommend, or explain? | Semantic transformation | Preserve source and review posture. |
| Does it resurface, rank, filter, or reorder context for attention? | Resurfacing projection | Show source-linked why-now, respect budget/caps, and do not make resurfacing priority or authority. |
| Does it correct, rewrite, or transcribe human-authored input? | Draft/proposal over text input | Show the change and require human confirmation before canonical save. |
| Does it silently autocorrect, smooth, or normalize style? | Authority/voice transfer | Reject unless the human explicitly requested that specific proposal and can review it. |
| Does it change what the human is considered to have approved? | Authority transfer | Route through governed confirmation. |
| Does it write canonical Markdown, receipts, provenance, memory extraction inputs, runtime authority, or agent interpretation? | Durable or authority-bearing mutation | Use an owner-doc contract, WriteGuard, and receipt path. |

The safe default is to downgrade a projection to non-authoritative review aid unless the governing
contract explicitly grants stronger behavior.

## Downstream Issue Guidance

Downstream issues should use this layer as a boundary, not as implementation evidence.

- #1641 should specify reading/listening requirements against this non-authoritative projection
  posture.
- #1642 should normalize proposal format as a decision surface without weakening confirmation
  authority.
- #1643 should specify display preferences as render-only projections.
- #1645 should implement confirmation only through the existing checkbox projection endpoint and
  should not treat this contract as permission to bypass `PANEL_CONFIRMATION_API_CONTRACT`.
- A follow-up text-production issue should specify dictation, correction-as-proposal,
  real-word-error flagging, and read-back verification against the existing direct note editor and
  Canvas/body-edit surfaces.
- #1662 defines FA-5 against the shipped Workspace Orientation and resurfacing seams: backend caps
  versus scarce displayed budgets, pull-default, bounded foreground ambient refresh, pointer-first
  why-now provenance, and the task-support-versus-learning split.
- A browser-local TTS/read-back MVP should use local UI state and browser playback where available,
  add no backend API, avoid autoplay, and keep `/api/companion/note/save` and
  `POST /api/panel/checkbox-projection` as the unchanged save/confirmation paths.
- A local display-preferences UI slice should apply CSS/classes over the rendered view only, add no
  backend API, and prove the canonical body/content hash is unchanged when preferences change.

## Non-Goals

- This document does not implement runtime behavior.
- This document does not implement Companion UI controls.
- This document does not implement text-to-speech.
- This document does not implement resurfacing budgets, ambient refresh, notifications, or learning
  schedules.
- This document does not implement dictation, spellchecking, or correction assistance.
- This document does not implement display preferences.
- This document does not change Panel confirmation semantics.
- This document does not create durable reject, defer, or clarify semantics.
- This document does not make summaries, simplifications, or listening output authoritative.
