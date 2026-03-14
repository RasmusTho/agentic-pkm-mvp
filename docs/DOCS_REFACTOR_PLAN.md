State: Proposed docs refactor plan for the v5.5 baseline and v5.6 forward line.
# Documentation Refactor Plan

This document defines the step-by-step plan for simplifying the documentation set without losing current SoT coverage.

The goals are:
- reduce the number of documents treated as active decision inputs,
- separate current SoT from reference, planning, and historical material,
- remove duplicated guidance where multiple docs cover the same change workflow,
- make the reading order for humans and coding agents obvious.

## Validated findings

These findings were checked against the current documents before creating this plan:

- `docs/AI_DEVELOPMENT.md` and `docs/DEV_WORKFLOW.md` overlap substantially in change workflow, test expectations, and docs-first guidance.
- `docs/LLM.md` and `docs/LLM_BACKENDS.md` overlap substantially in provider, environment, and operational setup guidance.
- `docs/LLM_ROUTING.md` is distinct enough to keep as a routing/fabric contract rather than merge in the first pass.
- `docs/OBSERVABILITY.md` and `docs/OBSERVABILITY_STACK.md` are related but not duplicates: one is runtime observability contract and signals, the other is a local stack setup guide.
- `docs/OPERATIONS.md`, `docs/HEALTH.md`, and `docs/OPS_WATCHER.md` belong in one operational cluster, but they should not be blindly merged because they currently serve different scopes.
- `docs/AGENTS.md` and `docs/PANEL_AGENT.md` should remain separate, but their scope boundary must become explicit: system-level agent architecture vs PanelAgent-specific runtime contract.
- `docs/archive/architecture/SYSTEM_DESIGN_v4.10.md`, `docs/archive/architecture/SYSTEM_YGGDRASIL_Modules_And_Flows.md`, `docs/archive/architecture/SYSTEM_OVERVIEW.md`, and `docs/archive/architecture/DIAGRAMS.md` are historical/reference artifacts and should not sit in the active reading path.

## Target document roles

Every active document should be classified into exactly one role:

- `Core SoT`: normative current truth for runtime behavior and decisions
- `Reference`: supporting detail, contracts, or operator/developer reference
- `Plan`: forward-looking work and staged rollout notes
- `Historical`: archived or superseded material kept only for context

## Proposed active core

The long-term active reading set should be reduced to:

- `docs/STATUS.md`
- `docs/ARCHITECTURE.md`
- `docs/HUMAN-FLOWS.md`
- `docs/COMPONENTS.md`
- `docs/EVENTS.md`
- `docs/TESTING.md`
- `docs/OPERATIONS.md`
- `docs/DOCS_INDEX.md`

These are the documents that should remain first-class inputs for new work.

## Execution phases

### Progress snapshot

- Phase 1 completed on this branch: authority model, index role guidance, and entrypoint cleanup landed in `docs/DOCS_INDEX.md`, `README.md`, and `.codex/AGENTS.md`.
- Phase 2 completed on this branch: `docs/DEV_WORKFLOW.md` is now the primary dev workflow doc; the obsolete `docs/AI_DEVELOPMENT.md` redirect has been removed.
- Phase 3 completed on this branch: `docs/LLM.md` is now the operational LLM doc; the obsolete `docs/LLM_BACKENDS.md` redirect has been removed; `docs/LLM_ROUTING.md` remains separate.
- Phase 4 completed on this branch: `docs/OPERATIONS.md` is the operational entrypoint; `docs/OBSERVABILITY.md` and `docs/HEALTH.md` remain explicit companions, and the obsolete `docs/OBSERVABILITY_STACK.md` / `docs/OPS_WATCHER.md` redirects have been removed.
- Phase 5 completed on this branch: `docs/AGENTS.md` and `docs/PANEL_AGENT.md` now have a clearer system-vs-component split.
- Phase 6 partially completed on this branch: start surfaces and historical docs now carry stronger historical-only warnings, but no file moves have been done.
- Phase 7 partially completed on this branch: `docs/DOCS_INDEX.md` has been deduplicated and development docs now include rules for doc creation and classification.

### Phase 1: Authority model and classification

Goals:
- define document roles,
- classify current docs against those roles,
- reduce ambiguity in start surfaces.

Steps:
1. Add role-based guidance to `docs/DOCS_INDEX.md`.
2. Mark the intended active core explicitly.
3. Ensure `README.md`, `.codex/AGENTS.md`, and dev guidance point to the active core instead of the larger current doc surface.
4. Add a standard metadata pattern for future docs:
   - `State:`
   - `Doc role:`
   - `Authority:`
   - `Last reviewed:`

Deliverable:
- a clear authority model reflected in index and entrypoints.

### Phase 2: Consolidate development guidance

Goals:
- remove duplicate instructions for code changes,
- keep one primary dev workflow doc.

Steps:
1. Merge overlapping material from `docs/AI_DEVELOPMENT.md` and `docs/DEV_WORKFLOW.md`.
2. Keep one primary developer guidance document and reduce the other to either:
   - a short companion page, or
   - a redirect/deprecation stub.
