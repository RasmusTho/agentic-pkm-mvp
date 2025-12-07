State: SoT v4.10 Reality-MVP (current dev-layer quick guide).
# Codex Guidelines (agentic-pkm-mvp)

Purpose: quick checklist for the coding assistant. Canonical prompt lives in `.codex/AGENTS.md`; defer to it and the SoT docs for details.

## Scope & SoT anchors
- Follow SoT: `docs/ARCHITECTURE.md`, `docs/SYSTEM_DESIGN_v4.10.md`, `docs/AGENTS.md`, `docs/PANEL_AGENT.md`, `docs/EVENTS.md`, `docs/COMPONENTS.md`, `docs/STATUS.md`, `docs/ROADMAP.md`, `docs/INGEST.md`, `docs/RETRIEVAL.md`, `docs/DATA_MODEL.md`.
- Dev policy: `docs/AI_DEVELOPMENT.md`, `docs/DEV_WORKFLOW.md`.
- Historical/planned docs are context only; never override current SoT.

## Core rules
- Stores + Outbox + Components only; no raw DB/SDK shortcuts.
- Agents are runtime-agnostic: keep FastAPI/web concerns out of `app/agents/*`.
- Preserve invariants: Core-6 semantics, Outbox envelope, ASK AgentState contract.
- Event names come from `app/events/types.py` and `docs/EVENTS.md`; use the envelope even for best-effort audit.

## Current agent reality (MVP)
- ASK: retrieve → rerank → answer; default answer is top snippet when reasoning is off.
- PanelAgent: flag-gated dispatch; panels are not indexed.
- Promotion/Projector: audit + membership stubs; no filesystem/frontmatter projection yet.
- Future/parked: planner/orchestrator/MCP, MergeResolver, NoteHygiene; treat as planned, not active.

## LLM/retrieval defaults
- CI/smoke: `LLM_PROVIDER=mock` for determinism.
- Local dev: Ollama (`LLM_MODEL=llama3.1:8b`), optional reasoning model (`LLM_REASONING_MODEL`, e.g., DeepSeek). Timeouts ~120s chat / ~60s embeddings.
- Retrieval: hybrid BM25 + embeddings; optional rerank; reasoning off by default.

## Workflow expectations
- TDD + docs-first: confirm contract → add/adjust tests → minimal code → docs with correct `State:` lines.
- Reply with a short plan, concrete edits, validation commands, and an explicit SoT delta statement.
- Use `apply_patch` for focused edits; keep changes small and aligned to one goal.
