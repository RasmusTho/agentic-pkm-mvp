State: Active isolated test-channel UAT runbook.
Doc role: No-mock technical and synthetic-actor acceptance procedure.
Authority: Defines the execution and receipt procedure for `expansion-connect-create-accept-test-channel.v1`; Expansion behavior remains owned by `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`.
Owner: Cognitive Expansion / Retrieval
Temporal class: operational

# UAT — Expansion Connect → Create → Accept (isolated TEST)

## Boundary

This procedure runs only against an already-authorized, already-qualified isolated `test` channel. It never provisions, deploys, starts, restarts, re-indexes, repairs, or reconfigures a channel. It never targets production or the operator vault. The final action uses one synthetic test actor and one staged TEST draft; it does not record an actual owner's acknowledgement.

Connect may materialize only the existing governed unchecked `AI-åtgärder` proposal block on the selected source notes. It creates no draft or accepted canonical note. Create writes only a provenance-bearing draft under the configured TEST vault's staging directory. Draft exclusion is checked only after a fresh, healthy ingest watcher scan completes at a generation newer than the post-Create watermark, followed by stable index convergence. The synthetic actor checks the one dedicated `Accept this draft` control only after the technical phase passes; `app.expansion.accept.accept_draft` remains the only materialization path.

## Preconditions

1. Child #6293 is merged. Work from a clean checkout of the exact candidate to be evaluated; record `git rev-parse HEAD`, `git merge-base HEAD origin/main`, and confirm `git status --porcelain` is empty.
2. **Expansion actor authority:** verify the owner-authorized synthetic TEST actor amendment in [#4826](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4826#issuecomment-6107736254) still applies to this bounded journey. **Channel qualification is separate:** prove the exact current TEST target is already bound, running, and qualified by the preflight and identity checks below; API/DB reachability alone is insufficient. #3320 tracks a separate TEST recovery/security decision and does not authorize this Expansion actor or itself prove channel qualification. If preparing the target requires the exact principal/floor cutover described there, that cutover remains blocked until its own explicit approval; do not execute host or deployment effects as part of this UAT.
3. Run the candidate UAT on the host with explicit `PKM_ENVIRONMENT=test`, `PKM_CHANNEL=test`, `COMPOSE_PROJECT_NAME=pkm-test`, `VAULT_ROOT_TEST`, `VAULT_HOST_ROOT`, a host `app_test` DSN using a loopback address and the inspected TEST database's published port, `STORE_BACKEND=postgres`, and `INDEX_OUTBOX_PATH` set to this checkout's `tmp-test/index-outbox.jsonl`. `VAULT_ROOT_TEST` and `VAULT_HOST_ROOT` must resolve to the same selected TEST vault. Before any journey action, the runner read-only inspects the already-running `pkm-test` api, worker, and watcher containers: each must mount that exact host vault at `/app/vault`, have identical `DATABASE_URL` and `DB_DSN` bindings to the internal TEST endpoint `db:5432/app_test`, use the expected TEST bindings, and share the `pkm-test` `runtime-tmp` Docker volume at `/app/tmp-test`. DSN query parameters that can override the database endpoint or host selection are refused. It also inspects the running `pkm-test` db container, its actual published host port, and the default Compose network; host DSNs must parse to `localhost`, an IPv4/IPv6 loopback address, and that published port. The runner rejects host `db` overrides and resolves `db` from each app container to the inspected database container's address. The runtime volume must use Docker's local driver without bind/device options. No descendant mount may shadow a heartbeat or outbox path under `/app/tmp-test`. The runner binds the host action/audit outbox to the candidate checkout and rejects aliases into the inspected Docker volume mountpoint when that mountpoint is host-accessible. The host action/audit outbox and watcher outbox are separate storage locations; equal path strings do not prove they are shared. The runner reads watcher heartbeats through `docker exec` from the inspected watcher container. The selected reasoning backend must resolve to the live provider agent, and the effective reasoning route must resolve to a real provider; unsupported, mock, and golden backends are rejected. Create must record `outcome: success`, `degraded: false`, and no degradation reason before the technical phase can pass. Set no production or operator-vault values. Do not paste DSNs or credentials into the issue.
4. Choose exactly two seeded, indexed TEST notes with distinct identities. They must either carry the same explicit `domain` or both be unscoped (Connect treats that as the shared `unscoped` boundary); a mixed scoped/unscoped pair is invalid. The notes must be unlinked, contain no unresolved prior disposition for the selected Connect proposal, and the query must retrieve both as the top two results. The UAT verifies that exact top-two set before Connect runs, then sets `retrieval_k=2` to bound the production write scope to that pair. Do not run another Connect pass or modify either note concurrently. The existing bootstrap seeds an unlinked example pair: `reflection-journal.md` and `summary-request.md`.
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
python -m pytest -q tests/uat/test_expansion_connect_create_accept_test_channel.py
```

The runner repeats the channel preflight and doctor checks before the automated journey. All selected runtime scenarios must pass. The final synthetic-actor test self-skips unless its separate `RUN_EXPANSION_CONNECT_CREATE_ACCEPT_TEST_ACTOR` variable is set. The technical phase establishes:

- The candidate SHA, isolated TEST binding, and stored model identity.
- One same-scope Connect finding containing both selected identities; only the governed proposal block changes, and no draft or canonical artifact is created.
- One provenance-bearing Create draft, followed by a fresh healthy completed `ingest` scan generation newer than the post-Create watermark. The runner verifies the active container IDs, TEST project/service labels, host vault bind source, and shared named-volume identity before reading the heartbeat through that watcher container. The heartbeat must report the expected container paths; missing or mismatched bindings, stale, paused, degraded, malformed, reset, or newly errored observations fail closed. The UAT then requires current source hashes in stable durable index snapshots, an exhaustive direct index read that excludes the draft, and a retrieval check that also excludes it.
- A successful, non-degraded live cognition receipt; deterministic fallback collation is not a technical pass.
- An unchecked dedicated acceptance control is refused without a canonical write or acceptance receipt. Acceptance also refuses a checked copy when the draft-id-bound label occurs elsewhere in comments/code, and refuses destinations whose resolved path is not a descendant of the TEST vault.

The redacted receipt is written under the TEST vault's configured system receipts directory as `expansion-connect-create-accept-<run-id>.json`. Its `post_draft_watcher_scan` field records the completed generation and the verified TEST project, service mounts, and shared runtime volume. The receipt also records only relative artifact references, candidate/channel identity, the effective provider/model names, results, and the tested source identifiers/scope; it contains no source text, absolute vault path, DSN, or credential.

## Synthetic test-actor phase

After technical PASS, re-read the owner authorization at [#4826 comment 6107736254](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4826#issuecomment-6107736254) and confirm it still applies to this bounded synthetic actor action. Confirm the receipt's candidate SHA matches the current clean checkout and that its `technical_phase` is `pass`. The runner rechecks current channel preflight and strict index doctor before the action. #3320 is only relevant if a separate TEST recovery/security cutover is required; it is not the Expansion actor authorization.

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
