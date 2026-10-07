---
name: Add TypeSafe to the Mac Model Access Router
description: Add one authenticated, bounded System One judgment operation to the Product Mac executor.
task_id: TSO-02
github_issue: 5766
source_anchor: docs/MODEL_ACCESS_ROUTER/README.md :: Capability Contract
parent_capability: TYPESAFE_SYSTEM_ONE
prerequisites: [TSO-01, TSO-05]
depends_on: [DEFINE_SYSTEM_ONE_JUDGMENT_CONTRACT.md, DEFINE_TYPESAFE_CREDENTIAL_BINDINGS.md]
can_parallelize_with: []
---

# Add TypeSafe to the Mac Model Access Router

## Purpose

Product and Builder requests need to reach Jev through separate caller authorization without exposing the TypeSafe provider key to either caller, Linux, Codex, or Claude. One MARR Mac dev server owns that runtime credential.

## Credential-source supersession

TSO-02 was delivered against the then-current Keychain-only provider-key binding from TSO-05.
TSO-07 and follow-up #5808 replace that provider-key source with the existing `non-prod` BWS project
and reader identity, while retaining an MARR-only consumer binding. The BWS reader token remains in the MARR host Keychain. Product keeps the
same caller authorization and does not gain BWS access.

## What This Task Does

- Add a bounded System One judgment operation to the MARR service and Product client, reusing existing authenticated admission and channel/action authorization.
- Accept only the typed contract and the closed Product allowlist: `intent_text` up to 2,000 UTF-8 bytes; serialized request ≤4 KiB. Reject `current_body`, note titles, vault paths, prior turns, and unknown fields before dispatch.
- Execute one request with SDK retries disabled. Classify `unavailable_before_send`, `outcome_unknown_after_dispatch`, `provider_rejected`, `response_invalid`, and `success`; every state is terminal. A timeout after dispatch may have begun is `outcome_unknown_after_dispatch`, and the same request is never replayed.
- Resolve `typesafe.api-key` only for `marr-server-dev` on `dev` through the host-secret contract. TSO-02 originally used its Mac Keychain-only binding; TSO-07/#5808 supersede that source with the non-prod BWS identity. Product and Builder keep separate caller credentials and policies; neither receives the provider key. Missing or unauthorized server bindings fail closed.
- Do not retry a request after a send may have reached TypeSafe; do not fall back to Codex or Ollama after inference may have started.

## Concretely

The repository implementation provides `POST /v1/judgment` and
`CodexRemoteTransport.judge_product_intent(intent_text)`. The client uses the existing configured
HTTPS ingress and Product caller identity. Admission requires the loopback backend peer and the
authenticated `product` channel's `judgment` action; a `complete` or Builder grant does not authorize
this operation. `product_intent_request` constructs the two fixed Choice questions (`intent_class`
and `action_type`), including `unknown`. The executor requires that exact template and only the
`intent_text` state field. Caller-supplied question text, profile, model, endpoint, headers, keys and
provider parameters are rejected. The neutral `llm_contract` and existing classifier behavior are
unchanged; TSO-03 owns interpretation and confidence thresholds.

The Product-owned `config/model_access/product_typesafe_profile.json` declares the selected
`product.canvas_intent.v1` profile and its reviewed exact model allowlist. It currently pins
`typesafe` / `jev-1.13.0`. A supported release update changes only that profile configuration
(including its reviewed allowlist); it does not change the shared request, client or consumer.
Unknown profiles, another owner, unsupported models and moving aliases such as `jev-latest` fail
before credential lookup or dispatch. Profile-swap tests use a synthetic future release and do not
establish its live availability.

The separate package pin is `typesafe-sdk==0.7.2` in `pyproject.toml` and `requirements.txt`, checked
by `typesafe_adapter.py`. SDK upgrades belong to that adapter and
`tests/model_access/test_typesafe_sdk_conformance.py`; they do not change model selection. The adapter
fixes the documented API root, explicitly supplies the key/model, disables SDK and HTTP retries,
redirects and environment proxies, and disables SDK wire logging. It bounds the actual provider
request to 4 KiB and the response to 16 KiB, rejects duplicate JSON keys, and validates answers
against the exact request and returned model against the selected model. The result carries only
typed answers, safe outcome, selected profile/provider/model/SDK, returned provider/model and bounded
usage. No raw provider error crosses the boundary.

