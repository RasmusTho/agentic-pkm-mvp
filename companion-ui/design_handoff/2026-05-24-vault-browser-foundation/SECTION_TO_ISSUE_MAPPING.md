# Section → Issue Mapping

Maps actionable recommendations from
[`VAULT_BROWSER_DESIGN_HANDOFF.md`](VAULT_BROWSER_DESIGN_HANDOFF.md) to the
existing Vault Browser Foundation issue stack, plus future-backlog candidates
that are **not** to be implemented as part of #1259.

This mapping is the source of the workspace-shell prerequisite call-out: the
shipped Companion workspace shell (the surface the browser opens notes into)
has issues that block deeper browser UI work, and those need addressing first.

> **Authority reminder.** This mapping is design input, not a contract change.
> It must not silently re-scope any existing issue. If a design recommendation
> implies scope changes to #1253–#1257, route the change through
> `issue-maintenance-change-control`, not through implementation.

## Prerequisite: workspace shell orientation alignment → #1260

**Source sections:** §02 critique (C1–C7), §05 layout rules, slice **A** in §19.

**Insight.** The current workspace shell — the surface a note opens into when
the Vault Browser hands it off — renders frontmatter as body (C1), stacks three
competing safety strips (C2), renders disabled affordances as enabled (C3),
leaks internal state vocabulary to the user (C4), buries the artifact identity
strip (C5), fills the right rail with idle/unavailable stubs (C6), and is
shaped for a runtime engineer rather than the human-first user (C7). The
browser will inherit each of these problems if they are not corrected first.

**Why this maps to #1260 first.**

