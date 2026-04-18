State: Proposed (under evaluation).

# ADR-0006: DeepAgents as Outer Agent Harness

**Date:** 2026-03-25
**Status:** Proposed — evaluation memo; decision pending pilot

---

## Context

The repo currently uses:
- **LangGraph** (locked in requirements at `langgraph==0.6.10`) for per-agent decision graphs — 13 agents already have `graph.py` files following the custom `PERSpec` (Plan → Act → Reflect → Emit) pattern from `app/agents/base/graph.py`
- **Orchestrator V1** (`app/orchestrator/runtime.py`) — a custom deterministic sequential executor using the `PlanExecutor` protocol with `MockPlanExecutor` for CI
- **Planner** (`app/planner/`) — LLM-backed plan generation producing `Plan` objects with typed steps

The v5.6 forward line planned **Orchestrator V2** (LangGraph-based, parallel execution, checkpointing, compensation/rollback) as the replacement for Orchestrator V1. However, before committing to building Orchestrator V2, it is worth evaluating whether **LangChain DeepAgents** could serve as the outer orchestration harness instead, given:
1. It is purpose-built for multi-agent coordination above LangGraph
2. It removes the need to build Orchestrator V2 from scratch
3. Its filesystem and planning tools overlap directly with existing vault tool patterns
4. Building Orchestrator V2 before evaluating DeepAgents risks building toward the wrong substrate

---

## What DeepAgents is

LangChain DeepAgents (`pip install deepagents`) is a higher-level agent harness built on LangChain core + LangGraph runtime. Its primary features:

- **`create_deep_agent(model, tools, system_prompt)`** — main entrypoint; returns a compiled LangGraph runnable
- **`write_todos` built-in tool** — structured task decomposition and progress tracking (replaces manual PER planning phase)
- **Filesystem tools built-in** — `write_file`, `read_file`, `ls`, `edit_file` with pluggable backends: in-memory, local disk, LangGraph Memory Store (cross-thread), sandbox environments (Modal, Daytona, Deno)
- **`task` tool** — spawns specialized subagents with context isolation while maintaining clean outer orchestration
- **LangGraph Memory Store** — cross-thread persistence

Default model: `anthropic:claude-sonnet-4-6`. Other providers supported via model string (OpenAI, Google, etc.).

---

## How DeepAgents maps to this repo's architecture

| This repo (current) | DeepAgents equivalent |
|---|---|
| Orchestrator V1/V2 (custom) | `create_deep_agent()` outer harness |
| PERSpec inner graphs (13 agents) | DeepAgents subagents via `task` tool |
| `app/mcp/vault_tools.py` (`append_note`, `get_vault_root`) | DeepAgents filesystem backend (vault as virtual FS) |
| `ReasoningFacade` (planned v5.6 blocker) | DeepAgents' tool-calling loop (built-in) |
| `write_todos` equivalent (absent today) | DeepAgents `write_todos` built-in |
| `MockPlanExecutor` for CI | DeepAgents in-memory filesystem backend |

---

## Evaluation criteria

### 1. LLM provider compatibility — CONDITIONAL PASS

DeepAgents supports multiple providers via model string (`anthropic:...`, `openai:...`, `google:...`). This is compatible with the repo's multi-provider fabric (`app/components/llm/router.py`).

**Risk:** If agents constructed via `create_deep_agent()` bypass the existing `LLMRouter` and `ChatClient` abstraction, the repo loses:
- Task-aware model routing (`LLMTaskIntent` profiles)
- Compiled settings overrides (`vault/@Settings/llm_routing.md`)
- Mock provider for deterministic CI

**Mitigation path:** Pass a LangChain model object constructed via the existing fabric layer as the `model` parameter rather than a bare string. Needs prototyping.

### 2. Outbox event contract — REQUIRES ADAPTER

DeepAgents' `task` tool spawns subagents and coordinates state internally via LangGraph Memory Store. It does not emit Outbox events.

The repo's coordination model requires all cross-cutting side effects to be emitted via the Outbox event system with the canonical envelope (`event`, `event_id`, `trace_id`, `source`, `timestamp`, `payload`, `meta`).

**Required adapter:** An `OutboxEmittingToolWrapper` that intercepts tool call completions and emits the canonical Outbox event before returning. This is feasible via LangChain tool callbacks.

### 3. Core-6 and trust model — PRESERVED VIA PAYLOAD DISCIPLINE

DeepAgents' Memory Store does not carry Core-6 fields or trust tiers. However, Core-6 fields live in Stores (`ObjectStore`), not in LangGraph state. As long as agents read from Stores and write via Stores (not via DeepAgents Memory Store for durable state), the trust model is preserved.

**Risk:** Developers may be tempted to use DeepAgents' cross-thread persistence for artifact state. Must be prevented via convention + architectural test.

### 4. Existing 13 LangGraph agent graphs — PARTIAL REUSE

The 13 existing PER graphs are compiled LangGraph runnables. DeepAgents spawns subagents via the `task` tool; the mechanism isn't fully documented but likely passes a LangGraph runnable or a tool-calling agent.

**Options (in order of migration effort):**
- **Option A (minimal migration):** Wrap existing compiled PER graphs as tools callable by the outer DeepAgents harness. Each agent's `run(input)` becomes a tool function.
- **Option B (full migration):** Rebuild agents as `create_deep_agent()` instances; the PERSpec pattern becomes implicit in DeepAgents' planning loop.
- **Option C (hybrid):** Keep inner PER graphs for deterministic pipeline agents (chunker, indexer, normalizer); adopt DeepAgents for reasoning/decision agents (ASK, reviewer, panel, orchestration).