Official conformance sources: [Python client](https://docs.typesafe.ai/sdk/python/api/clients/sync),
[retry policy](https://docs.typesafe.ai/sdk/python/api/retries),
[answer types](https://docs.typesafe.ai/sdk/python/api/types/responses), and
[versioned models](https://docs.typesafe.ai/models). Repository proof uses the installed pinned SDK
with injected fake HTTP transport; it is not live acceptance.

## Why This Matters

Sending the runtime key to Product, Builder, Linux, or a coding-agent process would widen the credential boundary and bypass the chosen Mac-executor path.

## Acceptance Criteria

- [ ] The production MARR route authorizes the same Product channel/action as its peer operations and dispatches exactly one TypeSafe request. Verify: `tests/model_access/test_typesafe_judgment_executor.py::test_executor_dispatches_one_bounded_system_one_request`.
- [ ] Missing or malformed MARR provider credentials fail before the provider request and never enter logs, responses, or receipts. TSO-02 proved this with a fake Keychain source; TSO-07 adds the fake BWS/keychain-token path. Verify: `tests/model_access/test_typesafe_judgment_executor.py::test_missing_typesafe_credential_fails_before_provider_call`.
- [ ] The SDK transport performs one attempt and maps pre-send failure, ambiguous post-dispatch timeout, provider rejection, and invalid response to distinct terminal outcomes. Verify: `tests/model_access/test_typesafe_judgment_executor.py::test_provider_outcomes_are_terminal_and_never_retried`.
- [ ] The executor rejects disallowed fields and over-limit serialized requests before network dispatch. Verify: `tests/model_access/test_typesafe_judgment_executor.py::test_request_allowlist_and_size_limit_fail_before_dispatch`.
- [ ] The TypeSafe binding is limited to the `marr-server-dev` Mac dev server consumer and does not grant it to unrelated consumers or channels. Verify: `tests/ops/test_host_secret_contract.py::test_typesafe_key_is_dev_only_and_agent_processes_cannot_resolve_it`.
- [ ] MARR owner docs distinguish typed judgments from generic completions and state the supported behavior accurately. Verify: doc writeback at `docs/MODEL_ACCESS_ROUTER/README.md :: Current State and Boundary`.
- [ ] Product profile swaps preserve the request/client contract and reject unknown, unpinned, unsupported or wrong-owner profiles before dispatch.
  - Verify: `tests/model_access/test_typesafe_judgment_executor.py::test_supported_model_profile_swap_keeps_request_contract`
  - Verify: `tests/model_access/test_typesafe_judgment_executor.py::test_unconfigured_model_profile_fails_before_dispatch`

## How to Verify (Pre-Merge)

- `pytest -q tests/model_access/test_typesafe_judgment_executor.py`
- `pytest -q tests/ops/test_host_secret_contract.py::test_typesafe_key_is_dev_only_and_agent_processes_cannot_resolve_it`
- `pytest -q tests/model_access/test_typesafe_sdk_conformance.py`
- `pytest -q tests/model_access/test_codex_executor_service.py tests/model_access/test_codex_remote_transport.py tests/model_access/test_executor_network_authorization.py`
- `git diff --check`

## Out of Scope

- Builder routing, Product intent-classifier semantics, catalog discovery, provider fallback, production host activation, live key provisioning, or live API calls in CI.

## Development Acceptance Gate

The Product route remains disabled/unavailable after code merge until the parent Issue records `typesafe.system_one.product_dev_acceptance.v1` from one explicitly authorized synthetic dev call through the designated MARR Mac server, after owner confirmation of rotation and scoped host installation. The server owns the provider key and the Product caller uses its separate caller credential. The host receipt is not a CI test and does not activate test/prod.

The host entrypoint defaults `MODEL_ACCESS_PRODUCT_TYPESAFE_MODE` to `disabled`. It recognizes
`acceptance_once` and `accepted_dev` only inside the existing `dev` / `marr-server-dev` bootstrap
identity. A pending or malformed host configuration performs no key lookup. The server resolves
the fixed MARR-only provider binding itself; ambient `TYPESAFE_API_KEY` is not a credential source.
`acceptance_once` consumes one durable Product-owned allowance before credential lookup, using the
operator-configured `TYPESAFE_ACCEPTANCE_STATE_DIRECTORY` and an owner-only
`product.acceptance.json` marker. Creation writes the marker, fsyncs it and its containing
directory, and only then permits lookup; a valid marker, malformed marker, marker-write failure,
or missing state directory fails closed before BWS or provider access. A timeout, rejection,
process restart, or new executor never rearms it. `accepted_dev` is permitted only after the
separate Product receipt is approved.
There is no checked-in activation, production binding or installation in this slice.

The later operator acceptance plan is:

1. After confirmed rotation and separately authorized scoped installation, start a temporary
   MARR process through the existing `dev` / `marr-server-dev` bootstrap in `acceptance_once` mode.
   Keep the normal Product runtime route disabled. Use the existing authenticated Product ingress
   with its explicit `judgment` action and Product caller credential, separately from Builder.
2. Once TSO-03 has delivered its consumer, invoke `IntentClassifierCognition.classify` exactly once
   with a synthetic intent (for example, asking to compare two plans without writing). Supply its
   actual Product MARR client through the existing injection/configuration seam; the call must reach
   `judge_product_intent` → authenticated `/v1/judgment` → this pinned SDK adapter. Do not substitute
   a direct adapter/helper smoke. Do not print the input, judgment or exception.
3. Build the redacted `typesafe.system_one.product_dev_acceptance.v1` receipt from that same result:
   schema/consumer ID, logical Product caller/profile ownership, selected and returned provider/model,
   separate SDK version, question IDs, terminal outcome, confidence bucket, bounded usage, input
   UTF-8 byte count and SHA-256, and a random correlation ID. Exclude prompts, source text, answers,
   credentials, endpoints, host identity and raw errors. Review the allowlisted receipt before
   publishing it on parent #5764.
4. Stop the temporary process. An ambiguous result ends that authorization with no replay/fallback.
   Approve the receipt before any separate change to `accepted_dev`; this plan authorizes no call,
   installation or route change by itself. TSO-03 must bind the final exact consumer invocation.

## Related Docs

- `docs/TYPESAFE_SYSTEM_ONE/README.md`
- `docs/MODEL_ACCESS_ROUTER/README.md`
- `docs/LOCAL_SECRET_PROVISIONING/README.md :: Declared identifier contract`
- `docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md`
