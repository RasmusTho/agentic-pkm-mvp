State: research synthesis (analysis, docs-only; non-normative).
Doc role: Research
Authority: Evidence grounding for cognitive-load reduction issue #1644. This memo can inform
downstream issue contracts and owner-doc proposals, but it does not override current-state owner
docs, Panel runtime contracts, Companion UI contracts, or shipped implementation truth.
Owner: `docs/HUMAN-FLOWS.md` / Companion UI and Panel downstream issue lanes
Last reviewed: 2026-06-07
Last verified against: docs/HUMAN-FLOWS.md, docs/COGNITIVE_PROSTHESIS_CHARTER.md,
docs/COGNITIVE_LOAD_PROJECTION_LAYER.md, docs/PANEL_AGENT.md, companion-ui/docs/PANEL_CONFIRMATION_API_CONTRACT.md,
app/panel/checkbox_projection.py, tests/panel/test_panel_checkbox_projection.py,
docs/DOCS_INDEX.md

# Cognitive Load Reduction Research Memo

## Purpose

This memo grounds issue #1644: cognitive-load reduction as a central Yggdrasil cognitive-prosthetic
capability. Dyslexia and reading-disability evidence are used as constraints and stress tests for
the design, not as the category that owns the work. This is research material, not a
shipped-runtime contract.

The practical conclusion is:

> Cognitive-load reduction is a governed human-agent workflow capability, not a UI theme.

For the current system, the highest-leverage first surface is the proposal and confirmation loop:
`Intent -> propose -> decide -> execute -> receipt`. A better interface should help the human
understand, compare, decide, and audit while preserving source authority, explicit confirmation,
WriteGuard, provenance, and receipts.

## Executive Summary

The evidence and repo contracts point to a layered approach:

1. Reduce avoidable extraneous load around review and decision handoff.
2. Keep intrinsic task difficulty visible instead of hiding risk or uncertainty.
3. Use listening, spacing, layout, and structured decision patterns as aids.
4. Treat diagnosis-specific fonts and Bionic-style rendering as optional or experimental, not core.
5. Keep summaries, simplifications, and display transformations non-authoritative.
6. Keep confirmation as an authority surface, not a convenience click.

In repo terms, cognitive-load reduction must not mutate canonical Markdown, receipts, provenance,
memory extraction, runtime authority, or agent interpretation. It should produce human-facing
projections over source material and proposals, and it should make source comparison and review
easier before action.

## Wave 1 Addendum: Agent Proposal-And-Confirmation Surface

A later Wave 1 memo on FA-1 / FA-2 / RQ-9 matches the merged repo work in its core architecture:
proposal rendering is non-authoritative, human confirmation is the authority boundary, and governed
mutation routes through the existing policy, WriteGuard, idempotency, and receipt path. Treat that
memo as an upstream research addendum, not as a replacement for this document or the owner docs.

Repository reconciliation as of 2026-06-07:

- The earlier caveat that `companion-ui/docs/PANEL_CONFIRMATION_API_CONTRACT.md` and
  `app/panel/checkbox_projection.py` could not be read should not be carried forward in repo-local
  docs. They are available and are part of the verification source set for this memo.
- `POST /api/panel/checkbox-projection` is not a pure read-only projection. It is the
  source-backed, runtime-mediated confirmation path that may project a human-confirmed `- [x]`
  checkbox through the governed backend writer path. The non-mutation invariant applies to
  display/proposal/projection behavior before explicit human confirmation, and to summaries or
  display/readability transformations that are not routed through governance.
- The long RQ-9 simplification-vs-authority checklist is a useful proposed owner gate, but it is
  not yet a hard runtime or product norm. The compact owner-doc version currently lives in
  `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md` as the Decision Test. A future owner-doc change should
  decide whether to promote the longer gate wholesale or narrow it.
- Thresholds such as option-count ceilings, one-decision-per-surface, and verify prompts should be
  treated as recommendations until an owner contract adopts them. They are especially useful for
  design review, but they should not be described as shipped behavior.

Proposed RQ-9 gate, in owner-review form:

- Presentation may reduce parsing cost, but must not replace source review or rewrite the decision.
- The human must still make the decision; no pre-checked governance-bearing actions, auto-confirm,
  or confirm-all over governed effects.
- Consequences, uncertainty, reversibility, and source posture must remain visible before
  confirmation.
