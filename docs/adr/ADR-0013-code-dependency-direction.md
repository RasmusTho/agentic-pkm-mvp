State: Accepted and enforced (blocking). Flipped from advisory to blocking 2026-06-24 via #2481: all known violations cleared before flip, no allowlist required, contract exits 0 on every PR. Defines code import-dependency direction as a directional, contract-based projection of DESIGN_PRINCIPLES §3 system layers onto `app.*` packages. v1 enforces one invariant — the interaction layer is import-protected — via a module-level import-linter `forbidden` contract, run BLOCKING on PRs.
Doc role: Decision record (ADR)
Authority: Authoritative for code import-dependency direction; the governing rule for `importlinter.ini`.
Owner: Architecture
Temporal class: Durable decision (supersede via a new ADR, do not edit in place)
Review cadence: On change to the layer model or the enforced contract
Source of truth: This ADR (with `importlinter.ini` as the machine projection)

# ADR-0013: Code Dependency Direction

**Date:** 2026-06-16
**Status:** Accepted and enforced (blocking) — merged via #2070; enforcement posture flipped to blocking via #2481 (2026-06-24)

---

## Context

The repository's design docs govern two kinds of boundary, but not the third:

- `docs/DESIGN_PRINCIPLES.md` (Core SoT) governs **conceptual system layers** — interaction, cognition, execution, memory, governance (§3) — and interaction-first composition (§2A).
- `docs/CONCEPTS/LAYERING_MODEL.md` governs **data/artifact boundaries** — Domain, Plane, Trust, Zone.
- **No doc governs code import-dependency direction** between `app.*` packages.

Because of that gap, the only enforced code boundary was a single `importlinter.ini` contract — `app.api` must not import `app.agents`/`app.services` — that was:

1. **Ungrounded** — derived from no stated principle.
2. **Contradictory** — §2A says interaction surfaces compose foundational capabilities (retrieval, reasoning, execution); §3 says a layer may depend on an adjacent layer's contract. `app.api` *is* the interaction layer and `services`/`agents` are execution/cognition capabilities, so `api → services` is exactly what the principles prescribe. The rule inverted it.
3. **Dormant and silently broken** — the job that ran it (`.github/workflows/architecture-ci.yaml :: arch-imports`) is `workflow_dispatch`-only, so it never ran on PRs. It also ran bare `lint-imports`, which cannot auto-discover the non-standard filename `importlinter.ini` (import-linter looks for `.importlinter` / `setup.cfg` / `pyproject.toml`), so the step exited non-zero with "Could not read any configuration" whenever dispatched. The boundary was effectively unenforced.

The codebase itself is reasonably modular (~50 small, mostly-acyclic subsystems under `app/`). The complexity that prompted this decision was that the one mechanism meant to make module boundaries *legible* was dormant and wrong. This ADR supplies the missing principle so enforcement can descend from intent rather than from an orphan rule. Splitting the repository into multiple packages or repos was considered and rejected: for a single-developer, single-user product it imports multi-team coordination cost with no offsetting benefit.

## Decision

Code import dependencies are **directional and contract-based**, as a projection of the §3 system layers onto `app.*` packages.

1. **Forward-only.** A package may depend on packages in the same or a lower layer. It must not depend on a higher layer. Layer order, highest to lowest: `interaction → cognition → execution → memory`, with **governance** cross-cutting (depends downward) and a **foundation** (shared kernel) leaf any layer may import.
2. **Interaction is import-protected.** No package outside the interaction layer may import an interaction-layer package. This is the primary invariant and the only one enforced in v1: nothing reaches *backward* into a human/agent-facing surface.
3. **Depend on contracts, not internals.** Import another package through its public entrypoint, not a private submodule or underscore-prefixed symbol. Enforcement is **module-level** (import-linter catches cross-package imports of any submodule); symbol-level privacy (`_helper`) is a review convention on top.
4. **Foundation is exempt.** Shared-kernel packages (`events`, `settings`, `schemas`, `config`, and similar pure contract/util modules) may be imported by any layer and carry no inward restriction. They must stay leaf-like (no upward imports) so they remain safe to depend on everywhere.
5. **Enforcement posture.** The contract runs on every PR via `import-linter` (`.github/workflows/import-linter.yaml`), **blocking** (no `continue-on-error`). It gates merges: a new backward import from a non-interaction package into the interaction layer (`app.api`, `app.chat`, `app.cli`, `app.web`) will fail the job. Flipped from advisory to blocking in #2481 (2026-06-24) after all known violations were confirmed cleared — the contract ran clean (exit 0, 0 violations) on the first run after the flip. No `ignore_imports` allowlist was required.

