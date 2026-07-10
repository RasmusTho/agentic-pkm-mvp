---
name: Prove And Accept Karakeep To Mimer
description: Produce the real test-channel verification ledger, replay proof, negative-path evidence, and parent closure handoff.
task_id: KMA-06
source_anchor: "docs/KARAKEEP_MIMER_ACQUISITION/README.md :: Validation / acceptance path"
parent_capability: Karakeep Mimer Acquisition
prerequisites: [KMA-05]
depends_on: [SCHEDULE_INCREMENTAL_KARAKEEP_ACQUISITION]
can_parallelize_with: []
---

# Prove And Accept Karakeep To Mimer

## Purpose

Accept the capability on real evidence rather than CI fixtures and reconcile all backlog/docs state
only when the complete Karakeep → KAP path is true.

## What This Task Does

Run one saved-link journey containing a note and highlight on the mac-mini test channel; link source
item, raw identity, candidate path, stage/run receipts, and service health; test restart/replay,
duplicate no-op, WriteGuard refusal, and source-unavailable behavior; audit logs for secret leakage;
then update the parent ledger and owner-doc promotion disposition.

## Concretely

The parent receives a timestamped acceptance comment with commit/deployment identity, test
channel, source revision (non-secret identifier), raw/candidate linkage, negative-path outcomes,
replay result, and explicit pass/fail for every capability AC.

## Why This Matters

Stubbed CI cannot prove the self-hosted service, runtime configuration, governed vault write, and
restart semantics compose on the real host. This ledger is the supported-truth gate.

## SBS Impact

Product/Runtime verification across EBF, DRI, HKA/SIP/GOV, OEF, and EXE. This task changes supported
truth only through the normal parent closure and owner-doc PR path.

## Restart / Durability Posture

Restart the service and worker between fetch and replay. Proof must show the cursor resumes, stored raw
evidence replays with zero source egress, and deterministic candidate writeback does not duplicate.

## Acceptance Criteria

- [ ] Real saved link + note + highlight produces linked raw and draft candidate artifacts through
  KAP, with no capture call. Verify: validation receipt on the parent issue containing source
  revision, raw `content_identity`, candidate path, and stage/run receipt ids.
- [ ] Duplicate run and restart/replay produce no duplicate candidate; replay from raw uses zero
  Karakeep egress. Verify: same parent receipt, `Restart/replay` section.
- [ ] Service unavailable and WriteGuard blocked paths fail legibly without unsafe cursor advance or
  false completion. Verify: same parent receipt, `Negative paths` section.
- [ ] Logs/events/notes contain no credential or private endpoint value. Verify: same parent receipt,
  `Secret audit` section with command/output reference.
- [ ] Every capability AC maps to evidence; unresolved AC keeps parent open; accepted truth triggers
  one owner-doc promotion PR and spec state reconciliation. Verify: parent closing ledger plus doc
  writeback at `docs/KARAKEEP_MIMER_ACQUISITION/README.md :: State`.

## How to Verify (Pre-Merge)

- Run the KMA-02 health procedure on the test channel.
- Trigger one bounded KMA-05 run and collect receipt ids.
- Stop/restart service and worker; replay stored raw with source access disabled.
- Repeat identical acquisition; verify no-op and unchanged candidate count/path.
- Disable writes; verify blocked outcome and unchanged cursor, then re-enable and retry once.
- Search bounded logs/receipts/rendered artifacts for the known test secret and endpoint value; expect
  zero matches. Post only redacted evidence to the parent.
- Run `pytest -q tests/knowledge_acquisition/test_karakeep_*.py tests/ops/test_karakeep_service_contract.py`.

## Out of Scope

Production rollout, private configuration disclosure, ongoing SLO monitoring, Direction A MCP setup,
Raindrop ingestion, and closing the parent without complete evidence.

## Related Docs

- `docs/RELEASE_CHANNELS/README.md`
- `docs/KNOWLEDGE_ACQUISITION/REPLAY_AND_STAGE_EVENTS.md`
- `docs/KARAKEEP_MIMER_ACQUISITION/README.md`

## Related GitHub Issues

Future terminal child, strictly after KMA-05. TCD hint: strongest available model / high reasoning plus
operator-assisted test-channel execution; acceptance truth and secret handling require careful review.