- #1260 should **precede #1255, #1256, #1257.** Inspector design (#1255),
  action display (#1256), and receipts/review posture (#1257) are illegible if
  the workspace shell behind them still treats frontmatter as body and leaks
  state-machine labels.
- #1260 should **precede or at least inform #1253 and #1254** where visual
  metadata surfaces (pills, identity strip, safety posture) are affected by
  the same C1/C2/C5 problems.
- #1260 must not silently absorb the slice-A wording from §19. Slice A is a
  design recommendation. The actual scope of #1260 is whatever its issue body
  declares; if §19 slice A would expand that scope, route through
  `issue-maintenance-change-control`.

**Verify:** [`README.md`](README.md) and this file reference #1260 as the
prerequisite to deeper browser UI implementation.

## Foundation stack — downstream implementation issues

Each row below identifies sections that inform an existing issue. The design
content **does not re-scope** any of these issues. If an actionable item is
out of an issue's current scope, it remains design input only.

### #1253 — Normalized metadata read model

| Design section | What it informs |
|---|---|
| §04 Information architecture (Inspector area) | Read-model surface contract: which fields the inspector consumes. |
| §07 Metadata filter UX | Filter dimensions implied by the read-model fields (kind, zone, review_state, trust, origin, source_ref, health). |
| §08 Artifact list / card design | Row template fields that depend on the normalized read model. |
| §09 Inspector — Metadata / Health / Provenance tabs | Per-field source attribution (`frontmatter / system / inferred`). |
| §15 Test IDs / data attributes | `data-uuid, data-kind, data-zone, data-review-state, data-trust, data-origin, data-health` on row + `data-tab, data-available` on inspector tabs. |

**Out of scope for #1253 (design-only input):** UI rendering of the read-model
data. That lives in #1254/#1255.

### #1254 — Metadata filters and badges

| Design section | What it informs |
|---|---|
| §07 Metadata filter UX | Filter dimension table (kind, zone, review_state, trust, origin, source_ref, health); chip behavior; "what is forbidden" rules. |
| §08 Artifact list / card design | Pill rendering, ordering, color rules. |
| §10 Provenance, trust, review posture | Pill semantics across the three axes and orthogonality. |
| §15 data attributes | `vault-browser-filter-chip` selector and `data-key/data-value/data-active` state. |

**Out of scope for #1254:** anything that introduces semantic ranking, "smart"
filters, or filter-driven writes — those are explicit non-goals in §16.

### #1255 — Artifact inspector

| Design section | What it informs |
|---|---|
| §09 Artifact inspector | Tab inventory (Preview · Metadata · Health · Provenance · Links · Activity · Receipts · Actions); inspector rules; per-tab samples. |
| §13 Empty / error / degraded states | Per-tab degradation (Links tab degraded, Receipts source down, etc.). |
| §15 data attributes | `vault-browser-inspector` + `vault-browser-inspector-tab` selectors with `data-artifact-uuid, data-open-tab, data-tab, data-available`. |

**Out of scope for #1255:** Links tab beyond placeholder (deferred), Actions
tab logic (lives in #1256), Receipts tab logic (lives in #1257).

### #1256 — VaultAction display model

| Design section | What it informs |
|---|---|
| §11 VaultAction display model | Six-mode visual treatment matrix; mode pill rules; "hard rule" on collapsing bounded vs governance. |
| §09 Inspector — Actions tab | Actions tab is never empty; minimum content rules. |
| §15 data attributes | `vault-browser-action` with `data-mode, data-blocked-reason`. |

**Out of scope for #1256:** the runtime that declares VaultAction modes —
the browser never reclassifies and never invents a mode.

### #1257 — Agent receipts and review posture

| Design section | What it informs |
|---|---|
| §12 Receipts and review posture | Receipt state machine; rail vs inspector receipts; identifier visibility rules. |
| §09 Inspector — Activity / Receipts tabs | Per-artifact activity timeline and receipts list. |
| §13 Empty / error / degraded states | Receipt source unavailable ≠ "no receipts". |
| §15 data attributes | `vault-browser-receipt` + `vault-browser-receipt-source` with `data-receipt-id, data-trace-id, data-status, data-source-available`. |

**Out of scope for #1257:** authoring receipts — the browser surfaces them, it
does not author them.

### #1261 — Foundation-stack sequencing / planning

**Source sections:** §16 MLP vs future capability, §19 Recommended
implementation slices (entire table, especially the "must / near / defer /
later" verdict column), §20 closing notes.

**Insight.** §19 is the design's own slice grid (A–P) after #1253–#1257. It
proposes an ordering — workspace shell parity → shell + Files view migration →
Artifacts view → inspector tabs → action rendering → receipts → review queue →
activity/timeline → agent activity → degraded-state contract pass → responsive
tiers → saved views / links / resurfacing / graph.

The mapping to existing issues is partial; many slices (G–P) are not yet
tracked as issues. #1261 is the natural home for converting that grid into a
sequencing/planning artifact and selecting which slices become bounded issues
next.

**Recommended next step.** Run #1261 (planning) before extracting any of the
G–P slices into new issues. That keeps the slice-extraction discipline inside
the planning lane rather than during this docs landing.

## Future-backlog candidates (do not implement here)

The handoff identifies design surfaces that are **not** covered by an existing
implementation issue. These are recorded for future backlog extraction. They
must **not** be implemented as part of #1259.

| Capability | Source section | Verdict per §19 | Notes |
|---|---|---|---|
| Saved views | §06, §07 (deferred dims), §17, §19 slice M | later | Deterministic only. No "smart" saved views. |
| Timeline / activity browsing | §06, §09 Activity tab, §17, §19 slice H | near | Same row template, time-grouped. Depends on #1257 receipts/activity read model. |
| Artifact relation read model | §09 Links tab, §17 | later | Inferred vs human-confirmed must stay distinct. |
| Links / relations inspector beyond placeholder | §09 Links tab, §19 slice N | later | Currently degradable; full implementation deferred. |
| Graph as secondary browsing mode | §06, §17, §19 slice P | later | **Never the landing.** Hard contract from §16 non-goals. |
| Source / evidence dependency browser | §06, §17 | later | Pivot row template onto `source_ref`. |
| Review campaigns | §17 | later | Saved view + `campaign:` tag on review queue. |
| Guarded bulk operations | §17 | later | Bounded vs governance bulk are different shapes; both server-declared VaultActions. |
| Resurfacing candidates view (read-only) | §06, §17, §19 slice O | later | Read-only first. No urgency semantics. |
| Duplicate candidates | §17 | later | Proposed merges enter proposal/receipt loop. |
| Contradiction candidates | §17 | later | Surfaced as proposals with two-side evidence. |
| Agent activity explorer | §06, §17, §19 slice I | near | Depends on #1257 receipts + #1257-derived activity stream. |
| Responsive / mobile read-only behavior | §14, §19 slices K + L | defer | Governance writes hidden on mobile. |
| Visual hierarchy / density pass (workspace shell + browser) | §02 critique, §08 row rules, §18 risks | — | Should be incorporated into the planning issue (#1261), not extracted as a separate implementation issue without scope.|

**How to convert these into issues.** Use the `docs-to-issue` /
`feature-breakdown` skills under the planning lane (#1261), not as part of
landing this handoff. Each item needs bounded `Scope`, `Source Anchors`,
`Acceptance Criteria` with `Verify:` markers, and a clear non-overlap with
existing issues #1253–#1257 / #1260.

## Conflict-with-SoT log

No conflicts identified at landing time. The handoff's hard rules (no graph
landing; no agent auto-apply; no opaque ranking; bounded vs governance
distinction; degraded states explicit) align with
`docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md §8` and the gated-execution invariant
in `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`.

If a future reading of the handoff surfaces a conflict, append the row here
and open an `issue-maintenance-change-control` issue with the conflict
description and proposed resolution. Do not modify SoT silently.
