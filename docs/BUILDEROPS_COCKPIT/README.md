State: Active capability specification + owner doc. All seven v1 slices in the task table are
delivered; parent feature issue #4447 remains the live validation hub.
Doc role: Capability specification directory README and owner doc for the cockpit surface.

# BuilderOps Cockpit

A **read-time join** over existing builder authorities, served at `/cockpit` with its payload at
`GET /api/cockpit/registry`. The surface owns no plane, no queue, no register, and no decision
right. Every row it shows has a named source and a read time, and nothing it renders survives a
reload.

## Capability boundary

The owner's charter, verbatim intent: a register of everything in motion, with coverage control,
answering four questions in locked order — *What are we working on? What is done? What has flaws?
What is forgotten?* — plus a needs-you band **inside** the register, never as the front page. Five
thread states are positions in the process chain (in progress / delivered / tried by owner / has
flaws / forgotten), and deficiency types are predicates derived from the chain. "Tested" is a dated
claim with a receipt behind it, never a green dot; emptiness is a dated positive claim; a view that
cannot name per-source freshness must not claim emptiness (INV-DG-6 — invariant IDs and finding IDs
like F9 throughout this directory resolve to
`docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md :: Invariants` and `:: Findings, ranked by
blast radius × silence of failure`).

Classification: **Builder System** surface (SBS: builder boundary; no Product/Runtime write). The
join contract is upstream input to #4169's `DeliveryRunView` — extend/depend, never duplicate;
#4169 owns initiation/approval, this capability owns only reading and freshness.

Design provenance: the 2026-07-30 `builderops-cockpit` design exploration (Yggdrasil Design System
`f2b13410-af14-4875-8029-445352123f57`), archived with its verified token receipt in
`design/2026-07-30-cockpit-exploration/INTAKE.md`. Every open design question is closed as an
explicit decision in `DESIGN_DECISIONS.md`. This directory is the normalized authority; the design
pack is supporting input.

## Relationship to the devUI target

`docs/DEVUI.md` owns the accepted target Product Owner experience across capability evidence, work
in motion, delivery decisions, active runs, and receipts. This cockpit remains the delivered
read-only work register and a source view for that target. Its registry, freshness, chain, and lens
contracts should be reused by devUI; its no-decision, no-persistence, and no-authority boundaries do
not move.

The standalone `/cockpit` route is therefore a current transitional and diagnostic surface, not a
separate long-term owner product or primary navigation destination. The owner-facing target is one
devUI shell organised around owner intent and selected subject. devUI may compose this registry with
CKM and dispatcher/Signboard evidence, while provider names and raw routes remain progressive
provenance or repair detail.

The planned authenticated delivery controls are not added to this static/read-time join. They appear
inside the owner-perceived devUI flow through a separately authenticated action boundary owned by
DDO-06. One experience therefore does not make this registry a control plane.

## What the delivered increment renders (#4438)

