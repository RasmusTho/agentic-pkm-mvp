State: Active capability specification + owner doc. v1 first increment delivered (#4438); parent
feature issue #4447 is the live validation hub; children #4448-#4453 filed.
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

## What the delivered increment renders (#4438)

- **Four bands in locked order plus a needs-you band**, derivation fail-closed (`STATUS_BAND` in
  `app/builderops/cockpit_registry.py`): an unmapped status lands in the explicit `unclassified`
  list, never guessed. `agent:needs-human` routes to the needs-you band — with a caveat: label
  routing reads the sync mirror's `sync_state`, which production sync does not populate with labels
  or URLs until #4441 lands (audit F9), so the needs-you band and mirror out-links are structurally
  empty in production today.
- **An eight-rung evidence spine per thread** — intention · capability · epic · slice · PR ·
  CI/sha · receipt · tried, locked order; rung class derives from the key's nature (`proven` only
  for DB-keyed or CI-forced edges). Intention, capability, epic, and tried render `absent` — their
  visible absence is the point.
- **Per-source freshness** — pills with per-source `last_successful_read` for `dispatcher-store`,
  `verification-runs` (SQLite read-only), `deploy-receipts`; unread planes named as unread.
- **Honest emptiness in three forms** — dated true emptiness; refused claims on dead sources
  ("cannot be counted", never zero); structural absence distinct from death.
- **Two tiers in the done band** — "Ready for you to use" above "Tried by you" (empty by contract
  until INV-DG-7 has an owner-acceptance receipt contract).

## Implementation tasks and execution order

| Order | Task | task_id | Issue | State |
|---|---|---|---|---|
| 1 | [REGISTRY_READ_TIME_JOIN](REGISTRY_READ_TIME_JOIN.md) | BOPS-COCKPIT-01 | #4438 | Delivered |
| 2 | [INDUCED_FAILURE_JOURNEYS](INDUCED_FAILURE_JOURNEYS.md) | BOPS-COCKPIT-02 | #4448 | Ready |
| 2 (par) | [COGNITIVE_LOAD_SIBLING](COGNITIVE_LOAD_SIBLING.md) | BOPS-COCKPIT-07 | #4449 | Ready |
| 3 | [GITHUB_LIVE_PLANE](GITHUB_LIVE_PLANE.md) | BOPS-COCKPIT-03 | #4450 | Ready |
| 3 (par) | [DOCS_PLANE_CAPABILITY_LANES](DOCS_PLANE_CAPABILITY_LANES.md) | BOPS-COCKPIT-05 | #4451 | Ready |
| 4 | [CHAIN_DERIVED_STATES](CHAIN_DERIVED_STATES.md) | BOPS-COCKPIT-04 | #4452 | Blocked on 03 |
| 5 | [SURFACE_LENSES](SURFACE_LENSES.md) | BOPS-COCKPIT-06 | #4453 | Blocked on 02+04+05 |

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

- [ ] All seven task rows above are Delivered with their per-AC `Verify:` targets green on merged SHAs
- [ ] The induced dead-source journey runs in the post-merge browser lane and proves red-not-calm
- [ ] Every plane the surface reads has fresh/stale/unavailable pill states with its own threshold
- [ ] The five chain-derived states and the flaw predicates render from live data on the host, with
      every unreadable predicate named as unread
- [ ] This README's task table, coordination constraints, and decision ledger reflect delivered
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
