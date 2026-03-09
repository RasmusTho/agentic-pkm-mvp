State: SoT v5.5 baseline + v5.6 forward line (boundary contract).
# Core Runtime vs Agentic Lab Boundary

## Purpose
Define a strict architecture split between:
- **Core Runtime**: operator-safe default runtime for single-user, local-first, human-in-the-loop operation.
- **Agentic Lab**: advanced/experimental agentic orchestration and learning capabilities that remain opt-in.

This boundary preserves advanced agentic learning as a core value without making default operations harder to run or reason about.

## Applicable SoT and Contracts
- `docs/DOCS_INDEX.md` (active doc set, historical handling)
- `docs/ARCHITECTURE.md` (runtime and SoT lines)
- `docs/STATUS.md` (baseline runtime behavior and defaults)
- `docs/HUMAN-FLOWS.md` (operator-facing runtime expectations)
- `docs/CONCEPTS/CONFIG_AS_PRODUCT_CONTRACT.md` (settings precedence/provenance)
- `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md` (event envelope compatibility)
- `docs/contracts/OBSIDIAN_KNOWLEDGE_PORT.md` (vault/Obsidian write boundary)

## Boundary Contract
### Core Runtime (default, operator-safe)
Core Runtime is the production/operator path and MUST remain explicit, predictable, and minimal in settings surface.

It includes:
- Registry watcher runtime path (`python -m app.cli watcher run`, `app/watcher/registry.py`)
- Vault ingest and indexing baseline (`app/ingest`, `app/indexer`, `app/index`, `app/store`, `app/stores`)
- ASK API baseline (`app/api`, `app/retrieval`, `app/search`)
- Panel runtime baseline and allowlisted actions (`app/agents/panel*`, `docs/settings/panel-actions.md`)
- Health/observability/status surfaces (`app/observability`, `docs/HEALTH.md`, `docs/STATUS.md`)
- Knowledge boundary helpers and contracts (`app/knowledge/*`, `docs/contracts/OBSIDIAN_KNOWLEDGE_PORT.md`)

### Agentic Lab (advanced, opt-in)
Agentic Lab contains advanced or evolving capabilities that are valuable for learning and iteration but are not required for default operator runtime.

It includes:
- LangGraph expansion beyond current baseline usage
- ReasoningFacade and experimental reasoning flows (`app/reasoning`, `app/langgraph`, gated graph work)
- Orchestrator V2 and richer tool-planning paths (`app/orchestrator`, flagged advanced modes)
- Experimental eval/research stacks (`app/eval`, `docs/eval*`, research notes)
- Legacy/dev-only watcher or runtime-loop workflows not used by startup flows

### Cross-boundary Rules
- Core Runtime MUST run without requiring Agentic Lab features.
- Agentic Lab features MUST require explicit enablement flags/profiles.
- Agentic Lab changes MUST NOT silently alter Core Runtime defaults or operator-facing contracts.
- Shared contracts (events, settings provenance, knowledge boundary) remain mandatory for both sides.

## Module Ownership Map
Ownership here means architectural ownership (which side controls runtime behavior), not team ownership.

| Path / module area | Boundary owner | Notes |
| --- | --- | --- |
| `app/watcher/registry.py`, `app/watcher/config.py`, `configs/watchers.yaml` | Core Runtime | Canonical watcher runtime path for operators. |
| `app/ingest/*`, `app/index*`, `app/store/*`, `app/stores/*`, `app/outbox/*` | Core Runtime | Canonical ingest/index/store/event pipeline. |
| `app/api/*`, `app/retrieval/*`, `app/search/*` | Core Runtime | ASK and retrieval runtime surface. |
| `app/knowledge/*`, `app/ports/*` | Core Runtime | Obsidian/vault and write boundary contracts. |
| `app/agents/panel*`, `app/promotion/*` | Core Runtime | Panel runtime baseline and promotion safety. |
| `app/observability/*`, `app/health*`, `app/write_guard.py` | Core Runtime | Operational safety/health spine. |
| `app/reasoning/*`, `app/langgraph/*` (beyond baseline-enabled paths) | Agentic Lab | Advanced reasoning/graph expansion remains opt-in. |
| `app/orchestrator/*` advanced modes and V2 tracks | Agentic Lab | Experimental orchestration beyond baseline. |
| `app/eval/*`, `docs/research/*` | Agentic Lab | Evaluation and research tracks are non-default. |
| Legacy snapshot watcher flows (`vault-watcher-run`, daemon/runtime-loop paths) | Agentic Lab | Dev-only/historical; not production startup path. |

## Non-goals
- No rewrite of baseline runtime or event contracts in this step.
- No removal of advanced agentic capabilities.
- No change to historical documents except keeping them explicitly historical.
- No silent default flips through this boundary doc alone.

## Change Control
- Moving a module from Agentic Lab into Core Runtime requires:
  - explicit contract check against active SoT docs above,
  - docs updates in the same change set,
  - boundary/regression tests when behavior contracts change.
- If a requested move conflicts with active SoT/contracts, stop and request explicit approval before implementation.
