State: Delivered v1 (#4438). Owner doc for the BuilderOps cockpit registry surface.

# BuilderOps Cockpit Registry

A **read-time join** over existing builder authorities, served at `/cockpit`
with its payload at `GET /api/cockpit/registry`. The surface owns no plane, no
queue, no register, and no decision right. Every row it shows has a named
source and a read time, and nothing it renders survives a reload.

Design provenance: the 2026-07-30 `builderops-cockpit` design exploration in
the Claude Design project (design system `Yggdrasil Design System`,
id `f2b13410-af14-4875-8029-445352123f57`). The design package is external
design input; this document is the normalized authority for what was accepted.
This surface is distinct from the CKM cockpit render mode
(`docs/CKM_COCKPIT_DIRECTION_B/README.md`), whose honesty idiom it reuses.

## What v1 renders

- **Four bands in locked order plus a needs-you band** — the four questions:
  What are we working on? What is done? What has flaws? What is forgotten?
  Band derivation from dispatcher status is fail-closed (`STATUS_BAND` in
  `app/builderops/cockpit_registry.py`): an unmapped status is listed under
  *Unclassifiable*, never guessed into a band. The `agent:needs-human` label
  routes a thread to the needs-you band.
- **An eight-rung evidence spine per thread** — intention · capability · epic ·
  slice · PR · CI/sha · receipt · tried, in locked order. Rung class derives
  from the key's nature, not content quality: `proven` only for DB-keyed or
  CI-forced edges (slice issue number, linked PR, `verified_head_sha`,
  verification terminal receipt). In v1 the intention, capability, epic, and
  tried rungs render `absent` — their visible absence is the point.
- **Per-source freshness** — each source pill carries its own
  `last_successful_read` computed at render: `dispatcher-store`,
  `verification-runs` (both the dispatcher SQLite, opened strictly read-only),
  and `deploy-receipts` (`ops/deployments/<channel>-latest.json`). Planes not
  read in v1 (GitHub live, docs frontmatter, CKM projection, git) are named as
  unread rather than implied.
- **Honest emptiness in three forms** — true emptiness is a dated claim backed
  by fresh source reads; a dead source yields a refused claim ("cannot be
  counted", never zero); a missing deploy receipt is structural absence
  (`empty`), not a dead source.
- **Two tiers in the done band** — "Ready for you to use" (delivered threads
  with an out-link to the authority) above "Tried by you", which is empty by
  contract until an owner-acceptance receipt contract exists (INV-DG-7); its
  emptiness is rendered as an honest claim.

## Authority boundaries (binding)

| Boundary | Owner | Consequence here |
|---|---|---|
| Attention state (`done`/`ignore`) | ADR-0065 (PostgreSQL-only, receipt-backed; writer gated on BCP-06 #3793) | No "mark handled" anywhere; nothing persists across reloads |
| Delivery approval | `verification-and-closure` | No approve button |
| Task register and workflow | Dispatcher | No status fields, no drag-and-drop, no ordering owned here |
| Capability maturity | CKM projection (a lens, not a spine) | No scalar maturity number |
| Source content | GitHub, Signboard, the repo | Deepest layer is an out-link, never a copy |

v1 is entirely read-only: no contract calls, no agent starts, no
hold-to-confirm friction (those are later slices with their own contracts).

## Visual contract

All visual values come from the Yggdrasil token sheet. The served
`app/web/static/colors_and_type.css` must stay byte-identical to the binding
source `companion-ui/companion-app/colors_and_type.css`; the parity is
CI-enforced by `tests/api/test_cockpit_api.py::test_token_sheet_parity_with_binding_source`.
`app/web/static/cockpit.css` consumes tokens only and introduces no new
color, radius, or type value.

## Deliberately not built in v1

Capability lanes from the CKM projection; the graph and one-question-at-a-time
lenses; action buttons of the `contract`/`agent` classes; Signboard
tokenization (design open question DS-3); any GitHub live read (GitHub-derived
fields come from dispatcher sync state and are only as fresh as the last
`dispatcher pull`).
