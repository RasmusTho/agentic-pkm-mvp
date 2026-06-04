---
name: Topology-Aware Zone Projection — Parent Feature Issue
description: Local source for the delivered parent feature/validation hub. Filed as GitHub Issue #1473 (relabelled from deferral record into parent hub).
type: parent-feature-issue
github_issue: 1473
state: closed — delivered via #1554/#1555 with owner-doc promotion PR #1567
---

# Parent feature issue: Topology-Aware Zone Projection

This is the local source for the delivered parent feature/validation hub. It was filed as **GitHub Issue #1473**, which was relabelled from a pure deferral record into the parent hub once its blocker #1488 (PR #1527) landed the topology authority decision. GitHub is the authoritative backlog and validation record; this file mirrors delivered intent.

## Context

#1473 deferred topology-aware cognitive-distance projection pending a topology authority/runtime model. That model landed via #1488 / PR #1527 in `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md`. The decision named the current zone source (active-vault frontmatter-preferred / path-derived), the required `source`/`authority_role`/`provenance`/`degradation` envelope for any topology-derived field, and kept a genuinely new topology source deferred. That is exactly enough to split #1473 into bounded children.

## Scope

Delivered a self-describing `zone` projection (envelope over the existing source) and surfaced its signals in the Vault Browser UI. No new topology source was added; that stays deferred.

## Implementation Tasks

Spec directory: `docs/TOPOLOGY_AWARE_ZONE_PROJECTION/`

1. `ZONE_PROJECTION_ENVELOPE.md` — backend/API envelope, delivered by #1554 / PR #1558.
2. `SURFACE_ZONE_SIGNALS_IN_BROWSER_UI.md` — UI surfacing, delivered by #1555 / PR #1561.

Execution order: `ZONE_PROJECTION_ENVELOPE -> SURFACE_ZONE_SIGNALS_IN_BROWSER_UI`.

## Verification Path

Each child merged with its own pre-merge tests (backend test module for the envelope; companion-ui test for the UI signal). Each PR is the task verification receipt.

## Validation / Acceptance Path

#1473 closed after the README capability-level acceptance was satisfied: API emits the envelope, UI distinguishes durable vs. path-derived zone, no new source/schema/semantic ranking was introduced, and no new ordering was added. Owner-doc promotion (claiming the envelope as supported) happened in PR #1567.

## Out of Scope

Configured topology registry / multi-vault / graph / semantic source (still deferred per #1488); `zone` schema changes; graph-primary browser UI.
