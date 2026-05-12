State: SoT v5.5 baseline; v6 active planning direction. Navigation document; not a current-state architecture claim.
Doc role: Reference
Authority: Practical reading paths for common tasks in this repository. Use it to choose what to read before touching a given area. Owner docs win on contract content.
Owner: Docs / kernel
Temporal class: timeless
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-05-12
Last verified against: docs/DOCS_INDEX.md, docs/PROJECT_KERNEL.md, docs/HUMAN-FLOWS.md, docs/ARCHITECTURE.md

# Reading Paths

> Audience: any contributor or agent about to change something in this repo and needing to know which docs to read first.

This document is a practical index. It does not replace `docs/DOCS_INDEX.md` (which is the
canonical map of doc roles). Use this when you know what kind of change you are making but
don't yet know which docs are load-bearing for it.

For every path: read the listed docs in order. The first doc in each path is the one that
defines intent; later docs add detail.

## Understanding the product purpose

1. `docs/COGNITIVE_PROSTHESIS_CHARTER.md` — product thesis.
2. `docs/PROJECT_KERNEL.md` — long-lived stability contracts.
3. `docs/HUMAN-FLOWS.md` — human-facing functions the system must support.
4. `docs/CONCEPTS/USER_NEEDS_MODEL.md` — canonical human needs.
5. `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md` — second-brain ontology.

## Changing human flows

1. `docs/HUMAN-FLOWS.md` — owner doc.
2. `docs/COGNITIVE_PROSTHESIS_CHARTER.md` — keep the change compatible with product thesis.
3. `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md` — verify the runtime side of the flow.
4. `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md` and `docs/CONCEPTS/USER_NEEDS_MODEL.md` — ontology fit.
5. `docs/STATUS.md` — what is actually shipped for the flow today.

## Changing runtime architecture

1. `docs/ARCHITECTURE.md` — owner doc.
2. `docs/PROJECT_KERNEL.md` — stability contracts the change must respect.
3. `docs/COMPONENTS.md`, `docs/EVENTS.md`, `docs/CONCURRENCY.md`, `docs/OBSERVABILITY.md` — supporting reference.
4. `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md` and `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md` — mirror/projection invariants.
5. `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md` — verify which human flow the change affects.

## Changing agent memory

1. `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md` — agent semantics and authority.
2. `docs/COGNITIVE_PROSTHESIS_CHARTER.md` §3 — the kinds-of-state distinctions.
3. `docs/AGENTS.md` (runtime-agent doc) and `docs/PANEL_AGENT.md` — current agent surfaces.
4. `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md` — receipt expectations.
5. `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` — agent-produced companion artifacts.

## Changing companion UI

1. `docs/CANVAS_CHAT_SURFACE/README.md` — canvas/chat surface design.
2. `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md` — authority boundaries between Chat, Panel, and Canvas.
3. `docs/HUMAN-FLOWS.md` — flows the surface serves.
4. `companion-ui/` source and design handoffs — current implementation surface.
5. `docs/STATUS.md` — what has shipped.

## Changing vault topology / persistence surfaces

1. `docs/SEPARATING_PERSISTENCE_SURFACES/README.md` — persistence-surface separation.
2. `docs/CONCEPTS/ARCHIVE_BRAIN_CONTRACT.md` and `docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md` — retention surface contracts.
3. `docs/CONCEPTS/CATALOG_PROJECTION_PRINCIPLES.md` and `docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md` — path/catalog discipline.
4. `docs/FRONTMATTER.md` — artifact frontmatter contract.
5. `docs/CONCEPTS/PORTABILITY_CONTRACT.md` — cross-platform constraints.

## Changing governance / writeback

1. `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md` — authority boundaries.
2. `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md` — delegation and receipts.
3. `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md` — ASSERT / SUGGEST / APPLY.
4. `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md` — event/intent envelope discipline.
5. `docs/EVENTS.md` and `docs/OBSERVABILITY.md` — current event surface and observability.

## Creating issues from docs

1. `.codex/skills/docs-to-issue/SKILL.md` — the canonical extraction skill.
2. `.codex/skills/feature-breakdown/SKILL.md` — when the source is a docs-defined capability that needs decomposition.
3. `docs/DOCS_INDEX.md` — confirm the source doc is an active spec surface, not a historical or planning-only doc.
4. `docs/development/DEV_WORKFLOW.md` — the working loop and validation expectations.
5. `.github/ISSUE_TEMPLATE/*.yml` and `.github/pull_request_template.md` — the contract any extracted issue must satisfy.
