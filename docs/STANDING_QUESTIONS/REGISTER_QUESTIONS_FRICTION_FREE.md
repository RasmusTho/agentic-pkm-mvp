---
name: Register Questions Friction-Free
description: Two registration paths into the SQ-01 store — LLM capture-intent classification behind a deterministic admission gate (checkbox-confirmed proposal, zero typing beyond the question), and explicit companion-UI registration; no manual paths, ever
task_id: SQ-02
source_anchor: docs/research/yggdrasil-closed-loops-ideation.md :: 3. Standing questions
parent_capability: Standing Questions
prerequisites: [SQ-01]
depends_on: [STORE_QUESTION_NOTES_AND_PROJECTION.md]
can_parallelize_with: [Match Evidence to Open Questions]
---

# Register Questions Friction-Free

## Purpose

An owner who carries open questions for months will not register them if registration is a form. This
task makes registration frictionless in both directions the owner already uses: saying/writing
"find out whether X" during an ordinary capture, and an explicit one-shot registration action in the
companion UI. Consistent with the owner's dyslexia-friendly, no-manual-paths posture: never require
typing or pasting anything beyond the question itself.

## What This Task Does

1. **Path (a) — capture-intent classification.** A new dedicated classifier
   (`app/components/llm/question_intent_classifier.py`, sibling to `IntentClassifierCognition`)
   labels a capture's text as `question_registration` or `not_a_question_registration`, using the
   shared schema-constrained-completion utility (`app/components/llm/constrained.py::
   constrained_completion`) — **the repo's standing LLM-cognition + deterministic-gate pattern**
   (`docs/RUNTIME_CORRECTNESS_KERNEL/STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN.md`), not a keyword
   heuristic. On validation failure or a degraded backend the classifier returns `UNKNOWN` — an
   explicit non-admitting class, never a silent default that registers or drops.
   - On a validated `question_registration` classification, the extracted question text (verbatim
     from the capture, no paraphrase) becomes an **unchecked suggested checkbox proposal** —
     "Registrera stående fråga: '…'?" — attached to the source capture note's own `AI-åtgärder`
     section, following the existing Panel suggested-checkbox convention
     (`docs/PANEL_AGENT.md :: PA2-SUGGESTED-CHECKBOXES`). This keeps the moat intact (agents propose,
     human disposes) while satisfying "zero typing": the human's only input is one checkbox tap.
   - Checking the box executes the governed write into the SQ-01 store (a new `open` Question note),
     through the same confirm→execute Panel loop every other checkbox-gated action uses — no new
     approval mechanism invented here.
2. **Path (b) — explicit registration.** A companion UI action lets the human state a question
   directly (typed or dictated) and registers it immediately as `open` — this is unambiguous explicit
   human intent, so it writes through the SQ-01 guarded seam directly, no proposal/confirm step (the
   human already confirmed by taking the action). "Zero typing beyond the question itself" — no
   scope/date/metadata form; scope is inferred from the active companion-UI workspace/vault scope
   context the same way other same-scope writes infer it.
3. **No silent default.** Both paths funnel through SQ-01's write seam; neither path can create a
   Question note with `registered_via` unset or with a fabricated `text` — `text` is always either the
   human's own words (path b) or a verbatim quote from their capture (path a), never a paraphrase or
   summary the classifier invents.
4. **Idempotent proposals.** A repeated capture-intent classification of the same (or near-identical)
   source text does not stack duplicate registration checkboxes — the proposal is keyed by
   `hash(source_capture_id, extracted_question_text)`, following the same idempotency discipline as
   the Panel proposal-offered receipt and the Connect `finding_id` pattern.

## Concretely

```
# Heimdal capture transcript: "Note to self: should we fully migrate to BGE-M3? Find out before Q3."
$ python -m app.cli captures classify-question-intent <capture_id> --json
{"classified": true, "class": "question_registration", "extracted_text": "should we fully migrate to BGE-M3?"}
# → capture note gains: - [ ] Registrera stående fråga: "should we fully migrate to BGE-M3?"
# The extraction is a verbatim span of the capture (point 3 below). A capture that only
# *implies* a question, with no question the human actually uttered, is not registered —
# the classifier may never compose the question text itself.
# Human checks the box in Obsidian (or via Companion UI read-mode click) →
$ python -m app.cli questions create --text "Should we fully migrate to BGE-M3?" --scope work --registered-via capture_intent
→ WriteReceipt(locator=vault://questions/sq-...)

# Explicit path, Companion UI:
$ python -m app.cli questions create --text "What's our stance on cross-scope federation?" --scope work --registered-via explicit
```

## Why This Matters

