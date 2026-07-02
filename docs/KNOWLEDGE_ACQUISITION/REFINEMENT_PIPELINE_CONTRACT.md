State: Specification (docs-authoring; target-state framing). Not implemented.
Doc role: Capability contract
Authority: Defines the machine-side refinement stages, derived-artifact levels, lineage/replay semantics, and the extraction registry for acquired content. Triage states and promotion are owned by `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md`; state-axis semantics by `docs/CONCEPTS/STATE_AXES_CONTRACT.md`; event mechanics by `docs/EVENTS.md`. This contract must never be read as redefining any of them.

# Acquisition Refinement Pipeline Contract

The refinement pipeline is what happens between "a source plugin fetched an item" and "candidate
knowledge is queued for human triage." It is entirely machine-side: every artifact it produces is
derived, rebuildable, and non-authoritative.

## Axis disambiguation (read this first)

The community-standard framing ("raw → normalized → extracted → candidate → integrated →
evergreen" as one ladder) collapses four axes this repo keeps separate:

| Axis | Question it answers | Owner | This pipeline's relationship |
| --- | --- | --- | --- |
| **Refinement level** (this doc) | how far has the machine processed this acquired item? | this contract | defines `raw / normalized / extracted / candidate` |
| Triage state (`captured`…`promoted`) | where is the artifact in the human ingestion workflow? | `INGESTION_AND_TRIAGE_POLICY.md` | pipeline output enters at `captured`; pipeline never advances triage state |
| `lifecycle` (`ephemeral`…`rebuildable`) | how durable is this artifact? | `ARTIFACT_METADATA_CONTRACT.md` | all pipeline intermediates are `rebuildable`; the raw evidence record is retained per source spec |
| `maturity` / `review_state` | knowledge standing / review posture | `STATE_AXES_CONTRACT.md` | pipeline never reads or writes either |

"Integrated" and "evergreen" are **not** refinement levels. They live entirely in the existing
human-gated promotion path. **The pipeline ends at `candidate`.**

## Refinement levels

### `raw` — immutable acquired evidence

The source plugin's `fetch` output: content exactly as acquired (caption file, transcript, audio
reference, document bytes) plus source metadata and provenance. Immutable and versioned by
`content_identity`; a changed source yields a new `raw` record, never an overwrite. Replay of
every later stage starts here without re-contacting the source.

### `normalized` — machine-readable, nothing semantic

One source-agnostic shape per content type. For time-based media, the normalized transcript
carries: text segments with start/end times, language (detected, marked as detected), speaker
labels where available, chapter boundaries where available, an acquisition-method field
(`captions_manual` / `captions_auto` / `asr`), and a quality note (e.g. auto-caption vs manual vs
ASR provenance — consumers may weigh them differently). Normalization is deterministic: same
`raw` in, same `normalized` out. No LLM calls at this level.

### `extracted` — structured evidence, still source-bound

Extractor outputs (see §Extraction registry): structured statements about what the source
contains. Extractions are regenerable claims *about the source*, not knowledge: if the `raw`
content changes or an extractor improves, the level is re-run and replaced. Every extraction
carries the extractor id + version + model identity in lineage.

### `candidate` — queued for human triage

A candidate bundles selected extractions into the shape the triage flow already expects: an
artifact entering at triage state `captured` / review posture `unreviewed`, with
`authority.requires_review: true` and full provenance, written back through the existing
companion-note / vault mechanics named in the source spec. From this point the ingestion/triage
policy governs; the pipeline is done.

## Stage execution model

- Stages form a small DAG, not a strict line: `normalize` depends on `raw`; each extractor depends
  only on `normalized` (extractors are mutually independent and may run in parallel or not at
  all); `candidate` assembly depends on the extractions the source spec selects.
- Each stage transition emits an event on the existing outbox with the standard envelope
  (`docs/EVENTS.md`); handlers follow the correctness-kernel idempotency requirements
  (`docs/RUNTIME_CORRECTNESS_KERNEL/`, MANDATORY_OUTBOX_IDEMPOTENCY / HANDLER_IDEMPOTENCY_HARNESS)
  rather than inventing pipeline-local delivery semantics.
- A stage failure is loud and item-scoped: it dead-letters that item at that stage without
  blocking other items or other extractors.
- **Rejection is a first-class outcome.** Policy filters (wrong language, duplicate
  `content_identity`, below minimum duration, channel ignored) run as early as their inputs allow
  — most at discovery/metadata time, before content is fetched — and produce a trace, not silence.

## Lineage and replay

Every derived artifact records: the `raw` record's `content_identity` it descends from, the stage
+ stage version + (for extractors) model identity that produced it, and a timestamp. Invariants:

- Re-running a stage with unchanged inputs and unchanged stage version is a no-op (idempotent).
- Improving a stage re-runs that stage and its descendants only — never re-acquisition, never a
  provenance rewrite.
- Deleting every derived level and replaying from `raw` reproduces an equivalent result
  (rebuildable, consistent with the machine-mirror posture in
  `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md`).

## Extraction registry

An extractor is a registered unit: `(extractor_id, version, input: normalized content type,
output schema, model identity)`. The registry is **open by design** — the platform's value grows
by adding extractors, not by changing the pipeline. Adding one MUST NOT require touching this
contract, other extractors, or any source plugin.

Initial worked examples (chosen to prove the contract across output shapes — **examples, not a
definitive list**):

| Extractor | Output shape it proves |
| --- | --- |
| `summary` | free-text with confidence |
| `claims` | list of statements with source-position anchors (timestamps) |
| `entities` | typed references (people, works, technologies) for later SIP linking |
| `action_items` | task-shaped candidates that must NOT become tasks without triage |

Anticipated later extractors (questions, concepts/definitions, quotations, contradictions-with-
existing-notes, difficulty, …) register the same way. Extractor output that code branches on is
schema-constrained and validated per the correctness kernel's typed-LLM-boundary invariants
(STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN applies in spirit: schema mismatch is an explicit failure,
never a silent default).

LLM usage inside extractors follows `docs/LLM_ROUTING.md`; extractors declare their capability
class per `docs/CAPABILITY_CONTRACT_MODEL.md` (proposal-class cognition; never
governance-bearing execution).

## What the pipeline MUST NOT do

- Advance triage state, or write `lifecycle`, `authority`, `review_state`, `maturity`,
  `artifact_class` on any human artifact (AI must not silently mutate governance-bearing
  metadata — triage policy §3).
- Promote anything, draft-or-otherwise, into `evergreen_note` / `synthesis_note` /
  `decision_record`.
- Create chunks, embeddings, or index entries directly — it hands normalized/extracted artifacts
  to the #2314 W3 spine through that epic's contracts.
- Contact the source: only plugins have egress.