## Layer model — §3 layers mapped to `app.*` packages

This map is the **seed**; package assignments may be refined, but the layer order and the five rules above are the decision.

| Layer | Role (DESIGN_PRINCIPLES §3) | Seed packages |
|---|---|---|
| **Interaction** (protected) | Human/agent-facing surfaces; carry authority of the request | `api`, `chat`, `cli`, `web` |
| **Cognition** | Derivation, understanding, retrieval, reasoning, projection | `agents`, `reasoning`, `retrieval`, `search`, `relevance`, `source_understanding`, `knowledge_compilation`, `planner`, `orientation`, `resurfacing`, `panel`, `context_bundles` |
| **Execution** | Orchestration and side-effecting capabilities | `orchestrator`, `dispatcher`, `services`, `a2a`, `watcher`, `ingest`, `sync`, `writeback`, `capture`, `tts`, `diarization`, `indexer` |
| **Memory** | Durable stores and knowledge persistence | `agent_memory`, `stores`, `store`, `index`, `db`, `knowledge`, `vault`, `objects`, `receipts`, `outbox` |
| **Governance** (cross-cutting) | Policy, authority, promotion, quality gates | `builderops`, `write_guard`, `promotion`, `release_channels`, `policy`, `guardrails`, `fitness`, `activation`, `quality`, `eval` |
| **Foundation** (shared leaf) | Pure contracts/utilities + tool providers importable by all | `events`, `settings`, `schemas`, `config`, `domain`, `ports`, `llm`, `observability`, `mcp` |

Rationale notes:
- **`panel` and `orientation` are cognition, not interaction** — they *derive* projections from artifacts. That is why `panel`'s import of `app.api` is a backward-direction violation, not legitimate forward use.
- **`mcp` is a tool-provider capability, not a protected surface.** `orchestrator.executor` imports `app.mcp.vault_tools` as a tool dependency, which is legitimate downward use. `mcp` is therefore in the foundation/capability tier, not the protected interaction set. (An earlier draft mis-placed it in interaction; the contract run surfaced the misclassification.)
- **Governance depends downward** (reads memory, wraps execution) but nothing depends upward on it for non-governance reasons; it is cross-cutting, not a strict tier.
- **Foundation must stay acyclic and upward-free.** The broad fan-out of `events` (~63 importers) and `settings` (~42 importers) is tolerable only because these are leaves; keeping them leaves is what makes them safe hubs.

## Enforcement reality (v1, updated to blocking in #2481)

