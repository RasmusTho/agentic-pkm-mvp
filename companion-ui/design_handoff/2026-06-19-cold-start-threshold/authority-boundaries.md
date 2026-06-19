# Authority boundaries — Cold-start entry threshold

## This design is

- **Visual / interaction guidance** for the `cold_start` and `no_vault` entry surfaces only.
- **An interaction contract** limited to the render behavior, `data-region` markers, and intent reuse enumerated in `implementation-contracts.md` and shown in `prototype.html`.
- **A target-state proposal** that amends the existing normalized spec `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md`. The one shipped fact it leans on is `GET /api/companion/orientation` and its `leave_point.status` / `scope.vault_id` fields (`WORKSPACE_ORIENTATION_CONTRACT.md`), cited where used.
- **A divergence report.** Its diagnosis (the orientation grid renders unconditionally on `cold_start`) cites shipped code by `file:line`; that part is current-behavior, verified, not target-state.

## This design is not

- **Architecture authority.** Authority lives in the owner-docs: `docs/COMPANION_UI_PRODUCT_SPEC.md` (Find/Reorient/Resurface/Act), `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`, `docs/INTEGRATION_FABRIC_CONTRACT.md`, `docs/CAPABILITY_CONTRACT_MODEL.md`, `docs/INTERACTION_SURFACES_AND_AUTHORITY/`, and the in-folder `WORKSPACE_ORIENTATION_CONTRACT.md` / `SYSTEM_ENTRY_POINT_SPEC.md`.
- **Runtime truth.** Runtime truth lives in shipped code, tests, `docs/STATUS.md`, and validation receipts.
- **A schema declaration.** It references runtime fields (`leave_point`, `scope.vault_id`, and the proposed most-recently-edited target); it does not declare or modify them. The recents-anchor field is a **proposal** that must land through a `WORKSPACE_ORIENTATION_CONTRACT.md` owner-doc PR before the UI consumes it.
- **A unilateral spec edit.** The four `SYSTEM_ENTRY_POINT_SPEC.md` amendments listed in `implementation-contracts.md` are **proposals**. They are applied through reviewed PRs (Crossing B → C → D), bundled with the implementation per owner-doc bundling — not committed in this package.

## The boundary, restated

This boundary is absolute. A passage here that appears to contradict an owner-doc does **not** win — the owner-doc wins and the passage is a proposal. The single place this package asserts current behavior is the verified divergence (`serve_dev_page.py:6377-6408` renders the grid unconditionally); that is cited from shipped code, and the spec it diverges from (`SYSTEM_ENTRY_POINT_SPEC.md` anti-dashboard rule) is the authority being honored, not overridden.

## Invariants this design honors

- **No AI-dashboard posture.** The whole point: `cold_start` renders no cards, counts, or feeds; relocated telemetry renders as read-only projection behind a pull-only surface, never as live tiles.
- **No false continuity.** `cold_start` and `no_vault` show no re-entry overlay of any kind; the recents-anchor is framed as a Find/recency fact, explicitly not a `leave_point`.
- **Gated execution.** The only durable write reachable from the threshold is `capture.save`, which routes through the shipped governed capture occupant; a write is claimed only on the runtime `WriteReceipt`. No body-edit, no governance mutation, on the door.
- **Server declares; UI renders.** Entry state, `scope.vault_id`, `leave_point.status`, and the proposed recents target are rendered as supplied. The UI never re-derives entry state or probes the vault.
- **Pull-only map.** The System map remains pull-based and never shown unbidden; the verb-line's "See the map" is an explicit `map.open`, the only opener on the surface.
- **No new authority surface.** The threshold is a renderer/router. It re-classifies nothing and owns no durable semantic truth.
