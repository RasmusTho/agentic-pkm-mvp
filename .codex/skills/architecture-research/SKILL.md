---
name: architecture-research
description: "Run a deliberate, evidence-based architecture research pass over the live system: parallel subsystem exploration, cross-system synthesis, research-question resolution, invariant extraction, and handoff to feature-breakdown. Produces an advisory audit doc in docs/audits/ and optionally a specification directory."
---

# Architecture Research

Use this skill for a deliberate research pass over the system's actual structure — code, contracts,
tests, and docs read together — when the goal is to find structural weaknesses, extract invariants,
and convert findings into a reconciled backlog. This is the workflow that produced
`docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md` and its specification directory
`docs/RUNTIME_CORRECTNESS_KERNEL/` (PR #2761 → issues #2762–#2777), made repeatable.

This skill produces analysis and backlog, never implementation. Its output is advisory until owner
or feature-breakdown machinery promotes it.

## When to trigger

Run an architecture research pass instead of incident-driven work when any of these hold:

- Repeated incidents share a structural root nobody has named (e.g. several "consumes nothing" /
  silent-divergence bugs pointing at the same substrate).
- A capability epic is about to be planned and the current-state evidence base is stale or
  contested — research first, decompose second.
- Owner docs, formal models (schemas, invariant registry), and runtime code have visibly drifted
  and the divergence set itself is the unknown.
- A window of strong-model capacity exists and the highest-leverage use is system-level analysis
  rather than one more slice.
- The owner asks a system-level research question ("what are the correctness conditions for X?")
  that no single owner doc answers.

Do **not** trigger for: a single bounded bug (use `bug-to-issue`), a known capability that just
needs decomposition (use `feature-breakdown` directly), or doc-freshness sweeps
(`temporal-doc-governance`).

## First context to load

- `AGENTS.md` (Dispatcher policy, Parallel-agent execution, `AGENTS.md :: Total Cost of Development`)
- `docs/DOCS_INDEX.md` — owner docs for every subsystem in scope; owner docs win over this audit
- `docs/architecture/SBS_OPERATING_MODEL.md` — subsystem boundaries used to cut explorer briefs
- `docs/testing/invariant-tests.md` — the existing invariant registry (extend, never fork)
- Prior audits under `docs/audits/` — format exemplars and reconciliation baselines
- `.codex/skills/feature-breakdown/SKILL.md` — the handoff target for backlog conversion

## Phase structure

The pass runs five phases in order. Phases 1–4 are analysis; phase 5 is the only one that touches
GitHub state.

### Phase 1 — Parallel subsystem exploration

- Cut the system into explorer briefs along subsystem/SBS boundaries (stores, event/outbox
  pipeline, LLM boundaries, eval framework, etc.), one explorer per brief. Explorers run in
  parallel in read-only mode.
- Each brief demands an **evidence-only** report: every claim carries a `file:line` anchor into
  the current `main` (or names the test/doc that proves it). No recommendations, no severity
  ranking, no prose-only claims — explorers report what *is*, not what *should be*.
- Explorers also report **divergences**: places where an owner doc, schema, or invariant registry
  says one thing and the code does another, each with both anchors.
- An explorer that cannot anchor a claim drops the claim.

### Phase 2 — Cross-system synthesis

- The coordinator merges explorer reports and looks for what no single explorer can see: shared
  root causes, split-truth substrates, silent-default patterns, enforcement that exists in tests
  but not in the runtime.
- Rank findings by **systemic impact (blast radius × silence of failure)**, not likelihood.
- Every synthesized weakness keeps its inherited anchors. If two explorer reports conflict, re-read
  the code — do not average.

### Phase 3 — Research-question resolution

- State the research questions the pass must answer (correctness conditions, scaling failure
  modes, determinism boundaries, ground-truth strategy — whatever the pass was chartered for).
- Answer each RQ explicitly from the synthesized evidence, in a dedicated section. An RQ with no
  evidence-backed answer is reported as open, not padded.

### Phase 4 — Invariant extraction

- Convert findings into named invariants with an **enforcement category** each:
  - `MUST` — fail-loud at runtime
  - `GATE` — CI/PR-blocking test
  - `DOCTOR` — detectable by read-only reconciliation
- For each invariant, note existing partial enforcement (`Exists — keep`, `Violated today` with
  anchor, `New`). Extend `docs/testing/invariant-tests.md` semantics; never create a competing
  registry.
- Identify the minimal kernel: the smallest invariant subset that carries the pass's correctness
  claims. Everything else is defense in depth and says so.

### Phase 5 — Disposition and backlog handoff (reconcile, don't duplicate)

- Record an explicit disposition for every finding before it can leave the advisory audit:
  accepted, rejected, deferred, or requiring an owner decision. Rejected and deferred findings do
  not enter backlog creation.
- For an accepted finding that crosses from research evidence into a normative specification,
  parent feature, or GitHub backlog, create and transition the existing BuilderOps
  `PromotionIntent` to `accepted` through `BuilderOpsPromotionGateway`. Its source references,
  target authority surface/ref, intended output, and accepted-transition `BuilderOpsReceipt` are
  the required handoff evidence. A research audit, task list, or chat transcript alone is not
  authority to invoke `feature-breakdown` or create a backlog artifact.
- Only after that accepted handoff evidence exists, convert the accepted findings into a
  dependency-ordered task list inside the audit doc, each task with `Verify:`-able acceptance
  kernel.
- **Reconcile against open epics and issues before creating anything.** Search existing epics,
  spec directories, and issues; where a task overlaps, extend or supersede explicitly (name the
  issue and which half stays where — see the audit's reconciliation-notes pattern) instead of
  filing a parallel hub.
- Hand the accepted-PromotionIntent-backed, reconciled backlog to
  `.codex/skills/feature-breakdown/SKILL.md` to produce the specification directory, parent
  feature issue, and child issues. Record their resulting source/result references, then use the
  same gateway to transition the intent to `promoted`. This skill does not file implementation
  issues directly.

## Working rules

- Evidence discipline is the contract: a finding without a `file:line` (or test/doc) anchor does
  not enter the audit.
- Where the audit and an owner doc disagree, the owner doc wins; raise the divergence via issue,
  never silently resolve it in the audit text.
- **SBS reconciliation (binding):** the audit carries an explicit SBS-reconciliation section — for
  every structural claim, state whether it **conforms to**, **extends**, or **proposes reshaping**
  `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` (and `docs/architecture/SBS_*`). Reshape proposals route
  through the SBS stewardship channel (CES / `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` /
  ADR + owner decision) — a research artifact never enacts or silently assumes a reshape.
  Precedent: `docs/architecture/runtime-semantics.md :: SBS boundary mapping`.
- Read the live code, not memory of it — anchors reflect `origin/main` at the audit date, and the
  audit header says so.
- Classify the pass per `issue-to-code`'s pre-implementation classification (this is Builder
  System work producing an advisory Product-analysis artifact); the audit itself changes no
  authority.
- Keep the pass bounded: charter the subsystems and RQs up front; scope creep in research is as
  real as in implementation.

## TCD guidance

Route capability per `AGENTS.md :: Total Cost of Development` — do not restate the policy. For
this skill specifically:

- Route the **root coordinator/synthesis role** to the current architecture-grade capability from
  the canonical ladder; do not hardcode a provider or generation here. It retains only the charter,
  RQs, subsystem map, contradiction ledger, synthesis, and invariant extraction.
- Give each genuinely independent subsystem a fresh read-only explorer with a minimal owner-doc,
  code, and test scope. Explorers may use cheaper capability when anchored evidence collection is
  mechanically verifiable; escalate only when the subsystem itself requires design judgment.
- Explorers return anchored facts and divergence receipts, not transcripts. One explorer may use at
  most one depth-2 helper for a bounded independent evidence question and remains responsible for
  its report.
- Emit a `tcd_plan` when chartering the pass. Count repeated input/context per explorer, preserve
  coordinator buffer for cross-system synthesis, and justify why fan-out beats one sequential read
  under `AGENTS.md :: Parallel-agent execution`.

## Output contract

- **Primary artifact:** an advisory audit doc at `docs/audits/<TOPIC>_<YYYY-MM-DD>.md` with the
  standard audit header (matching the existing docs under `docs/audits/`):
  - `State:` — advisory audit snapshot + date, subordinate to `docs/DOCS_INDEX.md` and owner
    contracts, pointer to any executable spec directory
  - `Doc role:` — Reference (audit snapshot)
  - `Authority:` — evidence-based structural analysis; anchors reflect `main` at the audit date;
    owner doc wins on disagreement
- Body sections follow the phase outputs: weakness analysis (ranked, anchored) → invariant set
  (with enforcement categories) → RQ resolutions → dependency-ordered backlog with reconciliation
  notes.
- Add the audit's row to `docs/DOCS_INDEX.md` (audit-snapshot format, see existing rows).
- **Optional secondary artifact:** a specification directory under `docs/<CAPABILITY>/` plus
  parent/child issues — produced via `feature-breakdown`, which owns that format.
- Publication routes through `.codex/skills/publish-pr/SKILL.md` (docs-authoring lane for the
  audit doc alone; the branch-truth gate applies as everywhere).

## Capturing learning

On a plan divergence (you did something unexpected, or discovered an earlier artifact was wrong),
route it through `capture-learning` — it owns the invocation timing and the "name an upstream
artifact or don't log" gate.
