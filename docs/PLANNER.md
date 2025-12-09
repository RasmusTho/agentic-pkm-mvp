State: SoT v4.10 Reality-MVP (current core).
# Planner & Hierarchical Plans — Agentic PKM

Planner is the central orchestration agent inside Hugin. It turns high-level goals into explicit, structured plans, executes those plans through domain agents (Normalizer, Classifier, Indexer, Promotion, PanelAgent, etc.), evaluates outcomes, and re-plans when needed. Plans are hierarchical: complex goals are decomposed into sub-goals with their own sub-plans so work stays traceable and bounded.

Outbox and background workers continue to cover simpler, ambient flows; Planner owns complex, multi-step tasks that need ordered steps, progress tracking, and guardrails.

## 2. Core concepts

### 2.1 Plan
- Typed object stored in ObjectStore with Core-6 metadata (uuid, origin, created, updated).
- Key fields:
  - `uuid: str`
  - `parent_plan: Optional[str]` (null for top level)
  - `depth: int` (0 for top-level, parent.depth + 1 for sub-plans)
  - `goal: str`
  - `status: "planned" | "in_progress" | "done" | "failed"`
- Control/loop fields:
  - `steps: list[PlanStep]`
  - `replans_used: int`
  - `max_replans: int`
  - `executed_steps: int`
  - `max_steps: int`

### 2.2 PlanStep
- Node in a plan:
  - `kind="composite"` → sub-goal that should receive its own sub-plan.
  - `kind="primitive"` → concrete call to a domain agent/tool.
- Fields:
  - `id: str`
  - `kind: "composite" | "primitive"`
  - `goal: Optional[str]` (for composite steps)
  - `action: Optional[str]` (for primitive steps, e.g. `"reindex_note"`, `"promote_to_evergreen"`)
  - `target: Optional[str]` (e.g. note UUID)
  - `args: dict[str, Any]`
  - `state: "pending" | "in_progress" | "done" | "failed"`
- A `composite` step should eventually be associated with a sub-plan whose `parent_plan` is the parent plan’s `uuid`.
- A `primitive` step corresponds to a guarded call into a domain agent/tool; state transitions are driven by PlannerGraph execution and evaluations.

## 3. Hierarchical planning and loop bounds
- Plan → Act → Evaluate → Replan loop:
  - For a top-level goal (e.g. “Make note X evergreen”), Planner creates a top-level Plan (`depth=0`).
  - For each `PlanStep(kind="composite")`, Planner may create a sub-plan with `parent_plan` = parent `uuid` and `depth = parent.depth + 1`.
  - Each plan runs its own Plan → Act → Evaluate → Replan cycle.
- Loop bounds:
  - `MAX_PLAN_DEPTH`: maximum depth; at or above this depth Planner may only create primitive steps.
  - `MAX_STEPS_PER_PLAN`: upper bound for `plan.max_steps`.
  - `MAX_TOTAL_STEPS_PER_TASK`: global bound for total executed steps across a task/session.
  - `MAX_REPLANS_PER_PLAN`: upper bound for `plan.replans_used`.
- If a plan hits any of these limits without reaching `status="done"`, it must transition to `status="failed"` and escalate (log, mark for human review).

## 4. PlannerGraph and AgentState
- Planner is implemented as a LangGraph-based graph (`PlannerGraph`) with at least:
  - `planner_node` — creates/updates plans based on goals and observations.
  - `executor_node` — picks and runs steps (composite → sub-plan, primitive → tool/agent).
  - `evaluator_node` — inspects results, updates plan/step status, and decides whether to continue, re-plan, or fail the plan.
- PlannerGraph uses the shared `AgentState` schema, extended with planning fields:
  - `current_plan_id: Optional[str>`
  - `current_step_id: Optional[str>`
  - Optional counters/budget fields (total steps, tokens, cost).
- Other graphs (ASK, etc.) may reuse the same AgentState type, but Planner is the primary owner of the planning-related fields. PlannerGraph is designed to integrate with human-facing entrypoints (CLI, PanelAgent intents, etc.).

## 5. Guardrail layer around each agent step
- Every `primitive` PlanStep is executed through a shared guarded tool runner.
- Pre-guardrails:
  - Schema/type validation of tool arguments (Pydantic/JSON Schema).
  - Policy checks (e.g. “do not modify Tyr without explicit human confirmation”, “respect zone policies”).
  - Optional safety checks (prompt injection/dangerous commands when applicable).
- Post-guardrails:
  - Schema/type validation of tool results.
  - Quality checks relevant to PKM (frontmatter parseable, UUID-links intact, minimal relation completeness for evergreen/promotion).
  - Optional safety checks on outputs.
- `GuardrailDecision`:
  - `status: "allow" | "modify" | "block" | "fail"`
  - Optional `modified_args` / `modified_result`
  - `reasons: list[str]`
- Pre-guardrails can block or normalize before a tool runs; post-guardrails can reject or flag results. Planner/Evaluator consume guardrail decisions as part of observations when deciding to continue, re-plan, or escalate to a human.

## 6. Interaction with Outbox and other agents
- Planner is the primary orchestrator for complex, multi-step tasks (e.g. make a note evergreen, run metadata + relations + reindex).
- Outbox remains the audit/event log; state-mutating agents still emit events there, and Outbox triggers simple background jobs (periodic hygiene, trivial reindex).
- Complex flows should run through PlannerGraph rather than loosely coordinated outbox workers.
- Domain agents (Normalizer, Classifier, Indexer, Promotion, PanelAgent, etc.) are exposed to Planner as tools/subgraphs and continue to respect Store/Outbox contracts.
