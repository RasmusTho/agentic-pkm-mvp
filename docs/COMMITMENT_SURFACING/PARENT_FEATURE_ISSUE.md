---
name: Commitment Surfacing — Parent Feature Issue
description: Local source for the parent validation hub of the commitment-surfacing capability
parent_capability: Commitment Surfacing
github_issue: 1960
lifecycle_state: closed (completed 2026-06-18; delivered via child slices)
---

State: The parent feature issue for this capability, **GitHub Issue #1960**, closed as completed on 2026-06-18 after child slices #2073-#2075 delivered and the repo-verifiable acceptance evidence landed on `main`. This file is the local source mirror of that delivered hub; GitHub is authoritative.

# Commitment Surfacing — Parent Feature Issue (#1960)

## Parent hub

- **GitHub issue:** #1960
- **Role:** parent feature / validation hub for the COMMITMENT_SURFACING capability; closed as delivered after the child slices landed.
- **Labels at closure:** `type:feature`, `prio:med`, `area:companion-ui`, `panel`.
- **Project status:** `Done`.

## Capability intent

Surface active human commitments (next_action / waiting / review_return) to the human from a **durable** commitment source, preserving the commitment-layer semantics from `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`. Read/proposal-only; commitment transitions remain governed and receipt-bearing. The durable source is the vault, in the companion-note family — not a new DB, not transient `AgentState` (owner decision, #1960, 2026-06-15).

## Why a parent hub and not one issue

The commitment domain model ships, but there is no durable persistence/query path, no companion API field, and no UI render. Building the surface directly over the ephemeral per-request `AgentState` `CommitmentHandle`s would make the surface volatile and semantically misleading. The capability therefore spans three independently mergeable slices with a strict dependency chain (persist → expose → render) plus a post-merge architecture-guard flip. That is multi-slice work with a post-merge validation need — the feature-breakdown shape, not a single bounded issue.

## Acceptance criteria (capability level)

See `README.md :: Acceptance`. Hub #1960 closed after durable persistence, companion-route exposure, and UI render were green on merged heads and the xfail architecture guard flipped.

## Implementation tasks

See `README.md :: Implementation tasks` and the three task files in this directory. Execution order: PERSIST_COMMITMENTS_AS_VAULT_ARTEFACTS (#2073) → EXPOSE_COMMITMENTS_IN_COMPANION_ROUTE (#2074) → RENDER_COMMITMENTS_IN_PANEL_UI (#2075).

Child issues (filed 2026-06-15, now all closed/completed): **#2073** (slice 1), **#2074** (slice 2), **#2075** (slice 3).

## Verification path

See `README.md :: Verification path`.

## Validation / acceptance path

See `README.md :: Validation / Acceptance path`. Each child PR posted a validation receipt to #1960; the closure receipt recorded delivered implementation while noting owner-doc promotion as a follow-up after end-to-end operator validation.

## Lifecycle notes

- Reshaped into the parent hub on 2026-06-15 (this breakdown).
- Closed as completed on 2026-06-18 after slices #2073-#2075 delivered and the acceptance evidence was recorded on the hub.
