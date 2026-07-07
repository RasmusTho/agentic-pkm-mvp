State: Active specification (2026-07-07). Governs B2 (#3024) — the Mimer-iPad thinking-canvas client — broken down to slices a Sonnet-class agent can build from the slice text alone.
Doc role: Specification directory (feature-breakdown lane)
Authority: Specifies the B2 work. Subordinate to `docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md` (design-of-record), `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md`, `docs/adr/ADR-0056-mimer-client-contract-and-transports.md`, and `docs/contracts/MIMER_CLIENT_CONTRACT.md`. Where the out-of-repo Heimdal UX design artifacts (journey mocks) and this spec differ, this spec is the committed authority for B2 — it was cut deliberately to be self-sufficient in-repo.
Owner: Architecture / product (Rasmus)

# Mimer iPad Thinking Canvas (B2)

## Why this spec exists

The design-of-record (`docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md` §2) commits iPadOS as the
**primary canvas** for Mimer's thinking surfaces: a multi-column layout (source list · item ·
inspector), side-by-side entity confirmation (JE — "the single biggest iPad win"), Pencil +
keyboard interaction, and drag-drop promotion into vault notes. B1 shipped the shell and the
iPhone lens set; on an iPad today the same `TabView` simply runs scaled-up — none of the
iPad-specific commitments exist.

Substrate facts this spec builds on (verified on bifrost `origin/main` = `b77cb205`):

- The Xcode project is already **universal** (`TARGETED_DEVICE_FAMILY = "1,2"`, iOS 17.0) — no
  target work needed, only adaptive layout.
- All Mimer surfaces are **direct-filesystem** over `VaultFileStore` (security-scoped bookmark,
  `read`/`readMany`/`write`/`readModifyWrite`/`listEntries`); there is **no HTTP anywhere** in the
  shipped client, and the client contract's API surface (`/search` k=10, `/api/ask`,
  `/api/artifacts/note`) has **no folder-listing/recent/backlinks endpoint** — vault navigation is
  filesystem by design.
- Entity confirmation (JE) already exists on iPhone as `EntityConfirmLensView` (A17): read
  `_heimdal/entities/review.md` `pending`, append to `decisions` via `readModifyWrite`; the hub
  applies decisions and clears pending entries. B2 widens this surface; it does not change the
  contract.

## Write gate (read this before picking up any slice)

The owner gate on #3024 blocks B2 on ADR-0055 **enactment**: hub #3129 (INV-VW2 append guard),
#3131 (contract/schema materialization), #3132 (stale-detection + conflict staging + iCloud
quarantine), plus the client-side B1 tasks bifrost#4 (coordinated writes) / bifrost#5 (provenance).
This spec re-cuts that gate at slice granularity, explicitly:

- **Write-free slices (MIPAD-01, MIPAD-02) are executable now.** They add no writer, touch no
  vault-write call site, and add no multi-writer risk — the gate's rationale does not reach them.
- **Write-bearing slices (MIPAD-03, MIPAD-04) stay blocked** on all five issues above landing.
  They must consume the post-bifrost#4/#5 `VaultFileStore` seam and must not invent any new write
  primitive (ADR-0055 item 5).
- **Closure slices (MIPAD-05, MIPAD-06) come last** and inherit whatever is still open.

This re-cut is recorded on #3024 so the gate stays auditable.

## Implementation tasks

| Task | Repo | Purpose |
|---|---|---|
| [ADAPTIVE_THREE_COLUMN_SHELL_ON_IPAD.md](ADAPTIVE_THREE_COLUMN_SHELL_ON_IPAD.md) | `RasmusTho/bifrost` | Regular-width iPad gets a `NavigationSplitView` three-column shell; iPhone `TabView` unchanged |
| [VAULT_BROWSE_COLUMNS_WITH_NOTE_INSPECTOR.md](VAULT_BROWSE_COLUMNS_WITH_NOTE_INSPECTOR.md) | `RasmusTho/bifrost` | Source list · item list · note detail + inspector panel (read-only), with hardware-keyboard navigation |
| [SIDE_BY_SIDE_ENTITY_CONFIRMATION_ON_IPAD.md](SIDE_BY_SIDE_ENTITY_CONFIRMATION_ON_IPAD.md) | `RasmusTho/bifrost` | JE on iPad: pending mention beside its candidate entities; merge/reject as reversible appended decisions |
| [ANNOTATE_AND_PROMOTE_INTO_NOTES.md](ANNOTATE_AND_PROMOTE_INTO_NOTES.md) | `RasmusTho/bifrost` | Pencil/keyboard annotation + drag-drop of an item/snippet into a vault note, as governed markdown appends |
| [PROVE_IPAD_UAT_JOURNEYS.md](PROVE_IPAD_UAT_JOURNEYS.md) | `RasmusTho/bifrost` | XCUITest journeys on iPad simulator in CI + operator's eyes-on device walkthrough receipt |
| [RECONCILE_AND_CLOSE_B2_TRACKING.md](RECONCILE_AND_CLOSE_B2_TRACKING.md) | `RasmusTho/agentic-pkm-mvp` (hub) | Assemble the verification ledger on #3024, close it truthfully, update Epic B #3020 |

