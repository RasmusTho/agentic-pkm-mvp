---
name: Use Jev for Product Canvas Intent Classification
description: Replace prompt-and-parse intent JSON with typed Jev judgments while preserving write gates.
task_id: TSO-03
github_issue: 5767
source_anchor: app/components/llm/intent_classifier.py :: IntentClassifierCognition.classify
parent_capability: TYPESAFE_SYSTEM_ONE
prerequisites: [TSO-01, TSO-02, TSO-05]
depends_on: [DEFINE_SYSTEM_ONE_JUDGMENT_CONTRACT.md, ADD_TYPESAFE_TO_MAC_EXECUTOR.md, DEFINE_TYPESAFE_CREDENTIAL_BINDINGS.md]
can_parallelize_with: [TSO-04 after TSO-01]
---

# Use Jev for Product Canvas Intent Classification

## Purpose

Repository implementation replaces the canvas completion classifier with typed Product MARR judgments while preserving fail-closed and human-confirmation behavior. The normal runtime route remains unavailable pending the separate Product dev acceptance on #5764.

## What This Task Does

- Replace the current constrained completion at the canvas intent-classifier call site with the Product-selected MARR System One operation.
- Use closed Choice sets for intent class and governance-action category; include a no-match/unknown outcome.
- Send only `intent_text` (≤2,000 UTF-8 bytes; serialized request ≤4 KiB). Do not send `current_body`, note title, vault path, prior conversation, or full prompt. Reject unknown fields and oversize input before MARR dispatch.
- Map service failure, malformed output, or evaluated low confidence to the existing `UNKNOWN` result.
- Keep confirmation, Apply authorization, WriteGuard, and all durable write boundaries unchanged.

## Concretely

The classifier sends one bounded state object and named Choice questions. The returned class/action is mapped to the existing `IntentClassification`. Unknown/uncertain results remain `classified=False` and cannot authorize a mutation.

## Why This Matters

The current consumer's output is a closed semantic choice, not generated prose. Preserving the existing downstream gates prevents better-typed inference from being mistaken for permission.

## Acceptance Criteria

- [ ] The production classifier uses the Product-owned MARR client and transmits only `intent_text` within the declared size limit; `current_body` never crosses the adapter. Verify: `tests/components/llm/test_intent_classifier_typesafe.py::test_production_classifier_uses_marr_and_minimal_state`.
- [ ] Unknown fields and oversize intent fail before provider dispatch; service errors and low-confidence answers map to `UNKNOWN`. Verify: `tests/components/llm/test_intent_classifier_typesafe.py::test_typesafe_input_allowlist_and_size_limit` and `tests/components/llm/test_intent_classifier_typesafe.py::test_uncertain_judgment_remains_unknown_without_authorizing_write`.
- [ ] Existing confirmation and write-guard call sites remain required for governance-bearing outputs. Verify: `tests/components/llm/test_intent_classifier_typesafe.py::test_governance_judgment_still_requires_confirmation_and_write_guard`.
- [ ] Product owner docs describe dormant repository support and pending Product dev acceptance; no activation is claimed. Verify: doc writeback at `docs/LLM_ROUTING.md :: Current policy and future work`.

## How to Verify (Pre-Merge)

- `pytest -q tests/components/llm/test_intent_classifier_typesafe.py tests/components/llm/test_intent_classifier.py`
- `pytest -q tests/api/test_canvas_coauthor_api.py tests/api/test_canvas_governance_handoff.py tests/chat/test_intent_unknown_route.py tests/chat/test_canvas_writer.py tests/panel/test_writeguard_retryable.py`
- `git diff --check`

## Out of Scope

- Full note-body transmission, automatic APPLY, removing confirmations, changing default chat generation, or activating Product test/prod channels.

## Related Docs

