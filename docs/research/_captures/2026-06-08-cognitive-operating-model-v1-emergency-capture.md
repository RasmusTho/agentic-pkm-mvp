---
doc_type: capture
authority: supporting
status: active
created: 2026-06-08
owner: Rasmus
origin: ChatGPT discussion + Yggdrasil cognitive-load research waves
agent_read_priority: P0-temporary
canonical_for:
  - cognitive-load/emergency-capture
  - cognitive-operating-model/v1-seed
superseded_by:
expires_when:
  - docs/START_HERE.md exists
  - docs/CAPABILITY_REGISTRY.md exists
  - docs/ARCHITECTURE_INVARIANTS.md exists
  - docs/RESEARCH_INDEX.md exists
related_research:
  - Start - Yggdrasil dyslexia research(2).md
  - Wave 1 - The Agent Proposal-and-Confirmation Decision Surface(2).md
  - Wave 2 - Cognitive Load as a Central Human-First Capability Comprehension Review Surface, Reading Throughput, and Text-Production(2).md
  - Wave 3 - Resurfacing and Memory- Context Support Without Overload(2).md
  - Wave 4 - Listening (TTS) and Bimodal Support Evidence & Contract(1).md
  - Wave 5 Display Preferences as Downstream, Local, Opt-In Rendering Aids(1).md
---

# Emergency Capture: Cognitive Operating Model v1 seed

This is an emergency capture, not a polished architecture document. It exists to prevent loss of the cognitive-load / dyslexia-aware system findings before a full documentation-control-plane refactor is possible.

## Status and authority

Treat this file as a temporary P0 agent-reading surface and backlog seed. It is supporting material, not implementation authority. Existing canonical contracts override this capture. Inferred or disputed repo claims must not be promoted to invariants without code verification.

## Existing research spine

1. Cognitive-load reduction is a foundational system capability across the human-agent workflow, not a UI accessibility theme.
2. The Markdown vault remains canonical; projections, UI, derived stores, summaries, display aids, TTS, and resurfacing must not silently become authority.
3. RQ-9 is the standing gate: reduce friction, decoding cost, presentation cost, or review cost, but never reduce or replace the user's decision, consequence, authority, provenance, or canonical state.
4. Proposal and confirmation surfaces are the safest high-leverage place to reduce cognitive load because they are proposal-class until explicit confirmation.
5. Text-production / spelling / encoding is a first-class gap and should not remain hidden behind reading support.
6. STT/dictation output must be draft-only; correction must be proposal-class; TTS/read-back is the verification loop for typed or dictated text.
7. Listening/TTS is a first-class comprehension path and must remain read-only projection.
8. Resurfacing is valuable only when scarce, justified, non-authoritative, provenance-bearing, and cheap to consume.
9. Display preferences are local, opt-in, downstream rendering aids only. They must never mutate markdown, receipts, provenance, memory extraction, or agent interpretation.

## New system-level findings to preserve

The missing layer is not more dyslexia tips. The missing layer is system orchestration around the user.

### F1 — Closed-loop cognitive telemetry

The system should learn whether support reduces actual cognitive cost for Rasmus on real tasks. Candidate signals: subjective effort 1-5, time to first decision, time to resume after interruption, context switches, read-back-caught errors, accepted/rejected/edited suggestion ratio, reorientation requests, summary-to-source follow-through, and task startability.

### F2 — Runtime cognitive modes

The same surface should behave differently by state and task type. Seed modes: deep reasoning, triage, low energy, return after interruption, and high-stakes write.

### F3 — Cognitive error taxonomy

Initial error classes: decoding miss, real-word error, STT misrecognition, meaning drift, summary laundering, false resurfacing authority, rubber-stamping, memory contamination, and identity drift.

### F4 — Recovery and undo

The system needs low-friction recovery after errors. Required concepts: human-readable diff receipts, undo-by-receipt where possible, recent system changes surface, explicit failure when receipts cannot be written, and recovery tests.

### F5 — External communication and voice preservation

Yggdrasil must support email, GitHub issues, documents, presentations, meeting notes, strategy text, comments, and public writing without normalizing Rasmus's voice into generic professional prose. Output-support modes: correct only; clarify; rewrite with intent lock.

### F6 — Emotional friction and task-startability

Dyslexia creates learned avoidance around text-heavy work. Treat this as system friction. Optimize for startability, provide ugly-draft capture, separate idea capture from polish, and make correction/read-back a normal flow.

