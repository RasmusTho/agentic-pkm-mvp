State: SoT v5.5 Reality-MVP baseline locked (watcher/panel safety + concurrency guardrails). This is the primary development workflow and dev-layer AI policy document.
# Developer Workflow

This document describes how to work on the Agentic PKM / Yggdrasil codebase.

It is the primary guide for:
- the order of operations for non-trivial changes,
- dev-layer AI/code-agent rules,
- required tests and eval expectations,
- how to keep code, tests, and SoT documents aligned.

It does not define runtime agent behavior. Runtime rules live in `docs/ARCHITECTURE.md`, `docs/AGENTS.md`, `docs/HUMAN-FLOWS.md`, and related SoT docs.

## Development agents vs system agents

This document and `.codex/AGENTS.md` govern development-time contributors, coding agents, and repo
automation.

`docs/AGENTS.md` and `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md` govern system agents that exist
inside the PKM runtime.

Do not read runtime/system-agent semantics as instructions for development-time agents.
Do not read dev-layer contributor instructions as if they described runtime agent authority or
behavior.

## Scope

- Applies to:
  - humans making code, test, or documentation changes,
  - AI/code agents operating during development,
  - local tools that generate or refactor implementation artifacts.
- Does not apply to:
  - runtime ASK/PanelAgent/Planner behavior,
  - production-time agent decisions,
  - user-facing runtime contracts except where changes must be reflected back into SoT docs.

## Sources of truth

When making non-trivial changes, read and respect these documents in order:

1. Core SoT:
   - `docs/STATUS.md`
   - `docs/ARCHITECTURE.md`
   - `docs/HUMAN-FLOWS.md`
   - `docs/COMPONENTS.md`
   - `docs/EVENTS.md`
   - `docs/TESTING.md`
   - `docs/OPERATIONS.md`
   - `docs/DOCS_INDEX.md`
2. Current reference and development guidance:
   - `docs/plans/ONTOLOGY_EXECUTION_COORDINATION.md`
   - `docs/AGENTS.md` (runtime/system-agent architecture, not dev instructions)
   - `docs/PANEL_AGENT.md`
   - `docs/TESTING.md`
   - `docs/eval.md`
   - `docs/guardrails.md`
   - `docs/OBSERVABILITY.md`
   - `docs/HEALTH.md`
3. Supporting domain chapters and specialized contracts:
   - `docs/CORE_CONTRACT.md`
   - `docs/DATA_MODEL.md`
   - `docs/FRONTMATTER.md`
   - `docs/NOTE_KIND_POLICIES.md`
   - `docs/contracts/OBSIDIAN_KNOWLEDGE_PORT.md`
4. Historical orientation only:
   - `docs/archive/architecture/SYSTEM_YGGDRASIL_Modules_And_Flows.md`
   - `docs/archive/architecture/SYSTEM_DESIGN_v4.10.md`
   - `docs/history/*`
   - `docs/archive/*`

If code and docs disagree, update the docs first or in the same change. Do not silently treat undocumented behavior as the new SoT.

Use `docs/DOCS_INDEX.md` to determine whether a document is Core SoT, Reference, Plan, or Historical before treating it as a decision input.

For semantics-adjacent work touching context, artifact meaning, archive exposure, commitments,
paths/layout semantics, architecture boundaries, or agent authority/accountability, also treat
`docs/plans/ONTOLOGY_EXECUTION_COORDINATION.md` as required reading.

## Development loop

For any non-trivial change:

1. **Update SoT/docs when behavior changes**
    - If the change alters runtime behavior, flows, or contracts:
        - Update (or at least annotate) the relevant docs first:
            - docs/ARCHITECTURE.md
            - docs/HUMAN-FLOWS.md
            - docs/AGENTS.md
            - docs/EVENTS.md, docs/DATA_MODEL.md, etc.
    - The docs should remain descriptive of reality. If code and docs disagree, either:
        - fix the docs, or
        - clearly mark that the code is ahead of the docs.

2. **Add or adjust tests before coding**
    - Follow docs/TESTING.md for which layers to exercise:
        - Unit tests for pure functions and small components.
        - Contract tests for .done events, Store behavior, and API contracts.
        - E2E/eval tests for whole flows (ingest, ASK, promotion).
    - Express the intended change in tests before or alongside implementation.

3. **Implement within the documented architecture**
    - Respect the layering:
        - Use Stores/Outbox/Index abstractions; no new ad-hoc DB access paths.
        - Keep agents server-agnostic; API stays as a thin HTTP surface.
    - Reuse patterns from docs/AGENTS.md and docs/settings/sample-* where applicable.

4. **Run tests and evals**
    - Minimum for non-trivial changes:

      ```bash
      PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"
      ```

    - For changes touching retrieval/reasoning/ASK or external surfaces:
        - run relevant API tests (e.g. tests/api) and eval suites described in docs/eval.md.

5. **Reflect progress in SoT**
    - When the SoT has actually shifted (architecture stabilized, new agent flow in production):
        - update docs/STATUS.md with current reality, and
        - adjust docs/ROADMAP.md if future milestones change.

## Hard constraints

- AI/code agents are accelerators, not architects.
  - SoT docs define what is allowed.
  - Tests and evals define what is acceptable.
- Respect layering.
  - Use Stores/Outbox/Index abstractions.
  - Do not introduce new ad-hoc DB access paths.
  - Keep agents server-agnostic; API remains a thin HTTP surface.
- Do not redesign Core-6 casually.
  - Do not change the semantics of `uuid`, `title`, `origin`, `source_ref`, `trust`, or `review_state` without an explicit SoT update.
  - `kind` remains a policy-routing field, not a schema.
  - `zone` remains a derived overlay.
