# AI-Assisted Development — Dev-Layer Policy (SoT v4.10)

This document governs how AI/code agents (e.g., Codex, local LLMs) operate **during development**. It does **not** define runtime agent behavior; see `docs/ARCHITECTURE.md`, `docs/AGENTS.md`, and related SoT docs for runtime rules.

## Scope
- Applies to development-time tooling: Codex prompts, local LLM helpers, code-gen scripts.
- Does not change the runtime behavior of PKM agents (Hugin, Reasoner, Promotion Agent, etc.).

## Sources of truth
- Architecture & flows: `docs/ARCHITECTURE.md`, `docs/HUMAN-FLOWS.md`, `docs/AGENTS.md`.
- Development workflow: `docs/DEV_WORKFLOW.md`.
- Testing and CI: `docs/TESTING.md`, `docs/CI.md`, `docs/eval.md`, `docs/guardrails.md`.
- Settings and SoT variants: `docs/STATUS.md`, `docs/ROADMAP.md`.

## Hard constraints
- Use documented layers: Stores/Outbox/Index abstractions are the IO boundary; avoid ad-hoc DB access in new code.
- Keep Core-6 semantics, zones, kinds, and events consistent with `docs/ARCHITECTURE.md` / `docs/EVENTS.md`; no new kinds/zones/events without updating the SoT.
- Respect existing agent patterns (Normalizer → Classifier → Chunker → Deduper → CitationChecker → Indexer → Reviewer → Promotion/Projector); do not bypass them in code changes.
- Separate dev prompts from runtime prompts; runtime agent prompts live with runtime docs, not in dev-layer guidance.

## Required tests (baseline)
- Run the fast test matrix for any non-trivial change: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"`.
- When touching retrieval/reasoning/ASK surfaces, also run: `pytest -q tests/api` and relevant evals noted in `docs/eval.md`.
- Keep lint/mypy in line with `docs/CI.md` guidance (ruff, mypy).

## Working with AI/code agents
- Read the relevant SoT docs **before** structural changes; if docs and code disagree, update the docs first or alongside the change.
- Prefer updating/adding tests before code changes; AI helpers should implement within those test constraints.
- Log significant SoT shifts in `docs/STATUS.md` or `docs/ROADMAP.md` when applicable.
- Treat AI outputs as drafts: verify against architecture, tests, and governance docs before merging.

## Patterns & references
- Follow examples in `docs/settings/sample-*`, `docs/AGENTS.md`, and existing agent flows when adding or modifying surfaces.
- Keep behavior deterministic in tests; rely on mocks/stubs where documented (see `docs/TESTING.md`).
