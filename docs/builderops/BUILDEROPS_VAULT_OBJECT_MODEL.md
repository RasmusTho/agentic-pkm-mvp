State: Initial schema contract for BuilderOps Vault object semantics. Minimal store/CLI mechanics are implemented separately in `docs/builderops/BUILDEROPS_VAULT_STORE.md`; this document remains the object semantics contract and does not define API, MCP, promotion gateway, generated projection, migration, or product/runtime behavior.
Doc role: BuilderOps schema contract
Authority: Defines the initial BuilderOps Vault object model for #1500, subordinate to ADR-0010 for authority and promotion boundaries.
Owner: BuilderOps governance
Temporal class: strategic
Review cadence: event-driven
Source of truth: ADR-0010 plus issue #1500 until a later BuilderOps implementation owner exists
Last reviewed: 2026-06-01
Last verified against: docs/adr/ADR-0010-builderops-vault-authority-boundary.md, issues #1498/#1499/#1500/#1495, PR #1510

# BuilderOps Vault Object Model

## Authority Baseline

ADR-0010 is the authority baseline for this contract:

- BuilderOps governs the building system.
- Repo governs product/runtime truth.
- GitHub Issues and skills are BuilderOps surfaces.
- Promotion across authority classes is explicit.
- No silent authority transfer.
- Generated projections must identify themselves as projections.
- Raw agent worklogs belong in BuilderOps Vault by default, not reviewed repo docs, `$CODEX_HOME`, or local-only ignored state by default.

This document defines object semantics and schema fields for the initial BuilderOps Vault. Store and
CLI mechanics live in `docs/builderops/BUILDEROPS_VAULT_STORE.md`; this contract does not define
API/MCP access, migration logic, generated projections, promotion-gateway behavior, or
product/runtime authority changes.

The goal is a contract precise enough for implementations to use without redefining object meaning.
Leases, idempotency, concurrency, projection generation, promotion execution, and migration of
existing docs remain follow-on work.

No actual BuilderOps records are created by this document. YAML blocks are illustrative examples for
future implementers.

## Authority Classes

Every BuilderOps object carries exactly one `authority_class`.

| Authority class | Meaning |
| --- | --- |
| `raw` | Unreviewed builder-agent working material. It is useful for traceability but not durable repo truth. |
| `operational` | Work-coordination or maintenance state inside the BuilderOps operating plane. |
| `analytical` | Derived pattern, cluster, summary, or interpretation over raw or operational material. |
| `staged` | Explicit intent to cross an authority boundary, awaiting review or execution elsewhere. |
| `decision` | Explicit BuilderOps decision material. It governs the building system only unless promoted through repo authority. |
| `projection` | Generated view or exported summary. It is not authority by default and must identify itself as a projection. |
| `receipt` | Immutable or append-only record of a material transition, promotion, discard, projection, lease/idempotency event, or workflow decision. |

## Lifecycle States

Objects use the smallest lifecycle set that fits their type. The shared vocabulary is:

| Lifecycle state | Meaning |
| --- | --- |
| `draft` | Created but incomplete or not yet reliable for coordination. |
| `active` | Usable current BuilderOps material. |
| `review_pending` | Waiting for explicit review, acceptance, or promotion decision. |
| `accepted` | Accepted as BuilderOps material or a BuilderOps decision, without implying repo/product truth. |
| `promoted` | Explicitly moved or represented in a target authority surface through a PromotionIntent and receipt. |
| `projected` | Included in a generated projection that identifies itself as a projection. |
| `archived` | Retained for history; no longer active. |
| `discarded` | Intentionally rejected or dropped; the discard should have a receipt. |
| `superseded` | Replaced by a newer object or corrective receipt. |

Recommended transition shape:

```text
draft -> active -> review_pending -> accepted -> promoted
draft -> active -> projected
active -> archived
active -> discarded
active -> superseded
accepted -> superseded
```

Receipts are special: they are written once and then treated as immutable. A bad receipt is not
silently edited; it is superseded by a corrective receipt that explains the correction.

## Promotion Status

Every promotable object carries `promotion_status`. Objects that must never be promoted still carry
`promotion_status: not_promotable` so callers do not infer promotability from a missing field.