- Projection/rendering must not mutate canonical Markdown, receipts, provenance, memory inputs,
  runtime authority, or agent interpretation unless routed through the governed mutation path.
- Explanations must not be used as a trust signal. They should be checkable, source-adjacent, and
  on demand when detail would otherwise overload review.
- Load reduction should lower extraneous burden: proposal length, option count, nesting, source
  distance, context switches, and resumption cost. It must not lower intrinsic burden by hiding the
  judgment the human is being asked to make.

## Wave 2 Addendum: Comprehension, Reading Throughput, And Text Production

Wave 2 sharpens the framing rather than reversing Wave 1. Cognitive-load reduction should be
treated as a central Human-First capability, not as an accessibility sidecar. The owner's concrete
profile calibrates the system, but the owning category is cognitive prosthesis design.

The practical principle is:

> Reduce friction, not intelligence.

The system should preserve complexity, nuance, vocabulary, source fidelity, and human judgment. It
should aggressively remove mechanical costs around decoding, parsing, spelling, transcribing,
re-reading, and resuming work because those costs consume the same working-memory budget needed for
high-level reasoning.

Wave 2 adds this taxonomy:

- Working-memory load: proposal density, option count, chunking, and self-contained labels.
- Reading throughput: TTS/listening, shorter columns, spacing, pacing, and
  comprehension-per-effort.
- Text-production / encoding load: spelling, dictation/STT drafts, correction suggestions,
  real-word-error checks, and TTS read-back.
- Decision / confirmation load: the Wave 1 authority surface.
- Orientation / resumption load: re-entry, open loops, notable changes, and source proximity.

Repository reconciliation as of 2026-06-07:

- The Companion UI product spec is available at `docs/COMPANION_UI_PRODUCT_SPEC.md`.
- `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md` defines the shipped read-only
  `GET /api/companion/orientation` projection with `leave_point`, open loops, notable changes,
  resurfacing, memory, governance, guards, and mutation-intent hints.
- `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md` defines `GET /api/companion/workspace` as a
  read-side aggregate with `panel.selectable_options`.
- `app/api/routes/companion.py` implements workspace/orientation reads and multiple human-present
  body-edit or save paths, including `POST /api/companion/note/save`.
- `tests/companion_ui/test_direct_note_editor.py` verifies a direct human note editor using a
  native `<textarea spellcheck>` and the `/api/companion/note/save` path.
- `companion-ui/docs/CANVAS_AGENT_MVP_CONTRACT.md` and
  `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` already define Canvas body co-authoring and staged
  body-edit suggestion lanes.

The Wave 2 intake conclusion should therefore be corrected from "no authoring surface confirmed" to
"authoring surfaces exist, but the advanced text-production/encoding support contract is missing."
Native OS spellcheck exists in the direct note editor, but the research basis says that is not
enough for severe spelling/encoding load: standard spellcheck misses far-from-target misspellings,
does not reliably catch real-word errors, and assumes the human can identify the correct suggestion
from a list.

Design consequences:

- Dictation/STT output is draft text, not authority.
- Correction and rewrite assistance are proposal-class over the human's draft. They must show the
  changed text and preserve meaning/voice; silent canonical rewriting is an authority transfer.
- TTS/read-back should be paired with dictation or correction so verification is not purely visual.
- Reading throughput should optimize comprehension per unit effort, not raw words per minute.
- Listening must be user-controlled; forced simultaneous identical audio/text is not the safe
  default for every review task.
- Summaries remain subordinate, source-traceable entry points. They do not replace source review.
- The Companion comprehension surface should be verifiability-first: orient, compare with source,
  then decide. It should not become a persuasion surface that front-loads agent reasoning as a
  trust signal.

## Wave 3 Addendum: Resurfacing And Memory/Context Support Without Overload

Wave 3 confirms resurfacing as part of the same central cognitive-load capability. Resurfacing is
valuable because cognitive offloading can free working-memory resources and reduce prospective
memory failures, but it becomes a net load if it turns into a stream the human must monitor.

The design posture is:

> Scarce, justified, non-authoritative, cheap to consume.

Repository reconciliation as of 2026-06-07:

- The orientation and resurfacing source files named in the external memo are readable in the repo.
- `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md` defines the shipped
  `GET /api/companion/orientation` shape with `leave_point`, `open_loops`, `notable_changes`,
  `resurface.candidates`, memory awareness, governance, guards, server-declared caps, and bounded
  `mutation_intents`.
