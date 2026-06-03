---
name: Companion UI State Map
description: Normalized status map of Companion UI product modes and surfaces (shipped/dev-staging vs target-state) before Resurface and Act slicing
doc_role: Normalized state map / reconciliation reference
authority: Non-normative reconciliation view. Authority for each surface stays with its owner contract (Panel, Workspace State, Workspace Orientation, Vault Browser, UI Runtime Boundaries) and with shipped runtime truth in docs/STATUS.md. This doc only maps current status; it does not define behavior.
owner: Companion UI / product architecture
last_reviewed: 2026-06-03
source_contracts:
  - docs/COMPANION_UI_PRODUCT_SPEC.md
  - companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md
  - companion-ui/docs/WORKSPACE_STATE_CONTRACT.md
  - companion-ui/docs/UI_RUNTIME_BOUNDARIES.md
  - companion-ui/docs/RESURFACING_HEURISTICS.md
  - docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md
  - docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md
  - docs/STATUS.md
---
State: Normalized Companion UI state map. Reconciliation/reference doc, not a runtime contract. Captures status as of 2026-06-03.

# Companion UI State Map

## Purpose

Stabilize how we talk about Companion UI **modes** and **surfaces** before more
target-state-heavy UI work (especially Resurface and Act) is sliced. This is a
normalization layer: it maps each mode and surface onto a small status taxonomy and an
authority posture, and reconciles a few stale references. It does not define new behavior,
add APIs, or claim target-state work is shipped.

Mode definitions are owned by `docs/COMPANION_UI_PRODUCT_SPEC.md`. Surface behavior and
authority are owned by the per-surface contracts. Shipped runtime truth is owned by
`docs/STATUS.md`. Where this map and an owner contract disagree, the owner contract wins.

## Product modes

The product spec defines four user-facing modes. They are affordances over existing
authority boundaries (Panel / Chat / Automation); they are not a new authority surface.

- **Find** — "Where is the thing I need, and what is the best source to cite?"
- **Reorient** — "What was I doing, what changed, and what should I do next?"
- **Resurface** — "What quietly important thing should return to attention now?"
- **Act** — "How do I turn intent into a governed, completed change?"

## Status taxonomy

Every surface row below is tagged with exactly one status:

- **shipped/dev-staging** — present on `main` and exercised in the dev/staging Companion
  shell. Not a claim of production hardening or packaging.
- **open PR** — change in flight, not yet merged.
- **blocked** — cannot proceed without a named dependency or decision.
- **target-state** — described in product/spec docs, not implemented as a Companion UI
  surface yet.
- **forbidden/non-goal** — explicitly out of bounds.

## Current-state surface map