| Promotion status | Meaning |
| --- | --- |
| `none` | No promotion is currently being considered. |
| `not_promotable` | This object type or instance must not be promoted. |
| `candidate` | The object may deserve promotion, but no intent has been accepted. |
| `promotion_pending` | A PromotionIntent exists and awaits review or execution outside this object. |
| `promoted` | The promotion completed and has a receipt. |
| `rejected` | A promotion attempt was rejected without discarding the source object. |
| `discarded` | The source was intentionally discarded or found invalid. |
| `superseded` | Promotion or source meaning was superseded by newer material. |

Promotion is a boundary crossing, not synchronization. A promoted source remains traceable to its
BuilderOps object and receipt, but the target surface owns the resulting authority according to
ADR-0010.

## Common Field Model

The following fields define the common envelope. Individual object types below mark fields as
required, recommended, or optional. Do not mechanically require every common field for every object
when the object type says otherwise.

| Field | Shape | Meaning |
| --- | --- | --- |
| `id` | string | Stable opaque BuilderOps object identifier. Suggested prefixes are implementation details, but examples use readable prefixes. |
| `object_type` | string | One of the object types in this contract. |
| `authority_class` | string | One authority class from the vocabulary above. |
| `lifecycle_state` | string | Current lifecycle state from the allowed states for the object type. |
| `promotion_status` | string | Current promotion status. Required for promotable objects and set to `not_promotable` for non-promotable receipts. |
| `created_at` | RFC 3339 timestamp | Creation time. Prefer UTC. |
| `updated_at` | RFC 3339 timestamp | Last material update time. For receipts, this should equal `created_at` unless a corrective receipt supersedes it. |
| `created_by` | ActorRef | Human, agent, or automation identity that created the object. |
| `updated_by` | ActorRef | Human, agent, or automation identity that last changed the object. Recommended for mutable objects. |
| `summary` | string | Human-readable one-line or paragraph summary. |
| `body` or `content` | string or structured object | Main content. Name depends on object type. |
| `source_refs` | SourceRef[] | Provenance inputs for the object. Empty only for explicit bootstrap/genesis receipts with a reason. |
| `tags` | string[] | Search and grouping tags. |
| `related_issue_refs` | SourceRef[] | GitHub Issues related to the object. |
| `related_pr_refs` | SourceRef[] | GitHub PRs related to the object. |
| `related_doc_refs` | SourceRef[] | Repo docs, ADRs, skills, or AGENTS surfaces related to the object. |
| `related_ids` | string[] | Related BuilderOps object IDs. |
| `parent_id` | string | Parent BuilderOps object ID when the object is nested under another object. |
| `supersedes` | string[] | Object IDs superseded by this object. |
| `superseded_by` | string | Object ID that supersedes this object. |
| `promotion_refs` | PromotionRef[] | Promotion intents, target refs, and receipts. |
| `receipt_refs` | string[] | BuilderOpsReceipt IDs that record creation, transition, projection, promotion, discard, or supersession events. |
| `projection_refs` | ProjectionRef[] | Generated projections that include this object. |

### ActorRef

```yaml
actor:
  actor_type: agent | human | automation
  id: codex-session-2026-06-01
  display_name: Codex
```

### SourceRef

`source_refs` are the traceability backbone. They can point to GitHub, repo docs, BuilderOps
objects, generated projections, or external tools.

```yaml
source_ref:
  ref_type: github_issue | github_pr | repo_doc | adr | skill | agents_md | builderops_object | external_tool | generated_projection | receipt
  ref: "#1500"
  title: "type:task(builderops): define BuilderOps Vault object model and schemas"
  url: "https://github.com/RasmusTho/agentic-pkm-mvp/issues/1500"
  locator: "Acceptance Criteria"
  authority_surface: github | repo | builderops | projection | external
  observed_at: "2026-06-01T18:30:00Z"
```

Rules:

- `ref_type` and `ref` are required.
- `builderops_object` refs include local BuilderOps IDs such as AgentWorklog, LearningSignal,
  RetroCluster, PromotionIntent, and receipt IDs.
- `authority_surface` is recommended and should be explicit when crossing repo, GitHub, BuilderOps,
  projection, or external boundaries.
- `locator` is recommended for docs and issue sections.
- Source refs do not transfer authority. They only preserve traceability.

### PromotionRef

