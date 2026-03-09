State: SoT v5.5 baseline + v5.6 forward line (settings tiering design).
# Settings Tiering Design and Inventory

## Purpose
Reduce operator cognitive load by separating settings into two tiers:
- **Operator-facing**: human-meaningful runtime controls for normal single-user operation.
- **Dev/Lab-only**: advanced tuning, experiments, and feature-flagged agentic behavior.

This document is the Step 3 design/input for Step 4 enforcement.

## Applicable SoT and Contracts
- `docs/ARCHITECTURE.md`
- `docs/STATUS.md`
- `docs/SETTINGS.md`
- `docs/INVENTORY.md`
- `docs/CORE_RUNTIME_AGENTIC_LAB_BOUNDARY.md`
- `docs/CONCEPTS/CONFIG_AS_PRODUCT_CONTRACT.md`

## Tier Definitions
### Operator-facing tier (default runtime)
Criteria:
- directly affects human-observable operation,
- safe and predictable for day-to-day use,
- needed to run the Core Runtime without lab features.

### Dev/Lab-only tier (explicit opt-in)
Criteria:
- debugging/tuning/perf internals,
- experimental orchestration/reasoning/agentic features,
- compatibility shims and non-production paths.

Rule target (for Step 4): normal runtime reads operator-facing settings only, unless lab mode is explicitly enabled.

## Inventory (Current Settings)
This table is scoped to high-impact runtime controls used by startup/watcher/worker/ASK flows.

| Setting | Current source(s) | Tier | Why |
| --- | --- | --- | --- |
| `VAULT_ROOT` | env / startup scripts | Operator-facing | Primary operator runtime boundary (which vault to operate on). |
| `DATABASE_URL` / `DB_DSN` | env / compose / startup scripts | Operator-facing | Required for canonical DB outbox runtime path. |
| `WATCHER_AUTO_EXEC` | env + `vault/@Settings/watchers.md` | Operator-facing | Core operator mode switch (`1` default, `0` emit-only). |
| `WATCHER_SCOPE_GLOB` | env / watcher config | Operator-facing | Human-meaningful runtime scope control. |
| `watcher_settings.allowed_actions` | `vault/@Settings/watchers.md` | Operator-facing | Human-meaningful action safety policy. |
| `LLM_PROVIDER` / model endpoints (`OLLAMA_URL`, etc.) | env + model settings | Operator-facing | Chooses runtime inference backend used by ASK/panel flows. |
| `PANEL_PROACTIVE_ASSIST` | env | Operator-facing | Directly changes panel assist behavior seen by the operator. |
| `INDEX_OUTBOX_PATH` | env | Dev/Lab-only | JSONL audit/diagnostic path; non-canonical queue. |
| `STORE_BACKEND` | env | Dev/Lab-only | Backend switching is mainly test/dev infra tuning; operator runtime should be canonical. |
| `WATCHER_DEBOUNCE_MS`, `WATCHER_RATE_LIMIT_PER_MIN`, `WATCHER_BACKOFF_SECONDS`, `WATCHER_TICK_SLEEP_SECONDS` | env / watcher config | Dev/Lab-only | Performance/guardrail tuning, not day-to-day operator intent. |
| `WATCHER_REQUIRE_DB_OUTBOX` | env | Dev/Lab-only | Infra enforcement/debug control. |
| `PANEL_AGENT_PIPELINE`, `PANEL_AGENT_DECIDER` | env | Dev/Lab-only | Advanced pipeline/decider experiments. |
| `ORCHESTRATOR_ENABLE`, `ORCHESTRATOR_VERSION` | env | Dev/Lab-only | Advanced orchestration rollout flags. |
| `REASONING_ENABLE`, `REASONING_PROVIDER` | env | Dev/Lab-only | Experimental reasoning rollout controls. |
| `A2A_ENABLE`, `MCP_ENABLE` | env | Dev/Lab-only | Forward-line agentic integration flags. |

## Migration Map and Impact Notes
| Area | Current behavior | Target behavior | Compatibility path | Impact/Risk |
| --- | --- | --- | --- | --- |
| Watcher mode and policy | Mixed env/settings, partly implicit | Operator tier owns default runtime behavior | Keep existing env names; normalize precedence and provenance | Low; improves predictability. |
| Watcher perf tuning | Any runtime may set low-level knobs | Dev/Lab-only unless explicit lab mode | Keep env support in lab mode; ignore/warn in operator mode | Medium; may surprise users relying on hidden tuning in normal runs. |
| Backend/path internals (`STORE_BACKEND`, JSONL paths) | Often exposed in normal runbooks/tests | Canonical runtime path in operator mode; internals moved to lab mode | Keep overrides for tests/CI/lab profile | Low-medium; requires clear runbook notes. |
| Panel/orchestrator/reasoning experimental flags | Flags are globally available | Lab mode required | Continue honoring flags in lab mode; operator mode ignores or warns | Medium; removes accidental activation risk. |

## Enforcement Design (Step 4 Acceptance Targets)
- Add a runtime mode gate with explicit profile:
  - default: `operator`
  - opt-in: `lab`
- In `operator` mode:
  - read/apply operator-facing tier,
  - reject or warn on dev/lab-only settings with provenance output.
- In `lab` mode:
  - allow both tiers (operator + dev/lab).
- Keep settings provenance in `settings-explain` / `settings-validate`.
- Add boundary tests asserting:
  - operator mode ignores/blocks lab-only knobs,
  - lab mode enables them explicitly,
  - `WATCHER_AUTO_EXEC` operator semantics stay stable.

## Non-goals (Step 3)
- No behavior changes in this step (design/inventory only).
- No removal of advanced agentic capabilities.
- No silent reclassification of historical docs as active SoT.
