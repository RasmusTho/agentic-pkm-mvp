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
only when the complete Karakeep → Heimdal published handoff → Mimer/KAP path is true.

## What This Task Does

Run one saved-link journey containing a note and highlight in the logical `test` channel, after the
Karakeep service host, private route to TEST Heimdal, and governed runtime configuration have been
qualified through current authorized evidence. The old machine-specific test-channel instruction is
stale; local Compose is not TEST evidence. Link the
source item, Heimdal published-evidence identity, Mimer candidate path, both cursors, stage/run
receipts, and service health; test restart/replay,
duplicate no-op, WriteGuard refusal, and source-unavailable behavior; audit logs for secret leakage;
then update the parent ledger and owner-doc promotion disposition.

## Concretely

The parent receives a timestamped acceptance comment with commit/deployment identity, test
channel, source revision (non-secret identifier), published-evidence/candidate linkage, both cursor
positions, constituent-specific negative-path outcomes,
replay result, and explicit pass/fail for every capability AC.

## Why This Matters

Stubbed CI cannot prove the self-hosted service, runtime configuration, governed vault write, and
restart semantics compose on the real host. This ledger is the supported-truth gate.

## SBS Impact

Product/Runtime boundary verification across Heimdal/EBF, Mimer/DRI/HKA/SIP/GOV, OEF, and EXE. This
task changes supported truth only through the normal parent closure and owner-doc PR path.

## Restart / Durability Posture

Restart Karakeep, Heimdal producer, and Mimer consumer independently. Proof must show each cursor
resumes, Mimer replays published evidence with zero source egress, and candidate writeback does not
duplicate.

## Acceptance Criteria

- [ ] Real saved link + note + highlight produces linked Heimdal published evidence and Mimer draft
  candidate, with no capture call. Verify: validation receipt on the parent issue containing source
  revision, published `content_identity`, attribution/provenance, candidate path, and receipt ids.
- [ ] Duplicate run and restart/replay produce no duplicate candidate; replay from raw uses zero
  Karakeep egress. Verify: same parent receipt, `Restart/replay` section.
- [ ] Service unavailable blocks Heimdal only; WriteGuard refusal blocks Mimer consumer progress only;
  neither creates false completion. Verify: same parent receipt, `Negative paths` section.
- [ ] Logs/events/notes contain no credential or private endpoint value. Verify: same parent receipt,
  `Secret audit` section with command/output reference.
- [ ] Every capability AC maps to evidence; unresolved AC keeps parent open; accepted truth triggers
  one owner-doc promotion PR and spec state reconciliation. Verify: parent closing ledger plus doc
  writeback at `docs/KARAKEEP_MIMER_ACQUISITION/README.md :: State`.

## How to Verify (Pre-Merge)

- Repository-native wiring is exposed only as `scripts/karakeep-acquire test` and
  `scripts/karakeep-project test`. Each uses the existing authenticated SSH/root-only encrypted
  reader supervisor, then a separate fixed child in the selected TEST Product image. DEV, PROD,
  unknown actions and extra arguments refuse before lookup or work. Ordinary supervisor/boot
  imports do not require Product packages in the BWS Python runtime. The generic BWS consumer
  launcher remains denied for `heimdal-karakeep-fetch`.
- Before a live invocation, main must install the reviewed control code/launcher and qualify the
  selected exact-SHA TEST Product image, existing `app_test` PG endpoint and password-file protocol,
  channel-owned vault, active initialized binding/GOV authority, instance-state/ownership mounts
  and shared TEST runtime volume. Admission checks actual container/code/mount identities; the
  child proves PG server/database and migration-owned store availability in its own namespace and
  revalidates the existing binding under its shared effect lease. Missing inputs refuse without
  selecting or repairing a vault, database or credential.
- Acquisition additionally requires an observed existing route to Karakeep in that namespace:
  a matching shared Docker network, or the host namespace with loopback port 3000. Missing topology
  refuses; this slice does not connect networks or grant egress. The saved service `server_url` is
  the Mac's SSH-forwarded client route and is never a worker endpoint. Only the producer resolves
  `test/karakeep.api-key` for `heimdal-karakeep-fetch`, delivered through stdin in memory; Mimer
  receives neither that key nor an endpoint and can replay while Karakeep is down.
- Every invocation holds an OS flock for its own constituent through work/acknowledgement.
  The two locks are independent. Process interruption or lost acknowledgement reports `pending`,
  never completion; retry reconstructs full published lineage and deliberately rescans page one.
  Mimer advances only its existing `mimer.candidate_projector` durable prefix. Receipts contain
  closed statuses and counts, no upstream pagination token, private path/endpoint or raw errors.
- Installing a newer control checkout does not reauthorize the retained exact-revision service
  boot request. Main performs explicit service lifecycle re-admission separately after merge.
  Fixture verification of Issue #6025 proves this native wiring only. Actual installation and the
  following PG/source-to-candidate, replay, negative-path and secret-audit receipts remain required
  on open parent #3367 before live acceptance or owner-doc supported-truth promotion.
- Run the KMA-02 health procedure on the test channel.
- Run `scripts/karakeep-acquire test`, then separately `scripts/karakeep-project test`; collect
  their bounded outcomes and durable source/log/candidate/cursor linkage in the parent receipt.
- Stop/restart service, Heimdal producer, and Mimer consumer independently; replay published evidence
  in Mimer with source access disabled.
- Repeat identical acquisition; verify no-op and unchanged candidate count/path.
- Disable writes; verify blocked Mimer outcome and unchanged consumer cursor while Heimdal producer
  cursor remains independent, then re-enable and retry once.
- Search bounded logs/receipts/rendered artifacts for the known test secret and endpoint value; expect
  zero matches. Post only redacted evidence to the parent.
- Run `pytest -q tests/heimdal/test_karakeep_*.py tests/knowledge_acquisition/test_karakeep_*.py tests/ops/test_karakeep_service_contract.py`.

## Out of Scope

Production rollout, private configuration disclosure, ongoing SLO monitoring, Direction A MCP setup,
Raindrop ingestion, and closing the parent without complete evidence.

## Related Docs

- `docs/RELEASE_CHANNELS/README.md`
- `docs/KNOWLEDGE_ACQUISITION/REPLAY_AND_STAGE_EVENTS.md`
- `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`
- `docs/KARAKEEP_MIMER_ACQUISITION/README.md`

## Related GitHub Issues

Issue #3376, strictly after KMA-05. TCD hint: strongest available model / high reasoning plus
operator-assisted test-channel execution; acceptance truth and secret handling require careful review.
