State: v5.6 — PanelAgent runtime V1 baseline (v5.0) + freeform catalog-driven proposal path shipped (PA2-FREEFORM) + LLM-first runtime posture established (decider default changed to llm; cognition_mode in emitted events). This document defines the PanelAgent-specific runtime contract.
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

<!-- PANEL-INTENT-MANIFESTATION -->
## Conceptual Role: Artifact-Local Intent Manifestation

Panel is not only a checkbox executor.

Panel is the artifact-local surface where the agent may manifest likely user intention for the current artifact as reviewable proposals. These proposals help the user recognize what they may want to do next — before the user has necessarily formulated that intention as an explicit command.

The interaction posture is:

```
artifact state -> agent proposes likely intention -> user recognizes/corrects/confirms -> confirmed intention enters governed execution -> receipt is written near the artifact.
```

Key distinctions:

- **Proposal generation is cognition/proposal/clarification.** The agent's proposals are bounded to the active catalog and artifact context. LLM output from Panel cognition is always in the proposal or clarification class; it is never promoted to governed-execution authority without an explicit human confirmation step.
- **Governance-bearing execution requires explicit confirmation.** For `governance-bearing-execution` capability classes (effects such as promotion, archiving, lifecycle changes), freeform LLM proposals are written back as suggested unchecked checkboxes and do not fire in the same pass. Governed effects run only after explicit human confirmation on a subsequent pass via policy, WriteGuard, idempotency, deterministic writer, and receipt. Non-governance-bearing classes (orientation, clarification, retrieval, proposal, synthesis/read-only) may still execute or log in the same pass — they surface bounded `panel.action.logged` receipts and never cross WriteGuard or the governance APPLY path. See PA2-FREEFORM for the full contract.
- **Panel is artifact-local.** Proposals are bounded to the specific artifact currently open. Panel is not a generic conversation surface, not a co-authoring surface, and not a Canvas Suggestion Flow variant.
- **Panel is proposal-oriented before confirmation and command/receipt-oriented at the execution boundary.** These two layers coexist; neither removes the other.

This conceptual role is consistent with the shipped runtime contract below. The freeform path (PA2-FREEFORM) and the suggested-checkbox write-back (PA2-SUGGESTED-CHECKBOXES) are the current runtime realization of this model. The capability taxonomy section further below maps each Panel cognition path to its authority class.

For the interaction-surface authority contract, see:
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_PANEL_AUTHORITY_BOUNDARY.md`
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/NAME_THE_THREE_INTERACTION_SURFACES.md`

## PanelAgent Runtime V1 (current baseline)
- Panel should be read as the current mutation-capable interaction surface in the runtime.
- Runtime V1 uses a fixed mapping from panel actions to follow-up events (e.g., promotion intents) and writes receipts into an in-note AI status callout; the panel stays a small working set with no history.
- This is a simplified bridge/runtime loop, not the final agentic design; it keeps watcher and manual panel flows working while the agent migrates to LangGraph.
- Internal implementation now runs through a LangGraph-based control flow (`PanelAgentState`), but external behaviour and emitted events remain identical.
- Planner pipeline (opt-in, `PANEL_AGENT_PIPELINE=planner`): PanelAgent builds a `PanelActionIntent` and asks the Planner to create a plan for the selected actions. Plans can now be executed via the Orchestrator using the CLI (`python -m app.cli panel-orchestrate-plan --plan-id <plan_id>`), while the default direct path remains unchanged.
- Action catalog (`docs/settings/panel-actions.md`) is the canonical list of actions (id, kind, labels/synonyms, description/llm_hint, downstream event, params). Rule-mode matches checkbox labels deterministically; LLM-mode is opt-in and uses the catalog + panel/note context with checkboxes as hints.
- Checkboxes are treated as explicit consent; executed items remove their checkbox from the panel working set.
- The panel can also surface system-generated suggested actions as unchecked checkbox proposals when the runtime has a plausible action but should keep the human-facing approval step visible. That suggestion path is for proposal quality, not a blanket requirement that every low-risk action wait for manual review.
- Receipts live in the AI status callout (foldable) to acknowledge outcomes without bloating the panel history.
- The AI status callout is a bounded receipt surface, not the same thing as the metadata mirror.

## PanelAgent 2.0 (v5.6, accepted)

