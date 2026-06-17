---
name: Classify Co-Authoring Intent
description: Build an LLM-backed cognition that classifies a canvas co-authoring intent as co-authoring, governance-bearing, or exploratory — and, when governance-bearing, which GovernanceActionType — independent of any generated body
task_id: CANVAS-INTENT-01
source_anchor: docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md :: Intent Classes
parent_capability: Intent-level governance classification on the /coauthor path
prerequisites: []
depends_on:
  - GENERATE_COAUTHORING_EDIT.md
  - GATE_GOVERNANCE_BEARING_MUTATIONS.md
can_parallelize_with: []
---

State: Implementation task specification. Today the `/coauthor` path decides whether a mutation is governance-bearing only by inspecting the *generated body* for a frontmatter block (`CoAuthoringCognition.generate_body` → `_body_contains_frontmatter`). The co-authoring prompt explicitly instructs the provider not to emit frontmatter, so a semantically governance-bearing natural-language intent (e.g. "promote this note to evergreen") produces an ordinary body edit and is applied in place — the governance handoff is unreachable through normal intents. This task builds the missing classifier so intent class is decided from the *intent*, not the output. It does not wire the classifier into the route (that is `ROUTE_GOVERNANCE_INTENT_ON_COAUTHOR.md`).
Doc role: Implementation task spec
Authority: Implements the three-intent-class taxonomy from `docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md` :: Intent Classes. Does not change the gated-execution invariant in `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`; the classifier only labels intent, it never executes or mutates.
Owner: v6.0 architecture owner
Last reviewed: 2026-06-09

# Classify Co-Authoring Intent

## Purpose

`HYBRID_CHAT_INTEGRATION_SCHEMA.md` defines three intent classes — **co-authoring**, **governance-bearing**, and **exploratory** — *by the intent itself*. The `/coauthor` path currently classifies by the wrong predicate (does the generated body contain frontmatter?), which the co-authoring prompt deliberately suppresses. This task builds an LLM-backed cognition that classifies the intent string into one of the three classes and, when governance-bearing, into the correct `GovernanceActionType`, so a downstream route can decide *before* (and independent of) body generation.

## What This Task Does

- Add `app/chat/intent_classifier.py` with:
  - `IntentClass` enum: `CO_AUTHORING`, `GOVERNANCE_BEARING`, `EXPLORATORY`.
  - `IntentClassification` (frozen dataclass): `intent_class: IntentClass`, `action_type: GovernanceActionType | None` (set **iff** `GOVERNANCE_BEARING`), `classified: bool`, `rationale: str | None`, `trace_id: str | None`.
  - `IntentClassifierCognition` mirroring `CoAuthoringCognition`: a `facade_factory: Callable[[], ReasoningFacade]` injectable (default `get_reasoning_facade`) so tests run without a live LLM, and a `classify(*, intent, current_body=None, trace_id=None) -> IntentClassification` method.
- The cognition calls `ReasoningFacade.answer(...)` with a classification prompt that asks the model to return a structured label (intent class + governance action type when applicable) and parses that into the typed `IntentClassification`. The provider is asked for a **label**, never a note edit.
- **Governance-bearing taxonomy → `GovernanceActionType`** (the four already in `app/chat/governance_router.py`; no new types):
  - maturity / promote / evergreen / seedling / demote → `MATURITY_TRANSITION`
  - frontmatter field / tag / classification / property / metadata → `FRONTMATTER_UPDATE`
  - create / delete / rename / archive / split / note lifecycle → `NOTE_LIFECYCLE`
  - link / move-to / merge-with / cross-note → `CROSS_NOTE`
- **Conservative degraded policy.** When the backend is mock/degraded (sentinels `MOCK_…`), returns a failed/empty run, or returns an unparseable label, return `IntentClassification(intent_class=CO_AUTHORING, action_type=None, classified=False, …)`. The classifier must **never fabricate a governance routing** from an untrusted/degraded response; the route keeps the body-frontmatter check as its backstop (see the wiring task). This is the no-regression default: an unavailable classifier reproduces today's behavior, not a hard block on all co-authoring.
- The cognition is **pure**: it reads the intent (and optionally the current body for context) and returns a label. It never imports or calls `CanvasWriter`, never writes to disk, and never stages a Panel intent.

