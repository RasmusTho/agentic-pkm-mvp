State: SoT v4.10 (current; details may lag ARCHITECTURE).
# Settings

This repo uses a **settings-as-artifacts** approach. “Settings” are not only runtime knobs; they are also
versioned contracts for how the system behaves (agents, flows, panel wiring, prompts, and standards).

## Runtime settings (compiled)

Runtime settings are compiled from vault-backed Markdown settings into `runtime/settings/`.

Primary source folder:
- `vault/@Settings/`

Compiler:
- `python -m app.cli settings compile`

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
