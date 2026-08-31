State: Current-state owner document for the delivered Settings Spine (SETTINGS-01..08).
Doc role: Core SoT / owner document
Authority: Owns the settings mechanism, scopes, resolution order, canonical vault location,
ingestion/degradation semantics, receipts, and operator/lab tiering. Runtime validation commands
and the code contracts they exercise remain the executable evidence.

## Ownership and reading order

This document is the single owner for settings mechanism. `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md`
owns the conceptual vault/context model and defers here for settings mechanism; `docs/ENVIRONMENTS.md`
owns environment and vault terminology and defers here for settings resolution. The Settings Spine
specification directory records decomposition and invariants, while GitHub Issues and merged PRs
record delivery evidence.

The two settings scopes are:

- **Instance scope** — app-local settings that exist before a vault and may select the instance's
  default binding, UI state, ports, cache paths, and credential references.
- **Vault scope** — human-visible Markdown settings under the selected vault's canonical
  `<vault>/settings/` root, divided into vault-shared and clone-local files.

Both scopes resolve through one `SettingsService` and one default registry. A runtime/session
override is an explicit final-layer override, not a third persistent settings location.

## Current-state baseline
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run defaults on (`WATCHER_AUTO_EXEC=1`); set `WATCHER_AUTO_EXEC=0` for emit-only mode. LangGraph/Reasoning rollout remains opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

The delivered spine covers ingestion and visible degradation (SETTINGS-01), one default registry
(SETTINGS-02), one canonical vault settings root (SETTINGS-03), durable receipts for settings
writers (SETTINGS-04), protected picker/watcher rebind (SETTINGS-05), prompt settings (SETTINGS-06),
and the serial model/TTS/watcher tuning wave (SETTINGS-07A..07C). The owner-document consolidation
and parent validation handoff are SETTINGS-08; no separate settings owner or orphan schema is
implied by the older roadmap.

## Target-state boundary

The current spine is a one-compatibility-watcher lifecycle, not generic multi-vault lifecycle
supervision. Future multi-vault background supervision remains owned by the MVR handoff. Operator
mode and lab mode are documented policy boundaries; adding new settings, changing defaults, or
retiring compatibility inputs still requires the owning Issue, source-doc update, and the relevant
validation evidence.

# Settings

This repo uses a **settings-as-artifacts** approach. “Settings” are not only runtime knobs; they are also
versioned contracts for how the system behaves (agents, flows, panel wiring, prompts, and standards).

Related docs:
- `docs/ARCHITECTURE.md` for current authority boundaries and runtime baseline
- `docs/development/DEV_WORKFLOW.md` for required validation/update order when changing settings artifacts
- `docs/LLM_ROUTING.md` for the LLM-specific routing/fabric contract

## Runtime settings (compiled)

Runtime settings are compiled from vault-backed Markdown settings into `runtime/settings/`.

Primary source folder:
- `<vault>/settings/`

`<vault>/settings/` is the only canonical per-vault settings root. During the
bounded compatibility release, retired source locations remain readable with a
warning; a canonical file shadows the corresponding legacy file and their
contents are never merged.

Compiler:
- `python -m app.cli settings compile`

Runtime settings cover the panel action catalog, watcher policy, watcher cadence, and curation/expansion tuning under `runtime/settings/`.
`python -m app.cli settings-explain` is a narrow operator-facing diagnostics surface for environment/database state plus panel-action and watcher provenance/gating; it also reports the effective watcher/tuning values with their compiled source origin and active tier. It is not a full dump of every compiled runtime YAML.
Compiled bundle files such as `runtime/settings/llm_routing.yaml` remain the direct artifact for the broader runtime payload, while `python -m app.cli settings-validate` checks registries, panel/watcher source artifacts, and any compiled-runtime unresolved-secret sentinels visible locally.
They also include task-specific LLM routing policy via `<vault>/settings/llm_routing.md` -> `runtime/settings/llm_routing.yaml`.
The provider-neutral reasoning path and `settings-explain` resolve the same compiled
`default_reasoning` route. During this one-release compatibility window,
`REASONING_MODEL` may replace that route's model only; it never selects or changes
the compiled provider. `llm_routing.timeout_seconds` and `.temperature` feed the
same route; `LLM_TIMEOUT` and `LLM_TEMPERATURE` remain bootstrap overrides. The
explain payload reports the effective identity and origin.

## Authority

