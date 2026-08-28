State: Active test-channel UAT runbook.
Doc role: Operator procedure / no-mock validation.
Authority: Defines the isolated technical and human acceptance procedure for `expansion-connect-create-accept-test-channel.v1`; Expansion semantics remain owned by `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`.
Owner: Cognitive Expansion / Retrieval
Temporal class: operational

# UAT — Expansion Connect → Create → Accept (test channel)

## Boundary

This runbook is test-channel only. It must use `PKM_ENVIRONMENT=test`, `PKM_CHANNEL=test`, `app_test`, `VAULT_ROOT == VAULT_ROOT_TEST`, and test-scoped outbox artifacts. Abort on a prod or operator-vault binding. It does not deploy, restart, re-index, or change any production/default/authority setting.

Connect remains proposal-only: it may add only the governed, unchecked `AI-åtgärder` candidate checkbox to source notes. It must not check a checkbox, create a draft, or alter frontmatter or note text outside that proposal block. Create writes only `_system/drafts/`; only the human checkbox followed by `app.expansion.accept.accept_draft` materializes a final note.

## Technical phase

1. Use an already bootstrapped and seeded test channel. This UAT never starts,
stops, restarts, re-indexes, or reconfigures it. Export the channel's existing
canonical environment into the shell before proceeding.

2. Confirm the BGE-M3 identity and strict index state. This is read-only; do not repair it inside this UAT.

```bash
python -m app.cli ops channel-preflight --channel test --context host
python -m app.cli index doctor --strict --json
```

The doctor must exit zero and report exactly `ollama/bge-m3:latest/1024/normalize=true` as both expected and stored identity.

3. Select two already indexed, same-scope test-vault notes and a query that returns both. Use a fresh filesystem-safe run id. These values are deliberate UAT inputs, not mocks.

```bash
export RUN_EXPANSION_CONNECT_CREATE_ACCEPT_UAT=1
export UAT_EXPANSION_RUN_ID="$(date +%Y%m%dT%H%M%S)"
export UAT_EXPANSION_SOURCE_PATHS='Test/source-a.md,Test/source-b.md'
export UAT_EXPANSION_CONNECT_QUERY='shared subject from those two notes'
python -m pytest -q tests/uat/test_expansion_connect_create_accept_test_channel.py \
  -k 'not checked_checkbox'
```

Expected technical PASS:

- Connect emits `propose` findings, adds only unchecked candidate checkbox affordances, and creates no draft.
- Create writes one proposal draft with resolvable source ids; that draft is absent from live retrieval.
- An unchecked acceptance call is rejected and leaves the draft non-canonical.
- The test-vault receipt is `_system/receipts/expansion-connect-create-accept-<run-id>.json` with `technical_phase: pass` and `human_checkbox_result: pending`.

## Human checkbox phase

After technical PASS, open only the draft named by that receipt in the test vault. A human checks exactly one `Accept this draft` checkbox. Do not check source-note Connect checkboxes, do not target an existing note, and do not use a production vault.

Then run:

```bash
export RUN_EXPANSION_CONNECT_CREATE_ACCEPT_HUMAN_ACCEPT=1
python -m pytest -q tests/uat/test_expansion_connect_create_accept_test_channel.py \
  -k checked_checkbox_uses_only_governed_materialization_path
```

Expected result: `app.expansion.accept.accept_draft` is the sole materialization call; the final test-vault note retains `sources`, `accepted_by: human`, and `acceptance_receipt_id`. The receipt changes to `human_checkbox_result: accepted` and records the final note plus acceptance receipt id.

## Publication receipt

Post a redacted copy of the receipt to #4826 and parent #2980 after the human phase, including the exact PR head SHA, technical result, human-checkbox result, and disposition. Never include vault content, absolute vault paths, or production identifiers.