| Surface | Status | Mode(s) | Authority posture | Owner contract / evidence |
|---|---|---|---|---|
| Workspace orientation (re-entry, nothing open) | shipped/dev-staging | Reorient | read-only (may emit `mutation_intents`, never applies) | `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md`; `GET /api/companion/orientation`, `/api/orientation`; re-entry UI (#1452/#1453/#1460/#1461/#1462) |
| Active note workspace (single-shell, renderer, body edit) | shipped/dev-staging | Find, Reorient, Act | UI-local rendering; body edit is governed handoff via `active_note_body_update` + WriteGuard | `docs/STATUS.md`; adaptive single-shell (#1395 line), body edit (#1346/#1416) |
| Vault Browser (browse, outline, artifact inspector) | shipped/dev-staging | Find, Reorient | read-only; `queue_review` is governed handoff (`POST /api/companion/vault-browser/actions/queue-review`) | `docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md`; `app/api/routes/companion.py` |
| Panel / agent rail | shipped/dev-staging | Act | governed handoff (propose → decide → execute → receipt); owns governed action | `companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md`; CanvasPanelPipeline, checkbox projection |
| Receipts / provenance | shipped/dev-staging | Act, Reorient | read-only display; receipts must not be invented by the UI | `docs/STATUS.md` (APPLY accountability fields); receipt query (#1532) |
| Memory candidate boundary (orientation seam) | shipped/dev-staging | Reorient | read-only awareness + intent emission only; never hidden authority | ADR-0009; `tests/api/test_orientation_memory_seam.py` (#1457/#1466) |
| Agent-memory posture in Vault Browser inspector | shipped/dev-staging | Find, Reorient | read-only projection; server-declared | scope decision #1474 (closed); read-only projection #1547 (closed); Vault Browser surfacing #1551 (`app/agent_memory/posture_projection.py`). See **Known blocked areas**. |
| Ambient foreground orientation refresh | shipped/dev-staging (default-off) | Reorient | read-only; non-notification | feat #1458 (closed), receipt/orientation fixes #1532 (merged). **Not** an open item. |
| Resurface read-side candidates | shipped/dev-staging | Resurface | read-only suggestion display; no persistence or urgency escalation | `app/resurfacing/runtime.py`; `GET /api/companion/workspace` resurface projection; workspace shell rendering/tests; MLP capability docs |
| Resurface persistence/orchestration (dismiss/snooze/pin, tray, cross-artifact surfacing workflow) | target-state | Resurface | future governed persistence/orchestration; must remain low-pressure unless runtime declares urgency | Product spec §Resurface; `companion-ui/docs/RESURFACING_HEURISTICS.md`; MLP docs mark durable controls unavailable until persistence exists |
| Act flow visual states (unified propose/stage/apply UX) | target-state (parts shipped via Panel/runtime) | Act | governed handoff; must not blur stage/apply | product spec §Act; Panel flow shipped, unified Companion Act UX target-state |

## Authority posture per mode

- **Find** — read-only by default. Presents and summarizes; cannot promote retrieved
  material into durable knowledge without a governed flow.
- **Reorient** — read-only synthesis and proposal. May surface candidates and emit
  `mutation_intents`; never applies them.
- **Resurface** — read-only suggestion in the shipped/dev-staging workspace shell. May
  suggest; must not escalate to urgent-task semantics. Durable dismiss/snooze/pin,
  tray-level persistence, and richer orchestration remain target-state.
- **Act** — governed handoff only. Routes through Panel/governance; must not bypass
  WriteGuard or blur propose/stage/apply.

## Known blocked areas

- **Agent-memory posture in the Vault Browser inspector** was previously gated on a safe
  artifact-scoped read-only source/API. That scope is now resolved:
  - #1474 (closed) scoped the agent-memory review-posture layer for the inspector.
  - #1547 (closed) delivered the read-only agent-memory posture projection.
  - #1551 (merged) surfaced the agent-memory posture projection in the Vault Browser
    (`app/agent_memory/posture_projection.py`, `app/api/routes/companion.py`).
  This map references #1474/#1547/#1551 as the governing scope and does **not** redefine or
  duplicate agent-memory posture here. Any future change to that posture must extend those
  contracts, not this map. No currently-open blocker remains for this surface.

## Downstream candidates

Listed for awareness only. **Do not** create implementation issues from this section
without an owner decision; this map exists in part to prevent premature Resurface/Act
slicing.

- Resurface persistence/orchestration normalization (durable dismiss/snooze/pin,
  tray-level behavior, and cross-artifact surfacing workflow).
- Act flow visual hardening (unified propose/stage/apply Companion UX).
- Fixture-safe UAT / state coverage for Companion UI modes (tracked by #1550).
- Optional re-entry degraded/manual-refresh audit, only if a concrete post-#1532 gap is
  identified.

## Required reconciliation (applied in this map)

- PR #1532 is **merged**, not open — treated as shipped.
- #1458 (foreground ambient refresh) is **closed**, not open — treated as shipped
  (default-off).
- Agent-memory posture references #1474 / #1547 instead of duplicating that scope.
- Resurface read-side candidate rendering is **shipped/dev-staging**; durable
  Resurface persistence/orchestration and unified Act UX remain **target-state**.
- No design/planning language in this doc is runtime truth; runtime truth lives in
  `docs/STATUS.md` and the owner contracts.

## Authority boundaries to preserve

These invariants hold across every mode and surface above:

- Server declares; UI renders.
- Chat is not source of truth.
- Agent memory is not hidden authority.
- Orientation is read-only.
- Resurfacing is not notification delivery.
- Vault Browser is not execution authority.
- Panel / governance owns governed action handoff.
- Receipts must not be invented.
- The UI must not infer governance, memory authority, urgency, salience, or actionability
  locally.

## Related docs

- `docs/COMPANION_UI_PRODUCT_SPEC.md` — mode model (Find/Reorient/Resurface/Act)
- `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md` — orientation read-side contract
- `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md` — artifact-scoped workspace state
- `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md` — UI runtime / cognition separation
- `companion-ui/docs/RESURFACING_HEURISTICS.md` — resurfacing heuristics
- `docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md` — Vault Browser capability/authority
- `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md` — salience vs urgency
- `docs/STATUS.md` — shipped runtime truth
