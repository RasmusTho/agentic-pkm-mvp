State: Concept contract (forward line; not yet shipped) — defines the "moment" as a first-class vault-native artifact for the Contextual Relevance Engine.
Doc role: Core SoT (moment artifact)
Authority: Canonical definition of the moment artifact — its vault home, schema, provenance, receipt, lifecycle, and non-authoritative projection. Subordinate to the human-need brief `docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md` and to the artifact, companion-note, receipt, and cognitive-load contracts it composes; it does not override current runtime truth in `docs/STATUS.md` / `docs/ARCHITECTURE.md`. The relevance evaluator that *produces* moments and the scarcity gate that decides *whether to reach out* are defined separately (CRE-02); this contract defines only the artifact they exchange.
Owner: Product / Contextual Relevance Engine capability authority
Temporal class: strategic
Review cadence: event-driven
Source of truth: docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md
Last reviewed: 2026-06-13
Last verified against: docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md, docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md, docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md, docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md, docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md, docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md, docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md, docs/COGNITIVE_LOAD_PROJECTION_LAYER.md

# Moment Artifact Contract

## Purpose

The Contextual Relevance Engine produces **moments** — *the right thing surfaced at the right
moment, context-dependent* (`docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md` §1). A moment is the unit
the engine emits: a proposal that *this* deserves the human's attention *now* (or soon), carrying the
need it serves, the references it brings, an urgency assessment, and a lifecycle.

This contract defines the moment as a **first-class, vault-native artifact** so that the rest of the
capability has a concrete shape to produce, store, project, and govern. It is the foundation the
relevance evaluator, the scarcity gate, and both implementation slices build on (CRE-02..CRE-04).

A moment is a **projection / proposal, never silent truth.** It surfaces and links; it does not
mutate the human's notes, re-prioritize their work, or assert a fact. Materializing a moment is the
only durable effect it has, and that effect is governed (write guard + receipt).

## What a moment is — and is not

A moment **is**:

- a durable Markdown artifact in the vault (vault-first), so the UI is a projection of it, not the
  other way round (`docs/HUMAN-FLOWS.md` §13);
- a *system-emitted, non-authoritative* artifact — a new **artifact class** alongside the vault note
  (human-authored) and the companion note (system identity anchor) in the artifact-class dimension
  family of `docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md` §"Dimension families" (1);
- a composition of capabilities the system already names — orientation/resurfacing, the commitment
  layer, context dimensions, the context bundle — carried through the standard
  `trigger + context bundle + capability composition + policy + proposal/action + receipt + feedback`
  pattern of `docs/EMERGENT_FEATURES_MODEL.md`.

A moment **is not**:

- a notification. The *channel* a moment reaches out on (glance / in-app / OS push) and *whether* it
  may interrupt are decided by the reach-out/scarcity gate (CRE-02), not by the moment itself. A
  materialized moment with no reach-out is the normal, quiet case.
- a ranking or priority authority. A surfaced moment says "this may help you right now"; it never
  says "this is important / urgent / approved" about the human's own work
  (`docs/COGNITIVE_LOAD_PROJECTION_LAYER.md` §"Resurfacing mode").
- a copy of its sources. It references them with provenance; the source notes remain the authority.

## Schema