- `docs/TYPESAFE_SYSTEM_ONE/README.md`
- `docs/CANVAS_CHAT_SURFACE/README.md`
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md :: Rules for writes`


## Implemented Consumer Boundary

`IntentClassifierCognition(judgment_client=...).classify(intent=..., trace_id=...)` accepts only
intent text plus a local trace. The default uses the first declared Product executor path from
`resolve_executor_paths(EXECUTOR_NETWORK_PROFILE)` and the existing authenticated
`CodexRemoteTransport.judge_product_intent`; it does not consult generic model routing.
Caller-selected model/provider/profile controls and note context are absent. Invalid text fails
before constructing a client. Every returned Product result and both fixed named Choice answers
are revalidated, including injected or mutated models. Neither SDK imports nor provider key
resolution occur in the classifier.

The consumer floor is 0.8 for both confidence and selected-choice probability. Intent must meet
both; governance additionally requires a known action meeting both. A non-governance class must
carry the `unknown` action; its action confidence is immaterial. Unknown intent, unknown governance
action, contradiction, malformed response or any terminal failure yields `UNKNOWN` and
`classified=False`. Deterministic tests cover these boundaries; no semantic benchmark or live
calibration is claimed. The route still requires its existing confirmation/APPLY/WriteGuard path.

## Development Acceptance Gate

This plan is not an acceptance receipt or execution authority. Before executing it, require
confirmed rotation after the earlier exposure, separately authorized scoped MARR dev installation,
Product caller authentication and `judgment` authorization, and explicit permission for one
synthetic actual-consumer call. Runtime stays disabled in this repository delivery. Builder's
separate acceptance cannot satisfy Product's gate.

Use a temporary foreground `dev/marr-server-dev` process with
`MODEL_ACCESS_PRODUCT_TYPESAFE_MODE=acceptance_once`. Its atomic allowance is consumed before
provider-key lookup, including setup failure. Never reset, rearm or restart to repeat the attempt.
The final consumer invocation is:

```python
from uuid import uuid4
from app.components.llm.intent_classifier import IntentClassifierCognition
from app.model_access.codex_remote_transport import CodexRemoteTransport
from app.model_access.executor_network_policy import EXECUTOR_NETWORK_PROFILE, resolve_executor_paths

class CaptureOneResult:
    def __init__(self, delegate):
        self.delegate = delegate
        self.result = None
        self.called = False

    def judge_product_intent(self, intent_text):
        if self.called:
            raise RuntimeError("acceptance allowance consumed")
        self.called = True
        self.result = self.delegate.judge_product_intent(intent_text)
        return self.result

path = resolve_executor_paths(EXECUTOR_NETWORK_PROFILE)[0]
client = CodexRemoteTransport(
    endpoint=path.endpoint, path_adapter=path.adapter, tls_verify=path.tls_verify,
    client_certificate=path.client_certificate, timeout_seconds=30.0,
)
observed = CaptureOneResult(client)
correlation_id = str(uuid4())
try:
    classification = IntentClassifierCognition(judgment_client=observed).classify(
        intent="Compare two plans without writing or changing notes.", trace_id=correlation_id,
    )
finally:
    client.close()
# Inspect only allowlisted metadata from observed.result in memory; never print
# classification, the result model, answers, path, request or exception details.
```

This invokes the actual classifier -> existing Product client -> authenticated dev MARR -> pinned
SDK once. The delegating observer retains that same result; no second adapter/helper smoke is
allowed. Use the genuine provider only under the acceptance authority, not a fake backend. Stop the
temporary server after the attempt. An ambiguous outcome terminates authorization without retry or
fallback. Receipt approval precedes any separately authorized `accepted_dev` route change.

The redacted `typesafe.system_one.product_dev_acceptance.v1` receipt permits only:

| Field | Allowed content |
| --- | --- |
| `schema_version`, `consumer_id` | Receipt version and logical classifier consumer ID |
| `logical_product_caller_owner`, `profile_id`, `profile_owner` | Declared logical Product ownership identifiers |
| `selected_provider`, `selected_model`, `returned_provider`, `returned_model` | Exact validated selection/provenance identifiers; absent if unavailable |
| `sdk_package`, `sdk_version` | Actual package/version separately from model release; current server pin is `typesafe-sdk==0.7.2` |
| `question_ids` | Fixed `intent_class` and `action_type` identifiers, never answer values |
| `terminal_outcome` | Only `success`, `unavailable_before_send`, `outcome_unknown_after_dispatch`, `provider_rejected`, or `response_invalid`; absent result means no successful acceptance |
| `confidence_bucket` | `at_or_above_floor`, `below_floor`, or `unavailable`, computed over both answers without encoding their choices |
| `usage` | Non-secret validated input/output token counts only |
| `input_utf8_bytes`, `input_sha256`, `random_correlation_id` | Size/hash of the approved synthetic input and this random correlation |

Exclude prompts, source text, answers, semantic classification/action values and derived Choice
encodings under any renamed field (including `consumer_outcome_class`), credentials, endpoints,
host identity and raw errors. Do not serialize entire result/exception objects. A provider/model
identity mismatch or missing required successful-call evidence refuses acceptance. The profile's
current model `jev-1.13.0` is independently pinned; a supported owner-profile model update does not
change the consumer or neutral contract. No test/prod activation follows from this receipt.