- Treat trust and review state as guardrails.
  - Do not mutate reviewed content without explicit intent.
  - Read write permissions and behavior constraints from settings/policy, not from note layout guesses.
- Do not invent new global categories on the fly.
  - New zones, kinds, event names, or top-level settings must be reflected in `docs/ARCHITECTURE.md`, `docs/EVENTS.md`, or relevant schema docs before code relies on them.
- Keep dependencies controlled.
  - Do not add new external dependencies without updating `pyproject.toml` and, where relevant, `docs/DEPENDENCIES.md` and `docs/TESTING.md`.
- Keep tests deterministic.
  - Use documented mocks/stubs/providers.
  - Avoid non-repeatable side effects in tests unless the test explicitly covers them.
- Keep runtime prompts and behavior separate from dev prompts.
  - Runtime rules live in runtime SoT docs and settings.
  - Dev-layer prompts live in `.codex/AGENTS.md`.

## Required tests

For any non-trivial change:

- Run the fast test matrix:

  ```bash
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"
  ```

- When touching retrieval, reasoning, ASK, or external surfaces:
  - run relevant API tests (for example `pytest -q tests/api`)
  - run the relevant eval suites in `docs/eval.md`

- Keep lint and type checks aligned with CI:

  ```bash
  ruff check app tests
  mypy app
  ```

Eval tests live under `tests/eval/`, are marked `@pytest.mark.eval`, and remain opt-in unless a workflow explicitly enables them.

## Local setup

Suggested bootstrap:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
if [ -f pyproject.toml ]; then pip install -e ".[dev]"; fi
```

Expected local toolchain:
- Python: see `docs/DEPENDENCIES.md` for the supported floor and compatibility policy
- `venv` + `pip`
- Docker and Docker Compose for full runtime paths
- Postgres for DB outbox + store backed runtime mode
- Optional: Ollama for local LLM-backed flows

## Branch strategy

- `main` -> stable SoT
- `feature/*` or `codex/*` -> short-lived, scoped branches
- Keep branches focused on one coherent change (feature, refactor, or SoT-step)

## Documentation rules

- Treat the active core set as the default reading path:
  - `docs/STATUS.md`
  - `docs/ARCHITECTURE.md`
  - `docs/HUMAN-FLOWS.md`
  - `docs/COMPONENTS.md`
  - `docs/EVENTS.md`
  - `docs/TESTING.md`
  - `docs/OPERATIONS.md`
  - `docs/DOCS_INDEX.md`
- For any documentation or specification task, use this reading order:
  - `docs/DOCS_INDEX.md` to identify document role and owner
  - the owning `Core SoT` doc
  - adjacent `Core SoT` docs that define neighboring boundaries
  - current `Reference` docs for implementation or operational detail
  - `Plan` and `Historical` docs only for context, never as current truth
- Do not create a new top-level doc if the content fits an existing core or reference doc.
- If you add a new doc:
  - start from `docs/templates/DOC_TEMPLATE.md`,
  - add it to `docs/DOCS_INDEX.md`,
  - classify it clearly as Core SoT, Reference, Plan, or Historical,
  - link it from the owning parent doc if it is meant to be read.
- Historical or planned docs must not be presented as current runtime truth.
- If a doc becomes a redirect or compatibility alias, say so explicitly at the top of the file and in `docs/DOCS_INDEX.md`.
- When writing specification documents in a complex area:
  - read the surrounding Core SoT docs first,
  - identify which document owns the final decision,
  - keep invariants, boundaries, and decision rules explicit,
  - avoid duplicating implementation detail that belongs in reference docs.

## Documentation update procedure

Use this procedure whenever behavior, policy, or document structure changes:

1. Identify the topic owner
   - Use `docs/DOCS_INDEX.md` to find the owning document and its role.
   - Do not start in a summary doc just because it is shorter.

2. Update the owner first
   - If the change affects current truth, edit the owning `Core SoT` doc first or in the same commit.
   - If the change is operational or explanatory only, update the owning `Reference` doc.

3. Propagate only where needed
   - Update neighboring docs only if they are part of the intended reading path.
   - Prefer links and short boundary notes over repeated prose.

4. Remove duplication created by the change
   - If two docs now overlap, merge the content into the owner and tighten or remove the secondary doc.
   - Do not leave multiple near-authoritative descriptions of the same behavior.

5. Update the map
   - Update `docs/DOCS_INDEX.md` whenever a doc is added, merged, deleted, archived, deprecated, or re-scoped.

6. Choose the smallest durable document shape
   - Prefer extending an existing owner doc over creating a sibling doc.
   - Create a new doc only when the topic has a distinct owner, audience, and maintenance boundary.

## Anti-dilution rules

- One topic should have one owner document.
- Core rules and invariants must live where they are owned.
- Indexes, summaries, runbooks, and examples must not become hidden specification layers.
- Reference docs may explain how the system works, but they must not quietly overrule `Core SoT`.
- Plan docs must separate future intent from current reality.
- Historical docs must never be used as justification for current behavior without a current owner doc adopting the rule.

## Review checklist

- Tests pass locally for the slice you changed
- New or changed events are reflected in `docs/EVENTS.md`
- Agent input/output contract changes are reflected in `docs/AGENTS.md` or the owning agent spec
- `docs/DOCS_INDEX.md` is updated if docs were added, merged, deprecated, archived, or re-scoped

## Coding discipline

- **Deterministic**: no unseeded randomness in logic or tests.
- **Explicit**: every state-changing action must be observable in logs/events.
- **Transparent**: logs consistently include agent, action, trace_id where applicable.
- **Modular**: agents and services should be replaceable behind clear interfaces.

## Debugging (local)

Examples:

```
tail -n 50 /tmp/agent.log
docker compose logs -f api
```

Add more detailed troubleshooting steps in docs/runbooks/* as the system evolves.
