State: SoT v5.5 Reality-MVP baseline locked (watcher/panel safety + concurrency guardrails).
# **Developer Workflow — SoT v5.5**

This document describes how to work _on the codebase_ for the Agentic PKM / Yggdrasil
system. It complements docs/ARCHITECTURE.md (runtime design) and docs/AI_DEVELOPMENT.md
(dev-layer AI policy).

## **Development loop (order of operations)**

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

## **AI-assisted development**

- AI/code agents are **accelerators**, not architects.
    - Architecture and SoT docs define _what is allowed_.
    - Tests and evals define _what is acceptable_.
- Follow docs/AI_DEVELOPMENT.md for:
    - scope (dev-time only),
    - constraints (layers, Core-6, events),
    - required test commands.
- Eval tests live under `tests/eval/`, are marked `@pytest.mark.eval`, and remain opt-in (see `docs/eval.md`).
- Keep runtime prompts/behavior separate from dev prompts:
    - runtime rules live in docs/ARCHITECTURE.md, docs/AGENTS.md, and settings,
    - dev-layer prompts live in .codex/AGENTS.md.

## **Branch strategy**

- main → stable SoT.
- feature/* → short-lived, scoped branches.
- Keep branches focused on one coherent change (feature, refactor, or SoT-step).

## **Coding discipline**

- **Deterministic**: no unseeded randomness in logic or tests.
- **Explicit**: every state-changing action must be observable in logs/events.
- **Transparent**: logs consistently include agent, action, trace_id where applicable.
- **Modular**: agents and services should be replaceable behind clear interfaces.

## **Debugging (local)**

Examples:

```
tail -n 50 /tmp/agent.log
docker compose logs -f api
```

Add more detailed troubleshooting steps in docs/runbooks/* as the system evolves.
