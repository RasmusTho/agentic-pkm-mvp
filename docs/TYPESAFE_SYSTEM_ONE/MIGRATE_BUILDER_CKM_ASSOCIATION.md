---
name: Use Jev for Builder CKM Semantic Association
description: Select CKM associations from a deterministic candidate set using typed Jev judgments.
task_id: TSO-04
github_issue: 5768
source_anchor: docs/CAPABILITY_KNOWLEDGE_MODEL/SEMANTIC_EVIDENCE_ASSOCIATION.md :: What This Task Does
parent_capability: TYPESAFE_SYSTEM_ONE
prerequisites: [TSO-01, TSO-05]
depends_on: [DEFINE_SYSTEM_ONE_JUDGMENT_CONTRACT.md, DEFINE_TYPESAFE_CREDENTIAL_BINDINGS.md]
can_parallelize_with: [TSO-03 after TSO-02]
---

# Use Jev for Builder CKM Semantic Association

## Purpose

The repository CKM path uses typed Jev choices over deterministic candidate IDs. This replaces
free-form proposal JSON while keeping CKM non-authoritative. The implementation is dormant until
the separate Builder dev acceptance below is approved.

## What This Task Does

- Build a deterministic set of at most 8 candidate records and 8 capability records. Each artifact has only an opaque candidate ID, enumerated artifact kind, and CKM-curated provenance excerpt ≤500 UTF-8 bytes; each capability has an opaque ID and name/definition summary ≤500 UTF-8 bytes. Serialized request ≤12 KiB. Reject `source_ref`, full records, repository/file text, prompts, unknown fields, and oversize requests before dispatch.
- Use the Builder-owned resolver/adapter path and `fallback_forbidden`; the production Builder call site does not name a provider or import Product MARR policy.
- Use a Choice with an explicit no-match option. Reject answers outside the submitted candidate set.
- Preserve inferred/candidate provenance, the existing confidence floor, stable edge identity, snapshot revalidation, watermark transaction, explicit `confirm-edge` receipt, and visible zero-edge skip on unavailable/degraded results.
- Authenticate to the bounded MARR operation with a separate Builder caller credential and policy. TSO-05 grants `typesafe.api-key` only to the Mac `marr-server-dev` consumer; CKM and Linux never resolve or receive it. Keep the Builder route unavailable pending its own dev acceptance; do not widen any BWS reader or grant test/prod access.

## Concretely

Jev returns one candidate ID (or no-match) with its probability/confidence. The CKM layer maps that result to the existing proposal schema using source IDs and deterministic provenance text. Any stale candidate snapshot or unusable answer writes zero edges and leaves the watermark unchanged.

The Builder resolver accepts only its provider-free CKM intent. Its own caller uses
`BUILDER_CKM_MARR_ENDPOINT`, `BUILDER_CKM_MARR_CA_BUNDLE`, `BUILDER_CKM_MARR_CLIENT_CERT` and
`BUILDER_CKM_MARR_CLIENT_KEY` as host-local endpoint/file references under `PKM_ENVIRONMENT=dev`.
The HTTPS client verifies its own CA and hostname and presents the separate Builder certificate.
The loopback MARR backend requires the authenticated ingress's `builder` / `ckm_judgment` grant.
Neither Product credentials nor the TypeSafe provider key are caller inputs.

The server's `config/model_access/builder_typesafe_profile.json` owns the exact `typesafe` /
`jev-1.13.0` selection under `builder.ckm_association.v1`. A supported release swap changes that
configuration and its reviewed allowlist only. Unknown, unpinned, unsupported or wrong-owner
profiles fail before key resolution. The independently pinned `typesafe-sdk==0.7.2` is confined to
the shared adapter; an SDK upgrade changes adapter/conformance rather than consumer or neutral
contracts. Fake profile-swap tests use a synthetic release and make no availability claim.

The actual SDK body has a Builder-only 12 KiB bound; Product keeps 4 KiB. Both paths preserve
single-attempt transport, suppressed SDK/HTTP diagnostic logging, safe terminal failures and exact
selected/returned model identity. Candidate writes reuse the existing snapshot revalidation and
SQLite edge-plus-watermark transaction. Any below-floor choice, including an uncertain no-match,
rejects the whole batch. Confirmation and authenticated rebuild receipts remain explicit.