- ADR-0011 confirms the shipped orientation posture remains pull, snapshot, and read-only. It
  allows only later bounded foreground ambient refresh, not server push, notifications, badges,
  inboxes, urgency feeds, or focus stealing.
- `app/orientation/bundle_consumer.py` rejects orientation bundles with `may_write=True` and
  returns `may_write=False`.
- `app/resurfacing/bundle_consumer.py` requires `may_resurface=True`, rejects `may_write=True`,
  requires `intended_use` to include `resurface`, preserves exclusions, separates relatedness from
  priority, and returns `suggestion_only=True`, `may_write=False`.
- `app/resurfacing/runtime.py` evaluates derived relevance-change signals as read-only and returns
  no mutation intents.
- Tests in `tests/resurfacing/test_context_bundle_resurfacing.py`,
  `tests/resurfacing/test_resurfacing_runtime.py`, `tests/orientation/test_context_bundle_orientation.py`,
  and `tests/knowledge_compilation/test_reorientation_packet.py` prove the non-write posture at
  code level.

The Wave 3 caveat should therefore be corrected from "may_write=false is inferred" to
"may_write=false is confirmed for the shipped orientation/resurfacing/context-bundle seams." The
remaining #1657 issue is real, but it concerns an overbroad Panel checkbox-projection AI-status
receipt claim. It should not be used as evidence that resurfacing has a mutation or receipt
problem.

Design consequences:

- Resurfacing-for-task-support and resurfacing-for-learning are different modes. Task support uses
  just-in-time orientation cues; learning uses spaced retrieval practice. Do not share one timer,
  card shape, or metric.
- Resurfacing should be budgeted: small caps per orientation moment, low-frequency foreground
  refresh only, and a relevance/salience threshold below which nothing surfaces.
- Pull is the default. Bounded ambient refresh is an owner-contract exception and must remain
  read-only, foreground, and low-noise.
- Each item needs a short, source-linked "why now". Prefer pointer/provenance over generated
  rationale.
- Resurfacing must not silently re-prioritize the human's work. If ranking/filtering is used, the
  basis must be visible and source-linked.
- Resurfaced cards should be short, self-contained, pointer-first, and TTS-ready. A wall of
  resurfaced text reintroduces the reading load the feature is meant to reduce.
- Memory/context resurfacing should avoid system-driven over-offloading. The system may preserve
  reliable pointers and review posture, but it should not aggressively volunteer to remember more
  than the human chose.

## Evidence Ranking

| Intervention / concern | Evidence posture | Yggdrasil implication |
| --- | --- | --- |
| Twice-exceptional cognitive profile | Strong enough to treat higher-order reasoning and mechanical decoding/encoding as separable design parameters. | Preserve full intellectual complexity; reduce decoding, spelling, parsing, and working-memory friction. |
| Cognitive Load Theory framing | Strong conceptual fit for separating intrinsic difficulty from avoidable interface load. | Optimize proposal/review surfaces by reducing unnecessary parsing, source distance, context switches, and ambiguous action identity. |
| TTS / listening / read-aloud | Moderate positive evidence for readers with reading disabilities; still variable by user and setup. | Treat TTS/listening as a credible P0/P1 review aid, especially for source review and decision confirmation. |
| Shorter lines, spacing, line height, layout, clear structure | Evidence is user/subset-dependent but low-risk as render-only adaptation. | Support render-only throughput/layout preferences and structured sections; do not encode them into canonical Markdown. |
| Dictation/STT plus read-back | Positive accommodation evidence, with proofreading burden shifted to verification. | Treat STT as draft capture; pair correction/dictation with TTS read-back and human confirmation before save. |
| Standard spellcheck for severe spelling load | Insufficient; misses far-from-target and real-word errors and leaves suggestion selection to the human. | Native spellcheck is a baseline only; smarter correction must remain proposal-class and transparent. |
| Cognitive offloading / resurfacing | Net-positive when reliable, scarce, and provenance-backed; risky when it becomes noisy, unreliable, or over-encourages offloading. | Treat resurfacing as bounded read-only orientation support with hard caps, why-now provenance, and no notification-style monitoring burden. |
| Task-support vs learning resurfacing | Different evidence bases and timing logic. | Keep just-in-time orientation separate from spaced retrieval practice. |
| Dyslexia-specific fonts | Mixed to weak. Studies often find no reliable speed/accuracy gain from the typeface itself; user preference can still matter. | Offer as optional display preference, not as a claimed core intervention. |
| Bionic-style rendering | Weak/negative current evidence for reading speed and eye-movement benefit. | Mark experimental only; do not make it the primary cognitive-load support story. |
| Automation bias | Strong enough to require design safeguards around AI recommendations. | Do not make agent recommendations look like settled decisions; show source, uncertainty, risk, and reject/defer/clarify paths. |
| Summarization faithfulness | Active risk area; factual consistency evaluation remains difficult, especially outside simple news summaries. | Summaries must be source-preserving projections with review posture, not authoritative replacements for the source. |
| Cognitive offloading / intention offloading | Useful and well-aligned, but offloading can change what users remember and rely on. | External aids should preserve reviewability, cues, receipts, and provenance so offloading does not become hidden authority transfer. |