Vault selection and the separately deployed watcher use the protected
`settings_rebind.v1` compatibility transaction. A picker change is prepared,
the old watcher root is acknowledged and drained, and selection plus binding
are committed in one registry generation. The watcher then resumes on the
candidate root, after which the Settings Spine reloads exactly once for the
committed revision after durable completion. If a process dies after the
idempotent reload callback but before its completion marker is written,
recovery may replay that callback; the marker prevents a second reload after
completion. `WATCHER_VAULT_PATH` remains a startup/bootstrap input, while
health reads the durable phase and desired / applied / reload revisions;
compiled display fields never choose a binding. Only one compatibility watcher
root is active at a time. Generic multi-vault lifecycle supervision remains
owned by the later MVR handoff.

Settings tiering guidance (operator-facing vs dev/lab-only), inventory, and migration targets are described below.
Runtime profile switch for tier enforcement: `PKM_SETTINGS_PROFILE=operator|lab` (default `operator`).

## Settings Tiering

The active settings model separates:
- **Operator-facing settings** for normal single-user runtime operation
- **Dev/Lab-only settings** for tuning, experiments, and compatibility paths

Core rules:
- normal runtime defaults to `PKM_SETTINGS_PROFILE=operator`
- lab/experimental controls require explicit `PKM_SETTINGS_PROFILE=lab`
- provenance and precedence should remain inspectable, with `settings-explain` focused on watcher/panel operator diagnostics and `settings-validate` covering registry/source consistency plus local unresolved-secret checks

High-impact examples:
- Operator-facing:
  - `VAULT_ROOT`
  - `DATABASE_URL` / `DB_DSN`
  - `WATCHER_AUTO_EXEC`
  - `WATCHER_SCOPE_GLOB`
  - `watcher_settings.allowed_actions`
  - task-specific LLM model selection and fallback policy
  - `PANEL_PROACTIVE_ASSIST`
- Dev/Lab-only:
  - `INDEX_OUTBOX_PATH` as JSONL audit path
  - `STORE_BACKEND`
  - watcher performance-tuning knobs
  - pipeline/decider/orchestrator/reasoning feature flags
  - `HEALTH_THRESHOLDS_*` env-var threshold overrides (see `docs/HEALTH.md`)
  - `watchers.debounce_ms`, `watchers.rate_limit_per_min`, `watchers.backoff_seconds`, `watchers.tick_sleep_seconds`
  - `watchers.connect_relatedness_floor`, `watchers.contradiction_floor`

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
- Panel action wiring: `docs/settings/panel-actions.md` and `docs/settings/panel-action-wiring.yaml`
- Flow settings: `docs/settings/flows.settings.yaml`

## Prompt settings

The ASK system prompt is canonical vault settings at
`<vault>/settings/prompts/ask.md`. It is seeded for a newly initialized vault,
loaded through the Settings Spine, and exposes its effective origin through
`settings-explain`. When the file is absent, the code registry default
`DEFAULT_ASK_SYSTEM_PROMPT` preserves the historical behavior exactly.

Legacy repository prompt mirrors and their registry were retired; they are not
runtime input. The classifier's schema-constrained instructions remain
code-owned because they are coupled to its completion schema; this slice does
not migrate that separate classifier contract.

## Standards Registry

To keep architectural contracts explicit and reviewable, we maintain a “standards registry”:

- `docs/settings/standards.yaml`

This lists adopted standards and the canonical repo references implementing each standard
(e.g. MCP tools, A2A schemas, OpenAPI, AsyncAPI, JSON Schema).

## Tool Registry

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

## Operational guidance
- Use `python -m app.cli settings-validate --json` to validate registries, panel/watcher source artifacts, and locally compiled unresolved-secret sentinels.
- Use `python -m app.cli settings-explain --json` to inspect environment/database resolution plus watcher/panel provenance and gate state.
- When changing a registry or settings artifact, update the owning doc and validation expectations in the same change.
- Treat `<vault>/settings/llm_routing.md` as the user-facing source of truth for chat, reasoning, embedding, and eval model choices. The compiler derives providers from the model registry.
- Migrate an existing vault only through the explicit governed command:
  `python -m app.cli settings migrate-location --vault-root <path>`. The command
  checks WriteGuard before its first mutation, refuses canonical/legacy
  conflicts instead of overwriting or merging them, publishes the canonical
  tree as one fsynced swap, and emits a durable settings-write receipt. Retired
  roots and the previous canonical tree are atomically quarantined in the
  receipt's owned `.settings-migration-*` recovery directory; they are not
  recursively deleted during the migration. A zero-source rerun is a no-op
  receipt and does not create another recovery directory.
