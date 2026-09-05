---
name: learning-retrospective
description: "Read BuilderOps LearningSignal records, include historical docs/learning-log.md compatibility entries when needed, cluster signals by upstream artifact, and propose concrete edits or execute explicit autonomous maintenance when requested."
---

# Learning Retrospective

Periodic maintenance pass. Reads batched BuilderOps `LearningSignal` records and converts them into
concrete, actionable edit proposals for upstream artifacts.

This is Builder System learning governance. It may propose edits to `AGENTS.md`, `.codex/skills/**`,
Builder System owner docs, issue/PR templates, transition debt, fitness rules, roadmap entries, or
bounded GitHub Issues. It must not silently promote learning into runtime/user memory, HKA, MEM, or
Product behavior; any Product/Runtime effect must be routed through the Product System authority path
and SBS impact procedure in `docs/architecture/SBS_OPERATING_MODEL.md`.

Cross-cutting: when a clustered learning shows a capability-routing mistake (a task class under- or
over-modeled, or run at the wrong review/verification depth), surface it as a `tcd_retrospective` per
`docs/development/TOTAL_COST_OF_DEVELOPMENT.md :: Output blocks` (do not restate the schema here).
Wrong context topology is also a routing mistake: coordinator implementation, sibling-context reuse,
missing fresh issue context, unjustified helper/fan-out, repeated oversized input, coordinator-buffer
pressure, or a terminal receipt too weak to avoid reopening raw worker context.

`docs/learning-log.md` is historical/compatibility material after #1506. Read it only for
pre-BuilderOps entries or explicit compatibility fallback entries that are not yet represented as
`LearningSignal` records.

Select mode from the task: a request to handle the retro or improve the workflow authorizes
autonomous maintenance within its scope; an explicit review/proposal-only request produces
proposals. Do not require a second acceptance step for already-authorized safe repairs.

## Trigger

Run when the human requests a retrospective, or after approximately 10 delivery-learning
`LearningSignal` records have accumulated since the last retrospective receipt.

This is a cold-path repair step, not a hot-path delivery routine.

## Workflow

### Step 1: Read BuilderOps learning material

```bash
python -m app.builderops builderops list --type LearningSignal --json
python -m app.builderops builderops list --type BuilderOpsReceipt --json
python -m app.builderops builderops generate-projections \
  --type learning-summary \
  --output-dir tmp/builderops-learning-retro \
  --json
cat tmp/builderops-learning-retro/learning-summary.md
```

Use the generated `learning-summary` projection as the repo-readable review view, but treat
BuilderOps Vault as the source of truth. Projection Markdown is non-authoritative.
Before deciding which signals are unprocessed, filter the `BuilderOpsReceipt` records to
`event_type=learning_retrospective` and inspect their `target_refs` for already-processed
`LearningSignal` IDs. `LearningSignal` records are not mutated when a retrospective receipt is
appended, so the receipt stream is the processing ledger.

Declare the snapshot time, record count, date range, and requested scope. A full-history request
includes all LearningSignals, including previously processed records, plus all dated historical
compatibility entries. Prior receipts describe treatment; they do not exclude a signal from pattern
analysis. Recheck repairs against the current target branch, not a stale working checkout.

For an automatic cadence pass, fewer than 3 unprocessed signals may justify waiting. An explicit
human request proceeds regardless of count; do not add a confirmation gate.

Do not use raw `AgentWorklog` records as authoritative learning material. A raw worklog may support
a signal through `source_refs`; if it contains a durable learning, create or request a
`LearningSignal` first.

### Step 1b: Read historical compatibility entries only when needed

```bash
cat docs/learning-log.md
```

For an incremental pass, use the last retrospective marker to select new compatibility entries.
For a full-history pass, read all dated entries, including those before markers. Match represented
entries to their LearningSignal by provenance and divergence, and count a duplicate event once in
pattern totals. Preserve old entries. In autonomous maintenance mode, convert unmatched operational
fallbacks through `capture-learning` with stable idempotency keys when the configured store is
available. In proposal-only mode, propose the conversion without writing records.

### Step 2: Cluster by upstream artifact

Group signals by their `Upstream artifact` content or equivalent structured field. Example
clusters:

- `AGENTS.md §X` — entries pointing to AGENTS.md
- `.codex/skills/issue-to-code/SKILL.md` — entries pointing to the issue-to-code skill
- `task-contract template` — entries pointing to the issue body template
- `unknown — flag for retro` — signals where the artifact was unresolved at capture time

Prefer batching similar low-signal entries into one repair proposal when they point at the same upstream artifact.
Also compare repeated mechanisms across time and artifacts: a local wording fix may leave the
same failure elsewhere. Distinguish a missing rule from an existing rule that is ineffective,
contradictory, obsolete, or unnecessarily strict. Prefer deleting duplication or narrowing an
existing rule to adding another gate. Bound concurrency and threat assumptions to this owner's
supported deployment; do not introduce enterprise or adversarial guarantees without a concrete
in-scope requirement. A policy edit does not prove a reported runtime defect is fixed.

Full-history maintenance trace: 2026-09-05, owner request and historical compatibility review;
retain per-signal evidence and terminal outcomes in BuilderOps rather than another repo ledger.

Build the retrospective from LearningSignals, compact delivery receipts, and measured or named-proxy
`context_cost` data, not full historical chat transcripts. Independent clusters may use fresh
read-only analysis agents only when the expected synthesis benefit exceeds duplicated input context;
the root retrospective agent alone joins clusters and proposes upstream edits.

### Step 3: Propose concrete edits

