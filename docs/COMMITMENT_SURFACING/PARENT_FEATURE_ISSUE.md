---
name: Commitment Surfacing — Parent Feature Issue
description: Local source for the parent validation hub of the commitment-surfacing capability
parent_capability: Commitment Surfacing
github_issue: 1960
lifecycle_state: open (validation hub, agent:blocked)
---

State: The parent feature issue for this capability is **live on GitHub as Issue #1960** (open). #1960 pre-existed this breakdown as a `type:feature` issue and was reshaped — not replaced — into the parent validation hub for the COMMITMENT_SURFACING capability per the owner decision recorded on it (2026-06-15). This file is the local source mirror of that hub; GitHub is authoritative.

# Commitment Surfacing — Parent Feature Issue (#1960)

## Live parent hub

- **GitHub issue:** #1960
- **Role:** parent feature / validation hub for the COMMITMENT_SURFACING capability. It is **not** a direct pickup issue while child slices are outstanding.
- **Labels:** `type:feature`, `agent:blocked`, `prio:med`, `area:companion-ui`, `panel`.
- **Project status:** `Backlog` (validation hub posture; child slices carry the active pickup state).

## Capability intent

Surface active human commitments (next_action / waiting / review_return) to the human from a **durable** commitment source, preserving the commitment-layer semantics from `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`. Read/proposal-only; commitment transitions remain governed and receipt-bearing. The durable source is the vault, in the companion-note family — not a new DB, not transient `AgentState` (owner decision, #1960, 2026-06-15).

## Why a parent hub and not one issue

The commitment domain model ships, but there is no durable persistence/query path, no companion API field, and no UI render. Building the surface directly over the ephemeral per-request `AgentState` `CommitmentHandle`s would make the surface volatile and semantically misleading. The capability therefore spans three independently mergeable slices with a strict dependency chain (persist → expose → render) plus a post-merge architecture-guard flip. That is multi-slice work with a post-merge validation need — the feature-breakdown shape, not a single bounded issue.

## Acceptance criteria (capability level)

See `README.md :: Acceptance`. The capability is accepted (and #1960 closes) when durable persistence, companion-route exposure, and UI render are all green on merged heads and the xfail architecture guard flips.

## Implementation tasks

See `README.md :: Implementation tasks` and the three task files in this directory. Execution order: PERSIST_COMMITMENTS_AS_VAULT_ARTEFACTS (#2073) → EXPOSE_COMMITMENTS_IN_COMPANION_ROUTE (#2074) → RENDER_COMMITMENTS_IN_PANEL_UI (#2075).

Child issues (filed 2026-06-15): **#2073** (slice 1, `Ready`/`agent:ready`), **#2074** (slice 2, `agent:blocked`), **#2075** (slice 3, `agent:blocked`).

## Verification path

See `README.md :: Verification path`.

## Validation / acceptance path

See `README.md :: Validation / Acceptance path`. Each child PR posts a validation receipt to #1960; owner-doc promotion is decided only after end-to-end operator validation.

## Lifecycle notes

- Reshaped into the parent hub on 2026-06-15 (this breakdown).
- When #1960 closes after acceptance, update this file's `lifecycle_state` and the `README.md` `State:` line + acceptance checklist together so neither continues to read as an active pre-delivery lane.
