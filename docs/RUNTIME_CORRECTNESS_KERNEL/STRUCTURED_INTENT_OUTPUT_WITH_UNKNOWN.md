---
name: Structured Intent Output With UNKNOWN
description: Shared schema-constrained completion utility; intent classifier migrated to it; explicit UNKNOWN class with a read-only degrade + re-ask landing surface replaces the silent CO_AUTHORING default
task_id: KERNEL-07
source_anchor: "docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: CW-2, I-A1, I-A2"
parent_capability: RUNTIME_CORRECTNESS_KERNEL
prerequisites: []
depends_on: []
can_parallelize_with: [TRANSACTIONAL_VAULT_SYNC, DEAD_LETTER_HEALTH_SIGNAL]
---

# Structured Intent Output With UNKNOWN

## Purpose

The intent classifier (`app/chat/intent_classifier.py :: IntentClassifierCognition.classify()`)
gets LLM text via `ReasoningFacade.answer()` and parses it with regex + `json.loads`
(`_extract_json_object` / `_parse_label`, approx. lines 189–243 at audit time). Unparseable or
degraded output falls through `_defaulted(...)` to **`CO_AUTHORING` with `classified=False`**
(lines 158–165) — a *mutation-capable* class as the failure default, not a refusal. Audit
invariants **I-A1** (structured boundary) and **I-A2** (no default routes): CW-2.

## What This Task Does

- (a) Add a shared constrained-completion utility at the existing LLM seam. `ChatClient.chat()` and
  `LLMTaskIntent(json_schema_required: bool)` already exist in `app/components/llm/` (fabric.py,
  router.py); fit the utility there (e.g. `app/components/llm/constrained.py :: constrained_completion(schema_ref)`)
  so it requests schema-constrained output (Ollama `format=json` / JSON-schema constrained decoding;
  provider tool-call where supported) and **validates against a registered schema before returning**.
- (b) Migrate `IntentClassifierCognition.classify()` to call the utility instead of free-text
  `facade.answer()` + regex. Regex extraction on this control path is removed.
- (c) Add an explicit `UNKNOWN` member to `IntentClass` (`app/chat/intent_classifier.py`, the enum
  at approx. lines 53–58 alongside `CO_AUTHORING`/`GOVERNANCE_BEARING`/`EXPLORATORY`). On validation
  failure the classifier returns `UNKNOWN` surfaced to the caller with a defined landing surface:
  degrade to read-only/exploratory handling **plus** a re-ask affordance. Per cross-task invariant
  #7, the `_defaulted → CO_AUTHORING` fallback is removed **only together with** this surface.
- (d) Governance-bearing routing (`GOVERNANCE_BEARING` → gated pipeline) can never be reached from an
  unvalidated parse — only a schema-validated classification can route to a mutation-capable class.
- **Owner-decision guardrail:** LLM classification stays the mechanism. This task *strengthens* the
  LLM boundary; it MUST NOT replace the classifier with keyword heuristics.

## Concretely

```bash
pytest -q tests/chat/test_intent_unknown_route.py
pytest -q tests/chat/test_intent_classifier.py   # existing suite stays green
```

## Why This Matters

The governance chain (intent → capability class → authority gate) is only as strong as a regex
today, and its failure mode silently converts governance-bearing intent into body edits. A validated
boundary with an explicit `UNKNOWN` makes misclassification visible and safe instead of a silent
mutation route.

## Acceptance Criteria

- [ ] `constrained_completion` validates LLM output against a registered schema and raises/returns a
      typed failure on invalid output (no regex extraction on the control path).
      Verify: `tests/chat/test_intent_unknown_route.py::test_constrained_completion_validates`
- [ ] Classifier emits explicit `UNKNOWN` on validation failure, landing on read-only/exploratory
      handling with a re-ask affordance; the `CO_AUTHORING` default is gone.
      Verify: `tests/chat/test_intent_unknown_route.py::test_unknown_degrades_read_only_and_reask`
- [ ] Enforcement AC: the schema validation is invoked from the production `classify()` entrypoint —
      the test drives `IntentClassifierCognition.classify()` (not the utility in isolation) and
      asserts validation runs on that path.
      Verify: `tests/chat/test_intent_unknown_route.py::test_validation_invoked_from_classify`
- [ ] Fuzz: a garbage-LLM stub over many random outputs never yields a governance-bearing (or any
      mutation-capable) route — UNKNOWN or a validated class only.
      Verify: `tests/chat/test_intent_unknown_route.py::test_fuzz_unknown_never_a_route`

## How to Verify (Pre-Merge)

1. `pytest -q tests/chat/test_intent_unknown_route.py tests/chat/test_intent_classifier.py tests/chat/test_governance_router.py`
2. Full `pytest -q -m "not pg"` (control-path change on the chat hot path).
3. `ruff check app tests`.

## Out of Scope

- Applying the utility to planner/reasoning prompts (KERNEL-09 uses it for plans; reasoning is later).
- Event-topic schemas (KERNEL-08); intent-classification golden set (KERNEL-13).
- Replacing LLM classification with heuristics (explicitly forbidden — see owner-decision guardrail).

## Related Docs

- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: CW-2, I-A1, I-A2`
- `docs/settings/prompts/*` (classifier prompt is a descriptive mirror; SoT stays in code)
- `docs/ARCHITECTURE.md` (typed-boundary description at promotion)

## Related GitHub Issues

One bounded issue. TCD hint: Sonnet / high effort (governance-critical boundary + a fuzz proof that
UNKNOWN is never a route; the shared utility is reused by KERNEL-09). Escalate if constrained
decoding requires provider-abstraction changes beyond `app/components/llm/`.