## Execution order

1. `ADAPTIVE_THREE_COLUMN_SHELL_ON_IPAD` — the layout skeleton everything else hangs on. **Ready now.**
2. `VAULT_BROWSE_COLUMNS_WITH_NOTE_INSPECTOR` — after 1. **Write-free; ready once 1 merges.**
3. `SIDE_BY_SIDE_ENTITY_CONFIRMATION_ON_IPAD` — after 2 and the write gate. May run parallel with 4.
4. `ANNOTATE_AND_PROMOTE_INTO_NOTES` — after 2 and the write gate. May run parallel with 3.
5. `PROVE_IPAD_UAT_JOURNEYS` — after 1–4 merge.
6. `RECONCILE_AND_CLOSE_B2_TRACKING` — strictly last; blocked on 5's receipts.

## Cross-Task Invariants / Interaction Safety

- **INV-B2-1 — iPhone never regresses.** Every slice keeps the compact-width experience exactly
  as B1 shipped it (`TabView`, same lenses). Each slice's CI run must keep the existing iPhone
  XCUITests green alongside any new iPad tests; a slice that needs to change shared views must
  branch on size class, not edit iPhone behavior.
- **INV-B2-2 — One write seam, no new primitives.** All vault writes go through the
  post-bifrost#4/#5 `VaultFileStore` (coordinated access, stale-verify, provenance). No slice adds
  a bespoke write path, client-side conflict logic, or queued/deferred writes. If a write-bearing
  slice is picked up and the seam is not merged yet, the slice is blocked — it must not ship a
  plain-`FileManager` interim.
- **INV-B2-3 — Markdown-first canvas.** Column selection, drag state, and in-progress annotations
  are ephemeral view state; anything meant to survive lands as markdown in the vault or does not
  exist. No client-local store of meaning (contract §3 invariant 3). Partial-failure path: an
  annotation/promotion whose write fails is surfaced to the human with its text still visible
  (recoverable by copy), never silently dropped and never cached to a hidden retry queue.
- **INV-B2-4 — JE decisions are reversible appends.** A merge/reject is an appended `decisions`
  entry in `_heimdal/entities/review.md` (idempotent on exact duplicates, as `HeimdalNotes`
  already guarantees); reversal is a compensating decision, not an edit or deletion of history.
  The client never deletes or rewrites `pending` entries — clearing pending is the hub's job.
  This satisfies #3024's "reversible" AC at the decision layer; materializing entity-register
  redirects from decisions stays hub-side (Mimer organ, ADR-0049 §2), not client work.
- **INV-B2-5 — Write-gate honesty.** MIPAD-03/04 must not merge while any of hub
  #3129/#3131/#3132 or bifrost#4/#5 is open. If sequencing pressure demands the UI early, the
  degraded form is read-only preview with actions disabled and labeled — never live writes on the
  ungated substrate.

## Capability acceptance criteria

B2 (#3024) can be closed when all of the following hold:

- [ ] iPad (regular width) presents the three-column canvas; iPhone is unchanged (MIPAD-01/02
  merged; bifrost CI green on both destinations).
- [ ] Side-by-side JE works on iPad: pending mention with candidate context, merge/reject recorded
  as reversible appended decisions with provenance (MIPAD-03 merged).
- [ ] Annotation and drag-drop promotion land as markdown appends with provenance (MIPAD-04 merged).
- [ ] The iPad journeys run as XCUITests in bifrost CI and the operator's eyes-on iPad walkthrough
  receipt is posted to #3024 (MIPAD-05).
- [ ] #3024 closed with the assembled ledger; Epic B #3020 updated (MIPAD-06).

## Relationship to GitHub issues

- **Parent / validation hub:** #3024 (`task: B2 — Mimer-iPad thinking-canvas client`) — already
  exists and stays the live validation hub; no new parent issue. Its body gets an
  Implementation-Tasks pointer to this spec when the spec lands.
- **Grandparent:** Epic B #3020.
- **Bifrost child issues** implement MIPAD-01..05; the hub child implements MIPAD-06. Each posts
  its delivery receipt to #3024.
- Gating (adjacent, not children): hub #3129/#3131/#3132, bifrost#4/#5 — see "Write gate" above.

## Verification path

Swift verification runs in bifrost CI (`macos-14`, real Xcode) — each task file names its tests;
iPad coverage uses an iPad simulator destination added in MIPAD-01. The operator's laptop has no
Xcode by design; CI is the accepted gate (same posture as B1). Device verification is the one
human step, in MIPAD-05, under `docs/BIFROST/APP_DEPLOYMENT_POSTURE.md` (free-provisioning
sideload).

## Evidence surface

Validation receipts accumulate as comments on #3024 (one short receipt per merged task).
Owner-doc promotion happens once, at MIPAD-06.