## Why This Matters

Free-form JSON can invent IDs or output fields. Restricting the judgment to known candidates reduces that failure mode without granting CKM ranking, decision, dispatch, or confirmation authority.

## Acceptance Criteria

- [ ] The production CKM path uses the Builder-owned typed judgment adapter with provider-free intent and `fallback_forbidden`. Verify: `tests/builderops/ckm/test_semantic_typesafe.py::test_production_call_uses_builder_judgment_resolver`.
- [ ] The request contains only the declared allowlist and stays within the count/byte ceilings; answers outside the candidate set are rejected. Verify: `tests/builderops/ckm/test_semantic_typesafe.py::test_choice_is_limited_to_supplied_candidates` and `tests/builderops/ckm/test_semantic_typesafe.py::test_request_allowlist_and_size_limit_fail_before_dispatch`.
- [ ] Missing credentials, degraded route, low confidence, or stale input writes zero edges and leaves the semantic watermark unchanged. Verify: `tests/builderops/ckm/test_semantic_typesafe.py::test_unavailable_or_stale_judgment_writes_zero_edges`.
- [ ] The Builder route remains unavailable until the parent Issue records the synthetic dev acceptance receipt. Verify: runtime receipt: `typesafe.system_one.builder_dev_acceptance.v1`.
- [ ] Candidate lifecycle, confidence-floor, confirmation-receipt, and rebuild behavior remain enforced through the production store path. Verify: `tests/builderops/ckm/test_semantic_typesafe.py::test_existing_candidate_confirmation_and_rebuild_contract`.
- [ ] CKM documentation reports the TypeSafe path as dev-scoped and does not present inferred proposals as confirmed truth. Verify: doc writeback at `docs/CAPABILITY_KNOWLEDGE_MODEL/SEMANTIC_EVIDENCE_ASSOCIATION.md :: What This Task Does`.

## How to Verify (Pre-Merge)

- `pytest -q tests/builderops/ckm/test_semantic_typesafe.py tests/builderops/ckm/test_semantic.py`
- `pytest -q tests/ops/test_host_secret_contract.py::test_typesafe_key_is_dev_only_and_agent_processes_cannot_resolve_it`
- `lint-imports --config importlinter.ini`
- `git diff --check`

## Out of Scope

- Capability invention, confirmation or auto-apply, Product routing, Model Inquiry subscription reuse, test/prod credentials, live key provisioning, or full repository text transmission.

## Development Acceptance Gate

The Builder route remains unavailable after code merge until the parent Issue records `typesafe.system_one.builder_dev_acceptance.v1` from one explicitly authorized synthetic dev call through MARR using the separate Builder caller credential, after owner-confirmed provider-key rotation and scoped MARR dev host installation. This receipt does not activate any Product route or test/prod environment.

`MODEL_ACCESS_BUILDER_TYPESAFE_MODE` defaults to `disabled`. The host entrypoint accepts
`acceptance_once` or `accepted_dev` only with `HOST_SECRET_BOOTSTRAP_CONSUMER=marr-server-dev` and
`HOST_SECRET_BOOTSTRAP_CHANNEL=dev`. The server resolves its fixed Keychain tuple internally;
ambient provider keys are ignored. One `acceptance_once` allowance is consumed atomically before
credential lookup. Configure the persistent, owner-only `TYPESAFE_ACCEPTANCE_STATE_DIRECTORY`;
the Builder-owned `builder.acceptance.json` marker is atomically created and fsynced before that
lookup. Missing, malformed, or indeterminate marker state fails closed. No failure, timeout,
rejection, concurrent call or process restart grants a retry.
`accepted_dev` requires the separate approved Builder receipt; no committed configuration enables it.

The later operator plan, not executed by repository tests, is:

1. Confirm rotation and separately authorize scoped Mac installation plus exactly one synthetic
   Builder call. Start a temporary MARR process in `acceptance_once` through the existing dev
   bootstrap. Keep normal routes disabled and install/authorize only the distinct Builder mTLS
   identity and `builder` / `ckm_judgment` ingress grant. Do not copy the Product identity or grant.