If registration requires typing a form, the owner's actual months-long open questions never make it
into the system — the exact gap the ideation capture names. If the classifier auto-registers without
a checkbox, a misclassified capture pollutes the open-question list with junk the human never asked
for; if it silently drops ambiguous captures, the "zero typing" promise is broken because the human
must then remember to register manually anyway.

## Acceptance Criteria

- [ ] AC1: a fixture capture containing an explicit question-registration intent ("find out whether
      X", "jag undrar om X", …) is classified `question_registration` with the verbatim question text
      extracted. Verify:
      `tests/standing_questions/test_question_intent_classifier.py::test_capture_intent_classified_and_extracted`
- [ ] AC2: a fixture capture with no question-registration intent classifies as
      `not_a_question_registration`; a garbage/degraded-backend fixture yields explicit `UNKNOWN`,
      never a silent registration. Verify:
      `tests/standing_questions/test_question_intent_classifier.py::test_unknown_never_silently_registers`
- [ ] AC3 (enforcement): schema validation of the classifier's output is invoked from the production
      classification entrypoint (not only unit-tested on the utility in isolation). Verify:
      `tests/standing_questions/test_question_intent_classifier.py::test_validation_invoked_from_production_entrypoint`
- [ ] AC4: a validated `question_registration` classification lands as an unchecked suggested
      checkbox on the source capture note, never a directly-created Question note. Verify:
      `tests/standing_questions/test_register_capture_intent.py::test_classification_lands_as_suggested_checkbox_not_direct_write`
- [ ] AC5: checking the suggested checkbox creates exactly one `open` Question note with `text` equal
      to the verbatim extracted question and `registered_via: capture_intent`. Verify:
      `tests/standing_questions/test_register_capture_intent.py::test_checkbox_confirmation_creates_open_question`
- [ ] AC6: repeated classification of the same source text does not stack duplicate proposal
      checkboxes (idempotent on `hash(source_capture_id, extracted_text)`). Verify:
      `tests/standing_questions/test_register_capture_intent.py::test_repeated_classification_idempotent`
- [ ] AC7: the explicit companion-UI registration path creates an `open` Question note directly (no
      proposal/confirm step) with `registered_via: explicit`. Verify:
      `tests/standing_questions/test_register_explicit.py::test_explicit_registration_writes_directly`
- [ ] AC8: a fuzz pass over many random/garbage classifier outputs never yields a directly-created
      Question note from path (a) — only a suggested checkbox or `UNKNOWN`. Verify:
      `tests/standing_questions/test_question_intent_classifier.py::test_fuzz_classifier_never_bypasses_checkbox`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/standing_questions/test_question_intent_classifier.py tests/standing_questions/test_register_capture_intent.py tests/standing_questions/test_register_explicit.py
pytest -q -m "not pg"
RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q -m "not pg" tests/uat   # vault write-path change (capture note + question note)
```

## Out of Scope

Duplicate/near-duplicate question detection against already-open questions (a future refinement —
two independently registered questions that mean the same thing both land as separate notes for now);
evidence matching against the newly registered question (SQ-03); voice-native registration (the Mimer
voice loop, `docs/research/yggdrasil-closed-loops-ideation.md :: 5`, is a separate future capability —
this task's "explicit" path accepts whatever text/dictation the companion UI already supports, it does
not build new speech-to-text).

## Restart / Durability Posture

Suggested registration checkboxes live inside the source capture note (vault-durable), following the
existing `AI-åtgärder` persistence model — a restart loses no pending proposal. No in-memory
registration state exists.

## Related Docs

- `docs/RUNTIME_CORRECTNESS_KERNEL/STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN.md` (the classification +
  `UNKNOWN` pattern this task's classifier follows)
- `docs/PANEL_AGENT.md :: PA2-SUGGESTED-CHECKBOXES`, `:: Normalized Decision-Surface Proposal Format`
- `app/components/llm/intent_classifier.py` (sibling classifier this task's classifier is structured
  after, kept as a separate module — different intent taxonomy, same pattern)
- [STORE_QUESTION_NOTES_AND_PROJECTION](STORE_QUESTION_NOTES_AND_PROJECTION.md) (the write target)

## Related GitHub Issues

One issue: `[Standing Questions] register-questions-friction-free: capture-intent + explicit
registration paths`. Blocked until SQ-01 merges. TCD hint: Sonnet / high effort — reuses the existing
`constrained_completion` utility (not a new provider boundary) but the checkbox-confirmation
correctness proof (AC4/AC8: classifier can never bypass the human confirm step) is the kind of
LLM-boundary-safety work the repo routes above default Sonnet/medium; escalate to Opus only if
constrained decoding needs new provider-abstraction work.
