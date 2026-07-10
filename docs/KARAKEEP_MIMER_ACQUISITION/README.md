State: FILED specification directory (parent #3367; children #3372–#3377). D1 is settled. All
children remain `agent:blocked` until this specification merges; no Karakeep service or ingestion
support is claimed as shipped.
Doc role: Capability specification (feature-breakdown lane)
Authority: Product/Runtime target-state specification subordinate first to accepted `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`, then `docs/HEIMDAL/FABLE_COMPANION.md`, `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md`, and `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md`.
Owner: Architecture / Product

# Karakeep → Mimer Acquisition

## Capability boundary

Run the owner-selected, self-hosted Karakeep service on the mac mini and incrementally acquire its
saved links, notes, and highlights across the accepted Heimdal→Mimer boundary. **Heimdal owns the
entire external front:** REST watch/fetch, source identity and provenance, attribution/entity
mentions, durable cursoring, and the published-evidence handoff. **Mimer starts only at that durable
handoff:** KAP refines the published evidence and writes review-required reading candidates through
the governed `app/knowledge_acquisition/candidate_writeback.py` path.

The handoff is the capability boundary. Heimdal never writes a Mimer candidate note; Mimer never
contacts Karakeep, owns a Karakeep fetch cursor, or redoes source attribution. Mimer may resolve
entity mentions and extract meaning after handoff, consistent with ADR-0049.

This is **not companion capture** and does not call Mimer's `/api/capture` endpoint. Karakeep's
bundled MCP server is also outside this capability: connecting an interactive assistant to that
server is Direction A operator configuration. Private endpoint selection, credential values, DNS,
and firewall policy remain operator-owned deployment inputs and are deliberately not specified here.

## Product/Runtime SBS classification

This is Product/Runtime **boundary work between two runtime constituents**, not Builder System work.
Heimdal/EBF owns Karakeep egress, identity, attribution, producer cursor, and published evidence;
Mimer/DRI owns refinement from that handoff, while HKA/SIP/GOV are touched only through governed,
review-required candidate writeback. OEF owns the managed service/schedule substrate. No BuilderOps
or Builder System authority changes.

## Implementation tasks

| Order | Task | Outcome |
|---|---|---|
| 1 | [DEFINE_READING_SOURCE_AND_CANDIDATE_CONTRACT.md](DEFINE_READING_SOURCE_AND_CANDIDATE_CONTRACT.md) | Define Heimdal Karakeep acquisition/published-evidence → Mimer KAP refinement contract. |
| 2 | [DEPLOY_KARAKEEP_AS_A_MANAGED_SERVICE.md](DEPLOY_KARAKEEP_AS_A_MANAGED_SERVICE.md) | Add a reproducible, health-checked mac-mini service deployment. |
| 3 | [FETCH_KARAKEEP_READING_EVIDENCE.md](FETCH_KARAKEEP_READING_EVIDENCE.md) | Implement Heimdal REST fetch, identity/provenance/attribution, producer cursor, and published handoff. |
| 4 | [NORMALIZE_AND_WRITE_READING_CANDIDATES.md](NORMALIZE_AND_WRITE_READING_CANDIDATES.md) | Consume published evidence in Mimer/KAP and write deterministic review-required candidates. |
| 5 | [SCHEDULE_INCREMENTAL_KARAKEEP_ACQUISITION.md](SCHEDULE_INCREMENTAL_KARAKEEP_ACQUISITION.md) | Coordinate independent Heimdal producer and Mimer consumer runs without crossing ownership. |
| 6 | [PROVE_AND_ACCEPT_KARAKEEP_TO_MIMER.md](PROVE_AND_ACCEPT_KARAKEEP_TO_MIMER.md) | Prove real test-channel flow and close the capability only on receipts. |

## Execution order

`1 → (2 ∥ 3 → 4) → 5 → 6`.

Tasks 2 and 3 are independent after the contract lands: deployment uses a health fixture while the
Heimdal adapter uses stubbed REST fixtures. Task 4 depends only on task 3's published-evidence
contract, not on the live service. Task 5 waits for both the managed service (2) and Mimer consumer
(4), and coordinates them without a cross-constituent direct call. Acceptance is last.

## Cross-Task Invariants / Interaction Safety

- **KMA-INV-1 — Karakeep never becomes knowledge authority.** Source values retain Karakeep
  provenance and produce `requires_review: true`, `review_state: draft` candidates. If writeback is
  blocked after refinement, the published evidence remains replayable and the item is not reported as
  complete. No retry may promote or overwrite a human-reviewed artifact.
- **KMA-INV-2 — one stable identity crosses the published handoff.** Heimdal identity derives
  from the Karakeep item id plus content revision/fingerprint; the same revision is a no-op and a
  changed revision is new lineage. If a page succeeds and cursor persistence fails, replay of that
  page deduplicates before the cursor advances, preventing duplicate notes.
- **KMA-INV-3 — two cursors, no distributed transaction.** Heimdal advances its source cursor only
  after the corresponding published evidence is durable; Mimer advances its consumer cursor only
  after candidate materialization or an explicit item-scoped failure. If Mimer is down, Heimdal may
  continue publishing. If Mimer writeback is blocked, only its consumer cursor stays put. Restart
  replays each side idempotently without coupling the cursors.
- **KMA-INV-4 — only Heimdal talks to Karakeep.** Mimer normalization, candidate writeback, replay,
  and acceptance consume published evidence. If Karakeep is unavailable after publication, Mimer
  replay remains possible with zero source egress.
- **KMA-INV-5 — service and worker failures are legible and isolated.** An unhealthy service stops
  acquisition before fetch; one malformed item dead-letters only that item; WriteGuard refusal
  blocks only materialization. None is converted into an empty-success receipt or cursor advance.
- **KMA-INV-6 — operator secrets stay outside repo artifacts.** Code accepts endpoint and credential
  references through established runtime configuration, but fixtures, logs, events, notes, and
  committed deployment files contain neither private endpoints nor credential values. Authentication
  failure is reported without echoing the secret.

## Restart / durability posture

Karakeep owns the external durable source. Heimdal owns durable published evidence and its source
cursor. Mimer owns a separate durable consumer cursor plus governed candidate notes; refinement is
derived and replayable from the published handoff. A restart may repeat producer or consumer work but
may not skip evidence, duplicate notes, regress either cursor, or require Karakeep egress for Mimer
replay.

## Capability acceptance criteria

- [ ] The Heimdal published-evidence→Mimer refinement contract fixes identity, provenance, both
  cursors, revision, authority, and
  deletion semantics. Verify: doc writeback at `docs/KARAKEEP_MIMER_ACQUISITION/README.md :: Capability boundary` and `:: Cross-Task Invariants / Interaction Safety`.
- [ ] A managed Karakeep service has deterministic health, backup/update, and restart behavior
  without committed secret material. Verify: `tests/ops/test_karakeep_service_contract.py::test_service_manifest_is_health_checked_and_secret_free`.
- [ ] Heimdal incrementally fetches, attributes, and publishes links, notes, and highlights with a
  restart-safe producer cursor. Verify: `tests/heimdal/test_karakeep_ingestion.py::test_incremental_fetch_attributes_and_publishes_reading_evidence`.
- [ ] Governed writeback produces deterministic draft reading candidates and never uses companion
  capture. Verify: `tests/knowledge_acquisition/test_karakeep_candidate_writeback.py::test_reading_candidate_uses_kap_writeback_not_capture`.
- [ ] Scheduled overlap, source failure, item failure, and WriteGuard refusal are legible and do not
  advance either unsafe state. Verify: `tests/heimdal/test_karakeep_schedule.py::test_failed_or_overlapping_run_preserves_constituent_cursors`.
- [ ] A real test-channel saved item completes Karakeep → Heimdal published evidence → Mimer
  candidate with a linked receipt and
  replay proof. Verify: validation receipt on the parent feature issue following
  `PROVE_AND_ACCEPT_KARAKEEP_TO_MIMER.md :: Acceptance Criteria`.

## Verification path

Each task owns the named test or receipt targets in its Acceptance Criteria. CI uses stubbed REST
fixtures and secret scans; only the final task uses the real test-channel service. Full regression:
`pytest -q tests/heimdal tests/knowledge_acquisition tests/ops/test_karakeep_service_contract.py`
plus docs guard.

## Validation / acceptance path

The parent issue is the live validation hub. Child PR receipts accumulate there. The final
task performs one real saved-link/note/highlight journey, restart/replay, and negative-path check.
Only then may the parent close and owner docs be promoted from planned to delivered truth.

## Relationship to GitHub issues

- Parent validation hub: #3367 (`agent:blocked`).
- KMA-01: #3372 — dependency-free contract head; becomes ready after this spec merges.
- KMA-02: #3373 and KMA-03: #3374 — blocked on #3372; parallel after the contract lands.
- KMA-04: #3375 — blocked on #3374 only.
- KMA-05: #3377 — blocked on #3373 and #3375.
- KMA-06: #3376 — blocked on #3373 and #3377; final live acceptance/closure handoff.

[PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md) points to the live validation hub; GitHub owns
pickup/lifecycle truth and this directory owns the task contracts.

## TCD plan

Complexity high; risk high; verification difficulty hard; human review burden medium; defect blast
radius high. Cheapest acceptable route: feature-breakdown + Codex/Claude high reasoning for the
contract, external API, cursor, governed-write, and scheduling slices; medium reasoning for the
mechanical service deployment; Level 2/3 review at the external boundary and real-runtime acceptance.