<!-- PA2-ENGINE-SEAM -->
**Engine-neutral cognition seam (shipped, v5.6 enabling).** Panel action selection is now invoked through a dedicated `PanelCognitionBackend` Protocol defined in `app/agents/panel_agent/cognition.py`. `graph.py` no longer owns cognition-selection concerns directly; it receives a backend through `build_panel_graph(cognition_backend=...)` and calls it via `_decide_actions_with_backend`. Current backends: `RuleCognitionBackend` (default, checkbox-driven) and `LLMCognitionBackend` (routes through `ReasoningFacade`). Parser, execution, receipt, and emitted-event contracts remain unchanged. A future backend (DeepAgents-style or otherwise) implements only `select_actions(state)` without reworking those surfaces. Tracked by: #244.

<!-- PA2-FREEFORM -->
**Freeform catalog-driven proposal path (shipped).** When a panel has an instruction but no checkbox actions, the LLM decider (`PANEL_AGENT_DECIDER=llm`) consults the full active catalog and proposes canonical action IDs from instruction text + catalog metadata (`llm_hint`, `labels`, `description`) alone, without requiring any checkbox-label match. Proposals are restricted to the active catalog; out-of-catalog IDs are dropped. Proposal-vs-execution boundary (hardened by #979): for governance-bearing capabilities (`capability_class: governed_execution` / `authority_class: governed_effect` per `docs/CAPABILITY_CONTRACT_MODEL.md`), freeform LLM proposals are written back as suggested unchecked checkboxes and surface a `panel.action.logged` event with `reason: proposal_offered`; the governed effect (e.g. `promote.intent.created`) does NOT fire in the same runtime pass. It runs only after explicit human confirmation on a subsequent pass. Non-governance-bearing classes (orientation / proposal / clarification / retrieval / synthesis_review / read-only) may still execute in the same pass. As of #982 the governance gate is data-driven: each catalog entry in `docs/settings/panel-actions.md` declares its `capability_class`, `authority_class`, and `requires_human_gate`, and `_is_governance_bearing` in `app/agents/panel_agent/graph.py` reads those fields from the active catalog rather than from a hardcoded action-id allowlist. The catalog also ships a minimal proposal-only cognitive capability set (`proposal.note_diagnosis`, `proposal.next_actions`, `proposal.clarifying_questions`, `retrieval.related_notes`, `note.summary.propose`) for orientation / retrieval / clarification / proposal moves; these surface bounded `panel.action.logged` receipts and never cross WriteGuard or the governance APPLY path. Fallback to rule mode on LLM error or empty catalog. Tracked by: #241.

- Surface uncertain or no-checkbox interpretations as suggested unchecked checkboxes instead of direct execution so panel ambiguity stays human-reviewable until explicit confirmation. Delivery receipt: Issue #242 delivered in current runtime behavior; follow-up wording reconciliation tracked by #291. Source Anchor: PA2-SUGGESTED-CHECKBOXES.
- Delivery receipt: Issue #240 accepted after a real-vault Alpha soak on 2026-04-08. Evidence came from the live server runtime on the Alpha vault: `settings-explain --json`, `status`, `/api/health`, `/api/status`, and `scripts.alpha_e2e` all agreed on the same runtime, and the soak produced a promotion-intent event on the Alpha runtime note. Source Anchor: PA2-REAL-VAULT-ACCEPTANCE. Tracked by: #240
- Emit ordered multi-step panel plans through the planner/orchestration contract rather than investing in richer LangGraph-only node choreography. Delivery receipt: Issue #243 delivered via PR #302. Source Anchor: PA2-MULTISTEP-PLANS.
- Broader PanelAgent expansion remains bounded beyond the current shipped slices. Treat any new behavior beyond the current slices as a separately scoped follow-up and break it into smaller issues before implementation.

<!-- PA2-OPTION-B -->
**Option B — Proposal generator + executor split (accepted decision, recorded from #977, 2026-05-16).** When `AI-åtgärder` is empty or insufficient and `AI-instruktion` is present, the accepted PanelAgent behavior is to treat `AI-instruktion` as a bounded proposal-generation input. The LLM decider writes safe, unchecked, AI-generated proposal actions into the panel working set. Key invariants: (1) generated proposals are always unchecked and distinguishable from human-authored actions, (2) generated proposals are idempotent on rerun and produce visible bounded feedback (proposal receipts), (3) **generated proposals must never execute or produce durable governance effects in the same runtime pass** — same-pass bounded receipts (e.g. `panel.action.logged` for proposal-only paths) are permitted; durable vault writes and governance-bearing execution remain limited to explicit, reviewable, checked actions that pass policy, allowlist/capability contract, WriteGuard, idempotency, and receipt rules. PanelAgent owns the first bounded implementation slice for this behavior; architecture leaves room to split proposal generation into a separate Planner/PanelGenerator if the behavior grows beyond a small proposal path. This decision is recorded here as the accepted contract; runtime implementation of the proposal-generation path follows in bounded follow-up issues.

Other implementation notes:
- Introduces an explicit `PanelAgentState` (note reference, panel intent, actions, history, policy) and drives behaviour from a LangGraph graph (e.g., `app/agents/panel_agent/graph.py`).
- LLM-based reasoning decides which panel actions to execute (and in what order) rather than relying on fixed mappings.
- PanelAgent Runtime V1 remains the baseline until the PanelAgent 2.0 path is fully implemented and operationally accepted. The real-vault acceptance receipt for #240 now closes that line for the shipped v5.6 path.
- LangGraph control flow supports a decider mode (`PANEL_AGENT_DECIDER=rule|llm`); `llm` is the default runtime posture for LLM-backed intent interpretation, while `rule` is an explicit opt-out for unit tests, CI, and other bounded deterministic validation lanes. Both modes route through the shared `ReasoningFacade` with the canonical `decide` task kind.
- The executed `cognition_mode` is included in the `panel.intent.executed` event payload and in `panel.log.created` entries so external consumers can observe which interpretation path was used.
- <!-- panel-agent-cognition-observability --> Bounded LLM-route observability (`cognition_metadata`) accompanies `cognition_mode` on `panel.intent.executed` and `panel.log.created`, and is mirrored onto the `panel.action.logged` receipts (`proposal_offered`, `no_actions_matched`) so runtime decisions stay debuggable. The metadata dictionary is bounded to scalar fields only and intentionally excludes prompt bodies, raw LLM output, and any secret material:
  - `cognition_mode` — `"rule"` or `"llm"`, mirrors the top-level field.
  - `route` — `"rule"`, `"checkbox"`, or `"freeform"`; identifies which selection pathway ran.
  - `provider` / `model` — taken from the most recent `ReasoningFacade` telemetry record for the call; `null` when the route did not invoke the facade.
  - `fallback_used` (bool) and `fallback_reason` (string or `null`) — `fallback_reason` is one of `instruction_hint_fallback`, `llm_error:<ExcType>`, or `no_catalog_available`.
  - `proposal_candidate_count` — raw count of action entries returned by the LLM.
  - `proposal_accepted_count` — count that mapped to canonical catalog IDs.
  - `proposal_rejected_count` — count dropped because they were missing/blank IDs or out of catalog.
  - `no_match` (bool) — `true` when the cognition decision produced zero accepted catalog actions (drives the `no_actions_matched` receipt).
- LLM-driven contract tests live under `tests/e2e/test_panel_llm_e2e.py` (gated by `@pytest.mark.panel_llm_e2e` and `PANEL_AGENT_LLM_E2E=1`) to validate end-to-end promotion/non-promotion scenarios (including the freeform no-checkbox path) using the real decider. Tests requiring deterministic rule-mode behavior explicitly set `PANEL_AGENT_DECIDER=rule`.
- Any future PanelAgent expansion beyond the current shipped slices should be decomposed via the issue/track flow first so the remaining work stays bounded and reviewable.

Direction note:
- the forward direction is richer cognition in support of Panel,
- but mutation authority remains bounded by policy, validation, deterministic note-writer paths, and downstream controlled execution.

<!-- capability taxonomy alignment -->
Capability taxonomy alignment (v6.x cognitive mediation, `docs/CAPABILITY_CONTRACT_MODEL.md`):
- Panel action selection maps to the **proposal** capability class: the agent proposes actions as unchecked checkboxes; the human confirms; governance gates apply on execution. No Panel cognition path collapses proposal into governed execution.
- Panel instruction parsing and checkbox interpretation map to the **clarification** capability class: they resolve ambiguity about what the human intends but do not assert intent on behalf of the human.
- Orientation signals available to Panel (note context, recent activity) map to the **orientation** capability class: read-only, no mutation.
- Execution of confirmed panel actions (e.g., promotion, frontmatter patch) maps to the **governance-bearing execution** capability class: requires the event envelope, policy gate, WriteGuard, and a receipt artifact.
- PanelAgent does not currently implement synthesis/review or repair/maintenance capability classes directly; those remain future-track work.
- LLM output from Panel cognition (LLM decider, freeform path) is always in the proposal or clarification class; it is never promoted to governed-execution authority without the human confirmation + policy gate step.
- See `docs/CAPABILITY_CONTRACT_MODEL.md` (`Cognitive mediation capability classes`) for the full taxonomy, authority/risk metadata fields, and composition rules.

## Panel syntax (Markdown)
- Panels are delimited by tolerant AI fences: any `%% ...ai... %%` (case-insensitive) line opens/closes a panel. First fence opens, second closes, third opens the next, etc.
- Inside a panel:
  - Instruction heading: `## AI-instruktion` (localized variants supported)
  - Actions heading: `## AI-åtgärder` (localized variants supported)
  - Checkboxes: `- [ ]` or `- [x]` (checked means run the action)
- AI status callout (foldable, outside the panel): `> [!info]- AI status` with receipt lines (`- ✅ ...` executed, `- ⏳ ...` queued, `- ⚠️ ...` fallback diagnostic with reason, `- 💡 Förslag: ... (väntar bekräftelse, ...)` proposal pending human confirmation, `- ℹ️ Inga åtgärder matchade ...` for a freeform no-op pass). The runtime appends receipts for executed/failed/proposal/no-match outcomes and trims to the last 20; already-executed IDs remove their checkbox from the panel on re-run. Proposal-offered receipts (#980) are emitted only when the proposal is newly inserted into the panel block; reruns over an already-proposed panel stay silent so the receipt block remains bounded and idempotent. Fallback receipts surface checked actions that did not execute (e.g. `unmapped_action`, `watcher_not_allowed`, `ambiguous_action`) and are idempotent on unchanged action; no-match receipts surface a freeform LLM pass that produced no actionable selection and are idempotent on unchanged instruction (#1012)—reruns do not emit new receipts or events so the receipt block remains bounded. Both also emit `panel.action.logged` events with the matching `reason` for downstream observability.
- This callout is a human-visible receipt overlay on the warm surface, not the canonical mirror artifact.
- Legacy notes that only use the headings without fences are still parsed; new panels should use fences.
- Panel content is not indexed or used as knowledge.

### Canonical confirmation semantics

The canonical human-facing confirmation signal for Panel execution is a checked Markdown task item:

```markdown
- [x] ...
```

inside a valid Panel `AI-åtgärder` section.

This signal is substrate-neutral. It may be produced by a human in Obsidian, by a plain text editor, by a CLI-compatible flow, by a watcher-compatible flow, or by a Companion UI action that asks the runtime to project the same checked checkbox state. All surfaces converge on the same semantics: the runtime observes a valid checked Panel action, validates it, and only then admits it to governed execution.

Companion UI read-mode clicks are an acceleration of this checkbox semantics. They are not a separate approval model. A browser click must not execute an agent action directly, must not mutate vault files directly, and must not become an authority store separate from the vault-visible Panel state.

Only task checkboxes inside a valid Panel `AI-åtgärder` section are eligible for Panel confirmation. Ordinary Markdown task checkboxes remain ordinary task checkboxes. Checkboxes inside fenced code blocks or other non-Panel regions are not Panel actions.

### Panel identity vocabulary

- `panel_id`: Runtime identifier for one parsed Panel block within one note/artifact. It scopes proposals and options but does not identify an option by itself.
- `proposal_id`: Identifier for one proposal-generation event or staged proposal set. It groups options produced together and may be useful for receipts or freshness checks, but it is not by itself the durable identity of an individual selectable checkbox option.
- `option_id`: Durable identity for one selectable Panel option line in `AI-åtgärder`. This is the identity a Companion UI projection request must target.
- `action_id`: Canonical catalog/runtime action identifier, such as `promote.evergreen`. Multiple options may map to the same `action_id` with different labels, parameters, evidence, or source locations.
- `ai:id`: Existing hidden Markdown marker used by current runtime idempotency/removal paths. Existing implementations may derive it from a label hash. Therefore it MUST NOT be treated as a durable `option_id` until this document explicitly promotes it and defines collision, duplicate-label, and migration semantics.
- `ai:proposed`: Existing hidden Markdown marker that means the checkbox was system-proposed and is still pending human confirmation. It is not a unique option identity.
- `source_line` / `source_range`: The source location of the option line in the current note content, using runtime-defined line/range indexing. It is a locator and freshness aid, not authority by itself.
- `source_hash` / `content_hash`: Hash over the current note content or over the relevant source range, used to reject stale UI projections. The hash proves the UI is acting on the same content snapshot the runtime validates; it is not an identity substitute.

Blocking identity decision: before Companion UI read-mode checkbox confirmation is implemented, the docs MUST decide whether `ai:id` is promoted to durable `option_id` with stronger generation rules, or whether a new explicit option marker such as `<!--ai:option_id=...-->` is introduced. Until then, Companion UI must not infer durable option identity from label text, rendered DOM position, or `ai:proposed`.

Recommended decision: introduce a new explicit `option_id` marker and leave `ai:id` as a legacy/current runtime idempotency and removal marker until the runtime is migrated.

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
> - 💡 Förslag: Gör denna anteckning evergreen (väntar bekräftelse, 2025-03-01 10:00)
> - ℹ️ Inga åtgärder matchade (2025-03-01 10:01)
> - ⚠️ Unmapped freeform request (unmapped_action, 2025-03-01 10:02)
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
  - `PANEL_AGENT_DECIDER=rule|llm` selects how actions are chosen (default `llm` for runtime; explicit `rule` opt-out for tests).
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
- `panel.action.blocked` — payload `{note_uuid, note_path, gate, reason, proposal_id}` (timestamp on outbox envelope) emitted when a confirmed action is blocked at a gate; checkbox is preserved in the working set (intention not acted upon). Delivered by #1057.
- `promote.intent.created` — payload includes `{note, panel, action, instruction, maturity}` plus `{action_id, intent_source="panel.note", note.path}`; emitted when a checked action has `intent_type: promotion`; downstream consumer uses `note.path` to patch the vault note frontmatter (for example `maturity: evergreen` plus a compatibility-mapped review posture).

## Wiring configuration
- Default wiring: `docs/settings/panel-action-wiring.yaml` (maps canonical action ids to target events).
- Resolution order: `PANEL_ACTION_WIRING_PATH` env override > `<vault>/System/Config/panel-action-wiring.yaml` (vault override) > repo default.
- Validation: config must define an `actions` list with `id`, `kind` (event|intent, defaults to event), and `event_type`/`target_event` (or `intent_type`). Unknown/invalid configs emit a warning and fall back to the default wiring; runtime behaviour stays unchanged.
- CI/operator validation path: run `python -m app.cli settings-validate` to validate panel action catalog entries, panel action wiring schema, and watcher settings schema before rollout.
- CLI/Watcher use the same wiring; panel decider (rule/LLM) still selects actions, wiring only controls emitted events.
- Guardrails remain unchanged: watcher auto-exec still requires `WATCHER_AUTO_EXEC=1`, only allows configured `auto_run.allowed_actions`, and preserves per-note opt-out via `ai_panel_auto_run: never`.

Promotion intents (`promote.intent.created`) represent intent-only; apply effects by running the promotion consumer (`python -m app.cli promote-consume`), which emits `promote.done` when successful and updates the vault note frontmatter via the note writer path, writing standing changes to `maturity` and review posture separately (Store updates remain optional).

## Capability taxonomy alignment

This section aligns PanelAgent's shipped runtime with the cognitive-mediation capability taxonomy in `docs/CAPABILITY_CONTRACT_MODEL.md`. It is documentary; it does not change runtime behavior, event payloads, the action catalog, or the panel syntax.

- Existing catalog actions (`promote.evergreen`, `note.archive`, `ingest.summary.create`, `note.move.workbench`) are `governance-bearing-execution` capabilities under the taxonomy. Their authority class is `governed effect`; their approval envelope is `panel-checkbox` (the human checks the box, the runtime emits the intent, the governed APPLY path applies the effect).
- PA2-FREEFORM is the catalog-driven proposal path. Proposals returned by the LLM decider for an instruction with no checkboxes are `proposal`-class outputs in intent-space (they originate as LLM-suggested actions without explicit human checkbox); they are written back as suggested unchecked checkboxes and do not execute in the same runtime pass (boundary hardened by #979; Option B decision recorded in #977). The approval envelope is `panel-checkbox`: the human reviews the suggested checkbox on a subsequent pass and explicitly checks it before execution enters the governed path.
- PA2-SUGGESTED-CHECKBOXES is the visible write-back contract for that same proposal-class output. The checkbox is the approval envelope; the explicit later human pass is the authority hop.
- Proposal-only cognitive capability classes (orientation, clarification, retrieval, synthesis, proposal) are represented in the action catalog as of #982. The minimum set delivered: `proposal.note_diagnosis`, `proposal.next_actions`, `proposal.clarifying_questions`, `retrieval.related_notes`, `note.summary.propose`. The freeform proposal path can now bind to these proposal-class targets directly. Their `panel.action.logged` receipt is the bounded surface the human reviews; admission to the durable surface still requires an explicit governance-bearing action.
- The capability metadata vocabulary (`authority_class`, `capability_class`, `risk_tier`, `reversibility`, `approval_envelope`, `side_effect_class`, `provenance_required`) is the authority/risk language new catalog entries are expected to populate. Existing entries remain valid without retroactive backfill.

This alignment does not claim shipped support for any capability class not already represented in the runtime, and it does not loosen Panel's mutation gating, WriteGuard, or governed APPLY contract.