A moment is stored as Markdown with YAML frontmatter. The frontmatter is the machine-legible
contract; the body is the human-legible projection. Fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `uuid` | yes | Stable lineage identity. Lineage metadata only — **advisory, never a render or precondition gate** (a moment with a missing/!invalid uuid still renders; the uuid is for continuity, not authorization). |
| `type` | yes | Always `moment` — the artifact class. |
| `created` | yes | ISO-8601 emission timestamp. |
| `trigger` | yes | What in the context model produced this moment — the provenance of the "why now". `kind` (e.g. `start-of-day`, `pre-event`, `deadline-approaching`, `neglected-thread`, `declared-pattern`) plus an optional `source_ref` (vault path / commitment id / context signal). Time-based triggers may have no `source_ref`. |
| `need` | yes | The human need served, in salience vocabulary. `basis` ∈ {`open-loop-pressure`, `attentional-relevance`, `reorientation`, `commitment-risk`} (`docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`) and a one-line `summary`. |
| `surfaced_refs` | yes | What the moment brings: a list of references, **never copies**. Each carries `ref` (vault-relative path), `uuid` (source identity if known), and `why` — a short, pointer-first, source-linked "why now" (the `why_now` shape of `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md` §FA-5). |
| `urgency` | yes | The evaluator's **derived** urgency *assessment at emission* — not an authoritative intrinsic property of the artifact. `band` (an ordinal: `routine` < `timely` < `pressing` < `critical`), a `basis` (what drove it), and the `evaluator` id + cognition mode (`deterministic-fallback` \| `llm-cognition`). Salience/urgency is derived/provisional by contract; this records the assessment and its basis, never a truth claim. The scarcity gate (CRE-02) compares this to the current interruptibility threshold. |
| `context_snapshot` | yes | The context-model reading at emission, including the `interruptibility` value from `docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md :: Interruptibility`, and an optional `context_bundle_ref` (`docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`). The snapshot is provenance, not a live binding. |
| `lifecycle` | yes | One of `proposed` → `surfaced` → (`engaged` \| `dismissed` \| `deferred` \| `expired`). See §Lifecycle. |
| `authority` | yes | Always `non-authoritative`. |
| `authority_class` | yes | `proposal` — per the authority classes in `docs/COMPANION_UI_COGNITIVE_LOAD_OPERATING_MODEL.md`. Never `canonical`. |
| `receipt_ref` | yes | The receipt recording this moment's materialization (see §Receipt and governance). |
| `provenance` | yes | How it was produced: `produced_by` (relevance-evaluator contract id), `inputs_digest` (hash of the evaluator inputs for reproducibility/observability). |

`band` vs a continuous `0.0–1.0` scalar for `urgency` is a representation choice flagged for owner
ratification (see §Design choices for owner ratification). The ordinal band is the default because it
maps cleanly onto the reach-out ladder and resists false precision.

A worked example fixture is committed alongside this contract at
[`docs/examples/moment_artifact_example.md`](../examples/moment_artifact_example.md) so downstream
tasks (CRE-03/CRE-04) have a concrete shape to build against.

## Vault home and projection

A moment is a **system-owned** artifact, so it lives in the system plane of the vault, not in the
human's authored note tree — the same separation companion notes already use:

- **Home:** `<system_folder>/moments/<moment-id>.md`, where `<system_folder>` is the layout-configured
  system folder (e.g. `⚙️ System`), resolved the same way companion notes resolve theirs
  (`docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`; `get_vault_system_dir_rel()`). The path is
  layout-aware; vault settings may override it.
- **Projection:** the companion-UI "now" / glance surface renders moments **read-only**, as a
  projection of the vault artifact — never a second home for them. The renderer follows the
  read-only projection posture of `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md` and the workspace-state
  read-side aggregate rule; opening or following a surfaced reference is a read action, and any write
  routes through the governed path.

Keeping the moment in the system plane preserves source/projection separation
(`docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`): the moment is a projection *over* source
artifacts; those artifacts stay the authority.

## Provenance

Every `surfaced_ref` links back to its source note (`ref` + `uuid`) with a pointer-first `why`. A
moment never restates a source's content as new truth; it points. `provenance.produced_by` and
`provenance.inputs_digest` make the emission reproducible and inspectable, satisfying the
observability requirement the relevance-evaluator contract (CRE-02) will rely on. `trigger` and
`context_snapshot` record *why now*, so a reader can reconstruct the moment's basis without the
runtime.

## Receipt and governance

Materializing a moment is a durable vault write, so it **routes through the write guard and emits a
receipt** — there are no hidden writes. The receipt is the human-legible accountability record (what
moment was materialized, under what authority, on what basis, with what result), distinct from the
operational `OutboxEvent` trace, per `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`.
`receipt_ref` points to it.

Per the governance tiers settled in #1881 and summarized in the brief §4, **materializing a moment
and surfacing it are `Act` tier** (reversible, vault-internal, clear authority — the log + Git history
is the safety net). Routing a moment to a more capable agent for review is `agent-review`. No moment
may cause an external side-effect or an irreversible action — that is the `ask-you` tier and is out of
scope for the engine's core chain. **No moment ever triggers LLM-initiated external execution.**

## Lifecycle

A moment moves through a small, explicit lifecycle (an artifact lifecycle in the sense of
`docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md`):