```yaml
promotion_ref:
  promotion_intent_id: prom_20260601_001
  target_surface: github_issue | pull_request | adr | owner_doc_writeback | skill_or_agents_proposal | generated_projection | discard_receipt
  target_ref: "#1501"
  target_authority_class: operational | decision | projection | receipt
  status: promotion_pending | promoted | rejected | discarded | superseded
  receipt_id: receipt_20260601_001
  promoted_at: "2026-06-01T19:00:00Z"
```

Rules:

- `promotion_intent_id`, `target_surface`, and `status` are required once promotion begins.
- A completed promotion requires a receipt.
- A rejected, discarded, or superseded promotion should also have a receipt.

### ProjectionRef

```yaml
projection_ref:
  projection_id: projection_docs_freshness_20260601
  projection_type: docs_index_summary
  generated_at: "2026-06-01T19:10:00Z"
  receipt_id: receipt_20260601_002
```

Generated projections must identify themselves as projections and must preserve provenance back to
their BuilderOps sources.

## Common Relationship Model

Use BuilderOps IDs for relationships between BuilderOps objects. Use `source_refs` for external or
authority-surface references.

- `parent_id`: the immediate parent object, such as a RetroCluster under a larger retrospective run.
- `related_ids`: peer or supporting BuilderOps objects.
- `supersedes` / `superseded_by`: replacement lineage.
- `promotion_refs`: boundary-crossing intents and outcomes.
- `receipt_refs`: material transition evidence.
- `projection_refs`: generated views that include this object.
- `related_issue_refs`, `related_pr_refs`, `related_doc_refs`: convenience references for common repo and GitHub surfaces. These should duplicate, not replace, the authoritative `source_refs`.

## Object Types

### AgentWorklog

**Purpose:** Capture builder-agent working context, local observations, task progress, failures,
decisions-in-progress, and handoff notes.

**Authority class:** `raw` by default. `operational` is allowed only when the object is explicitly
created as a curated handoff log. In both cases it is not product/runtime truth.

**Required fields:**

- `id`
- `object_type: AgentWorklog`
- `authority_class`
- `lifecycle_state`
- `promotion_status`
- `created_at`
- `updated_at`
- `created_by`
- `source_refs`
- `summary`
- `body`
- `task_context`
- `receipt_refs`

**Recommended fields:**

- `related_issue_refs`
- `related_pr_refs`
- `related_doc_refs`
- `tags`
- `worklog_kind`: `scratch | progress | failure | handoff | recovery`
- `observations`
- `progress`
- `failures`
- `decisions_in_progress`
- `handoff_notes`
- `next_steps`

**Optional fields:**

- `tool_refs`
- `environment_refs`
- `local_context_refs`
- `attachments`
- `confidence`
- `expires_at`

**Lifecycle states:** `draft`, `active`, `review_pending`, `promoted`, `archived`, `discarded`,
`superseded`.

**Source/reference fields:** Must cite the governing issue, PR, repo doc, ADR, skill, terminal/tool
reference, or prior BuilderOps object that produced the worklog. A local observation without an
external source still cites the task or session source that caused the observation.

**Promotion fields:** Promotable. `promotion_status` may move from `none` to `candidate`,
`promotion_pending`, `promoted`, `rejected`, `discarded`, or `superseded`.

**Receipt/trace relationship:** Creation, promotion, discard, archive, and supersession should each
have a BuilderOpsReceipt. High-volume progress updates may be batched under one receipt if the later
implementation supports batching.

**May be promoted, projected, discarded, or archived:** May promote to LearningSignal, GitHub Issue,
PromotionIntent, owner-doc writeback proposal, learning summary projection, or discard receipt. May
be projected into a work queue or handoff summary if the projection identifies itself as a projection.

**Must not do:** Must not become product/runtime truth, update repo docs, mutate GitHub Issues, or
rewrite skills/AGENTS by itself. Must not store secrets or private scratch material that should
remain outside shared BuilderOps state.

