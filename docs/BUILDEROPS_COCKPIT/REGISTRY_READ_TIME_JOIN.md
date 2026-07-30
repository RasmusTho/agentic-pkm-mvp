---
name: Registry Read-Time Join
description: The delivered v1 join — bands, evidence spine, per-source freshness, honest emptiness over dispatcher/verification/deploy planes
task_id: BOPS-COCKPIT-01
source_anchor: "docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md :: RQ3 — Renderable today; minimal completion set"
parent_capability: BuilderOps Cockpit
github_issue: 4438
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Registry Read-Time Join

**Status: DELIVERED** — #4438 / PR #4439, merged 2026-07-30. This specification records what
landed so later tasks build on stated, not remembered, behavior.

## Purpose

Give the owner one read-only surface answering the four questions (working on / done / has flaws /
forgotten) as a read-time join over existing builder authorities, owning no plane and persisting
nothing.

## What This Task Does

- `GET /api/cockpit/registry` (`app/api/routes/cockpit.py`) builds the payload on every call via
  `app/builderops/cockpit_registry.py::build_registry`; `/cockpit` serves the static surface
  (`app/web/static/cockpit.html|js|css`).
- Reads three planes: dispatcher task store and verification runs (SQLite opened strictly
  read-only) and deploy receipts (`ops/deployments/<channel>-latest.json`). Unread planes
  (`github-live`, `docs-frontmatter`, `ckm-projection`, `git`) are named as unread
  (`UNREAD_PLANES`), never implied.
- Bands in locked order — working / done / flawed / forgotten / needs-you — derived fail-closed
  from dispatcher status (`STATUS_BAND`); unmapped statuses land in the explicit `unclassified`
  list, never guessed. `agent:needs-human` routes to the needs-you band — caveat: labels and URLs
  are consumed-if-present from the sync mirror's `sync_state`, and production sync populates
  neither until #4441 (audit F9 enrichment) lands, so the needs-you band and mirror out-links are
  structurally empty in production today.
- Eight-rung evidence spine per thread in locked order (intention · capability · epic · slice · PR
  · CI/sha · receipt · tried); rung class derives from key class, not content quality; intention,
  capability, epic, and tried render `absent` in this increment.
- Per-source freshness pills with `last_successful_read`; a dead source refuses counting
  ("cannot be counted", `countable: false`) instead of showing zero; true emptiness is a dated
  positive claim; missing deploy receipts are structural absence, not a dead source.
- Done band renders two tiers: "Ready for you to use" (out-links to the authority) above
  "Tried by you" (empty by contract until INV-DG-7 has a receipt contract).
- Served token sheet is byte-identical to the binding source, CI-enforced.

## Concretely

```
curl -s localhost:18001/api/cockpit/registry | jq '.sources, .bands[].key'
```

Expected: a `sources` array where each entry names `state` and `last_successful_read`, and bands in
the locked order with per-band `countable` flags.

## Why This Matters

Everything later in this capability layers onto this join. If banding were not fail-closed or
emptiness not refused on dead sources, every subsequent plane would inherit a surface that can lie
calmly — the exact failure the owner named as the central risk.

## Acceptance Criteria

All delivered and green on main:

- [x] Fail-closed banding with an explicit unclassified list
  - Verify: `tests/builderops/test_cockpit_registry.py::test_band_derivation_fail_closed`
- [x] Refused emptiness on unavailable sources; dated claim on true emptiness
  - Verify: `tests/builderops/test_cockpit_registry.py::test_refused_emptiness_on_dead_source` and
    `tests/builderops/test_cockpit_registry.py::test_true_emptiness_is_dated_claim`
- [x] Evidence spine classes by key nature; four rungs `absent` in v1
  - Verify: `tests/builderops/test_cockpit_registry.py::test_rung_classification_machine_edges_only`
- [x] Token parity with the binding source
  - Verify: `tests/api/test_cockpit_api.py::test_token_sheet_parity_with_binding_source`

## How to Verify (Pre-Merge)

Delivered; regression surface is `pytest tests/builderops/test_cockpit_registry.py
tests/api/test_cockpit_api.py -m "not pg"`.

## Out of Scope

GitHub live reads, docs-frontmatter and CKM planes, chain-derived states, lenses, any action
button, any persistence — all specified by the sibling tasks or excluded by the README's binding
out-of-scope list.

## Restart / Durability Posture

Nothing the surface shows survives a reload or process restart, by contract: every claim is
recomputed from the authorities at render time. The user consequence is honest staleness — a claim
row always carries its read instant, and after a restart the surface simply re-reads; there is no
cockpit-local state to lose or to contradict GitHub.

## Related Docs

- `docs/BUILDEROPS_COCKPIT/README.md`
- `docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md`
- `docs/adr/ADR-0065-builderops-temporal-intention-authority.md` (no attention-state writer)

## Related GitHub Issues

#4438 (delivered, closed). No further issues from this task.
