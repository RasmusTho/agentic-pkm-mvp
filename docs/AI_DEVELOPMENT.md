State: SoT v4.10 Reality-MVP (current core).
# AI-Assisted Development — Dev-Layer Policy (SoT v4.10)

This document governs how AI/code agents (e.g. Codex, local LLM helpers, code-gen scripts)
are allowed to interact with this repository during development.

It does not define the runtime behavior of PKM agents (Hugin, Reasoner, Promotion Agent, etc.).
Runtime rules live in `docs/ARCHITECTURE.md`, `docs/AGENTS.md`, and related SoT docs.

## Scope

- Applies to:
  - Codex / workspace LLMs in editors.
  - Local LLM helpers/tools that generate or refactor code, tests, or docs.
- Does not apply to:
  - Runtime calls made by the Agentic PKM system itself (ASK, Reasoner, PanelAgent, etc.).
  - How Hugin or other agents answer questions or transform notes at runtime.

## Sources of truth

When making non-trivial changes, conceptually read and respect:

- Architecture & flows:
  - `docs/ARCHITECTURE.md`
  - `docs/HUMAN-FLOWS.md`
  - `docs/AGENTS.md`
  - `docs/SYSTEM_YGGDRASIL_Modules_And_Flows.md`
- Development workflow:
  - `docs/DEV_WORKFLOW.md`
- Testing and CI:
  - `docs/TESTING.md`
  - `docs/CI.md`
  - `docs/eval.md`
  - `docs/guardrails.md`
- SoT variants and planning:
  - `docs/STATUS.md`
  - `docs/ROADMAP.md`

If code and docs disagree, prefer to update the docs (or clearly mark the delta) before
treating the new behavior as the SoT.

## Hard constraints

When generating or modifying code:

- Respect layers.
  - Use Stores/Outbox/Index abstractions for data access. Do not introduce new direct
    DB access paths; reuse existing DB helpers only where documented.
- Do not redesign Core-6.
  - Do not change the semantics of Core-6 fields (`uuid`, `title`, `origin`,
    `source_ref`, `trust`, `review_state`) without an explicit architecture update.
  - Core-6 is a semantic contract and may be implicit or derived; see `docs/CORE_CONTRACT.md`.
  - `kind` is a policy-routing field and does not define structure; `zone` is a derived overlay.
- Treat trust and review_state as guardrails.
  - Agents must not mutate reviewed content without explicit intent.
  - Writes must honor policy permissions defined in vault settings.
  - Behavior constraints must be read from vault settings, not guessed from note layout.
- Do not invent new global categories on the fly.
  - New zones, kinds, event names, or top-level settings must first be reflected in
    `docs/ARCHITECTURE.md` and/or `docs/EVENTS.md` / `docs/schema/*` before being used in code.
- Keep dependencies under control.
  - Do not add new external dependencies without updating `pyproject.toml` and, if relevant,
    `docs/DEPENDENCIES.md` / `docs/CI.md`.
- Keep tests deterministic.
  - In tests, use documented mocks, stubs, or deterministic providers (see `docs/TESTING.md`).
  - Avoid randomness and non-repeatable side effects.

## Required tests (baseline)

For any non-trivial change:

- Run the fast test matrix:

  ```bash
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"
  ```

- When touching retrieval, reasoning, or ASK surfaces:

  - Also run:

    ```bash
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/api
    ```

- And the relevant evals referenced in docs/eval.md (golden sets, guardrail metrics).

- Keep lint/mypy in line with CI:

  ```bash
  ruff check app tests
  mypy app
  ```

- (See docs/CI.md for the current CI stack.)

## Working with AI/code agents

- Read the relevant SoT docs before structural changes; if docs and code disagree,
  update the docs first or at least in the same change.
- Prefer updating or adding tests before implementation. AI helpers should implement
  code that makes those tests pass.
- Treat AI output as a draft:
  - Check it against architecture docs, tests, and guardrails.
  - Do not silently accept API shape, event names, or frontmatter changes that are not
    grounded in SoT docs.
- Log significant SoT shifts briefly in:
  - `docs/STATUS.md` (current reality)
  - or `docs/ROADMAP.md` (planned evolution).

- Eval tests live under `tests/eval/` and are marked `@pytest.mark.eval` (see `docs/eval.md` for commands and metrics).

## Patterns & references

When in doubt:

- Look at docs/settings/sample-* and `docs/AGENTS.md` for examples of agent and flow
  configuration.
- Follow existing agent patterns (PER-loop, Stores + Outbox, audit events) instead of
  inventing new ones.
- Keep behavior deterministic in tests; use the documented mocks/providers in docs/TESTING.md.