- `proposed` — materialized by the evaluator; exists in the vault with a receipt; not yet shown.
- `surfaced` — rendered at the glance surface (or reached out, once CRE-04 exists).
- `engaged` — the human opened/acted on a surfaced reference.
- `dismissed` — the human dismissed it; recorded as engagement signal (feeds the future learned loop).
- `deferred` — the scarcity gate held it below the current interruption threshold; it waits at the
  glance surface and re-attempts when interruptibility rises. **Defer is timing, not deletion**
  (`docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md` §3.3) — a deferred moment is never silently dropped.
- `expired` — its window passed without engagement; retained as a durable artifact (audit/learning),
  not deleted by default.

State transitions that are durable emit receipts. Whether a transition is durable or runtime-only is
sharpened by the implementation slices, but the contract is that **suppression/deferral is a recorded
lifecycle state, not a drop.**

## Authority posture

This section is binding and stated explicitly:

- **Non-authoritative.** A moment is a proposal/projection. It is never silent truth, never a
  ranking/priority authority over the human's own work, and never a substitute for the source.
  `authority: non-authoritative`, `authority_class: proposal`.
- **Vault-first.** Every moment has a durable Markdown artifact in the vault; the UI is a projection
  of that artifact, not its origin.
- **Provenance-preserving.** Every surfaced reference links to its source with provenance; the moment
  records its trigger, need-basis, context snapshot, and producing evaluator.
- **Governed by construction.** The only durable effect — materialization — goes through the write
  guard and produces a receipt. No hidden writes; no LLM-triggered external execution; no bypass of
  provenance or authority boundaries. Because the moment rides the emergent-features composition
  pattern, it *cannot* bypass these by construction.

## One context model, two consumers

The same context model feeds two distinct consumers, and this contract is the seam between them:

- **Relevance** — *what to surface* — reads the context model and produces moments (their `need`,
  `surfaced_refs`, and `urgency`). Defined by the relevance-evaluator contract (CRE-02).
- **Interruptibility** — *whether and how to reach out* — reads the context model's interruptibility
  dimension and gates reach-out. Defined by the reach-out/scarcity gate contract (CRE-02) and carried
  here as `context_snapshot.interruptibility`.

The moment carries the relevance output and an interruptibility snapshot; it does **not** itself
decide reach-out. That keeps the artifact stable while the gate stays free to re-evaluate against the
*current* threshold (the moment's snapshot is provenance, not a binding).

## Design choices for owner ratification

The owner is the design control point. These choices are surfaced for ratification in PR review
rather than silently locked:

1. **Vault home** `<system_folder>/moments/<moment-id>.md` (system plane, companion-note-style) vs an
   alternative (e.g. a per-day moments log, or adjacency to the triggering note). Default: system
   plane, for clean source/projection separation.
2. **`urgency` representation** — ordinal `band` (`routine`/`timely`/`pressing`/`critical`) vs a
   continuous scalar. Default: ordinal band.
3. **Moment as a distinct artifact class** named `moment` (vs modeling it as a specialized companion
   note). Default: distinct class, because its lifecycle and authority differ from a companion note.
4. **Retention of `expired`/`dismissed` moments** as durable audit/learning artifacts vs pruning.
   Default: retain (cheap, and feeds the future learned-pattern loop).

## Out of scope

- The relevance evaluator that produces moments and the reach-out/scarcity gate that decides
  interruption — defined in CRE-02 (`docs/CONCEPTS/RELEVANCE_EVALUATOR_CONTRACT.md`,
  `docs/CONCEPTS/REACHOUT_AND_SCARCITY_GATE_CONTRACT.md`).
- Any runtime implementation, UI, evaluator code, or test (CRE-03/CRE-04).
- External calendar/email/location sources (deferred connector slice).

## Related docs

- `docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md` — human-need brief (§1, §3, §4).
- `docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md` — context/artifact dimensions, incl.
  [Interruptibility](CONTEXT_AND_ARTIFACT_DIMENSIONS.md).
- `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md` — relevance/urgency vocabulary.
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`, `docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md`,
  `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md` — artifact/companion model.
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` — receipt vs trace.
- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md` — non-authoritative projection + `why_now`.
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`, `docs/EMERGENT_FEATURES_MODEL.md` — composition seam.
- GitHub #1881 — governance tiers.