For each cluster with 2 or more entries (or 1 entry with a strong, specific signal):

Write a concrete proposal. A proposal is one of:
- **Diff**: show the exact lines to add, remove, or change in the upstream artifact
- **Specific insertion**: quote the exact paragraph to add and state where it goes (before/after which section)

Do NOT write vague recommendations like "consider improving X" or "the skill could be clearer about Y". Every proposal must be concrete enough to be committed as a governance-lane PR without further design work.

Mark each proposal with:
- `[PROPOSE #N]` — numbered for human response
- The upstream artifact path
- The concrete edit text

### Step 4: Present proposals for human review

Output all proposals clearly. State:
- How many entries were read
- How many clusters were formed
- How many proposals are being made

In proposal-only mode, return the proposals for human review. In authorized autonomous maintenance
mode, continue directly to Step 5; do not request approval already supplied by the task.

### Step 5: Autonomous maintenance mode

Use this mode only when the human explicitly asks the agent to handle the retro end to end, improve the workflow, or create Issues for unresolved learnings.

In autonomous maintenance mode:
- apply only safe governance-lane edits whose upstream artifact is named by the LearningSignal or compatibility entry and whose exact repair is clear;
- verify whether any proposals were already applied by current repo reality before editing again;
- create canonical GitHub Issues via `learning-to-issue` for unresolved work, storage decisions, or changes that need human authority;
- do not change product/runtime behavior;
- do not record a retrospective completion receipt until every LearningSignal in scope has one
  terminal outcome: applied, already satisfied by repo reality, represented by an Issue, staged as a
  PromotionIntent, recorded as transition debt or fitness-rule work, or discarded/superseded by a
  receipt.

### Step 6: Record retrospective completion

Before appending a completion receipt, build an observe-only terminal-outcome ledger for the
processed signals. The ledger uses the terminal outcome vocabulary from
`docs/development/DELIVERY_FEEDBACK_LOOP.md :: Retrospective closure rule`:
`applied`, `already_satisfied`, `issue_created`, `promotion_pending`,
`debt_or_fitness_recorded`, and `discarded_or_superseded`.

```bash
python -m app.builderops builderops retrospective-closure check \
  --signals-file <signals.json> \
  --outcomes-file <outcomes.json> \
  --json
```

If `complete` is false, do not record a retrospective completion receipt. Resolve the listed
`unresolved_signals` first by applying the change, verifying it is already satisfied, creating an
Issue, staging a PromotionIntent, recording debt/fitness, or discarding/superseding it with a
receipt.

After the required proposal decision, or autonomous maintenance disposition, and once every
in-scope signal has a terminal outcome, append a BuilderOps receipt
targeting the processed LearningSignals (`<agent-id>` is the invoking agent, e.g. `codex`, `claude`).
Use the ledger's `receipt_body` or equivalent text so the receipt names the processed signal IDs and
their outcomes:

```bash
python -m app.builderops builderops append-receipt \
  --summary "Learning retrospective YYYY-MM-DD" \
  --event-type learning_retrospective \
  --actor "<agent-id>" \
  --occurred-at "<UTC timestamp>" \
  --target-ref "builderops_object:<learning-signal-id>" \
  --action retrospective_review \
  --receipt-body "<terminal-outcome ledger receipt_body>" \
  --idempotency-key "learning-retro:<YYYY-MM-DD>:<scope>" \
  --source-ref "builderops_object:<learning-signal-id>" \
  --json
```

Repeat `--target-ref` and `--source-ref` for each processed LearningSignal when practical. Where
N = accepted proposals and M = total proposals made.

Append the old `--- retro YYYY-MM-DD: applied N/M proposals ---` marker to `docs/learning-log.md`
only when the retrospective processed historical compatibility entries from that file.

In autonomous maintenance mode, N = entries with terminal outcomes and M = entries considered.
In an authorized maintenance task, invoke `publish-pr` for accepted governance changes and follow
its verification and closure chain before reporting those changes delivered.

## Success signal

After each retrospective, at least one upstream artifact should carry a dated edit traceable to a
LearningSignal, retrospective receipt, compatibility entry, or generated projection. If `AGENTS.md`
and skill prompts are static while LearningSignals accumulate, the retrospective step is broken.

## Capturing learning

On a plan divergence (you did something unexpected, or discovered an earlier artifact was wrong), route it through `capture-learning` — it owns the invocation timing and the "name an upstream artifact or don't log" gate.

## Output format

1. BuilderOps learning scope (LearningSignals read, date range, last retrospective receipt if known, historical compatibility marker if used)
2. Clusters formed (upstream artifact → entry count)
3. Proposals or autonomous actions (numbered, concrete, with artifact path and exact edit text or Issue receipt); when a cluster shows a task class was under/over-modeled, used the wrong context topology, or had the wrong review/verification depth, include a `tcd_retrospective` block using `docs/development/TOTAL_COST_OF_DEVELOPMENT.md :: Output blocks` and route its `routing_policy_update_recommendation` as a concrete proposed `AGENTS.md` or TCD-reference edit through the Step 3 proposal mechanic.
4. BuilderOps retrospective receipt, plus historical compatibility marker only if `docs/learning-log.md` entries were processed

## Workflow continuation

Follow `.codex/skills/README.md :: Workflow continuation`. In autonomous maintenance mode, invoke
`publish-pr` for applied governance changes and `learning-to-issue` for bounded unresolved repairs,
following authorized delivery through closure. Proposal-only scope returns proposals; accepted
proposals in an active maintenance task are executed in that task, not deferred to another agent
run.
