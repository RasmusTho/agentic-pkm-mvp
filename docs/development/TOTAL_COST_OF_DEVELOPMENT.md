State: Normative Builder System development reference. Not an auto-loaded instruction file.
Doc role: Detailed capability-routing policy subordinate to `AGENTS.md :: Total Cost of Development`.
# Total Cost of Development

Use this reference only when the selected workflow must choose capability or emit a TCD block. The
root instruction owns the early principle; this document owns the detailed decision rule and schemas.

## Decision rule

Capability means workflow/skill, configured Codex model, reasoning effort, context discipline, tool
choice, verification depth, and review gate. Optimize expected total cost per accepted delivery:

`TCD = model + reasoning + context + tools + parallelization + human time + rework + defects + delay + coordination`

Human time is the dominant term (`100 USD/hour` as the planning proxy). Spend more capability when
its incremental cost is lower than the human time, rework, defect, delay, and coordination it avoids.
Do not optimize for the cheapest isolated model run.

This is a single-operator project. Do not add multi-tenant, high-availability, pluggable-provider, or
enterprise coordination machinery unless the governing contract explicitly requires it.

## Capability selection

Resolve the model from current Codex configuration; never hard-code a provider, generation, or model
ID in workflow policy. Select reasoning and proof depth from risk:

- low reasoning: mechanical, local, deterministic, cheaply auto-verifiable work;
- medium reasoning: normal implementation, refactoring, test repair, and routine review;
- high reasoning: hard debugging, multi-layer changes, security/data/migration/concurrency/external
  boundaries, difficult test strategy, or consequential review;
- highest configured reasoning: architecture, broad migrations, complex state machines, or work where
  owner steering would otherwise exceed roughly 10-15 minutes.

The provider-neutral execution resolver may expose an explicit model choice within a capability
profile. For the `high-reasoning` / `sol` capability, `gpt-5.6-sol` remains the default and
`gpt-6-astra` is an opt-in selectable candidate. Both internal TCD decisions and external Codex
launcher invocations use the same declared census/resolver seam; workflow skills do not carry an
Astra-specific branch, and an undeclared model choice fails closed.

Escalate after two failed attempts or review rejects, unclear requirements, missing/hard-to-interpret
tests, high blast radius, non-trivial CI failure, or hard-to-assess residual risk. De-escalate when the
plan is mechanical, a focused test bounds the result, and no hidden correctness risk remains.

For external capacity pressure, follow
`docs/architecture/SBS_OPERATING_MODEL.md :: Provider-Capacity Admission Policy`. Capacity may defer
or downgrade suitable work; it never waives scope, CI, review, security, or merge requirements.

## Context and coordination

Count repeated input, agent starts, oversized context packs, compactions, and coordination as real
costs. Use a fresh issue context for independent non-trivial Issue work. Add a bounded read-only helper
only when its saved delay/rework/defect risk exceeds its added context and coordination cost.

Planning chooses capability and context topology separately from serial-versus-concurrent scheduling.
Verification may use stronger capability than implementation when that lowers hidden-defect risk.

## Output blocks

Emit only the block required by the active skill. Tier 1 or trivial work normally uses a one-line
capability/residual-risk note instead of a fixed schema tax.

### tcd_plan

```yaml
tcd_plan:
  task_summary:
  assumptions:
  complexity: low|medium|high|very_high
  risk: low|medium|high|critical
  verification_difficulty: easy|moderate|hard
  human_review_burden: low|medium|high
  defect_blast_radius: low|medium|high|critical
  budget_pressure: low|medium|high
  execution_context: coordinator_only|inline_deterministic|fresh_issue_agent
  issue_local_helper_budget: 0|1
  context_cost:
    measurement: estimated|actual|proxy
    input_tokens: <integer|unknown(reason)>
    agent_starts: <integer>
    context_pack_bytes: <integer|unknown(reason)>
    compactions: <integer|unknown(reason)>
  recommended_capability:
    workflow_or_skill:
    model_family:
    reasoning_effort:
    tools:
    github_context_required: true|false
  cheapest_acceptable_path:
  escalation_triggers:
  deescalation_triggers:
  review_gate:
```

### tcd_review

```yaml
tcd_review:
  verdict: accept|reject|accept_with_risk
  risk_level: low|medium|high|critical
  model_used:
  reasoning_effort_used:
  context_cost:
    measurement: actual|proxy
    input_tokens: <integer|unknown(reason)>
    agent_starts: <integer>
    context_pack_bytes: <integer|unknown(reason)>
    compactions: <integer|unknown(reason)>
  under_modeling_detected: true|false
  over_modeling_detected: true|false
  blocking_issues:
  non_blocking_issues:
  missing_tests:
  hidden_defect_risks:
  recommended_fixes:
  recommended_model_for_fix:
  recommended_reasoning_for_fix:
  residual_risk:
```

### tcd_retrospective

```yaml
tcd_retrospective:
  task:
  chosen_route:
  actual_iterations:
  estimated_human_minutes:
  model_used:
  reasoning_effort_used:
  context_cost:
    measurement: actual|proxy
    input_tokens: <integer|unknown(reason)>
    agent_starts: <integer>
    context_pack_bytes: <integer|unknown(reason)>
    compactions: <integer|unknown(reason)>
  under_modeling_detected: true|false
  over_modeling_detected: true|false
  missed_risk:
  routing_policy_update_recommendation:
  skill_update_recommendation:
```