## WP-A: Cognitive-Load Criteria And Extraneous-Load Proxies

Cognitive Load Theory distinguishes the complexity of the thing being learned from avoidable load
created by presentation, sequencing, or environment. Recent summaries emphasize limited working
memory and the need to minimize cognitive processing irrelevant to the learning or decision task.

For Yggdrasil, the goal is not to make hard decisions appear simple. The goal is to remove
avoidable parsing and coordination burden so the human can spend attention on the actual judgment.

Useful design criteria:

- Keep the decision object stable: what is being proposed, for which artifact, under which source.
- Keep evidence and source reference adjacent to the recommendation.
- Use consistent sections for facts, interpretation, recommendation, uncertainty, and action.
- Avoid forcing the user to infer option identity from prose, DOM order, or label text.
- Preserve review posture: what is known, inferred, stale, uncertain, or risky.
- Make interruption recovery explicit: what changed, what is pending, what can be safely resumed.

Soft proxies to track or inspect:

- Proposal length and density.
- Option count.
- Source distance: how far the source/evidence is from the confirmation affordance.
- Context switches needed to decide.
- Resumption lag after returning to a note or proposal.
- Confirmation granularity: one bounded decision versus grouped actions.
- Uncertainty visibility.
- Receipt visibility after execution.
- Number of surfaces needed to reconstruct what happened.

These should remain soft signals. They are not hard product limits because intrinsic difficulty
varies by task, source, user expertise, risk tier, and artifact class.

## WP-B: Listening, Structure, And Display Evidence Dossier

### TTS And Listening

TTS and related read-aloud tools have better support than font-specific interventions. Wood et al.
found a positive average weighted effect for reading comprehension among students with reading
disabilities, while still noting heterogeneity and a need for more moderator research. The British
Dyslexia Association also frames text-to-speech as compatible with dyslexia-friendly written
material.

Yggdrasil implication:

- Listening should be a credible review aid, especially for long source text, proposal review, and
  final confirmation.
- Listening is not authority. It re-presents source/projection content; it does not change what the
  user approved.
- Listening controls should preserve source comparison and let the user return to exact source
  anchors or proposal fields.

### Spacing, Layout, And Clear Structure

WCAG text-spacing guidance is about adaptability: content must tolerate user changes to line
height, paragraph spacing, letter spacing, and word spacing without loss of content or function.
W3C cognitive accessibility guidance also emphasizes clear structure, understandable content, and
including users in testing. The BDA style guide recommends sans-serif fonts, sufficient size,
spacing, headings, left alignment, short lines, and whitespace.

Yggdrasil implication:

- Reading and decision surfaces should expose render-only adjustments for font size, line height,
  paragraph spacing, column width, and reduced clutter.
- The system should use headings, stable field order, and short sections for review.
- Display preferences must be local rendering preferences and must not mutate source Markdown or
  affect receipts, provenance, memory extraction, runtime authority, or agent interpretation.

### Dyslexia Fonts

The current evidence does not justify treating dyslexia-specific fonts as a core intervention. The
Marinus et al. Dyslexie study found no reading-speed or accuracy benefit over common fonts for
children with or without dyslexia. Later reviews and related studies continue to distinguish user
preference from reliable objective benefit.

Yggdrasil implication:

- OpenDyslexic, Dyslexie, or similar fonts can be optional display preferences.
- The product claim should be "user-selectable preference", not "dyslexia support is solved by a
  font".