```yaml
id: awl_20260601_001
object_type: AgentWorklog
authority_class: raw
lifecycle_state: active
promotion_status: candidate
created_at: "2026-06-01T18:20:00Z"
updated_at: "2026-06-01T18:35:00Z"
created_by:
  actor_type: agent
  id: codex
summary: "Issue #1500 object-model drafting context"
task_context:
  issue: "#1500"
  branch: codex/docs-builderops-vault-object-model-1500
body: "Read ADR-0010, source docs, and issue contract; drafting schema-only object model."
source_refs:
  - ref_type: github_issue
    ref: "#1500"
    authority_surface: github
  - ref_type: adr
    ref: docs/adr/ADR-0010-builderops-vault-authority-boundary.md
    authority_surface: repo
tags: [builderops, schema-contract]
receipt_refs: [receipt_20260601_001]
```

### LearningSignal

**Purpose:** Capture recurring lessons, process failures, workflow improvements, review learnings,
or adoption signals from builder work.

**Authority class:** `operational` for a concrete delivery signal; `analytical` when the signal is
already summarized or interpreted across multiple sources.

**Required fields:**

- `id`
- `object_type: LearningSignal`
- `authority_class`
- `lifecycle_state`
- `promotion_status`
- `created_at`
- `updated_at`
- `created_by`
- `source_refs`
- `summary`
- `content`
- `signal_type`
- `receipt_refs`

**Recommended fields:**

- `tags`
- `related_issue_refs`
- `related_pr_refs`
- `related_doc_refs`
- `upstream_artifact_refs`
- `impact`
- `frequency`
- `suggested_action`
- `confidence`

**Optional fields:**

- `evidence_refs`
- `counter_evidence_refs`
- `applies_to_skills`
- `applies_to_docs`
- `expires_at`

**Lifecycle states:** `draft`, `active`, `review_pending`, `accepted`, `promoted`, `archived`,
`discarded`, `superseded`.

**Source/reference fields:** Should cite the AgentWorklog, PR, issue, review thread, learning-log
entry, or tool observation that generated the signal.

**Promotion fields:** Promotable to a learning summary projection, skill update proposal,
`AGENTS.md` proposal, GitHub Issue, RetroCluster, or discard receipt.

**Receipt/trace relationship:** Creation, acceptance, promotion, discard, and supersession require
receipt traceability. A learning signal created from multiple worklogs should preserve all source
refs or cite a RetroCluster source.

**May be promoted, projected, discarded, or archived:** May be promoted or projected. It may be
discarded when the evidence is invalid or already handled.

**Must not do:** Must not directly rewrite skills, `AGENTS.md`, issue templates, or repo docs. Must
not claim that one observation is recurring unless evidence refs show recurrence or the summary says
it is a one-off signal.

```yaml
id: lrn_20260601_001
object_type: LearningSignal
authority_class: operational
lifecycle_state: active
promotion_status: candidate
created_at: "2026-06-01T18:40:00Z"
updated_at: "2026-06-01T18:40:00Z"
created_by:
  actor_type: agent
  id: codex
summary: "Project status can drift from agent-ready labels"
signal_type: process_failure
content: "Issue #1500 had agent:ready but Project Status was Backlog after dependency completion."
source_refs:
  - ref_type: github_issue
    ref: "#1500"
    locator: labels/projectItems
    authority_surface: github
upstream_artifact_refs:
  - ref_type: skill
    ref: .codex/skills/issue-to-code/SKILL.md
tags: [github-governance, pickup]
receipt_refs: [receipt_20260601_002]
```

### RetroCluster

**Purpose:** Group related LearningSignals or AgentWorklogs into a pattern that is strong enough to
evaluate for system improvement.

**Authority class:** `analytical`.

**Required fields:**

- `id`
- `object_type: RetroCluster`
- `authority_class: analytical`
- `lifecycle_state`
- `promotion_status`
- `created_at`
- `updated_at`
- `created_by`
- `source_refs`
- `summary`
- `analysis`
- `cluster_subject`
- `member_refs`
- `receipt_refs`

**Recommended fields:**

- `tags`
- `related_issue_refs`
- `related_pr_refs`
- `related_doc_refs`
- `pattern_statement`
- `recommended_promotions`
- `affected_artifacts`
- `confidence`

**Optional fields:**

- `counterexamples`
- `time_window`
- `review_notes`
- `owner`

**Lifecycle states:** `draft`, `active`, `review_pending`, `accepted`, `promoted`, `archived`,
`discarded`, `superseded`.

**Source/reference fields:** `member_refs` names the LearningSignal and AgentWorklog objects grouped
by the cluster. `source_refs` may also cite the retrospective run, PRs, or issues that supplied the
raw material.