- **One `forbidden` contract**, not a `layered` contract. A `layered` contract over package *groups* would forbid legitimate intra-layer imports (e.g. `orchestrator → services`, both execution) because import-linter treats sibling modules in a layer as mutually independent. The directional invariant that adds value without false positives is the single rule "nothing outside interaction imports interaction", expressed as `type = forbidden` (deeper packages → `app.api`/`chat`/`cli`/`web`). Fuller per-layer `layered`/`independence` contracts are a documented refinement, deferred.
- **Namespace packages converted (#2085).** All 15 `app/` subdirectories that were implicit namespace packages (no `__init__.py`) now have empty `__init__.py` files, including `app.orientation` and `app.reasoning`. They are now included in `source_modules` in `importlinter.ini` and their inward leaks are machine-enforced.
- **Contract flipped to blocking (#2481, 2026-06-24).** By the time this flip landed, all known violations had been resolved (helpers extracted to `app.text.helpers`, cycle broken). The contract runs clean with no `ignore_imports` allowlist. Any new backward import now fails the job.

## Known violations at adoption (all resolved before blocking flip)

The contract run at adoption reported these real backward/past-contract leaks.  All were resolved by the time the enforcement posture was flipped to blocking in #2481:

**Resolved — helper extraction to `app.text.helpers`:**
- `app.panel.checkbox_projection → app.api.routes.artifacts` — was cognition → interaction, private `_content_hash`. Migrated to `app.text.helpers.content_hash`.
- `app.orientation.leave_point_cursor → app.api.routes.artifacts` — private `_content_hash`, `_extract_title`. Migrated to `app.text.helpers`.
- `app.orientation.leave_point_cursor → app.chat.canvas_writer` — private `_split_frontmatter`. Migrated to `app.text.helpers`.

**Resolved — observability cycle broken:**
- `app.observability.status_service → app.cli.health` — documented "lazy to avoid circular import" cycle. Broken; the status service no longer imports interaction-layer modules.
- `app.resurfacing.runtime → app.observability.status_service → app.cli.health` — transitive consequence of the cycle above. Cleared when the cycle was broken.

**Not machine-enforced (intra-interaction, below module granularity — unchanged):**
- `app.api.routes.companion` / `app.api.routes.canvas → app.chat.canvas_writer` (private `_split_frontmatter` / `_body_contains_frontmatter`) — intra-interaction; module-level contract does not flag intra-layer. Tracked as a review convention.

## No `ignore_imports` allowlist

The blocking gate is clean. No `ignore_imports` section was added to `importlinter.ini` because all violations were resolved before the flip. If a future violation is temporarily allowlisted, it must be annotated with a FIX issue reference and a target resolution date.

## Consequences

- `api → services` / `api → agents` are legitimate forward dependencies; the orphan `forbidden` rule is removed.
- Module boundaries become legible and self-reporting on every PR without blocking delivery.
- The contract immediately surfaces genuine coupling (a backward reach + one cycle) that previously had no detector.
- Foundation packages acquire an explicit obligation to stay leaf-like (no upward imports), constraining how `events`/`settings` may grow.
- Coverage is partial: intra-interaction private reaches are not enforced (below module granularity). Namespace packages are now fully covered as of #2085. The inventory is the bridge for intra-interaction reaches.
- A future move to a **required** gate is a one-line branch-protection change once the known violations are cleared.
- This ADR does not move any code or split any package; package topology is unchanged.

## Out of scope

- Fixing the known violations or breaking the `observability ↔ cli.health` cycle (→ follow-up FIX issue).
- Making the 15 namespace packages regular (`__init__.py`) so the contract and mypy fully cover them (→ completed in #2085).
- ~~Making the import-linter check a required PR gate (deferred).~~ **Done** — flipped to blocking in #2481 (2026-06-24).
- A fuller `layered`/`independence` contract set across all layers.
- De-coupling or re-homing the `events` / `settings` hubs beyond documenting the leaf obligation.
- Any change under `companion-ui/`.
- Splitting subsystems into separate packages or repositories (rejected for a single-developer, single-user product).

## Validation

```bash
# Contract exists and protects the interaction layer:
rg -n "interaction-protected|app\.api|app\.chat" importlinter.ini

# Contract evaluates and reports the real leaks (expected exit 1 under non-blocking posture):
lint-imports --config importlinter.ini

# Backward-import cross-check matches the reported violations:
rg -n '^\s*from app\.(api|chat|cli|web)' app/ | rg -v '^app/(api|chat|cli|web)/'

# The PR gate runs non-blocking:
rg -n "pull_request|continue-on-error" .github/workflows/import-linter.yaml
```

## References

- #2070 - task: ground the import-linter gate in DESIGN_PRINCIPLES
- `docs/DESIGN_PRINCIPLES.md` §2A (Interaction-First Architecture), §3 (Separation of System Layers), §9 (System-of-Systems Thinking)
- `docs/CONCEPTS/LAYERING_MODEL.md` (data boundaries — distinct from this code boundary)
- `docs/architecture/IMPORT_BOUNDARY_INVENTORY.md` (full coupling inventory)
- `importlinter.ini`
- `.github/workflows/import-linter.yaml`, `.github/workflows/architecture-ci.yaml`