3. Update `.codex/AGENTS.md` and any linked references accordingly.

Deliverable:
- one authoritative doc for how changes should be made in the repo.

### Phase 3: Consolidate LLM docs

Goals:
- remove duplicate provider/env documentation,
- preserve routing contract separately.

Steps:
1. Merge `docs/LLM.md` and `docs/LLM_BACKENDS.md`.
2. Keep `docs/LLM_ROUTING.md` separate as the routing/fabric contract.
3. Update index and cross-links so readers know:
   - where general LLM setup lives,
   - where routing policy lives,
   - where embedding identity rules live (`docs/EMBEDDINGS.md`).

Deliverable:
- one operational LLM doc plus one routing contract doc.

### Phase 4: Rationalize ops and observability surfaces

Goals:
- make the ops surface easier to navigate,
- preserve distinct operational contracts where needed.

Steps:
1. Keep `docs/OBSERVABILITY.md` as the runtime observability contract.
2. Keep `docs/OBSERVABILITY_STACK.md` as local stack/how-to guidance, but label it clearly as setup/reference.
3. Keep `docs/HEALTH.md` as the health contract and CLI behavior document.
4. Keep `docs/OPS_WATCHER.md` as watcher-specific operational guidance.
5. Update `docs/OPERATIONS.md` to be the top-level operational playbook that links to those narrower docs instead of partially duplicating them.

Deliverable:
- one clear operational entrypoint with specialized child docs.

### Phase 5: Tighten agent doc boundaries

Goals:
- avoid duplication between system-level agent architecture and component-specific detail.

Steps:
1. Keep `docs/AGENTS.md` focused on system-level agent patterns, agent matrix, and coordination architecture.
2. Keep `docs/PANEL_AGENT.md` focused on PanelAgent-specific behavior, syntax, events, and runtime contract.
3. Remove any duplicated explanation that belongs in only one of those documents.

Deliverable:
- explicit separation between architecture-level and component-level agent docs.

### Phase 6: Move historical docs out of the active reading path

Goals:
- stop old material from appearing current,
- keep history accessible but clearly secondary.

Priority historical/reference candidates:
- `docs/archive/architecture/SYSTEM_DESIGN_v4.10.md`
- `docs/archive/architecture/SYSTEM_YGGDRASIL_Modules_And_Flows.md`
- `docs/archive/architecture/SYSTEM_OVERVIEW.md`
- `docs/archive/architecture/DIAGRAMS.md`
- selected `docs/archive/*` and `docs/legacy/*`

Steps:
1. Ensure index and start surfaces label these as historical.
2. Prefer linking them from historical sections rather than active SoT sections.
3. Move or stub them later only if needed for cleaner navigation.

Deliverable:
- historical docs remain available but stop polluting the active decision surface.

### Phase 7: Final cleanup and enforcement

Goals:
- prevent the same drift from returning.

Steps:
1. Normalize headers and role metadata on active docs.
2. Update `docs/CONTRIBUTING.md` or the surviving dev workflow doc with rules for when a new doc is allowed.
3. Review `docs/DOCS_INDEX.md` for duplicate rows and stale classifications.
4. Update `README.md` docs links to reflect the final core set and reading order.

Deliverable:
- a simpler and self-maintaining docs system.

## Initial file actions

These are the first concrete actions to take after this plan lands:

- `keep as core`: `docs/STATUS.md`, `docs/ARCHITECTURE.md`, `docs/HUMAN-FLOWS.md`, `docs/COMPONENTS.md`, `docs/EVENTS.md`, `docs/TESTING.md`, `docs/OPERATIONS.md`, `docs/DOCS_INDEX.md`
- `merge candidate`: `docs/AI_DEVELOPMENT.md` into the surviving dev workflow surface
- `merge candidate`: `docs/DEV_WORKFLOW.md` into the surviving dev workflow surface
- `merge candidate`: `docs/LLM.md` and `docs/LLM_BACKENDS.md`
- `keep separate, re-scope`: `docs/LLM_ROUTING.md`
- `keep separate, re-scope`: `docs/AGENTS.md`
- `keep separate, re-scope`: `docs/PANEL_AGENT.md`
- `keep separate, re-scope`: `docs/OBSERVABILITY.md`, `docs/OBSERVABILITY_STACK.md`, `docs/HEALTH.md`, `docs/OPS_WATCHER.md`
- `historical path`: `docs/archive/architecture/SYSTEM_DESIGN_v4.10.md`, `docs/archive/architecture/SYSTEM_YGGDRASIL_Modules_And_Flows.md`, `docs/archive/architecture/SYSTEM_OVERVIEW.md`, `docs/archive/architecture/DIAGRAMS.md`

## Non-goals for the first pass

- changing runtime behavior,
- rewriting technical content that is already correct but merely verbose,
- restructuring every subdirectory in one step,
- deleting historical documents without first preserving references.