**Promotion fields:** Promotable to RoadmapExecutionItem, skill change proposal, docs update
proposal, GitHub Issue, BuilderDecision candidate, generated projection, or discard receipt.

**Receipt/trace relationship:** Receipts should record cluster creation, membership changes,
acceptance, promotion, discard, and supersession.

**May be promoted, projected, discarded, or archived:** May be promoted when a pattern needs action,
projected into retro summaries, archived after review, or discarded when the pattern is weak.

**Must not do:** Must not overrule the source objects, rewrite the learning log, or create product
roadmap truth by itself. It is analysis, not a decision or repo authority change.

```yaml
id: retro_20260601_001
object_type: RetroCluster
authority_class: analytical
lifecycle_state: review_pending
promotion_status: candidate
created_at: "2026-06-01T19:00:00Z"
updated_at: "2026-06-01T19:00:00Z"
created_by:
  actor_type: agent
  id: codex
summary: "Pickup-state drift during issue-backed work"
cluster_subject: issue_pickup_state
analysis: "Multiple signals show that label state and Project state can drift before implementation."
member_refs:
  - lrn_20260601_001
source_refs:
  - ref_type: builderops_object
    ref: lrn_20260601_001
tags: [retrospective, governance]
receipt_refs: [receipt_20260601_003]
```

### BuilderDecision

**Purpose:** Record explicit decisions about the building system.

**Authority class:** `decision`.

**Required fields:**

- `id`
- `object_type: BuilderDecision`
- `authority_class: decision`
- `lifecycle_state`
- `promotion_status`
- `created_at`
- `updated_at`
- `created_by`
- `source_refs`
- `summary`
- `decision_statement`
- `decision_scope`
- `decision_domain: builderops`
- `rationale`
- `receipt_refs`

**Recommended fields:**

- `tags`
- `related_issue_refs`
- `related_pr_refs`
- `related_doc_refs`
- `alternatives_considered`
- `consequences`
- `owner`
- `reviewers`
- `repo_authority_effect`: `none | proposal_required | promoted`
- `effective_at`

**Optional fields:**

- `expires_at`
- `supersession_policy`
- `open_questions`
- `implementation_followups`

**Lifecycle states:** `draft`, `review_pending`, `accepted`, `promoted`, `archived`,
`superseded`.

**Source/reference fields:** Must cite the issue, ADR, retro cluster, worklog, or human decision
source that led to the decision. If the decision references product/runtime surfaces, the refs must
show whether those surfaces are sources, targets, or non-authoritative context.

**Promotion fields:** Promotable when it affects repo authority. Targets include ADR/decision doc,
skill/AGENTS proposal, owner-doc writeback proposal, GitHub Issue, or PR. A BuilderDecision can also
remain accepted inside BuilderOps with `promotion_status: none` when it only governs BuilderOps.

**Receipt/trace relationship:** Decision acceptance and every promotion or supersession require a
receipt.

**May be promoted, projected, discarded, or archived:** May be promoted to repo decision surfaces
only through explicit PromotionIntent and repo gates. May be projected into decision summaries.

**Must not do:** Must not silently change product/runtime truth, product ADRs, current-state owner
docs, code, tests, or runtime behavior. Must distinguish BuilderOps decisions from product/runtime
ADRs.

```yaml
id: dec_20260601_001
object_type: BuilderDecision
authority_class: decision
lifecycle_state: accepted
promotion_status: promoted
created_at: "2026-06-01T15:30:00Z"
updated_at: "2026-06-01T15:42:05Z"
created_by:
  actor_type: human
  id: rasmus
summary: "BuilderOps Vault authority boundary"
decision_domain: builderops
decision_scope: "BuilderOps operating plane authority"
decision_statement: "BuilderOps governs the building system; repo governs product/runtime truth."
rationale: "Builder work needs shared operational state without silently mutating repo authority."
repo_authority_effect: promoted
source_refs:
  - ref_type: github_issue
    ref: "#1499"
    authority_surface: github
  - ref_type: adr
    ref: docs/adr/ADR-0010-builderops-vault-authority-boundary.md
    authority_surface: repo
promotion_refs:
  - promotion_intent_id: prom_20260601_010
    target_surface: adr
    target_ref: docs/adr/ADR-0010-builderops-vault-authority-boundary.md
    status: promoted
    receipt_id: receipt_20260601_010
receipt_refs: [receipt_20260601_010]
```

