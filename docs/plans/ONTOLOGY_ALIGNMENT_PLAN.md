State: Plan (ontology alignment work on top of the active SoT).

# Ontology Alignment Plan

## Purpose

This plan translates the new ontology and vocabulary contracts into a concrete documentation and runtime-alignment sequence.

It does not redefine the ontology.
Its role is to identify:
- which active documents should be revised first,
- which runtime contracts likely need clearer separation,
- which changes are naming/clarity changes versus deeper model changes.

Authoritative concept sources:
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`

## Current diagnosis

The highest current concept drift appears around:
1. `note`
2. `object`
3. `source`
4. `agent`
5. `review`
6. `promotion`
7. `memory`
8. `plan`
9. `action`

These terms are currently used across multiple ontology layers:
- actor,
- artifact,
- commitment structure,
- operation,
- state,
- transition,
- runtime representation.

Additional clarification candidates discovered during the first alignment pass:
- `Vault Note` likely needs explicit treatment in the ontology, not only in the vocabulary.
- `Artifact` versus `Projection` needs stronger separation.
- `Review`, `Promotion`, and `Maturity` appear semantically distinct even where the runtime currently compresses them.
- `Plan` likely needs a clearer split between commitment support and generated execution artifact.
- `Source` needs separation between epistemic artifact-role and operational emitter attribution.
- `System Artifact` may later need refinement into narrower subclasses such as receipt, mirror, and execution artifacts.

## Workstream A — Active SoT document rewrites

### Priority 1: terminology and ontology boundary

#### `docs/CORE_CONTRACT.md`

Why first:
- It currently compresses `note or object` into a single semantic phrase.
- This creates confusion between warm-surface artifacts and runtime/storage representations.

Required changes:
- Replace `note or object` wording with ontology-aware language.
- Clarify whether Core-6 applies to:
  - all cognitive artifacts,
  - only runtime-projected artifacts,
  - or only artifacts that cross the human/system boundary.
- Distinguish semantic contract from storage wording.

#### `docs/HUMAN-FLOWS.md`

Why first:
- It is the closest document to the actual domain.
- It currently over-compresses commitments, artifacts, proposals, and receipts into note-centric flows.

Required changes:
- Expand the framing from note-first to cognitive-work-first.
- Add commitment structures (`project`, `next action`, `review cycle`, open loops) where appropriate.
- Reduce ASK-centrality in the human framing.
- Clarify the panel as an interaction surface, not a knowledge artifact.

Status after first pass:
- A cautious first pass has been completed:
  - the doc now explicitly states that it is intentionally note-/vault-centric because those are the visible human surfaces in the current baseline,
  - it now points readers to the broader second-brain ontology,
  - it now states explicitly that ASK is only one current retrieval/synthesis surface and does not exhaust the domain.
- Follow-up still needed:
  - determine whether commitment structures should be made more explicit in the human-facing flow language,
  - determine whether creative and reflective work deserve dedicated flow subsections later.

#### `docs/AGENTS.md`

Why first:
- It currently uses `agent` primarily as an implementation/runtime term.
- It should be reconciled with the new ontological meaning of `System Agent`.

Required changes:
- Distinguish ontology-level `System Agent` from runtime component roles.
- Clarify which entries are true system agents versus deterministic components/pipelines.
- Separate role, agent, tool, and orchestration language more cleanly.

Status after first pass:
- A cautious first pass has been completed:
  - the doc now states explicitly that it uses `agent` in the architecture/runtime sense,
  - it now points to the ontology and vocabulary documents,
  - it now distinguishes the runtime coordination map from ontology-level `System Agent`,
  - and it now clarifies that some listed entries are closer to deterministic components than rich autonomous agents.

### Priority 2: architecture-language cleanup

#### `docs/ARCHITECTURE.md`

Why second:
- It mixes ontology, runtime wiring, and storage language.
- It uses `note`, `object`, and `agent` in compressed ways.

Required changes:
- Add explicit terminology note referencing `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`.
- Clarify when `object` means storage/runtime representation.
- Clarify when `note` means `Vault Note` versus any ingested artifact.
- Rephrase review/promotion where the intended meaning is transition/process rather than entity.

Status after first pass:
- A cautious first pass has been completed:
  - the doc now points explicitly to the ontology and vocabulary contracts,
  - it now includes architecture-first reading rules for `note`, `object`, `agent`, and transition language,
  - it now clarifies several runtime surfaces as projections/runtime objects rather than full artifact meanings,
  - and it now tightens the wording around the metadata mirror and vault-note boundary.
- Follow-up still needed:
  - decide whether `Vault Note` should become explicit enough in the ontology to be referenced directly in more architecture sections,
  - decide whether `Projection` should become a stronger recurring term across architecture/runtime docs,
  - revisit whether `store object` terminology should stay as-is in prose or be systematically qualified as runtime/store projection.

#### `docs/PROJECT_KERNEL.md`

Why second:
- It is already concept-level and now references the ontology.
- It should later be harmonized with commitment structures, metacognition, and broader second-brain framing.

Required changes:
- Expand wording that currently centers "personal knowledge system" into broader cognitive-work language where appropriate.
- Explicitly mention commitments, self-regulation, and review cycles in the product-level framing if desired.

## Workstream B — Runtime contract review

These are not immediate rename tasks.
They are concept-separation review points.

### Current findings from first seam review

The first runtime seam review confirms that several ontology clarifications are grounded in active
code rather than only in documentation drift:
- `app/ingest/vault_alpha.py` already treats the `Vault Note` as a distinct semantic path:
  frontmatter identity wins, mirror identity heals, and the note is then projected repeatedly into
  runtime stores, retrieval, and indexing.
- `app/planner/schema.py` uses `Plan` as an execution artifact keyed to `source_object_uuid`, not as
  the human ontology's broader commitment/project structure.
- `app/promotion/consumer.py` plus `app/services/note_update.py` currently compress promotion into
  `review_state` mutation, even when intent payloads speak about `maturity` or promotion.
- `app/services/note_log.py` is currently a mirror-path contract with future log ambitions, not yet
  a full receipt model.

These findings strengthen, rather than weaken, the pending ontology clarifications around:
- `Vault Note` as explicit class,
- `Artifact` versus `Projection`,
- `Plan` as execution artifact versus commitment structure,
- `Review` / `Promotion` / `Maturity` separation,
- `Mirror` / `Receipt` / `Execution Artifact` separation.

### Priority 1 runtime seams

#### `app/ingest/vault_alpha.py`

Observed issue:
- `note`, `kind="note"`, `review_state`, and store payload semantics are currently compressed together.

Review questions:
- Which parts represent the warm-surface `Vault Note`?
- Which parts represent runtime projection?
- Is `review_state` the right term for all current uses?

#### `app/events/types.py` and panel/promotion events

Observed issue:
- `promotion` vocabulary currently blends transition, intent, and result.

Review questions:
- Should event naming eventually distinguish:
  - transition intent,
  - transition execution,
  - transition receipt?

#### `app/planner/schema.py`

Observed issue:
- `Plan` mixes execution artifact semantics with note/decision/tool step kinds.

Review questions:
- Which plan constructs are commitment-ontology adjacent?
- Which are purely runtime execution artifacts?

#### `app/promotion/consumer.py`

Observed issue:
- Promotion is materially implemented as a review-state/frontmatter mutation.

Review questions:
- Is current `review_state` carrying too much semantic load?
- Should promotion/maturity/review be separated more explicitly later?

### Priority 2 runtime seams

#### `app/memory/store.py`

Observed issue:
- `memory` remains heavily overloaded.

Review questions:
- Is this cache/agent-memory, domain memory support, or historical terminology debt?
- Should it be narrowed to runtime memory terminology only?

#### `app/services/note_log.py`

Observed issue:
- The mirror/log vocabulary still carries older assumptions.

Review questions:
- Is this a `Mirror Artifact`, a `Receipt Artifact`, or both?
- Should logs/receipts be more clearly separated conceptually?

## Workstream C — Change categories

### Category 1: terminology-only changes

Safe early changes:
- clearer doc wording,
- added definitions,
- explicit qualification (`Vault Note`, `Source Artifact`, `System Agent`),
- comments and narrative corrections.

### Category 2: contract clarifications

Moderate-risk changes:
- changing what a field or event is claimed to mean,
- splitting compressed definitions in docs,
- adding stronger distinctions between role/state/transition.

### Category 3: representation changes

Higher-risk later work:
- renaming runtime payload fields,
- splitting state markers,
- changing event names,
- changing table or payload semantics.

These should happen only after the concept layer and contract layer are stable.

## Recommended execution order

1. Rewrite `docs/CORE_CONTRACT.md`
2. Rewrite `docs/HUMAN-FLOWS.md`
3. Rewrite `docs/AGENTS.md`
4. Perform terminology cleanup pass in `docs/ARCHITECTURE.md`
5. Revisit `docs/PROJECT_KERNEL.md` wording where second-brain / cognitive-work framing should be broadened
6. Review runtime seams (`vault_alpha`, planner, promotion, memory, note_log`) against the revised docs
7. Only then consider field/event/payload renames

Progress note:
- `docs/CORE_CONTRACT.md` has completed a first ontology-alignment rewrite.
- `docs/HUMAN-FLOWS.md` has completed a cautious first ontology-alignment pass.
- `docs/AGENTS.md` has completed a cautious first ontology-alignment pass.
- `docs/ARCHITECTURE.md` has completed a cautious first ontology-alignment pass.
- The next highest-value target is now either:
  - a second concept pass on `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`, or
  - runtime-seam review for `app/ingest/vault_alpha.py`, `app/planner/schema.py`, `app/promotion/consumer.py`, and `app/services/note_log.py`.

## Success criteria

Alignment work is successful when:
- active SoT docs use the same canonical meanings for `note`, `object`, `source`, `agent`, `review`, `promotion`, `memory`, `plan`, and `action`,
- ontology, architecture, and human-flows documents no longer silently collapse distinct ontology layers,
- runtime terminology drift is explicitly documented even where code is not yet changed,
- future schema/runtime discussions can begin from stable concepts rather than overloaded legacy words.