- **Four bands in locked order plus a needs-you band**, derivation fail-closed. #4438 derived the
  band from the dispatcher status word; BOPS-COCKPIT-04 (#4452) replaced that mapping with
  **chain-position** derivation (`derive_position` in `app/builderops/cockpit_chain.py`) over the
  joined planes: a thread whose position cannot be computed lands in the explicit `unclassified`
  list, never guessed. A canonically classified `agent:needs-human` authority exception routes to
  the needs-you band; ambiguous or unmapped technical state stays unclassified/flawed. Label
  routing reads the sync mirror's `sync_state`, which production sync has populated with labels and URLs since #4441
  (=#4456, audit F9) merged; each mirror-derived field now names its own `sync_state.last_pull_at`
  watermark rather than borrowing the dispatcher-store read instant (BOPS-COCKPIT-03, #4450).
- **An eight-rung evidence spine per thread** — intention · capability · epic · slice · PR ·
  CI/sha · receipt · tried, locked order; rung class derives from the key's nature (`proven` only
  for DB-keyed or CI-forced edges). Intention, capability, epic, and tried render `absent` — their
  visible absence is the point.
- **Per-source freshness** — pills with per-source `last_successful_read` for `dispatcher-store`,
  `verification-runs` (SQLite read-only), `deploy-receipts`; unread planes named as unread. The
  third pill state, **stale** (EXT-3), arrived with BOPS-COCKPIT-04 (#4452): a source whose own
  watermark is older than `SOURCE_STALE_AFTER_DAYS` turns the rungs it backs amber and has the
  counts it owns withdrawn rather than shown whole. A read carries `configured` alongside `state`
  (EXT-8, #4481): an optional-by-design plane whose enabling config is absent — `github-live` with
  `COCKPIT_GITHUB_REPO` unset — renders as *not enabled* rather than dead and never contributes to
  the claim banner's amber, while a plane that was configured and then failed still does both.
  `state` is unchanged in either case: an unconfigured plane still owns no countable facts. Since
  #4484 that unset state is a per-channel choice rather than the only reachable state: the runtime
  image ships the `gh` transport the plane reads through, and `docker-compose.dev.yml :: api`
  and `docker-compose.prod.yml :: api` commit `RasmusTho/agentic-pkm-mvp` for dev (18001) and prod;
  `test` stays unset. The prod repository binding is committed non-secret configuration, not
  credential-presence or deployment evidence. See
  `GITHUB_LIVE_PLANE.md :: What makes that command answer fresh (#4484)` for the full path,
  including the host-supplied `GITHUB_TOKEN` that rides the `api` consumer's existing host-secret
  env layer.
- **Honest emptiness in three forms** — dated true emptiness; refused claims on dead sources
  ("cannot be counted", never zero); structural absence distinct from death.
- **Two tiers in the done band** — "Ready for you to use" above "Tried by you" (empty by contract
  until INV-DG-7 has an owner-acceptance receipt contract).
- **Flaw predicates with named evidence** (BOPS-COCKPIT-04, #4452) — deficiencies are derived
  predicates over the joined planes, not an enumerated list: a blocked link, a dispatcher/GitHub
  contradiction, an expired lease, red or absent CI on a PR head SHA, a pushed branch with no PR,
  a delivery with no verification receipt, a stale epic with open children. Each carries its own
  evidence keys; a predicate whose plane is not fresh is **named as unevaluated** in the flaws band
  header rather than reading as "no flaw", and predicates needing a plane this capability never
  reads (git working trees, session records, issue comments) are named as unread there too. The
  same rule holds one level down, per evidence rather than per plane (#4471): when a *fresh* plane
  failed to read one specific fact — a per-PR check-status call that errored — the predicate that
  would have asserted something about that fact withholds instead of firing, and the thread's
  `ci_sha` rung names the unread read. Unread is never allowed to wear the shape of absent. A
  thread holds one position band and additionally appears in the flaws band — one identity, no
  copy drift. Within-band ordering is a four-tick reading signal only (EXT-7): it never crosses a
  band, never hides a card, and is never a selection input (ADR-0057 A1).

## Implementation tasks and execution order

| Order | Task | task_id | Issue | State |
|---|---|---|---|---|
| 1 | [REGISTRY_READ_TIME_JOIN](REGISTRY_READ_TIME_JOIN.md) | BOPS-COCKPIT-01 | #4438 | Delivered |
| 2 | [INDUCED_FAILURE_JOURNEYS](INDUCED_FAILURE_JOURNEYS.md) | BOPS-COCKPIT-02 | #4448 | Delivered #4458 |
| 2 (par) | [COGNITIVE_LOAD_SIBLING](COGNITIVE_LOAD_SIBLING.md) | BOPS-COCKPIT-07 | #4449 | Delivered #4467 |
| 3 | [GITHUB_LIVE_PLANE](GITHUB_LIVE_PLANE.md) | BOPS-COCKPIT-03 | #4450 | Delivered |
| 3 (par) | [DOCS_PLANE_CAPABILITY_LANES](DOCS_PLANE_CAPABILITY_LANES.md) | BOPS-COCKPIT-05 | #4451 | Delivered |
| 4 | [CHAIN_DERIVED_STATES](CHAIN_DERIVED_STATES.md) | BOPS-COCKPIT-04 | #4452 | Delivered |
| 5 | [SURFACE_LENSES](SURFACE_LENSES.md) | BOPS-COCKPIT-06 | #4453 | Delivered #4478 |

Flat order: journeys and the docs sibling first (they harden and govern what exists), then the two
independent planes in parallel, then chain semantics over the joined planes, then the lenses.
`github_issue:` frontmatter is populated at filing time (INV-DG-5 applies to this directory from
day one).

## Cross-Task Invariants / Interaction Safety

- **Honesty is monotone.** No later task may weaken a delivered honesty contract: band order stays
  locked; refusal-over-zero, dated emptiness, and fail-closed classification survive every plane
  addition. Each new plane arrives with its own freshness pill and its own refusal path *in the
  same slice* — a plane merged without its refusal path is a defect, not a partial.
- **Stale is a third pill state, not a variant of fresh.** Every source pill distinguishes fresh /
  stale / unavailable (the delivered increment ships fresh/empty/unavailable; the stale state
  arrives with the plane tasks, which each define their staleness threshold). A stale source turns
  every rung that depends on it amber and **withdraws the numbers that source owns** — a count
  backed by a stale read is removed, not shown whole (the accepted design's stale-source rule).
- **One identity, many appearances.** A thread appearing in two bands (position + flaw) is the
  same object with the same spine; tasks 03–06 must join on issue#/PR#/SHA and never clone card
  state. If 04 lands while 05 is unmerged (or vice versa), rungs owned by the unmerged plane stay
  `absent`/`unlinked` — visibly weaker, never guessed.
- **Read-only is load-bearing.** No task in this table writes to any authority, caches across
  renders, or persists attention state (ADR-0065: the lawful writer does not exist until BCP-06 /
  #3793). A slice that needs persistence is out of this capability by definition.
- **Partial-failure seam.** The registry composes per-source results; a source failing mid-compose
  refuses that source's claims while others render fresh — tested at the compose seam
  (`test_cockpit_registry.py` dead-source cases) and re-asserted by the induced-failure journey at
  the rendered-surface level.

## Verification model

V-model: every AC in every task doc carries an inline `Verify:` target; slice verification is the
required `"Unit tests (not pg)"` PR check plus per-AC targets on the head SHA. Browser-level
journeys (including the induced dead-source red-not-calm test) run in the **post-merge browser
lane** (`.github/workflows/browser-runtime.yml`) — that lane runs individually named test files,
so BOPS-COCKPIT-02 wires the journey file into it as its own step — and are never part of the
required PR check. The capability's top verification rung — the owner using the thing — has no
automated stand-in; the "tried by you" tier renders its absence until INV-DG-7 exists.

## Capability acceptance criteria

The capability may be claimed as supported when all of these hold (mirrored by the parent feature
issue, which is where progress is checked off):

- [x] All seven task rows above are Delivered with their per-AC `Verify:` targets green on merged SHAs
- [x] The induced dead-source journey runs in the post-merge browser lane and proves red-not-calm
      — the wiring itself has existed since #4448 (`.github/workflows/browser-runtime.yml` :: "Run
      cockpit induced-failure browser journeys (BOPS-COCKPIT-02)", a required, non-`continue-on-error`
      step). It went genuinely red on `main` starting with #4450's merge (confirmed via the lane's
      own run history: green through commit `2c7daf18`, red from `11712858` onward) — `#4450` added
      the opt-in `github-live` source, which this offline test harness never configures
      (`COCKPIT_GITHUB_REPO` unset, deliberately no live network in tests), so it always reads
      `unavailable` there; the original `.src.dead` assertions never accounted for that new,
      correctly-refusing source and started failing on every push since. This slice's own test-file
      changes repair that drift (scoping the dead-source check to exclude the one source that is
      supposed to be unconfigured here) rather than adding new wiring.
- [x] Every plane the surface reads has fresh/stale/unavailable pill states with its own threshold
- [x] The five chain-derived states and the flaw predicates render from live data on the host, with
      every unreadable predicate named as unread
      — the chain-derived bands and flaw predicates render from live data (proven by
      `test_cockpit_journeys.py` and `test_cockpit_chain_states.py`); the flaws band's own
      `header.not_evaluated`/`header.unread` fields — distinct from the coarser `unread_planes`
      list `cockpit.js` also renders — are now surfaced on the served surface too (#4479,
      `test_flaws_band_header_renders_not_evaluated_and_unread`).
- [x] This README's task table, coordination constraints, and decision ledger reflect delivered
      reality (no stale "pending" rows)

## Authority boundaries (binding)

| Boundary | Owner | Consequence here |
|---|---|---|
| Attention state (`done`/`ignore`) | ADR-0065 (PostgreSQL-only, receipt-backed; writer gated on BCP-06 #3793) | No "mark handled" anywhere; nothing persists across reloads |
| Delivery approval | `verification-and-closure` | No approve button |
| Task register and workflow | Dispatcher | No status fields, no drag-and-drop, no ordering owned here |
| Capability maturity | CKM projection (a lens, not a spine) | No scalar maturity number; no lane/band/count derives from CKM |
| Source content | GitHub, Signboard, the repo | Deepest layer is an out-link, never a copy |
| Ranking | ADR-0057 A1 | Ordering only within a band; a number never creates silence or selects |

## Out of scope for v1 (binding)

Session launcher (owner-deferred) · authoring/voice/canvas surfaces · approval flows · source
rendering in-cockpit (diffs, file contents) · cockpit-autonomous decisions · any cockpit-owned
persistence (ADR-0065; no attention-state writer until BCP-06/#3793) · CKM as spine · anything
owned by #4168 (fenced outbox reconciliation), #4169 (delivery initiation/receipt projection), or
#4131 (CKM design-agent hub) · a cockpit-owned task register or workflow engine (#4163's reducer
and the dispatcher own it) · Signboard tokenization (DS-3 rejected) · `contract`/`agent` action
buttons and hold-to-confirm (EXT-5/EXT-6 deferred with the future action slices) · search fields,
command palettes, typed identifiers of any kind (dyslexia rule: selection is visual) ·
owner-acceptance receipt contract (INV-DG-7 — owner-gated, the one item this spec cannot close).

## Coordination constraints (live while delivering)

- **PR #4406** (Signboard served from the dispatcher store) merged 2026-07-30T23:24Z; the earlier
  do-not-touch window on the Signboard files is closed. Cockpit slices still have no reason to
  edit the Signboard surface — it is a separate surface with its own owner flow.
- **The delivery-graph data-edge work is filed**: #4440 (single-source `task_id`, INV-DG-2),
  #4441 (sync-state labels/URL, F9), #4442 (epic ledger posting, INV-DG-4), #4443 (parent-line
  readiness check, INV-DG-3), #4444 (`github_issue:` backfill, INV-DG-5). Cockpit slices
  **render** those gaps honestly and **consume** the machine edges as they land — they never
  implement them. In particular, no cockpit slice modifies `app/dispatcher/sync_github.py`
  (#4440/#4441 own it) or `scripts/issue_pickup_claim.sh` (#4440).

## Relationship to GitHub issues

The parent feature issue (see `PARENT_FEATURE_ISSUE.md`) is the live validation hub; each child
posts a validation receipt to it before the next child is picked up. Child issues follow
`.codex/skills/_shared/ISSUE_CONTRACT.md` and reference their task doc as
"Implements BUILDEROPS_COCKPIT/<TASK>". The spec is the source of truth; issues track backlog
state.

## Visual contract

All visual values come from the Yggdrasil token sheet. The served
`app/web/static/colors_and_type.css` must stay byte-identical to the binding source
`companion-ui/companion-app/colors_and_type.css`; parity is CI-enforced by
`tests/api/test_cockpit_api.py::test_token_sheet_parity_with_binding_source`.
`app/web/static/cockpit.css` consumes tokens only and introduces no new color, radius, or type
value. Fonts carry meaning: display serif for claims, UI face for chrome, mono for every value the
runtime emits.
