State: Partially applied in SoT v4.10 (base exists; not enforced).
# ADR 0005: Standardize PER-loop agent base

Date: 2025-10-25  
Status (v4.10): Base loop present, usage optional.

## Context
Plan → Execute → Reflect was proposed to standardize agent lifecycles and trace propagation.

## Reality in SoT v4.10
- `app/agents/base/loop.py` provides `Agent` and `reflection_event`, but core agents (ASK LangGraph, PanelAgent, ingest agents) do not use this base.
- Trace propagation is handled per-agent/graph; observability is minimal.

## Decision (original)
- Provide a shared PER base with `plan/act/reflect/run`, generating/propagating `trace_id` and emitting reflection events.

## Current implementation
- Base class exists; no repo-wide requirement or CI check that agents use it.
- Agents rely on bespoke flows (LangGraph for ASK, simple functions for ingest/promotion/projector).

## Guidance
- Treat PER base as optional scaffolding. If standardization is desired, add tests/architecture rules and migrate agents explicitly; otherwise keep bespoke flows documented in `docs/AGENTS.md` and `docs/PANEL_AGENT.md`.
