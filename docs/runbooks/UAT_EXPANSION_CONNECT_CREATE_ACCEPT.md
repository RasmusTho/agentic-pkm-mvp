State: Active isolated test-channel UAT runbook.
Doc role: No-mock technical and synthetic-actor acceptance procedure.
Authority: Defines the execution and receipt procedure for `expansion-connect-create-accept-test-channel.v1`; Expansion behavior remains owned by `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`.
Owner: Cognitive Expansion / Retrieval
Temporal class: operational

# UAT — Expansion Connect → Create → Accept (isolated TEST)

## Boundary

This procedure runs only against an already-authorized, already-qualified isolated `test` channel. It never provisions, deploys, starts, restarts, re-indexes, repairs, or reconfigures a channel. It never targets production or the operator vault. The final action uses one synthetic test actor and one staged TEST draft; it does not record an actual owner's acknowledgement.

Connect may materialize only the existing governed unchecked `AI-åtgärder` proposal block on the selected source notes. It creates no draft or accepted canonical note. Create writes only a provenance-bearing draft under the configured TEST vault's staging directory. The draft remains excluded from retrieval after index convergence. The synthetic actor checks the one dedicated `Accept this draft` control only after the technical phase passes; `app.expansion.accept.accept_draft` remains the only materialization path.

## Preconditions

1. Child #6293 is merged. Work from a clean checkout of the exact candidate to be evaluated; record `git rev-parse HEAD`, `git merge-base HEAD origin/main`, and confirm `git status --porcelain` is empty.
2. Read #3320. Do not run either UAT phase until it contains the current explicit TEST-only authorization and qualification. The user-level TEST channel must already be bound and running; API/DB reachability alone is insufficient.
3. The host environment must already provide explicit `PKM_ENVIRONMENT=test`, `PKM_CHANNEL=test`, `VAULT_ROOT_TEST`, a host-reachable `app_test` DSN, `STORE_BACKEND=postgres`, and a TEST-scoped `INDEX_OUTBOX_PATH`. The effective reasoning route must resolve to a real provider; mock/golden backends are rejected. Set no production or operator-vault values. Do not paste DSNs or credentials into the issue.
4. Choose exactly two seeded, indexed TEST notes with distinct identities. They must either carry the same explicit `domain` or both be unscoped (Connect treats that as the shared `unscoped` boundary); a mixed scoped/unscoped pair is invalid. The notes must be unlinked, contain no unresolved prior disposition for the selected Connect proposal, and the query must retrieve both. The existing bootstrap seeds an unlinked example pair: `reflection-journal.md` and `summary-request.md`.
5. The TEST index must already store `ollama/bge-m3:latest/1024/normalize=true`. Do not download models or run any repair if the preflight or doctor fails.

## Technical phase

Use a unique, filesystem-safe run id and the two existing seeded relative paths. Keep all source text and environment values local:

```bash
export RUN_EXPANSION_CONNECT_CREATE_ACCEPT_UAT=1
export UAT_EXPANSION_RUN_ID="$(date +%Y%m%dT%H%M%S)"
export UAT_EXPANSION_SOURCE_PATHS='Test/AgenticPKM-UAT/reflection-journal.md,Test/AgenticPKM-UAT/summary-request.md'
export UAT_EXPANSION_CONNECT_QUERY='LangGraph agent experiments and concise summary'

python -m app.cli ops channel-preflight --channel test --context host
python -m app.cli index doctor --strict --json
python -m pytest -q tests/uat/test_expansion_connect_create_accept_test_channel.py \
  -k 'not checked_checkbox'
```

The runner repeats the channel preflight and doctor checks before the automated journey. All selected runtime scenarios must pass. The intentionally deselected test-actor action remains pending. The technical phase establishes:

- The candidate SHA, isolated TEST binding, and stored model identity.
- One same-scope Connect finding containing both selected identities; only the governed proposal block changes, and no draft or canonical artifact is created.
- One provenance-bearing Create draft, current source hashes in stable durable index snapshots, and an exhaustive direct index read that excludes the draft. Retrieval is also checked after that convergence observation.
- An unchecked dedicated acceptance control is refused without a canonical write or acceptance receipt.

The redacted receipt is written under the TEST vault's configured system receipts directory as `expansion-connect-create-accept-<run-id>.json`. It records only relative artifact references, candidate/channel identity, the effective provider/model names, results, and the tested source identifiers/scope; it contains no source text, absolute vault path, DSN, or credential.

## Synthetic test-actor phase

After technical PASS, re-read #3320 and confirm its explicit TEST-only authorization and qualification still apply to the same candidate and channel. Confirm the receipt's candidate SHA matches the current clean checkout and that its `technical_phase` is `pass`. The runner rechecks channel preflight and strict index doctor before the action.

Run exactly this one selected test with the same run id and source/query bindings:

```bash
export RUN_EXPANSION_CONNECT_CREATE_ACCEPT_TEST_ACTOR=1
python -m pytest -q tests/uat/test_expansion_connect_create_accept_test_channel.py \
  -k checked_checkbox_uses_only_governed_materialization_path
```

The synthetic actor changes exactly one dedicated checkbox in the named TEST draft and invokes the existing governed `accept_draft` function once. The resulting TEST note must preserve `sources`, `derived_by: synthesis`, `accepted_by: human`, and the acceptance receipt id. The receipt records that this was a synthetic TEST actor and links the draft, final note, and source identities.

If this phase fails or its result is uncertain, do not replay the checkbox action. Inspect the existing receipt, draft, final note, and acceptance receipt read-only; then report the actual disposition on #4826 and #2980.

## Receipt publication

Post the redacted receipt to #4826 and parent #2980. Include the exact base/head SHA, TEST qualification and doctor result, technical outcome, synthetic test-actor action and disposition, and relative artifact lineage. Exclude source contents, absolute paths, credentials, DSNs, and production identifiers. Never claim PASS when a required scenario is skipped, missing, failed, or based on a different candidate.