- Font choice should not replace TTS/listening, spacing/layout, source comparison, or structured
  decision review.

### Bionic-Style Rendering

Recent Bionic Reading studies are not strong enough to support a core claim. Snell's 2024 study
found no significant reading-time benefit, and a 2025 eye-movement study found no significant
change in reading speed or eye-movement behavior.

Yggdrasil implication:

- Bionic-style rendering should be explicitly experimental.
- It should be opt-in, reversible, render-only, and disabled by default.
- It must not be the central cognitive-load story or a substitute for governed source-preserving
  review.

## WP-C: Confirmation Flow And Checkbox Authority Study

The repo already treats confirmation as an authority surface. `docs/PANEL_AGENT.md` defines
Canonical confirmation semantics: a checked Markdown task item inside a valid Panel `AI-åtgärder`
section is the durable human-facing confirmation signal.

The Companion UI read-mode path is transport. `PANEL_CONFIRMATION_API_CONTRACT` says
`POST /api/panel/checkbox-projection` validates source freshness, `artifact_id`, `note_path`,
`panel_id`, `option_id`, content hash, source hash, idempotency, and WriteGuard before projecting
the canonical checked checkbox state.

The implementation reinforces this boundary: `app/panel/checkbox_projection.py` exposes
`extract_panel_selectable_options`, which omits ordinary Markdown tasks, code-block tasks, receipt
checkboxes, and Panel options without explicit `ai:option_id`. Tests prove the source-backed
selectable-option boundary and the runtime-mediated projection path.

Automation-bias research makes this more important, not less. If the system simplifies a decision
surface by hiding uncertainty, source evidence, or alternatives, it can reduce friction while
increasing over-reliance.

Design safeguards:

- Never default a governance-bearing checkbox to checked.
- Never batch-confirm multiple governance-bearing actions in this slice family.
- Do not infer option identity from label text, visual position, or DOM order.
- Keep reject, defer, and clarify visible even when only confirm is executable.
- Make the source/reference and freshness posture visible near the action.
- Show uncertainty, risk, and consequence before the confirm affordance.
- Show receipt/status after projection or execution.
- Keep simplified wording subordinate to the source text and proposal identity.

## WP-D: Companion UI Review-Sequence Spec

The first useful review sequence is orientation-first and source-preserving:

1. Show what artifact/proposal this is.
2. Show why it is being surfaced now.
3. Show what the human needs to decide.
4. Show the source/reference and freshness posture.
5. Separate facts/evidence from agent interpretation.
6. Show recommendation or available option.
7. Show risk, uncertainty, and consequence.
8. Offer confirm, defer, reject, and clarify affordances, with unimplemented choices honestly
   marked as local/non-mutating or not yet actionable.
9. Route confirm through the existing checkbox projection path when it is a Panel selectable option.
10. Refresh and show status/receipt after confirmation.

For interruption recovery:

- Preserve pending proposal identity and source freshness.
- Show whether the proposal is still selectable, stale, blocked, already projected, or executed.
- Keep the source comparison one step away.
- Avoid requiring the user to reconstruct the decision from raw dense panel text.

This review sequence should inform #1641 and #1645, but this memo does not implement it.

## WP-E: Source-Preserving Summary Pattern

Summaries and simplified explanations are access aids. They must not become canonical truth.

Use this pattern for ASK, Panel, Companion UI, and future Source Understanding surfaces:

```text
Source / artifact:
Scope:
Status: non-authoritative projection

Facts / source claims:
Agent interpretation:
Recommendation or possible next action:
Uncertainty / risk:
Source anchors / trace / receipt references:
Human review needed:
Promotion boundary:
```

Rules:

- Keep source facts separate from agent interpretation.
- Keep recommendation separate from approval.
- Preserve source anchors, spans, trace IDs, receipt IDs, or explicit anchor limitations.
- Mark summaries as non-authoritative projections.
- Do not index UI-only summaries as durable knowledge without a governed artifact class or
  promotion path.
- Do not mutate canonical source artifacts from a summary.
- Require human review before a source interpretation becomes a stabilized note, concept note, or
  durable proposal.

Summarization faithfulness work is still an active research area. LLM-based factual consistency
evaluation can help, but current methods remain incomplete, especially for specialized or complex
documents. The safe Yggdrasil pattern is therefore source-preserving projection plus explicit
review posture, not generic summary replacement.

## WP-F: Simplification-Vs-Authority Decision Memo

