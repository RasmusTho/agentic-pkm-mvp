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

## Target architecture and SBS operationalization

1. `docs/PROJECT_KERNEL.md` and `docs/COGNITIVE_PROSTHESIS_CHARTER.md` — north star and product thesis.
2. `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` — target SBS decomposition.
3. `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` — adoption plan and source-of-truth matrix.
4. `docs/architecture/SBS_OPERATING_MODEL.md` — how the SBS and Builder System boundary are used operationally (Product/Builder/boundary classification, Builder Learning/TCD governance, DoR/DoD, owner-doc writeback, review-gate fallback).
5. `docs/architecture/SBS_ROADMAP.md` — initiative phases (0 architecture residency → 5 opportunistic physical separation).
6. `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md` — current-to-target owner mapping.
7. `docs/architecture/SBS_BOUNDARY_REGISTER.md` — boundary status.
8. `docs/architecture/SBS_FITNESS_RULES.md` — target architecture fitness rules.

## Current runtime architecture

1. `docs/ARCHITECTURE.md` — current runtime owner doc.
2. `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` — current system-of-systems spine.
3. `docs/STATUS.md` — current shipped/posture status.
4. `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` — target-state context only.

## Major architecture changes

1. `docs/architecture/SBS_OPERATING_MODEL.md` — classify the change as Product/Runtime System, Builder System, or boundary work, then check Builder Learning/TCD governance, Definition of Ready/Done, owner-doc writeback, and the review-gate fallback policy.
2. `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` — phase and source-of-truth routing.
3. Relevant contract stub in `docs/contracts/` — subsystem contract.
4. `docs/architecture/SBS_BOUNDARY_REGISTER.md` — boundary maturity and enforcement status.
5. `docs/architecture/SBS_TRANSITION_DEBT.md` — known deviations and containment.
6. `docs/architecture/SBS_FITNESS_RULES.md` — fitness and failure-mode checks.
7. Current runtime owner docs such as `docs/ARCHITECTURE.md`, `docs/STATUS.md`, and subsystem-specific docs.

## Agents and Codex doing SBS work

1. `docs/architecture/SBS_OPERATING_MODEL.md` — operational entry point: Product/Runtime System, Builder System, and boundary-work classification; Builder Learning/TCD governance; DoR/DoD; issue/PR lifecycle; owner-doc writeback; transition-debt and fitness lifecycles; review-gate fallback policy; source-of-truth matrix.
2. `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` — task routing and phase plan.
3. `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` — target SBS source.
4. `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md` — current-to-target owner mapping.
5. Relevant contract stubs in `docs/contracts/`.
6. `docs/architecture/SBS_FITNESS_RULES.md` — review/enforcement expectations.
7. `docs/architecture/SBS_TRANSITION_DEBT.md` — debt and follow-up routing.

## Builder System and repo-local workflows

1. `AGENTS.md` — canonical builder-agent policy and TCD/parallel execution rules.
2. `.codex/skills/README.md` — repo-local skill routing and BuilderOps routing checkpoints.
3. `docs/architecture/SBS_OPERATING_MODEL.md` — Builder System boundary and authority model; classify work as Product/Runtime System, Builder System, or boundary work; route Builder Learning/TCD signals to governed destinations.
4. `docs/development/AGENT_OPERATING_PROTOCOL.md` — pre-implementation task classification and stop conditions.
5. `docs/development/DEV_WORKFLOW.md` — issue-first delivery loop, validation expectations, and acceptance verifiability.
6. Relevant `.codex/skills/*/SKILL.md` — workflow-specific pickup, publication, verification, closure, or maintenance instructions.

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

## Changing retrieval / embeddings

1. `docs/RETRIEVAL.md` — owner doc for the live retrieval scoring and serving path (in-memory hybrid, weighted linear fusion, rerank-off).
2. `docs/adr/ADR-0024-retrieval-topology.md` — ratified retrieval topology and the durable-spine direction; RRF/HyDE/low-trust-weights as future work.
3. `docs/EMBEDDINGS.md` — normative embedding identity, the `Fallback rule`, and the `EMBED_DIM` guardrail.
4. `docs/adr/ADR-0023-embedding-egress-gemini-fallback.md` — Ollama-primary + identity-preserving Gemini fallback posture (supersedes the no-generic-fallback invariant as a scoped exception).
5. `docs/LLM_ROUTING.md` and `docs/LLM.md` — embedding routing/fabric contract and operational provider/setup, kept in sync with the embedding-identity change policy.

## Changing agent memory

1. `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md` — agent semantics and authority.
2. `docs/COGNITIVE_PROSTHESIS_CHARTER.md` §3 — the kinds-of-state distinctions.
3. `docs/AGENTS.md` (runtime-agent doc) and `docs/PANEL_AGENT.md` — current agent surfaces.
4. `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md` — receipt expectations.
5. `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` — agent-produced companion artifacts.

## Implementing context bundles

1. `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` — semantic contract and boundary.
2. `docs/CONTEXT_BUNDLES/README.md` — implementation breakdown and acceptance path.
3. `docs/CONTEXT_BUNDLES/PARENT_FEATURE_ISSUE.md` — local parent issue draft and execution order.
4. `docs/FINDING_AND_REORIENTING/README.md` plus retrieval/orientation/resurfacing capability contracts — downstream consumers.
5. `docs/COMPANION_UI_PRODUCT_SPEC.md` — product-mode expectations for find, reorient, resurface, and act.

## Implementing agent memory

1. `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` — semantic contract and boundary.
2. `docs/AGENT_MEMORY/README.md` — implementation breakdown and acceptance path.
3. `docs/AGENT_MEMORY/PARENT_FEATURE_ISSUE.md` — local parent issue draft and execution order.
4. `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md` and `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md` — authority and guardrails.
5. `docs/COMPANION_UI_PRODUCT_SPEC.md` and `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md` — recall, review, and explanation expectations.

## Changing companion UI

1. `docs/COMPANION_UI_PRODUCT_SPEC.md` — Companion UI product shell and mode model.
2. `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` — context-bundle contract used across modes.
3. `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` — memory/knowledge boundary and promotion posture.
4. `docs/INTERACTION_SURFACES_AND_AUTHORITY/NAME_THE_THREE_INTERACTION_SURFACES.md` — canonical authority surfaces (Panel, Chat, Automation).
5. `docs/FINDING_AND_REORIENTING/README.md` — find/orient/resurface capability boundary.

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

## Future docs-to-issue extraction for context bundles and agent memory

1. `docs/CONTEXT_BUNDLES/PARENT_FEATURE_ISSUE.md` and `docs/AGENT_MEMORY/PARENT_FEATURE_ISSUE.md` — local parent issue drafts to file first.
2. `docs/CONTEXT_BUNDLES/README.md` and `docs/AGENT_MEMORY/README.md` — capability acceptance and execution order.
3. Child task specs in `docs/CONTEXT_BUNDLES/` and `docs/AGENT_MEMORY/` — bounded issue sources with `Verify:` targets.
4. `.codex/skills/feature-breakdown/SKILL.md` — issue-creation policy and parent/child workflow.
5. `.codex/skills/docs-to-issue/SKILL.md` — later extraction once the parent issues are filed and the repo is ready to execute implementation slices.