2. In the delivered checkout, with the four Builder file/endpoint references supplied host-locally,
   run the following actual CKM consumer once. Use its isolated synthetic store; do not ingest any
   repository or GitHub artifacts. The observer records the real caller result without substituting
   a direct SDK/helper call. Do not print the request, answer or exception.

   ```python
   import json
   from hashlib import sha256
   from pathlib import Path
   from tempfile import TemporaryDirectory
   from app.builderops.ckm.judgment import BuilderCkmJudgmentClient, BuilderCkmJudgmentResolver
   from app.builderops.ckm.semantic import BuilderSemanticAssociator, associate_unlinked_artifacts
   from app.builderops.ckm.store import CkmStore
   from app.model_access.ckm_judgment_contract import encode_ckm_request

   observed = []
   class ObserveCaller(BuilderCkmJudgmentClient):
       def judge(self, request):
           wire = encode_ckm_request(request)
           result = super().judge(request)  # actual authenticated Builder MARR client
           observed.append((len(wire), sha256(wire).hexdigest(), result))
           return result

   with TemporaryDirectory(prefix="ckm-synthetic-acceptance-") as directory:
       store = CkmStore(Path(directory) / "ckm.sqlite3")
       store.ensure_schema()
       store.upsert_artifact(source_ref="synthetic:retrieval", artifact_kind="document",
           source="repo_docs", watermark="synthetic:v1",
           provenance=json.dumps({"payload_summary": "Synthetic evidence for retrieval"}))
       store.upsert_capability(identity_key="synthetic:retrieval", name="Retrieval",
           definition="Find related evidence.", existence_provenance="synthetic fixture",
           lifecycle="confirmed")
       resolver = BuilderCkmJudgmentResolver(client_factory=ObserveCaller)
       outcome = associate_unlinked_artifacts(store, limit=1, confidence_floor=0.6,
           client=BuilderSemanticAssociator(resolver=resolver))  # one consumer invocation
       candidate_count = outcome.proposed
       confirmed_count = sum(edge.lifecycle == "confirmed" for edge in store.list_evidence_edges())
       # Build only the allowlisted receipt below from observed[0] and these counts.
   ```

3. Verify this call traversed CKM → Builder client → authenticated MARR operation → pinned SDK.
   On success, read selected provider/model/SDK from `result.selection` and returned provider/model
   from `result.judgment.provenance`; they must match. Record usage and a confidence bucket, never
   choices. One successful consumer call under the one-attempt server allowance proves one provider
   send; an ambiguous failure must say `unknown`, never invent a successful send/return. Review the
   allowlist before publishing the receipt on #5764. Use this template, replacing every placeholder
   from that same call; it is not evidence until completed and reviewed:

   ```json
   {
     "schema": "typesafe.system_one.builder_dev_acceptance.v1",
     "consumer_id": "builderops-ckm-semantic",
     "code_sha": "<delivered SHA>",
     "channel": "dev",
     "caller_owner": "builder",
     "profile_id": "builder.ckm_association.v1",
     "selected_provider": "<observed>", "selected_model": "<observed>",
     "returned_provider": "<observed or null>", "returned_model": "<observed or null>",
     "sdk_version": "<observed>", "question_ids": ["capability_1"],
     "outcome": "<safe terminal outcome>", "confidence_bucket": "<below_floor|accepted|unavailable>",
     "consumer_invocations": 1, "provider_sends": "<1|0|unknown>",
     "input_bytes": "<observed>", "input_sha256": "<observed>",
     "correlation_id": "<random UUID>", "usage": "<bounded counters or null>",
     "candidate_count": "<0 or 1>", "confirmed_count": 0
   }
   ```

4. Stop the temporary server. A failed or ambiguous attempt ends the authorization without replay,
   fallback or automatic rearming. Approval of the completed receipt precedes any separate change
   to `accepted_dev`. Prompts, state text, answer values, credentials, endpoints, host identity and
   raw diagnostics are forbidden in the receipt. This plan authorizes no installation or live call.

## Related Docs

- `docs/TYPESAFE_SYSTEM_ONE/README.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/SEMANTIC_EVIDENCE_ASSOCIATION.md`
- `docs/MODEL_ACCESS_SUBSTRATE/README.md`
- `docs/LOCAL_SECRET_PROVISIONING/README.md`
