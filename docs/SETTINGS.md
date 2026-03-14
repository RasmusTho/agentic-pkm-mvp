State: SoT v5.5 baseline (descriptive). Settings exist both as vault-backed compiled artifacts and as repo settings-as-code (registries).

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run defaults on (`WATCHER_AUTO_EXEC=1`); set `WATCHER_AUTO_EXEC=0` for emit-only mode. LangGraph/Reasoning rollout remains opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Settings

This repo uses a **settings-as-artifacts** approach. “Settings” are not only runtime knobs; they are also
versioned contracts for how the system behaves (agents, flows, panel wiring, prompts, and standards).

## Runtime settings (compiled)

Runtime settings are compiled from vault-backed Markdown settings into `runtime/settings/`.

Primary source folder:
- `vault/@Settings/`

Compiler:
- `python -m app.cli settings compile`

Runtime settings cover the panel action catalog and watcher policy; provenance (path/mtime/sha) and precedence follow the vault-first compiler plus `python -m app.cli settings-validate` / `python -m app.cli settings-explain`.

Settings tiering guidance (operator-facing vs dev/lab-only), inventory, and migration targets are described in the section below.
Runtime profile switch for tier enforcement: `PKM_SETTINGS_PROFILE=operator|lab` (default `operator`).

## Settings Tiering

The active settings model separates:
- **Operator-facing settings** for normal single-user runtime operation
- **Dev/Lab-only settings** for tuning, experiments, and compatibility paths

Core rules:
- normal runtime defaults to `PKM_SETTINGS_PROFILE=operator`
- lab/experimental controls require explicit `PKM_SETTINGS_PROFILE=lab`
- provenance and precedence should remain visible through `settings-validate` and `settings-explain`

High-impact examples:
- Operator-facing:
  - `VAULT_ROOT`
  - `DATABASE_URL` / `DB_DSN`
  - `WATCHER_AUTO_EXEC`
  - `WATCHER_SCOPE_GLOB`
  - `watcher_settings.allowed_actions`
  - `LLM_PROVIDER` and model endpoint selection
  - `PANEL_PROACTIVE_ASSIST`
- Dev/Lab-only:
  - `INDEX_OUTBOX_PATH` as JSONL audit path
  - `STORE_BACKEND`
  - watcher performance-tuning knobs
  - pipeline/decider/orchestrator/reasoning feature flags

Target behavior:
- operator mode should read/apply only operator-facing settings
- lab mode may enable both tiers explicitly
- low-level compatibility/tuning knobs should not accidentally shape normal runtime behavior

## Repo settings artifacts (non-compiled)

Some settings live as **repository artifacts** because they are:
- shared, stable, and reviewed (docs-as-code)
- validated in CI
- referenced by multiple subsystems (PanelAgent, Orchestrator, tooling)

Current artifacts:
- Panel action wiring: `docs/settings/panel-actions.md`
- Flow settings: `docs/settings/flows.settings.yaml`

## Prompt Registry (settings-backed)

Prompts live as files in settings, with a small registry manifest for discovery and validation:

- Registry manifest: `docs/settings/prompts/registry.yaml`
- Prompt files: `docs/settings/prompts/*.md` (Markdown + frontmatter + body)

The registry enables:
- deterministic discovery (no implicit globbing)
- strict validation (frontmatter id match, required fields)
- future governance (deprecation, allowed models, eval suite binding)
- linkage to architectural standards (MCP/A2A/JSON Schema/etc)

## Standards Registry (MCP, A2A, OpenAPI, AsyncAPI, ...)

To keep architectural contracts explicit and reviewable, we maintain a “standards registry”:

- `docs/settings/standards.yaml`

This lists adopted standards and the canonical repo references implementing each standard
(e.g. MCP tools, A2A schemas, OpenAPI, AsyncAPI, JSON Schema).

## Tool Registry (MCP tools)

Tools live under docs/settings/tools/; the registry keeps the list deterministic and CI-validated:

- Manifest: `docs/settings/tools/registry.yaml`
- Tool descriptors: `docs/settings/tools/*.yaml`

Descriptors describe `allowed_args` and optional `mock_result` for deterministic testing.

## Agent Registry

Agents live as settings artifacts:

- Manifest: `docs/settings/agents/registry.yaml`
- Agent descriptors: `docs/settings/agents/*.yaml`

Descriptors declare entrypoints, pipelines/events, allowed tools/stores, and settings references for validation.

## Graph Registry

Graphs/workflows are settings artifacts:

- Manifest: `docs/settings/graphs/registry.yaml`
- Graph descriptors: `docs/settings/graphs/*.yaml`

Descriptors reference agents (`agent_id`), entrypoints/state schemas, and I/O events.

## Model Registry

Models are settings-backed artifacts:

- Manifest: `docs/settings/models/registry.yaml`
- Model descriptors: `docs/settings/models/*.yaml`

The registry introduces stable model IDs; other registries (prompts, charts) should reference these IDs rather than raw provider names.

## Event Registry

Events are settings-backed artifacts:

- Manifest: `docs/settings/events/registry.yaml`
- Event descriptors: `docs/settings/events/*.yaml`

The registry lists canonical event IDs, producers/consumers, and optional schema refs. Other registries (e.g., graphs) must reference these IDs.