Use this test before accepting any cognitive-load projection:

| Question | If yes | If no |
| --- | --- | --- |
| Is this only a different rendering of the same source/proposal? | It may be a render-only preference. | Continue. |
| Does it change semantic meaning or omit material needed for the decision? | It is a semantic transformation and needs review posture/source anchors. | Continue. |
| Does it change what the human is considered to have approved? | It is an authority transfer and must use governed confirmation. | Continue. |
| Does it change what the agent can interpret as authority? | It needs owner-doc/contract treatment before implementation. | Continue. |
| Does it alter canonical Markdown, receipts, provenance, memory extraction, or runtime authority? | It is not a display preference; route through governed write/contract work. | Continue. |
| Are source, uncertainty, and receipt still visible? | Safer. | Block or downgrade confidence. |
| Are reject, defer, and clarify at least as legible as accept? | Safer. | Risk of rubber-stamping; repair the surface. |

This distinction is the key boundary between legitimate load reduction and hidden authority
transfer.

## Proposal Template Pattern For #1642

Use this as a draft decision surface pattern:

```text
What this is:
Artifact / source:
What the human needs to decide:
Recommendation / option:
Why this is proposed:
Facts / evidence:
Agent interpretation:
Risk / uncertainty / consequence:
Available choices:
  - Confirm
  - Defer
  - Reject
  - Clarify
Confirmation authority:
Source freshness / option identity:
Expected receipt or status:
```

Criteria:

- Checkbox labels must be self-contained enough for listening/TTS.
- Source/reference must remain available.
- Recommendation must not read as approval.
- Uncertainty must be explicit.
- Confirmation must preserve `option_id` and source freshness requirements.
- Defer/reject must not be misrepresented as durable unless implemented through a governed path.

## Render-Only Boundary For #1640 And #1643

Display preferences are local rendering aids:

- font size
- line height
- paragraph spacing
- column width
- reduced visual clutter
- focus mode
- optional reading-support font preference
- experimental Bionic-style rendering

They must not mutate canonical Markdown, receipts, provenance, memory extraction, runtime authority,
or agent interpretation. If a transformation changes meaning, selects content, summarizes, ranks,
or recommends action, it is not merely render-only.

## Listening And Review Implications For #1641

Listening should support the review chain:

- intake
- orientation
- comprehension
- source comparison
- decision-making
- confirmation / rejection / deferral
- receipt review
- later resurfacing

For proposal review, listening should read fields in a stable order: what this is, what the human
needs to decide, recommendation, why, risk/uncertainty, source/reference, choices, and expected
receipt/status. It should not read only the recommendation and skip risk or source.

## Open owner decisions

- Should the proposed RQ-9 simplification-vs-authority gate be promoted into an owner-doc contract,
  and if so which parts become hard blockers versus review guidance?
- Where should the durable product contract for the Cognitive Load Projection Layer live after
  #1640: `docs/INTERACTION_SURFACES_AND_AUTHORITY/`, Companion UI docs, or a new capability
  directory?
- Should listening/TTS be specified as a Companion UI capability, a general interaction-surface
  capability, or both?
- Which authoring surfaces should receive the first text-production contract: direct note editor,
  Canvas body edit, Panel clarification fields, ASK queries, or Inbox capture?
- Should dictation/STT support require TTS read-back before save on selected surfaces, or expose
  read-back as a strongly recommended verification affordance?
- What correction policy should govern severe spelling, real-word-error, and rewrite assistance:
  suggestion-only, diff-before-save, or Canvas user-present apply with undo and provenance?
- What resurfacing budget should become contractual for the cognitive-load layer: items per
  orientation moment, foreground refresh frequency, and minimum salience threshold?
- Should learning-oriented resurfacing stay out of FA-5 and become a later spaced-retrieval
  capability so it does not get conflated with task-support orientation?
- What is the minimal "why now" field shape for resurfacing cards: trigger, source, relevance basis,
  and confidence/degradation in one bounded line?
- What is the minimum status/receipt feedback required after read-mode confirmation in #1645?
- Should defer/reject be local UI affordances first, or should they wait for a governed proposal
  lifecycle contract?
