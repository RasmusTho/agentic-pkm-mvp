State: v5.6 — PanelAgent runtime V1 baseline (v5.0) + freeform catalog-driven proposal path shipped (PA2-FREEFORM). This document defines the PanelAgent-specific runtime contract.
# PanelAgent / NoteInteractionAgent (Runtime v5.0)

Purpose: translate human-driven AI panels in vault notes into structured intents/events while keeping the panel simple, optional, and human-first.

Scope:
- PanelAgent-specific behavior
- panel syntax and mutation rules
- emitted events and payload shapes
- runtime toggles, wiring, and watcher-facing behavior

For the system-level multi-agent architecture, agent matrix, and LangGraph/A2A direction, use `docs/AGENTS.md`.
For the design-layer rules on capability-based composition, interaction surfaces, and governed mutation authority, use `docs/DESIGN_PRINCIPLES.md`.
For the canonical distinction between mirror artifacts and receipt artifacts, use
`docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`.

Interpretation note:
- this document describes the current mutation-capable Panel surface and its runtime contract,
- not a claim that panel behavior should stay embedded in one architectural agent forever,
- and not a claim that event/outbox coordination is the whole long-term architecture.

## PanelAgent Runtime V1 (current baseline)
- Panel should be read as the current mutation-capable interaction surface in the runtime.
- Runtime V1 uses a fixed mapping from panel actions to follow-up events (e.g., promotion intents) and writes receipts into an in-note AI status callout; the panel stays a small working set with no history.
- This is a simplified bridge/runtime loop, not the final agentic design; it keeps watcher and manual panel flows working while the agent migrates to LangGraph.
- Internal implementation now runs through a LangGraph-based control flow (`PanelAgentState`), but external behaviour and emitted events remain identical.
- Planner pipeline (opt-in, `PANEL_AGENT_PIPELINE=planner`): PanelAgent builds a `PanelActionIntent` and asks the Planner to create a plan for the selected actions. Plans can now be executed via the Orchestrator using the CLI (`python -m app.cli panel-orchestrate-plan --plan-id <plan_id>`), while the default direct path remains unchanged.
- Action catalog (`docs/settings/panel-actions.md`) is the canonical list of actions (id, kind, labels/synonyms, description/llm_hint, downstream event, params). Rule-mode matches checkbox labels deterministically; LLM-mode is opt-in and uses the catalog + panel/note context with checkboxes as hints.
- Checkboxes are treated as explicit consent; executed items remove their checkbox from the panel working set.
- Receipts live in the AI status callout (foldable) to acknowledge outcomes without bloating the panel history.
- The AI status callout is a bounded receipt surface, not the same thing as the metadata mirror.

## PanelAgent 2.0 (v5.6, in progress)

<!-- PA2-ENGINE-SEAM -->
**Engine-neutral cognition seam (shipped, v5.6 enabling).** Panel action selection is now invoked through a dedicated `PanelCognitionBackend` Protocol defined in `app/agents/panel_agent/cognition.py`. `graph.py` no longer owns cognition-selection concerns directly; it receives a backend through `build_panel_graph(cognition_backend=...)` and calls it via `_decide_actions_with_backend`. Current backends: `RuleCognitionBackend` (default, checkbox-driven) and `LLMCognitionBackend` (routes through `ReasoningFacade`). Parser, execution, receipt, and emitted-event contracts remain unchanged. A future backend (DeepAgents-style or otherwise) implements only `select_actions(state)` without reworking those surfaces. Tracked by: #244.

<!-- PA2-FREEFORM -->
**Freeform catalog-driven proposal path (shipped).** When a panel has an instruction but no checkbox actions, the LLM decider (`PANEL_AGENT_DECIDER=llm`) consults the full active catalog and proposes canonical action IDs from instruction text + catalog metadata (`llm_hint`, `labels`, `description`) alone, without requiring any checkbox-label match. Proposals are restricted to the active catalog; out-of-catalog IDs are dropped. For this no-checkbox path, the runtime writes proposed actions back as suggested unchecked checkboxes for explicit human confirmation rather than executing them immediately; they do not enter the execution path until the human later confirms them as panel checkboxes. Fallback to rule mode on LLM error or empty catalog. Tracked by: #241.

