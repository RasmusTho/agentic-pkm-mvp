State: FILED specification directory (parent #3367; children #3372–#3377). D1 is settled. All
children remain `agent:blocked` until this specification merges; no Karakeep service or ingestion
support is claimed as shipped.
Doc role: Capability specification (feature-breakdown lane)
Authority: Product/Runtime target-state specification subordinate to `docs/KNOWLEDGE_ACQUISITION/README.md`, `docs/KNOWLEDGE_ACQUISITION/SOURCE_PLUGIN_CONTRACT.md`, `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md`, and `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md`.
Owner: Architecture / Product

# Karakeep → Mimer Acquisition

## Capability boundary

Run the owner-selected, self-hosted Karakeep service on the mac mini and incrementally acquire its
saved links, notes, and highlights into Mimer's existing Knowledge Acquisition Platform (KAP).
Karakeep is an external acquisition source. Its REST records become immutable/rebuildable KAP raw
records and then review-required reading candidates written by the existing governed
`app/knowledge_acquisition/candidate_writeback.py` path.

This is **not companion capture** and does not call Mimer's `/api/capture` endpoint. Karakeep's
bundled MCP server is also outside this capability: connecting an interactive assistant to that
server is Direction A operator configuration. Private endpoint selection, credential values, DNS,
and firewall policy remain operator-owned deployment inputs and are deliberately not specified here.

## Product/Runtime SBS classification

This is Product/Runtime System work. EBF is primary because Karakeep is an external acquisition
source; DRI owns raw/normalized rebuildable artifacts; HKA/SIP/GOV are touched only through the
existing candidate-writeback and review-required authority envelope. The service deployment also
touches OEF. No Builder System behavior or BuilderOps authority changes.

## Implementation tasks

| Order | Task | Outcome |
|---|---|---|
| 1 | [DEFINE_READING_SOURCE_AND_CANDIDATE_CONTRACT.md](DEFINE_READING_SOURCE_AND_CANDIDATE_CONTRACT.md) | Define Karakeep source records, cursor semantics, provenance, and review-required reading candidate shape. |
| 2 | [DEPLOY_KARAKEEP_AS_A_MANAGED_SERVICE.md](DEPLOY_KARAKEEP_AS_A_MANAGED_SERVICE.md) | Add a reproducible, health-checked mac-mini service deployment. |
| 3 | [FETCH_KARAKEEP_READING_EVIDENCE.md](FETCH_KARAKEEP_READING_EVIDENCE.md) | Implement the REST source plugin and durable incremental fetch cursor. |
| 4 | [NORMALIZE_AND_WRITE_READING_CANDIDATES.md](NORMALIZE_AND_WRITE_READING_CANDIDATES.md) | Normalize fetched evidence and write deterministic review-required candidates through KAP. |
| 5 | [SCHEDULE_INCREMENTAL_KARAKEEP_ACQUISITION.md](SCHEDULE_INCREMENTAL_KARAKEEP_ACQUISITION.md) | Schedule bounded runs with overlap protection and legible failure receipts. |
| 6 | [PROVE_AND_ACCEPT_KARAKEEP_TO_MIMER.md](PROVE_AND_ACCEPT_KARAKEEP_TO_MIMER.md) | Prove real test-channel flow and close the capability only on receipts. |

## Execution order

`1 → (2 ∥ 3) → 4 → 5 → 6`.

Tasks 2 and 3 are independent after the contract lands: deployment uses a health fixture while the
source plugin uses stubbed HTTP fixtures. Task 4 consumes task 3's raw shape. Scheduling follows a
working one-shot pipeline, and acceptance is last.

## Cross-Task Invariants / Interaction Safety

- **KMA-INV-1 — Karakeep never becomes knowledge authority.** Source values retain Karakeep
  provenance and produce `requires_review: true`, `review_state: draft` candidates. If writeback is
  blocked after normalization, the raw record remains replayable and the item is not reported as
  complete. No retry may promote or overwrite a human-reviewed artifact.
- **KMA-INV-2 — one stable identity across fetch, normalize, write, and schedule.** Identity derives
  from the Karakeep item id plus content revision/fingerprint; the same revision is a no-op and a
  changed revision is new lineage. If a page succeeds and cursor persistence fails, replay of that
  page deduplicates before the cursor advances, preventing duplicate notes.
- **KMA-INV-3 — cursor advancement follows durable downstream acceptance.** A cursor/checkpoint is
  committed only after every item represented by it is durably stored as raw evidence or recorded
  as an item-scoped failure. If the process crashes mid-page, restart resumes from the previous
  checkpoint and idempotently replays the page; it never skips unseen evidence.
- **KMA-INV-4 — only the source plugin talks to Karakeep.** Normalize, candidate writeback, replay,
  and acceptance consume stored raw records. If Karakeep is unavailable after fetch, downstream
  replay remains possible with zero source egress.
- **KMA-INV-5 — service and worker failures are legible and isolated.** An unhealthy service stops
  acquisition before fetch; one malformed item dead-letters only that item; WriteGuard refusal
  blocks only materialization. None is converted into an empty-success receipt or cursor advance.
- **KMA-INV-6 — operator secrets stay outside repo artifacts.** Code accepts endpoint and credential
  references through established runtime configuration, but fixtures, logs, events, notes, and
  committed deployment files contain neither private endpoints nor credential values. Authentication
  failure is reported without echoing the secret.

## Restart / durability posture

Karakeep owns the external durable source. KAP raw records and the acquisition cursor/checkpoint are
durable runtime state; normalized/extracted/candidate assembly is derived and replayable. Candidate
paths and stage-event keys are deterministic. A restart may repeat fetch or derived work but may not
skip evidence, duplicate notes, regress cursor state, or require Karakeep egress to replay already
stored raw evidence.

## Capability acceptance criteria

- [ ] The source/candidate contract fixes identity, provenance, cursor, revision, authority, and
  deletion semantics. Verify: doc writeback at `docs/KARAKEEP_MIMER_ACQUISITION/README.md :: Capability boundary` and `:: Cross-Task Invariants / Interaction Safety`.
- [ ] A managed Karakeep service has deterministic health, backup/update, and restart behavior
  without committed secret material. Verify: `tests/ops/test_karakeep_service_contract.py::test_service_manifest_is_health_checked_and_secret_free`.
- [ ] Incremental fetch stores links, notes, and highlights as deduplicated KAP raw records and
  resumes safely. Verify: `tests/knowledge_acquisition/test_karakeep_fetch.py::test_incremental_fetch_persists_all_reading_evidence_and_resumes`.
- [ ] Governed writeback produces deterministic draft reading candidates and never uses companion
  capture. Verify: `tests/knowledge_acquisition/test_karakeep_candidate_writeback.py::test_reading_candidate_uses_kap_writeback_not_capture`.
- [ ] Scheduled overlap, source failure, item failure, and WriteGuard refusal are legible and do not
  advance unsafe state. Verify: `tests/knowledge_acquisition/test_karakeep_schedule.py::test_failed_or_overlapping_run_never_advances_cursor_unsafely`.
- [ ] A real test-channel saved item completes Karakeep → raw → candidate with a linked receipt and
  replay proof. Verify: validation receipt on the parent feature issue following
  `PROVE_AND_ACCEPT_KARAKEEP_TO_MIMER.md :: Acceptance Criteria`.

## Verification path

Each task owns the named test or receipt targets in its Acceptance Criteria. CI uses stubbed REST
fixtures and secret scans; only the final task uses the real test-channel service. Full regression:
`pytest -q tests/knowledge_acquisition tests/ops/test_karakeep_service_contract.py` plus docs guard.

## Validation / acceptance path

The parent issue is the live validation hub. Child PR receipts accumulate there. The final
task performs one real saved-link/note/highlight journey, restart/replay, and negative-path check.
Only then may the parent close and owner docs be promoted from planned to delivered truth.

## Relationship to GitHub issues

- Parent validation hub: #3367 (`agent:blocked`).
- KMA-01: #3372 — dependency-free contract head; becomes ready after this spec merges.
- KMA-02: #3373 and KMA-03: #3374 — blocked on #3372; parallel after the contract lands.
- KMA-04: #3375 — blocked on #3374.
- KMA-05: #3377 — blocked on #3375 (and consumes the managed-service health contract from #3373).
- KMA-06: #3376 — blocked on #3373 and #3377; final live acceptance/closure handoff.

[PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md) points to the live validation hub; GitHub owns
pickup/lifecycle truth and this directory owns the task contracts.

## TCD plan

Complexity high; risk high; verification difficulty hard; human review burden medium; defect blast
radius high. Cheapest acceptable route: feature-breakdown + Codex/Claude high reasoning for the
contract, external API, cursor, governed-write, and scheduling slices; medium reasoning for the
mechanical service deployment; Level 2/3 review at the external boundary and real-runtime acceptance.