### PromotionIntent

**Purpose:** Represent an explicit intent to move BuilderOps material into another authority surface:
GitHub Issue, PR, ADR, owner-doc writeback, skill/AGENTS proposal, generated projection, or discard
receipt.

**Authority class:** `staged`.

**Required fields:**

- `id`
- `object_type: PromotionIntent`
- `authority_class: staged`
- `lifecycle_state`
- `promotion_status`
- `created_at`
- `updated_at`
- `created_by`
- `source_refs`
- `summary`
- `target_authority_surface`
- `target_action`
- `target_ref`
- `target_authority_class`
- `intended_output`
- `receipt_refs`

**Recommended fields:**

- `tags`
- `related_issue_refs`
- `related_pr_refs`
- `related_doc_refs`
- `requested_by`
- `review_required_by`
- `acceptance_criteria`
- `promotion_rationale`
- `risk_notes`
- `execution_blockers`
- `idempotency_key`

**Optional fields:**

- `expires_at`
- `approved_by`
- `rejected_by`
- `result_refs`
- `rollback_or_correction_refs`

**Lifecycle states:** `draft`, `review_pending`, `accepted`, `promoted`, `discarded`,
`superseded`.

**Source/reference fields:** Must include the BuilderOps source objects that would cross the
boundary. Must include any target issue/doc/ADR/skill refs if known.

**Promotion fields:** A PromotionIntent is the promotion staging object. It should use
`promotion_status: promotion_pending` while awaiting execution, `promoted` after the target update
is complete, `rejected` if review declines it, and `discarded` if the proper target is a discard
receipt.

**Receipt/trace relationship:** Creation, acceptance, execution, rejection, discard, and
supersession require receipts. Completed promotions record both the intent and target refs.

**May be promoted, projected, discarded, or archived:** May be executed by a later promotion
gateway, but this contract does not implement that gateway. May be projected into queues. May be
discarded or archived with a receipt.

**Must not do:** Must not execute promotion silently. Must not mutate GitHub, repo docs, skills,
ADRs, PRs, APIs, MCP surfaces, or generated projections by itself.

```yaml
id: prom_20260601_001
object_type: PromotionIntent
authority_class: staged
lifecycle_state: review_pending
promotion_status: promotion_pending
created_at: "2026-06-01T19:15:00Z"
updated_at: "2026-06-01T19:15:00Z"
created_by:
  actor_type: agent
  id: codex
summary: "Open follow-up issue for repeated pickup-state drift"
target_authority_surface: github_issue
target_action: create
target_ref: pending
target_authority_class: operational
intended_output: "Bounded GitHub Issue with Verify targets for pickup-state drift repair."
source_refs:
  - ref_type: builderops_object
    ref: retro_20260601_001
    authority_surface: builderops
promotion_rationale: "Pattern needs an executable task contract before workflow changes."
receipt_refs: [receipt_20260601_004]
```

### DocsFreshnessRecord

**Purpose:** Track review cadence, stale state, last review, next review, owner, and freshness
posture for repo docs. It supports future generated projections so `docs/DOCS_INDEX.md` can remain
stable while high-churn freshness state moves to BuilderOps Vault.

**Authority class:** `operational`. It is projection-support material, not the authoritative doc.

**Required fields:**

- `id`
- `object_type: DocsFreshnessRecord`
- `authority_class: operational`
- `lifecycle_state`
- `promotion_status`
- `created_at`
- `updated_at`
- `created_by`
- `source_refs`
- `summary`
- `doc_ref`
- `owner`
- `review_cadence`
- `freshness_posture`
- `last_reviewed_at`
- `next_review_due_at`
- `receipt_refs`

**Recommended fields:**

- `tags`
- `related_issue_refs`
- `related_pr_refs`
- `related_doc_refs`
- `last_verified_against`
- `last_verified_at`
- `stale_reasons`
- `freshness_evidence_refs`
- `projection_refs`
- `next_review_owner`

**Optional fields:**

- `review_notes`
- `posture_history`
- `blocked_by`
- `expiration_policy`
- `owner_doc_writeback_refs`