## Concretely

```python
from app.chat.intent_classifier import IntentClassifierCognition, IntentClass
from app.chat.governance_router import GovernanceActionType

cog = IntentClassifierCognition(facade_factory=lambda: stub_facade)

cog.classify(intent="promote this note to evergreen")
# IntentClassification(intent_class=GOVERNANCE_BEARING,
#                      action_type=GovernanceActionType.MATURITY_TRANSITION,
#                      classified=True, ...)

cog.classify(intent="expand the decision section with trade-offs")
# IntentClassification(intent_class=CO_AUTHORING, action_type=None, classified=True, ...)

cog.classify(intent="what does this note argue?")
# IntentClassification(intent_class=EXPLORATORY, action_type=None, classified=True, ...)

# degraded backend (MOCK_… / failed run / unparseable):
# IntentClassification(intent_class=CO_AUTHORING, action_type=None, classified=False, ...)
```

## Why This Matters

If intent class is read from the generated body, the gate is unreachable through natural language: the prompt forbids frontmatter, so a maturity-promotion intent silently becomes an in-place body edit and the governance mutation is lost while no Panel intent is staged. That violates the spirit of `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`. A clean, testable classifier that labels the *intent* is the unit the route needs to close the gap — and isolating it here keeps the wiring diff small and the classifier independently verifiable.

## Acceptance Criteria

- [ ] A maturity intent classifies as `GOVERNANCE_BEARING` with `action_type=MATURITY_TRANSITION`.
  Verify: `tests/chat/test_intent_classifier.py::test_maturity_intent_classified_governance_bearing`
- [ ] A frontmatter/tag/classification intent classifies as `GOVERNANCE_BEARING` with `action_type=FRONTMATTER_UPDATE`.
  Verify: `tests/chat/test_intent_classifier.py::test_frontmatter_intent_classified`
- [ ] A note-lifecycle intent (create/delete/rename/archive) classifies as `GOVERNANCE_BEARING` with `action_type=NOTE_LIFECYCLE`.
  Verify: `tests/chat/test_intent_classifier.py::test_lifecycle_intent_classified`
- [ ] A cross-note intent (link/move/merge) classifies as `GOVERNANCE_BEARING` with `action_type=CROSS_NOTE`.
  Verify: `tests/chat/test_intent_classifier.py::test_cross_note_intent_classified`
- [ ] A pure body-edit intent classifies as `CO_AUTHORING` with `action_type=None`.
  Verify: `tests/chat/test_intent_classifier.py::test_body_edit_intent_classified_coauthoring`
- [ ] A degraded/mock or unparseable backend response yields `classified=False`, defaults to `CO_AUTHORING`, and never produces a governance `action_type`.
  Verify: `tests/chat/test_intent_classifier.py::test_degraded_backend_defaults_coauthoring`
- [ ] The classifier performs no note mutation and never invokes the writer or Panel pipeline (only the injected facade is touched).
  Verify: `tests/chat/test_intent_classifier.py::test_classifier_is_pure_no_writes`

## How to Verify (Pre-Merge)

- `pytest -q tests/chat/test_intent_classifier.py`
- `ruff check app tests`
- `git diff --check`

## Out of Scope

- Wiring the classifier into `POST /api/canvas/sessions/{id}/coauthor` — that is `ROUTE_GOVERNANCE_INTENT_ON_COAUTHOR.md`.
- Any change to `GovernanceActionType` membership or the Panel admission/confirm/execute pipeline.
- A deterministic keyword fallback classifier (the chosen approach is LLM-backed with a conservative degraded default).
- Companion UI / served-page changes and runbook edits.

## Related Docs

- `docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md` :: Intent Classes, Minimum Future Runtime Questions
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`
- `app/chat/coauthoring_cognition.py` (the sibling cognition this mirrors)
- `app/chat/governance_router.py` (`GovernanceActionType`)
- `app/reasoning/facade.py` (`ReasoningFacade.answer`)

## Related GitHub Issues

The issue should reference "Implements CANVAS_CHAT_SURFACE/CLASSIFY_COAUTHORING_INTENT" and point back to the Phase 4 parent feature issue. The classifier must stay pure (no mutation) and must not fabricate governance routing from a degraded backend.
