State: research synthesis (analysis, docs-only; non-normative).
Doc role: Research
Authority: Evidence grounding for cognitive-load reduction issue #1644. This memo can inform
downstream issue contracts and owner-doc proposals, but it does not override current-state owner
docs, Panel runtime contracts, Companion UI contracts, or shipped implementation truth.
Owner: `docs/HUMAN-FLOWS.md` / Companion UI and Panel downstream issue lanes
Last reviewed: 2026-06-06
Last verified against: docs/HUMAN-FLOWS.md, docs/COGNITIVE_PROSTHESIS_CHARTER.md,
docs/PANEL_AGENT.md, companion-ui/docs/PANEL_CONFIRMATION_API_CONTRACT.md,
app/panel/checkbox_projection.py, tests/panel/test_panel_checkbox_projection.py,
docs/DOCS_INDEX.md

# Cognitive Load Reduction Research Memo

## Purpose

This memo grounds issue #1644: cognitive-load reduction as a Yggdrasil capability, with
dyslexia-aware support as a forcing function. It is research material, not a shipped-runtime
contract.

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
4. Treat dyslexia-specific fonts and Bionic-style rendering as optional or experimental, not core.
5. Keep summaries, simplifications, and display transformations non-authoritative.
6. Keep confirmation as an authority surface, not a convenience click.

In repo terms, cognitive-load reduction must not mutate canonical Markdown, receipts, provenance,
memory extraction, runtime authority, or agent interpretation. It should produce human-facing
projections over source material and proposals, and it should make source comparison and review
easier before action.

## Evidence Ranking

| Intervention / concern | Evidence posture | Yggdrasil implication |
| --- | --- | --- |
| Cognitive Load Theory framing | Strong conceptual fit for separating intrinsic difficulty from avoidable interface load. | Optimize proposal/review surfaces by reducing unnecessary parsing, source distance, context switches, and ambiguous action identity. |
| TTS / listening / read-aloud | Moderate positive evidence for readers with reading disabilities; still variable by user and setup. | Treat TTS/listening as a credible P0/P1 review aid, especially for source review and decision confirmation. |
| Spacing, line height, layout, clear structure | Strong accessibility guidance and low-risk adaptability requirement. | Support render-only spacing/layout preferences and structured sections; do not encode them into canonical Markdown. |
| Dyslexia-specific fonts | Mixed to weak. Studies often find no reliable speed/accuracy gain from the typeface itself; user preference can still matter. | Offer as optional display preference, not as a claimed core intervention. |
| Bionic-style rendering | Weak/negative current evidence for reading speed and eye-movement benefit. | Mark experimental only; do not make it the primary dyslexia support story. |
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

## WP-B: Dyslexia, Listening, And Display Evidence Dossier

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
- It must not be the central accessibility story or a substitute for governed source-preserving
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

Use this test before accepting any cognitive-load or accessibility projection:

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
- optional dyslexia-oriented font preference
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

- Where should the durable product contract for "Cognitive-load / Accessibility Projection Layer"
  live after #1640: `docs/INTERACTION_SURFACES_AND_AUTHORITY/`, Companion UI docs, or a new
  capability directory?
- Should listening/TTS be specified as a Companion UI capability, a general interaction-surface
  capability, or both?
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
- `docs/PANEL_AGENT.md` — artifact-local intent manifestation and Canonical confirmation semantics.
- `companion-ui/docs/PANEL_CONFIRMATION_API_CONTRACT.md` — checkbox projection endpoint and boundary.
- `app/panel/checkbox_projection.py` — `extract_panel_selectable_options` and projection implementation.
- `tests/panel/test_panel_checkbox_projection.py` — executable boundary proof.

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