**Lifecycle states:** `draft`, `active`, `review_pending`, `projected`, `archived`, `discarded`,
`superseded`.

**Source/reference fields:** Must cite the doc path as `doc_ref` and a `source_ref`. It may cite
issues, PRs, runtime surfaces, or owner docs used to verify freshness.

**Promotion fields:** Usually not promoted as truth. It may create a PromotionIntent for an
owner-doc writeback proposal, GitHub Issue, generated projection, or discard receipt. Use
`promotion_status: none` when it only tracks freshness and `candidate` or `promotion_pending` when
the freshness finding needs action.

**Receipt/trace relationship:** Review, stale marking, projection inclusion, archive, discard, and
supersession should have receipts.

**May be promoted, projected, discarded, or archived:** May be projected into freshness dashboards or
generated docs summaries. May be archived or superseded when the doc is removed or ownership moves.

**Must not do:** Must not replace `docs/DOCS_INDEX.md`, rewrite a doc's role, claim freshness as
authoritative doc content, or change product/runtime truth. The authoritative doc remains the repo
doc itself plus its owner documents.

```yaml
id: docsfresh_20260601_001
object_type: DocsFreshnessRecord
authority_class: operational
lifecycle_state: active
promotion_status: none
created_at: "2026-06-01T19:20:00Z"
updated_at: "2026-06-01T19:20:00Z"
created_by:
  actor_type: agent
  id: codex
summary: "DOCS_INDEX BuilderOps ADR entry is current as of ADR-0010 merge"
doc_ref:
  ref_type: repo_doc
  ref: docs/DOCS_INDEX.md
  locator: "ADRs"
  authority_surface: repo
owner: "Documentation role map"
review_cadence: event-driven
freshness_posture: current
last_reviewed_at: "2026-06-01T19:20:00Z"
next_review_due_at: "2026-06-15T00:00:00Z"
last_verified_against:
  - ref_type: adr
    ref: docs/adr/ADR-0010-builderops-vault-authority-boundary.md
source_refs:
  - ref_type: repo_doc
    ref: docs/DOCS_INDEX.md
    authority_surface: repo
receipt_refs: [receipt_20260601_005]
```

### RoadmapExecutionItem

**Purpose:** Track active roadmap execution state, blockers, movement, next decision, owner, and
related issues/PRs. It supports future projections so `docs/ROADMAP.md` can remain strategic while
high-churn execution state moves to BuilderOps Vault.

**Authority class:** `operational`. It is projection-support material, not strategic roadmap
authority.

**Required fields:**

- `id`
- `object_type: RoadmapExecutionItem`
- `authority_class: operational`
- `lifecycle_state`
- `promotion_status`
- `created_at`
- `updated_at`
- `created_by`
- `source_refs`
- `summary`
- `roadmap_ref`
- `execution_state`
- `owner`
- `next_decision`
- `receipt_refs`

**Recommended fields:**

- `tags`
- `related_issue_refs`
- `related_pr_refs`
- `related_doc_refs`
- `blockers`
- `movement_log`
- `current_slice_refs`
- `parent_issue_refs`
- `dependencies`
- `projection_refs`

**Optional fields:**

- `target_window`
- `risk_notes`
- `acceptance_evidence_refs`
- `supersession_policy`
- `archive_reason`

**Lifecycle states:** `draft`, `active`, `review_pending`, `promoted`, `projected`, `archived`,
`discarded`, `superseded`.

**Source/reference fields:** Must cite the roadmap path or anchor plus related GitHub issues/PRs and
source docs that define the work. It may cite a RetroCluster or BuilderDecision when execution state
comes from a retrospective or decision.

**Promotion fields:** May promote to a GitHub Issue, roadmap owner-doc writeback proposal,
generated projection, BuilderDecision candidate, or discard receipt. Use `promotion_status: none`
while it is only tracking execution.

**Receipt/trace relationship:** Creation, major state movement, blocker changes, projection,
promotion, archive, discard, and supersession should have receipts.

**May be promoted, projected, discarded, or archived:** May be projected into execution dashboards or
generated roadmap execution views. May be archived when work closes or superseded when roadmap
strategy changes.

**Must not do:** Must not redefine roadmap strategy, mark product work shipped, close issues, or
alter `docs/ROADMAP.md` by itself. The roadmap remains the strategic authority surface.

