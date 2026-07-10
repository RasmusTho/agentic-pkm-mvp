State: Specification directory — FILED (parent #3320; children #3321–#3324 filed 2026-07-07, all agent:blocked at filing per the uniform closed-loops filing policy). System-level source of truth for building Decision Calibration, the second of five closed loops named in `docs/research/yggdrasil-closed-loops-ideation.md`. Extends `docs/DECISION_RECEIPT_LOG/` (receipt-log architecture: vault-canonical append-only log + WriteGuard-gated seam + rebuildable Postgres projection) over `docs/CONTEXTUALIZATION_LAYER/LIFE_WIDE_ARTIFACT_TAXONOMY.md :: decision_record` (the owner's own decision journal, a Human Knowledge Artifact) — see **Grounding: which "decision" this capability calibrates** below, a deliberate disambiguation the ideation capture does not spell out.
Doc role: Capability specification (feature-breakdown lane)
Temporal class: strategic
Review cadence: event-driven (task merges, parent-issue lifecycle)
Source of truth: this directory; GitHub issues (#3320–#3324) are execution artifacts, this spec is the contract
Last reviewed: 2026-07-07

# Decision Calibration — Specification

Closes the loop on the owner's decision journal: revisit past decisions on a schedule, let the owner
stamp an outcome (did it hold?), and aggregate a calibration profile over time — so a senior architect
who treats decision-making as his craft can learn, over months, which decision types he over- or
under-estimates. The receipt log this capability extends is currently **write-only**: decisions get
recorded and nothing ever looks back.

Classification: **Product/Runtime System work** (new runtime capability, human-facing). Primary
subsystem: **GOV** (the outcome stamp is a receipt/accountability record — this is what the capability
adds); secondary: **HKA** (the `decision_record` artifacts being revisited are durable human knowledge),
**PDM** (JSONL-append + Postgres-projection persistence mechanics, mirroring the existing pattern),
**DRI** (the calibration profile is a rebuildable derived rollup), **HIX** (the companion UI revisit
card).

## Grounding: which "decision" this capability calibrates

The ideation capture (`docs/research/yggdrasil-closed-loops-ideation.md :: 2. Decision calibration`)
names the enabling substrate as "decision-receipt log (vault-canonical + PG projection, live on prod)"
— which reads, by name, as a pointer to `docs/DECISION_RECEIPT_LOG/` (feature #2969, delivered
2026-07-05/06). But that delivered log is the **GOV governance-judgment log**:
`app/services/decisions.py::insert_decision`, called only by `app/agents/reviewer/agent.py`,
`app/agents/set_evaluator/agent.py`, and `app/agents/classifier/agent.py` — machine-authored
`review`/`evaluate`/`classification` verdicts about ingested vault objects. Nothing there is the
owner's own architectural or product decision-making, and nothing there is currently keyed to
human authorship.

The entity that actually matches "decisions are the owner's craft" is `decision_record` — an already
-named Human Knowledge Artifact class (`docs/CONTEXTUALIZATION_LAYER/LIFE_WIDE_ARTIFACT_TAXONOMY.md ::
decision_record`: "context, options considered, chosen path, rationale, date... human-authored,
governance-bearing... append-only... e.g. ADR, life-decision record, project decision log"), with a
ready-made vault template at `docs/examples/vault-templates/decision-record.md` (`decided_on`,
`decided_by`, options-considered, chosen option, rationale — exactly the shape a revisit needs to quote
back to the owner).

**This spec's design call:** Decision Calibration operates over `decision_record` HKA notes (the data
the owner actually authors) while extending the **architecture pattern** `docs/DECISION_RECEIPT_LOG/`
established (vault-canonical append-only JSONL receipt, WriteGuard-gated seam, rebuildable Postgres
projection, receipt-before-ack commit point) — because that pattern is what the ideation capture cites
as proven and "live on prod," and because reusing it is exactly right for a new append-only,
accountability-bearing record. The two systems remain **structurally parallel, not the same table**:
outcome receipts never touch the `decisions`/`review`/`evaluate`/`classification` machinery. **This is
a judgment call, not a re-derivation of an existing owner ruling — flag it for confirmation before
filing issues** (see the RETURN note accompanying this breakdown).

A `decision_record` note becomes addressable to this capability once it is ingested as a vault object
(it gets the ordinary `objects.id` / `objects.uuid` pair like any other note — the same identity model
`app/receipts/decision_receipt_log.py::resolve_vault_uuid` already uses). A `decision_record` note that
has never been ingested has no addressable decision for CAL-02 to schedule against; this is a natural
consequence of the existing ingest/object model, not a new gate this capability adds.

## Implementation tasks (execution order)

| # | Task | id | Prereqs |
| --- | --- | --- | --- |
| 1 | [DEFINE_OUTCOME_RECEIPT_MODEL](DEFINE_OUTCOME_RECEIPT_MODEL.md) | CAL-01 | — |
| 2 | [SCHEDULE_DECISION_REVISITS](SCHEDULE_DECISION_REVISITS.md) | CAL-02 | 1 (∥ with 4) |
| 3 | [SURFACE_REVISIT_REVIEW_CARD](SURFACE_REVISIT_REVIEW_CARD.md) | CAL-03 | 1, 2 |
| 4 | [PROJECT_CALIBRATION_VIEW](PROJECT_CALIBRATION_VIEW.md) | CAL-04 | 1 (∥ with 2) |

Flat order: 1 → (2 ‖ 4) → 3. CAL-03 is last because it is the only task that needs both the durable
outcome-receipt write path (CAL-01) and the scheduler's notion of "which decision is due" (CAL-02).
CAL-04 only reads outcome receipts (CAL-01), so it does not depend on the scheduler and can build in
parallel with it.

## Out of scope (capability level)

- **Editing or re-scoring original decision receipts.** Every `decision_record` note and every GOV
  judgment receipt this capability might ever touch stays immutable; an outcome is always a new,
  separate, append-only record that references the original, never a mutation of it.
- **Automated outcome inference.** v1 is human-stamped only; no agent infers "held" from downstream
  evidence. A future capability could propose an outcome for the owner to confirm — that is not this
  capability.
- **Episode-closure-triggered revisits.** A revisit anchored to "this episode just closed, did the
  decision you made inside it hold?" is explicitly **future work**, dependent on the Episode Resolution
  Engine (`docs/EPISODE_RESOLUTION_ENGINE/`) shipping `episode.closed` events and episode-scoped
  decision lookup. Only the time-based ladder (CAL-02) ships now.
- **Briefing delivery.** Surfacing "you have N decisions due for revisit" inside a daily digest is a
  future seam owned by `docs/DAILY_BRIEFING/` (loop 1 in the ideation capture, sequenced first). This
  capability's only delivery surface is the companion UI card (CAL-03); it does not push, notify, or
  page anything.
- **Adding a `confidence` field to the `decision_record` template.** CAL-04 aggregates by stated
  confidence *where present* but does not introduce or require the field; that is a natural follow-on
  once the owner starts recording it, not a prerequisite here.

## Cross-Task Invariants / Interaction Safety

CAL-01 writes outcome receipts; CAL-02 reads them (to compute what is still due) and adds its own
durable dismissal ledger; CAL-03 is the human-facing seam that triggers both; CAL-04 reads everything
CAL-01 has ever written and rebuilds a rollup. A breakdown whose tasks are each locally correct can
still lose data or trust in the seams between them.

- **INV-CAL-A — original decisions are immutable; outcomes are always separate.** No task may add a
  write path that edits a `decision_record` note's decision content or a GOV judgment receipt. An
  outcome is always a new append-only record carrying a reference to the original decision's stable
  identity (`decision_object_id` / `decision_uuid`), never an in-place edit. Partial failure: if a
  future bug attempted to patch the original note, that is a contract violation any invariant probe
  must fail on, never silently accept — mirrors ERE's INV-ERE-B posture for proposal/canonical
  write-class separation.
- **INV-CAL-B — an outcome receipt is idempotent per (decision, ladder rung).** Re-submitting the same
  answer for the same decision at the same rung (retry after a timeout, double-click, replayed
  request) must not create two outcome rows. Partial failure: the append succeeds but the caller never
  sees the response (network drop) → the caller's retry must be a no-op against the same (decision_id,
  rung) key, not a duplicate receipt.
- **INV-CAL-C — at most one pending revisit per decision at a time.** CAL-02's scheduler surfaces only
  the earliest un-actioned (unanswered, undismissed) ladder rung whose due date has passed; it never
  stacks multiple overdue rungs into multiple simultaneous cards for the same decision. Partial
  failure: the owner ignores the workspace for months and several rungs fall due — the scheduler still
  reports exactly one pending revisit (the earliest), and only surfaces the next rung once the current
  one is actioned (answered by CAL-01's write path or dismissed by CAL-02's own ledger).
- **INV-CAL-D — a revisit answered while the projection is down is not lost.** The outcome-receipt
  JSONL append (CAL-01) is the commit point, exactly mirroring `docs/DECISION_RECEIPT_LOG`'s
  receipt-before-ack rule. If the Postgres projection write fails or the projection/rebuild job is
  down when the owner answers a card, the answer is already durable in the vault; the card must clear
  for the owner (the durable append succeeded) even though the projection has not caught up yet.
  Partial failure: projection write raises after the vault append succeeded → the caller still reports
  success (the receipt is durable and rebuildable into the projection later); the projection is
  degraded/stale, never the source of truth the human-visible acknowledgment depends on.
- **INV-CAL-E — dismiss is not an outcome.** Dismissing a card never writes an outcome receipt (CAL-01
  vocabulary is reserved for actual stamped judgments); it writes a distinct, durable dismissal marker
  (CAL-02) that advances the ladder rung without asserting held/partly-held/did-not-hold/unknown-yet.
  Partial failure: a dismiss-write fails (WriteGuard-blocked or I/O error) → the card must not silently
  clear client-side; the same rung remains pending and is shown again, exactly as if the dismiss never
  happened — never a client-only optimistic clear that diverges from durable truth.
- **INV-CAL-F — the calibration projection is rebuildable from vault-canonical outcome receipts alone,
  with zero loss, and this is checked *before* every rebuild, not asserted after the fact.** The repo
  has a live precedent for what happens when this is skipped:
  `app/jobs/decisions_projection.py::rebuild_decisions_projection` truncates and replays the
  `decisions` table from the JSONL log only — on prod this silently dropped **2 rows that existed only
  in Postgres and were never captured in the vault log** (pre-dual-write-cutover residue; see the
  operator's standing "don't run `rebuild_decisions_projection` on prod" caution). CAL-04's rebuild
  function must run a doctor-equivalence check first (`doctor_decisions_projection`-style: compare
  every Postgres `decision_outcomes` row against the vault JSONL log) and **refuse to truncate** — fail
  loud, do not proceed — if Postgres carries any outcome row the vault log cannot account for. This is
  the inverse safety net the historical incident was missing, not a hypothetical.

## Capability acceptance criteria

- [ ] An outcome is always a new append-only receipt; no code path edits an existing `decision_record`
      note's decision content or an existing outcome receipt in place.
      Verify: `tests/services/test_outcome_receipt_log.py::test_outcome_receipt_is_append_only_and_immutable`
- [ ] A decision has at most one pending revisit at a time, computed from the ladder + prior
      outcomes/dismissals, and answering or dismissing advances to the next rung (or exhausts the
      ladder).
      Verify: `tests/services/test_revisit_scheduler.py::test_at_most_one_pending_revisit_per_decision`
- [ ] Answering a revisit card writes the outcome receipt through the governed write path
      (WriteGuard asserted at the production call site) and the card clears from the surface.
      Verify: `tests/api/test_companion_calibration_revisit.py::test_answer_revisit_writes_outcome_receipt_via_writeguard`
- [ ] Dismissing a revisit card defers to the next ladder step without writing an outcome receipt.
      Verify: `tests/api/test_companion_calibration_revisit.py::test_dismiss_defers_without_outcome_receipt`
- [ ] The calibration profile is rebuildable from vault-canonical outcome receipts alone, and the
      rebuild refuses (fails loud) rather than silently dropping Postgres-only rows the vault log
      cannot account for.
      Verify: `tests/jobs/test_calibration_projection_rebuild.py::test_rebuild_refuses_when_db_has_unaccountable_rows`
- [ ] A revisit answered while the projection job is down is not lost: the durable receipt append
      succeeds and the card clears even when the projection write fails.
      Verify: `tests/integration/test_calibration_rebuild_from_log_only.py::test_answer_survives_projection_outage`
- [ ] The readable calibration profile (counts/rates by decision kind and, where present, stated
      confidence) is written back into the vault as a human-readable markdown surface.
      Verify: doc writeback at `vault/<system_dir>/calibration/calibration-profile.md` (generated;
      see `tests/jobs/test_calibration_projection_rebuild.py::test_markdown_profile_written_on_rebuild`)

## Relationship to GitHub issues

**Filed 2026-07-07.** Parent feature issue: **#3320** (Backlog, `agent:blocked` live validation hub; see [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md)). All four children were filed `agent:blocked`: CAL-01 → **#3321** (the dependency-free head — flips to `agent:ready` once this spec PR merges to `main`); CAL-02 → **#3323** and CAL-04 → **#3322** (both stay `agent:blocked` until CAL-01/#3321 merges); CAL-03 → **#3324** (stays `agent:blocked` until CAL-01/#3321 and CAL-02/#3323 both merge). The spec is the source of truth; issues track pickup state.

## Related Docs

- `docs/research/yggdrasil-closed-loops-ideation.md :: 2. Decision calibration` — the grounding capture
- `docs/DECISION_RECEIPT_LOG/README.md` — the architecture pattern this capability mirrors
- `docs/adr/ADR-0019-governed-writes-decision-token-authority-receipt.md` — governed-write authority
- `docs/CONTEXTUALIZATION_LAYER/LIFE_WIDE_ARTIFACT_TAXONOMY.md :: decision_record` — the artifact class
  being revisited
- `docs/examples/vault-templates/decision-record.md` — the note template
- `docs/SETTINGS_SPINE/README.md` — tunables posture the ladder constants follow
- `docs/COMMITMENT_SURFACING/RENDER_COMMITMENTS_IN_PANEL_UI.md` — companion-UI card-surface exemplar
- `app/receipts/decision_receipt_log.py`, `app/jobs/decisions_projection.py`,
  `app/services/decisions.py` — the code precedent this capability's modules mirror