Option C is the lowest risk path and most consistent with the existing "LangGraph inner, deterministic outer" pattern.

### 5. Vault filesystem mapping — STRONG FIT

DeepAgents' virtual filesystem backend maps naturally to vault operations:
- Local disk backend → existing vault root (`VAULT_DIR`)
- `write_file` → replaces `append_note()` in `app/mcp/vault_tools.py`
- In-memory backend → direct replacement for `MockPlanExecutor` in CI

This eliminates most of the need for a custom MCP filesystem layer.

### 6. LangSmith observability — ALREADY IN REQUIREMENTS

`langsmith==0.7.31` is pinned in `requirements.txt`. DeepAgents is built on LangChain and traces automatically via LangSmith when `LANGCHAIN_API_KEY` is set. This complements (not replaces) the Prometheus/status stack.

---

## Options

### Option 1: Adopt DeepAgents as outer harness (replace Orchestrator V2 plan)

- `create_deep_agent()` becomes the outer harness
- Existing PER graphs wrapped as tool-callable agents (Option A above) for minimal migration
- Reasoning/decision agents optionally migrated to `create_deep_agent()` instances
- Outbox adapter wraps tool completion callbacks
- Vault root becomes DeepAgents' local disk filesystem backend
- `ReasoningFacade` becomes a thin wrapper ensuring `LLMRouter`-routed model is passed to `create_deep_agent()`

**Pros:** Removes Orchestrator V2 build; built-in planning, filesystem, subagent coordination; LangSmith traces for free
**Cons:** LLM fabric bypass risk; incomplete state-flow documentation for `task` tool; adds external dependency; migration effort for existing agent callers

### Option 2: Adapt — use DeepAgents pattern, build Orchestrator V2 to match it

- Do not adopt DeepAgents directly
- Design Orchestrator V2 internals to mirror DeepAgents' pattern: inner loop with planning tool, filesystem abstraction, subagent delegation via typed tool
- Build `ReasoningFacade` as the explicit equivalent of DeepAgents' tool-calling loop
- Retain full control over Outbox events, trust model, and provider abstraction

**Pros:** Full control; no external harness dependency; same pattern, proven against this repo's constraints
**Cons:** More build effort; risk of diverging from DeepAgents as it evolves; no LangSmith auto-tracing

### Option 3: Reject — proceed with Orchestrator V2 as originally planned

- Build Orchestrator V2 in LangGraph as described in `docs/ROADMAP.md`
- Build `ReasoningFacade` as v5.6 blocker
- Assess DeepAgents in a future cycle when its state-flow and provider model are better documented

**Pros:** Known path; no external dependency; v5.6 gates are already defined
**Cons:** Builds what DeepAgents may already provide; misses the evaluation window before v6.0 semantic work begins

---

## Recommendation

**Option 2 (Adapt)** with a bounded pilot of Option 1.

Rationale:
1. DeepAgents' `task` tool state-flow between outer and inner agent is not yet well-documented enough to commit to for the Outbox event adapter design.
2. The LLM provider bypass risk is real and must be prototyped before adoption.
3. However, DeepAgents' pattern (planning loop + filesystem + subagent delegation) is the right target shape for Orchestrator V2 — building V2 to mirror this pattern means we can migrate to full adoption in a later cycle with minimal rework.

**Pilot scope (before v5.6 starts):**
- Build a `DeepAgentsProbe`: a single `create_deep_agent()` instance that wraps the existing `ask/graph.py` as a tool and emits a mock Outbox event on completion.
- Verify: does the fabric `LLMRouter` model object pass cleanly? Does `task` tool state flow have enough hooks for the Outbox adapter?
- Timebox: 1 session. Output: go/no-go memo appended to this ADR.

---

## Decision

_Pending pilot result. To be filled after the probe above._

---

## Consequences if adopted

- `app/orchestrator/runtime.py` + `app/orchestrator/executor.py` → wrapped or replaced
- `app/planner/` → `write_todos` pattern replaces explicit plan generation for agentic flows
- `app/mcp/vault_tools.py` → vault root registered as DeepAgents local disk backend; `append_note` kept for Outbox-emitting writes
- `app/agents/base/graph.py` (PERSpec) → kept for deterministic pipeline agents; reasoning agents migrate to `create_deep_agent()`
- New required test: `tests/architecture/test_deepagents_outbox_contract.py` — verifies Outbox events are emitted for all subagent tool completions

## Consequences if rejected / adapted

- Orchestrator V2 built in LangGraph; ReasoningFacade built as thin LLMRouter wrapper
- PERSpec remains canonical for all agents
- DeepAgents reassessed when `task` tool state-flow is documented

---

## Related

- `docs/ROADMAP.md` — v5.6 forward line, Orchestrator V2 plan
- `docs/plans/V56_FORWARD_LINE.md` — ReasoningFacade as v5.6 blocker
- `docs/adr/0005-per-loop.md` — PERSpec ADR (current inner pattern)
- `app/orchestrator/runtime.py` — Orchestrator V1
- `app/agents/base/graph.py` — PERSpec pattern
- `app/components/llm/router.py` — LLMRouter (must remain compatible)