- Surface uncertain or no-checkbox interpretations as suggested unchecked checkboxes instead of direct execution so panel ambiguity stays human-reviewable until explicit confirmation. Delivery receipt: Issue #242 delivered in current runtime behavior; follow-up wording reconciliation tracked by #291. Source Anchor: PA2-SUGGESTED-CHECKBOXES.
- Remaining backlog: #240 (real-vault acceptance).
- Emit ordered multi-step panel plans through the planner/orchestration contract rather than investing in richer LangGraph-only node choreography. Delivery receipt: Issue #243 delivered via PR #302. Source Anchor: PA2-MULTISTEP-PLANS.
- Prove the PanelAgent 2.0 path operationally on a real vault with soak, receipts, and owner-doc writeback before it is treated as operationally accepted. Source Anchor: PA2-REAL-VAULT-ACCEPTANCE. Tracked by: #240

Other implementation notes:
- Introduces an explicit `PanelAgentState` (note reference, panel intent, actions, history, policy) and drives behaviour from a LangGraph graph (e.g., `app/agents/panel_agent/graph.py`).
- LLM-based reasoning decides which panel actions to execute (and in what order) rather than relying on fixed mappings.
- PanelAgent Runtime V1 remains the baseline until the PanelAgent 2.0 path is fully implemented and operationally accepted.
- LangGraph control flow now supports a decider mode (`PANEL_AGENT_DECIDER=rule|llm`); `rule` remains the default to preserve current behaviour, while `llm` is an opt-in, experimental action selector routed through the shared `ReasoningFacade` with the canonical `decide` task kind.
- LLM-driven contract tests live under `tests/e2e/test_panel_llm_e2e.py` (gated by `@pytest.mark.panel_llm_e2e` and `PANEL_AGENT_LLM_E2E=1`) to validate end-to-end promotion/non-promotion scenarios (including the freeform no-checkbox path) using the real decider.

Direction note:
- the forward direction is richer cognition in support of Panel,
- but mutation authority remains bounded by policy, validation, deterministic note-writer paths, and downstream controlled execution.

## Panel syntax (Markdown)
- Panels are delimited by tolerant AI fences: any `%% ...ai... %%` (case-insensitive) line opens/closes a panel. First fence opens, second closes, third opens the next, etc.
- Inside a panel:
  - Instruction heading: `## AI-instruktion` (localized variants supported)
  - Actions heading: `## AI-åtgärder` (localized variants supported)
  - Checkboxes: `- [ ]` or `- [x]` (checked means run the action)
- AI status callout (foldable, outside the panel): `> [!info]- AI status` with receipt lines (`- ✅ ...`, `- ⚠️ ...`, `- ⏳ ...`). The runtime appends receipts for executed/failed actions and trims to the last 20; already-executed IDs remove their checkbox from the panel on re-run.
- This callout is a human-visible receipt overlay on the warm surface, not the canonical mirror artifact.
- Legacy notes that only use the headings without fences are still parsed; new panels should use fences.
- Panel content is not indexed or used as knowledge.

### Example
```markdown
%% AI:Start %%
## AI-instruktion
Make this note evergreen
## AI-åtgärder
- [ ] Gör denna anteckning evergreen
%% AI:End %%

> [!info]- AI status
> - ✅ Re-classify as Concept (2025-03-01 10:00)
```

## Runtime V1 (fan-out, promotion intent, receipts)
- Invocation: `python -m app.cli panel run --uuid <note_uuid>` (default runs the runtime loop). Use `--emit-only` to keep legacy “emit-only” behaviour without executing runtime actions.
- Multi-note invocation: `python -m app.cli panel run-many <uuid> [<uuid> ...]` (default runs runtime; `--emit-only` supported). Used by watcher flows; auto-run policy gates watcher-driven calls.
- Reads the note from ObjectStore (vault mirror), not directly from the filesystem.
- Finds each AI panel, parses instruction + checkbox actions, enriches actions via `docs/settings/panel-actions.md` mappings, and emits **one** Outbox event per panel: `panel.intent.created`.
- Interprets checked actions and:
  - emits `panel.intent.executed` with per-action status,
  - emits `panel.action.triggered` for handled actions,
  - emits `panel.action.logged` for unmapped/unhandled actions (v5.x placeholders),
  - emits `promote.intent.created` when an action has `intent_type: promotion` (e.g. `promote.evergreen` mapping) so Promotion Agent flows can react,
  - removes executed checkboxes from the panel working set, writes a receipt into the AI status callout, and records the hidden `ai:id` in `executed_action_ids` on the note payload to prevent re-execution.