### F7 — Cognitive energy budget

There is resurfacing budget, but not a full session/daily cognitive budget. Policy questions include decision caps, confirmation caps, batching, draft-only mode, read/listen switching, and suppressing suggestions while resurfacing is active.

### F8 — Cognitive Load Coordinator

Individual aids can conflict. A policy layer should limit concurrent cognitive demands across TTS, resurfacing, correction, confirmation, summaries, and display changes.

### F9 — Learning mode contract

Resurfacing-for-task-support and resurfacing-for-learning must remain separate. Distinguish find, orient, understand, decide, and internalize.

### F10 — FA-4 source-preserving summarization

Summaries must not replace sources. Needed contract pieces: summary type labels, claim-to-source map, contradiction surface, source sampling, uncertainty thresholds, and source-first review for high-risk material.

### F11 — Mandatory personal calibration

No cognitive aid should become default only because it is plausible in literature. Calibrate on real materials: GitHub issues, research memos, strategy docs, meeting notes, emails, own drafts, and source-heavy review tasks.

### F12 — External assistive-tool interoperability

Yggdrasil should not become a closed assistive silo. Allow external TTS/STT, OS dictation, browser zoom/extensions, screen readers, Obsidian-compatible markdown, clean copy/export with provenance, keyboard-first and voice-first navigation.

### F13 — Documentation control plane

The docs need a control plane so humans and agents can distinguish research vs canonical contract, confirmed vs inferred behavior, active vs superseded docs, explanation vs reference, and implementation task vs architectural invariant.

Needed later: docs/START_HERE.md, docs/SYSTEM_MAP.md, docs/ARCHITECTURE_INVARIANTS.md, docs/CAPABILITY_REGISTRY.md, docs/CONTRACT_INDEX.md, docs/RESEARCH_INDEX.md, docs/DECISION_LOG.md, docs/AGENT_CONTEXT.md, and AGENTS.md.

## Immediate decision

Do not create one issue per miss. Capture this as one parent issue/document, then later split into two parent tracks:

1. docs-control-plane parent issue;
2. cognitive-operating-model parent epic.

## Minimal later issue hierarchy

### Parent A: docs(architecture): create Yggdrasil cognitive-load documentation control plane

Child issues: START_HERE, SYSTEM_MAP, ARCHITECTURE_INVARIANTS, CAPABILITY_REGISTRY, CONTRACT_INDEX, RESEARCH_INDEX, DECISION_LOG/ADR template, AGENT_CONTEXT/AGENTS.md, and doc-lint/status taxonomy.

### Parent B: epic(cognitive-load): integrate Cognitive Operating Model v1

Child issues: runtime cognitive modes; cognitive load coordinator; cognitive error taxonomy and regression suite; recovery/undo-by-receipt; FA-4 source-preserving summarization; text-production and read-back loop; external communication and voice preservation; personal calibration telemetry; resurfacing budget and task-vs-learning split; assistive-tool interoperability.

## Temporary agent reading protocol

Until the documentation control plane exists, agents touching cognitive-load, Companion UI, PanelAgent, WriteGuard, TTS, display, intake, resurfacing, summarization, or text-production should read this file first.

Rules:

1. Research memos are supporting evidence, not operative authority.
2. Existing canonical contracts override this capture.
3. Every cognitive-load feature must pass RQ-9.
4. Any canonical write must pass WriteGuard and receipt requirements.
5. STT/dictation output is draft-only.
6. Correction/rewrite is proposal-class.
7. TTS/read-back/display/resurfacing are read-only projection unless an existing contract says otherwise.
8. Source summaries are entry points, not source replacements.
9. Inferred/disputed claims require repo verification before becoming invariants.

## Minimal next Codex/agent prompt

```md
Read `docs/research/_captures/2026-06-08-cognitive-operating-model-v1-emergency-capture.md`.

Task: create the smallest possible documentation-control-plane seed without refactoring all docs.

Do only:
1. add docs/START_HERE.md;
2. add docs/ARCHITECTURE_INVARIANTS.md;
3. add docs/RESEARCH_INDEX.md with Wave 1-5 rows;
4. add AGENTS.md pointer telling agents to read START_HERE and the emergency capture before cognitive-load work.

Do not change runtime code.
Do not implement TTS/STT/display/resurfacing.
Do not promote inferred claims to confirmed.
Preserve RQ-9 and WriteGuard/receipt boundaries.
```