- Which user preferences are persisted locally, and where, without becoming semantic authority?
- How should Source Understanding Mode (#1646/#1647) reuse the source-preserving summary pattern
  without conflating research-source interpretation and Panel proposal confirmation?

## Source Map

Repo authority:

- `docs/HUMAN-FLOWS.md` — product thesis and loops, including `Intent -> propose -> decide -> execute -> receipt`.
- `docs/COGNITIVE_PROSTHESIS_CHARTER.md` — provenance, source authority, WriteGuard, events, receipts.
- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md` — cognitive-load projection boundary.
- `docs/PANEL_AGENT.md` — artifact-local intent manifestation and Canonical confirmation semantics.
- `companion-ui/docs/PANEL_CONFIRMATION_API_CONTRACT.md` — checkbox projection endpoint and boundary.
- `app/panel/checkbox_projection.py` — `extract_panel_selectable_options` and projection implementation.
- `tests/panel/test_panel_checkbox_projection.py` — executable boundary proof.
- `docs/COMPANION_UI_PRODUCT_SPEC.md` — Companion UI product mode model.
- `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md` — note-independent orientation projection.
- `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md` — artifact-scoped workspace/read aggregate.
- `docs/adr/ADR-0011-orientation-push-ambient-resurfacing.md` — pull/snapshot/read-only ambient
  resurfacing boundary.
- `app/orientation/bundle_consumer.py` — orientation context-bundle consumer and non-write guard.
- `app/resurfacing/bundle_consumer.py` — resurfacing context-bundle consumer, why-now signal, and
  `may_write=False` guard.
- `app/resurfacing/runtime.py` — read-only derived-signal resurfacing runtime seam.
- `tests/resurfacing/test_context_bundle_resurfacing.py` and
  `tests/resurfacing/test_resurfacing_runtime.py` — executable resurfacing boundary proof.
- `app/api/routes/companion.py` — current Companion workspace, orientation, body update, and note
  save endpoints.
- `tests/companion_ui/test_direct_note_editor.py` — direct human note editor and native spellcheck
  coverage.
- `companion-ui/docs/CANVAS_AGENT_MVP_CONTRACT.md` — Canvas co-authoring authority model.
- `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` — staged Canvas suggestion flow.

External evidence context:

- Sweller et al., ["Cognitive Architecture and Instructional Design: 20 Years Later"](https://link.springer.com/article/10.1007/s10648-019-09465-5),
  for Cognitive Load Theory framing.
- W3C, ["Making Content Usable for People with Cognitive and Learning Disabilities"](https://www.w3.org/TR/coga-usable/),
  for cognitive accessibility patterns.
- W3C WCAG 2.2, ["Understanding Success Criterion 1.4.12: Text Spacing"](https://www.w3.org/WAI/WCAG22/Understanding/text-spacing),
  for text-spacing adaptability.
- British Dyslexia Association, ["Dyslexia Style Guide 2023"](https://cdn.bdadyslexia.org.uk/uploads/documents/Advice/style-guide/BDA-Style-Guide-2023.pdf),
  for practical dyslexia-friendly style guidance.
- Wood et al., ["Does Use of Text-to-Speech and Related Read-Aloud Tools Improve Reading
  Comprehension for Students with Reading Disabilities? A Meta-Analysis"](https://pmc.ncbi.nlm.nih.gov/articles/PMC5494021/),
  for TTS/read-aloud evidence.
- Marinus et al., ["Dyslexie font does not benefit reading in children with or without dyslexia"](https://pmc.ncbi.nlm.nih.gov/articles/PMC5934461/),
  for dyslexia-font caution.
- Snell, ["No, Bionic Reading does not work"](https://www.sciencedirect.com/science/article/pii/S0001691824001811),
  and Beelders, ["Guiding the Gaze: How Bionic Reading Influences Eye Movements"](https://pmc.ncbi.nlm.nih.gov/articles/PMC12565662/),
  for Bionic-style rendering caution.
- ["Automation bias: a systematic review of frequency, effect mediators, and mitigators"](https://pmc.ncbi.nlm.nih.gov/articles/PMC3240751/),
  for over-reliance risk.
- Gilbert et al., ["Outsourcing Memory to External Tools: A Review of Intention Offloading"](https://pmc.ncbi.nlm.nih.gov/articles/PMC9971128/),
  and related cognitive offloading work, for external-aid benefits and review risks.
- Luo et al., ["Factual consistency evaluation of summarization in the Era of large language models"](https://www.sciencedirect.com/science/article/pii/S0957417424013228),
  for source-faithfulness caution.
