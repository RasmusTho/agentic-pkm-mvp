State: Proposal / alignment working note on top of active SoT.
Doc role: Design recommendation
Authority: Non-authoritative recommendation document that consolidates ontology/runtime findings before field or event renames.

# Runtime Ontology Normalization

## Purpose

This document translates the ontology-alignment work into concrete normalization recommendations for
the active runtime.

It does **not** redefine the active runtime contracts by itself.
Its role is to answer:
- which runtime terms are currently overloaded,
- which meanings should be separated first,
- which changes are documentation-only versus contract-level versus code-level,
- and which source of truth should win when current code and concept language diverge.

Related documents:
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`
- `docs/CORE_CONTRACT.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_MODEL.md`
- `docs/EVENTS.md`
- `docs/plans/ONTOLOGY_ALIGNMENT_PLAN.md`

## Executive summary

The active runtime currently compresses four concept families too aggressively:
1. `note`
2. `review_state`
3. `promotion`
4. `plan`

The deepest issue is not naming alone.
It is that the runtime still uses a few labels to carry several ontologically distinct meanings:
- human artifact versus runtime projection,
- review gate versus maturity/quality,
- transition intent versus transition execution versus transition result,
- human project/commitment versus execution plan.

The codebase is workable as-is, but the compression is now strong enough that further feature work
will likely compound confusion unless the boundaries are made more explicit.

## Findings by concept family

## 1. `note`

### Current reality

The runtime uses `note` for at least four different things:
- a human-facing vault markdown artifact,
- a mirror-backed ingest path,
- a store/runtime projection with `kind="note"`,
- an index/retrieval document with `kind="note"`.

Observed in:
- `app/ingest/vault_alpha.py`
- `app/services/vault_sync.py`
- store/retrieval/index call sites

### Source of truth

For meaning:
- the human-facing vault note is primary.

For runtime coordination:
- projected runtime/store/index records are secondary but necessary.

### Recommendation

Do not rename storage labels immediately.
First normalize the terminology in docs and comments:
- `Vault Note` = human-facing editable artifact
- `note projection` or `runtime note record` = store/index/runtime representation derived from a vault note

### Invariant

No runtime projection labeled `kind="note"` should be described as if it were the full ontology of
the human artifact it mirrors.

## 2. `review_state`

### Current reality

`review_state` is currently used as:
- a frontmatter field,
- a core-ish runtime field,
- a mutation target for planner actions,
- the durable sink for promotion outcomes in active code,
- a gate for whether agents may rewrite reviewed content.

Observed in:
- `app/ingest/vault_alpha.py`
- `app/services/note_update.py`
- `app/promotion/consumer.py`
- `app/agents/planner/graph.py`
- `app/services/vault_sync.py`
- tests and policy docs

### Source of truth

Current runtime truth:
- `review_state` is the active mutation/gating field.

Concept truth:
- review is not the same thing as maturity.
- review is not the same thing as promotion.

### Recommendation

Retain `review_state` as the review/write-safety axis.
Do **not** let it continue to stand in for maturity or promotion outcome by default.

Recommended normalized meaning:
- `review_state` answers: what is the current review/mutation-protection posture of this artifact?

Recommended examples:
- `draft`
- `provisional`
- `reviewed`
- `protected`
- `archived`

Avoid using `review_state` for values that really express maturity or role, such as:
- `evergreen`
- `reference`
- `external_raw`

### Invariant

`review_state` should primarily gate mutation and review posture, not carry all lifecycle semantics.

## 3. `maturity`

### Current reality

`maturity` exists in parts of the runtime and docs, but it is not consistently preserved as its own
axis.
Promotion payloads may carry `maturity`, but active promotion application often writes only
`review_state`.

### Source of truth

Concept truth:
- maturity is a distinct dimension of artifact development or standing.

Runtime truth:
- maturity is currently partial and secondary.

### Recommendation

Promote `maturity` to the canonical axis for knowledge-development standing when that meaning is
intended.

Recommended normalized meaning:
- `maturity` answers: how developed, stabilized, or enduring is this artifact in its domain role?

Recommended examples:
- `raw`
- `draft`
- `developing`
- `stable`
- `evergreen`

### Invariant

`maturity` should not be inferred solely from `review_state`, and `review_state` should not be the
only durable sink for maturity changes.

## 4. `promotion`

### Current reality

The runtime currently uses both `promotion.*` and `promote.*` event families.
At execution time, promotion often resolves into a mutation of `review_state`.

Observed in:
- `app/events/types.py`
- `app/promotion/consumer.py`
- `app/services/note_update.py`
- `app/agents/planner/graph.py`

### Source of truth

Concept truth:
- promotion is a transition family.

Runtime truth:
- promotion is partly modeled as intent and partly as direct state mutation.

### Recommendation

Normalize `promotion` as a transition family with three separable layers:
1. `promotion intent`
2. `promotion execution`
3. `promotion receipt/result`

Short-term recommendation:
- do not rename all events immediately,
- but establish that `promote.intent.created` is an intent event,
- `promote.done` / `promote.error` are execution-result events,
- and future human-legible receipts should be modeled separately from the low-level event stream.

Longer-term recommendation:
- reconcile `promotion.*` and `promote.*` naming families so that prefixes reflect one consistent
  layering model.

### Invariant

Promotion must remain a transition, not a durable entity and not merely a synonym for setting one
status field.

## 5. `plan`

### Current reality

The active runtime uses `Plan` for generated execution structures:
- planner outputs,
- orchestration steps,
- runtime mutation paths.

Observed in:
- `app/planner/schema.py`
- `app/domain/plan.py`
- `app/agents/planner/graph.py`

### Source of truth

Current runtime truth:
- `Plan` is an execution artifact.

Concept truth:
- human project/commitment structures are broader and different.

### Recommendation

Keep the active runtime `Plan` machinery, but define it explicitly as:
- `Execution Plan`

Do not let plain `Plan` in docs silently stand for:
- project,
- commitment,
- next action structure,
- review cycle,
- or human planning in general.

### Invariant

The existing `Plan` object should be interpreted as an execution artifact until a separate
commitment/project model exists.

## 6. `mirror`, `note log`, and `receipt`

### Current reality

The metadata mirror exists as a path contract and light ingest surface.
It is described as log-like, but it is not yet a fully realized receipt model.

Observed in:
- `app/services/note_log.py`
- mirror-writing paths in `app/ingest/vault_alpha.py`
- architecture and data-model docs

### Source of truth

Current runtime truth:
- the mirror is real but thin.

Concept truth:
- mirror artifact and receipt artifact are related but not identical.

### Recommendation

Separate these meanings in docs now:
- `Mirror Artifact` = portable machine-side projection
- `Receipt Artifact` = human-legible accountability object

Implementation can remain combined for a time, but the concepts should no longer be collapsed.

### Invariant

The metadata mirror must not be described as if it already were the complete receipt model.

## Recommended normalized axes

These are the recommended first-class axes for artifact semantics in the near-term model.

### Axis 1: review posture
- canonical name: `review_state`
- question answered: may this artifact be safely changed, and what review posture does it currently have?

### Axis 2: development standing
- canonical name: `maturity`
- question answered: how developed or enduring is this artifact in its domain role?

### Axis 3: policy routing
- canonical name: `kind`
- question answered: which policy profile applies?

### Axis 4: derived overlays
- examples: `zone`, salience, recency, relation-derived signals
- question answered: how should the system orient to this artifact right now?

## Recommended transition model

The following transition families should be kept distinct:

### Review transition
- changes review posture
- mainly affects mutation safety and approval state

### Promotion transition
- changes standing, role, or maturity
- may also trigger review-state changes, but is not reducible to them

### Refinement transition
- changes the artifact content or structure without necessarily changing maturity or review posture

### Archive transition
- changes accessibility or active exposure without redefining the artifact's meaning

## Recommended event layering

If the event model is normalized later, prefer these semantic layers:

1. intent event
2. execution event
3. receipt/result event

Example:
- `promotion.intent.created`
- `promotion.execution.completed`
- `promotion.receipt.created`

This is a recommendation, not active contract.

## Recommended execution order

1. Keep current runtime field/event names stable while documentation converges.
2. Clarify `review_state` semantics in docs and tests first.
3. Clarify `maturity` as a separate axis in docs and policy language.
4. Rename or wrap runtime planner docs so `Plan` is read as `Execution Plan`.
5. Decide whether mirror and receipt stay combined or split.
6. Only then consider field renames or event-family migration.

## Non-goals for the next pass

The next pass should **not**:
- rename every `kind="note"` in code,
- rewrite all event families,
- replace the current planner implementation,
- or force a schema migration before the concept contract is stable.

## Compact recommendation set

1. Treat `Vault Note` as a first-class human artifact.
2. Treat `kind="note"` runtime records as projections, not full ontology.
3. Narrow `review_state` to review/mutation posture.
4. Use `maturity` for development/standing semantics.
5. Treat `promotion` as a transition family, not a status field.
6. Treat current `Plan` as an execution artifact.
7. Separate `Mirror Artifact` from `Receipt Artifact` conceptually now.
8. Delay field/event renames until docs and tests converge on the same meaning.