- No LangGraph/planner/tool calls; this remains a lightweight runtime loop on top of Reality-MVP.
- Markdown mutations (panel cleanup, receipts, promotion frontmatter) flow through the note writer; agents emit intents, and the writer/consumer apply deterministic file updates.
- Auto-run policy (SoT v5.3, watcher-facing): watchers treat any note that contains an AI panel fence (`%% ...ai... %%`, case-insensitive) as a candidate once the global arm switch `WATCHER_AUTO_EXEC=1` is set. The only per-note opt-out is `ai_panel_auto_run: never` (nested `ai_panel: { auto_run: never }` also works); other modes (`watcher`/`manual`) remain metadata for manual CLI contexts but no longer gate watcher eligibility. Manual CLI commands (`panel run`, `panel run-many`) ignore this policy.

Architectural reading note:
- these event and writer paths describe the current runtime contract,
- but they should be read as implementation of the Panel interaction surface,
- not as proof that every future cognition or capability boundary should be modeled as a dedicated event-emitting agent.

### Planner pipeline (opt-in)
- `PANEL_AGENT_PIPELINE=planner` keeps the external runtime behaviour the same and also builds a `PanelActionIntent` for ordered handled actions (`triggered` and `logged`), storing a plan via Planner (`plan_panel_actions`).
- Plans include promotion steps mapped to the `promotion.emit_intent` tool. They can be executed via Orchestrator in a CLI-first path: `python -m app.cli panel-orchestrate-plan --plan-id <plan_id>`. Watcher-driven execution remains off for now.
- Saved panel plans use an explicit ordered contract (`panel.ordered.v1`): plan context records the ordered action ids and each step carries sequence metadata plus a `depends_on` chain so orchestrator-facing execution order does not rely on list position alone.
- Decider and pipeline are orthogonal toggles:
  - `PANEL_AGENT_DECIDER=rule|llm` selects how actions are chosen (default `rule`).
  - `PANEL_AGENT_PIPELINE=direct|planner` selects whether to emit promotion directly (default) or also create plans (planner mode).

## UAT / Trying it out
- The quickest way to exercise PanelAgent + watcher flows on a small set of notes is in `docs/runbooks/UAT_PANEL_WATCHER.md` (prep notes, targeted ingest, panel run-many, watcher dry-run/run, and what to observe).

### Event payload (panel.intent.created)
```json
{
  "event": "panel.intent.created",
  "version": "1.0",
  "source": {"component": "panel_agent", "trigger": "cli", "sot": "v5.0-step1"},
  "payload": {
    "note": {"uuid": "NOTE-UUID", "path": "vault/Note.md", "origin": "vault"},
    "panel": {"panel_id": "panel-1", "instruction": "Do the thing"},
    "actions": [
      {
        "id": "promote.evergreen",
        "label": "Gör denna anteckning evergreen",
        "checked": true,
        "mapping": {
          "intent_type": "promotion",
          "downstream_event": "review.promote.evergreen",
          "params": {"maturity": "evergreen"}
        }
      },
      {"id": "unknown-action", "label": "Other", "checked": false, "mapping": null}
    ]
  }
}
```

### Derived runtime events
- `panel.intent.executed` — payload `{note, panel, actions:[{id,label,checked,status,emitted_events}], executed_action_ids:[...]}` (source `panel_agent` / trigger `runtime`).
- `panel.action.triggered` — payload `{note, panel_id, action:{id,label}, target_event}` for handled actions.
- `panel.action.logged` — payload `{note, panel_id, action:{id,label,checked}, reason, mapping?}` for unmapped/unimplemented actions.
- `promote.intent.created` — payload includes `{note, panel, action, instruction, maturity}` plus `{action_id, intent_source="panel.note", note.path}`; emitted when a checked action has `intent_type: promotion`; downstream consumer uses `note.path` to patch the vault note frontmatter (for example `maturity: evergreen` plus a compatibility-mapped review posture).

## Wiring configuration
- Default wiring: `docs/settings/panel-action-wiring.yaml` (maps canonical action ids to target events).
- Resolution order: `PANEL_ACTION_WIRING_PATH` env override > `<vault>/System/Config/panel-action-wiring.yaml` (vault override) > repo default.
- Validation: config must define an `actions` list with `id`, `kind` (event|intent, defaults to event), and `event_type`/`target_event` (or `intent_type`). Unknown/invalid configs emit a warning and fall back to the default wiring; runtime behaviour stays unchanged.
- CLI/Watcher use the same wiring; panel decider (rule/LLM) still selects actions, wiring only controls emitted events.

Promotion intents (`promote.intent.created`) represent intent-only; apply effects by running the promotion consumer (`python -m app.cli promote-consume`), which emits `promote.done` when successful and updates the vault note frontmatter via the note writer path, writing standing changes to `maturity` and review posture separately (Store updates remain optional).