```yaml
id: roadexec_20260601_001
object_type: RoadmapExecutionItem
authority_class: operational
lifecycle_state: active
promotion_status: none
created_at: "2026-06-01T19:25:00Z"
updated_at: "2026-06-01T19:25:00Z"
created_by:
  actor_type: agent
  id: codex
summary: "BuilderOps Vault child issue #1500 is active after ADR-0010"
roadmap_ref:
  ref_type: github_issue
  ref: "#1498"
  locator: "Suggested execution order"
  authority_surface: github
execution_state: in_progress
owner: "BuilderOps governance"
next_decision: "Review object model contract before minimal store/CLI implementation."
related_issue_refs:
  - ref_type: github_issue
    ref: "#1500"
source_refs:
  - ref_type: github_issue
    ref: "#1498"
  - ref_type: adr
    ref: docs/adr/ADR-0010-builderops-vault-authority-boundary.md
receipt_refs: [receipt_20260601_006]
```

### BuilderOpsReceipt

**Purpose:** Record material state transitions, promotions, discards, generated projections,
lease/idempotency events, and workflow decisions.

**Authority class:** `receipt`.

**Required fields:**

- `id`
- `object_type: BuilderOpsReceipt`
- `authority_class: receipt`
- `lifecycle_state`
- `promotion_status: not_promotable`
- `created_at`
- `updated_at`
- `created_by`
- `source_refs`
- `summary`
- `event_type`
- `actor`
- `occurred_at`
- `target_refs`
- `action`
- `receipt_body`
- `idempotency_key`

**Recommended fields:**

- `tags`
- `related_issue_refs`
- `related_pr_refs`
- `related_doc_refs`
- `previous_state`
- `new_state`
- `outcome`
- `supersedes_receipt_id`
- `correction_reason`
- `hash`

**Optional fields:**

- `external_receipt_refs`
- `tool_run_refs`
- `projection_refs`
- `retention_policy`

**Lifecycle states:** `active`, `archived`, `superseded`.

**Source/reference fields:** Must include source refs and actor identity. For a receipt that records
creation of another object, source refs include the object source material and `target_refs` include
the created object. For corrective receipts, source refs include the superseded receipt.

**Promotion fields:** Not promotable. Use `promotion_status: not_promotable`.

**Receipt/trace relationship:** A receipt is the trace object. It may reference earlier receipts, but
it is not silently rewritten. If wrong, a corrective receipt supersedes it.

**May be promoted, projected, discarded, or archived:** Must not be promoted or discarded silently.
May be projected into audit views. May be archived by retention policy while preserving integrity.
May be superseded only by a corrective receipt.

**Must not do:** Must not be silently edited, deleted, or rewritten. Must not itself perform the
state transition it records. Must not become a product/runtime receipt unless explicitly promoted
through repo/runtime authority.

```yaml
id: receipt_20260601_001
object_type: BuilderOpsReceipt
authority_class: receipt
lifecycle_state: active
promotion_status: not_promotable
created_at: "2026-06-01T19:30:00Z"
updated_at: "2026-06-01T19:30:00Z"
created_by:
  actor_type: agent
  id: codex
summary: "Created AgentWorklog awl_20260601_001"
event_type: object_created
actor:
  actor_type: agent
  id: codex
occurred_at: "2026-06-01T19:30:00Z"
target_refs:
  - ref_type: builderops_object
    ref: awl_20260601_001
    authority_surface: builderops
action: create
receipt_body: "Created worklog from issue #1500 drafting context."
idempotency_key: "object_created:awl_20260601_001"
source_refs:
  - ref_type: github_issue
    ref: "#1500"
    authority_surface: github
outcome: succeeded
```

## Contract Boundaries For Implementers

Future implementation issues may add storage mechanics, validation, indexes, leases, idempotency
rules, CLI commands, API/MCP exposure, promotion gateway behavior, or generated projections. They
must preserve these object semantics unless a later ADR or schema-contract update explicitly
changes them.

Implementation-specific IDs, table names, file paths, JSON Schema, Pydantic models, locking,
retention, encryption, redaction, batching, and indexing rules are intentionally out of scope here.

No BuilderOps object changes product/runtime truth unless an explicit promotion crosses into the
repo authority gate named by ADR-0010.
