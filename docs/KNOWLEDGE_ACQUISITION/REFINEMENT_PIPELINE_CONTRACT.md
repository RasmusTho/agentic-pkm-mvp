State: Specification (docs-authoring; target-state framing). The `raw` level and the deterministic `normalize` stage (rolling-cue dedup, detected language, `acquisition_method` propagation, quality note) are implemented (KA-01 `#2796`, KA-03 `#2798`, `app/knowledge_acquisition/`). The open extraction registry and its one worked-example extractor (`summary`) are implemented (KA-04 `#2799`, `app/knowledge_acquisition/extraction_registry.py`, `app/knowledge_acquisition/extractors/summary_extractor.py`): register/run without pipeline or plugin edits, lineage stamping (extractor id/version/model identity), and idempotent version-replacement semantics, all in-process (no durable persistence of extraction artifacts in this slice — see KA-05). The `candidate` level is implemented (KA-05 `#2800`, `app/knowledge_acquisition/candidate_writeback.py`: assembly + governed first-write-wins `youtube_source_note` writeback). Stage events, item-scoped dead-letters, and replay are implemented (KA-06 `#2801`, `app/knowledge_acquisition/stage_events.py` + `app/knowledge_acquisition/replay.py`): every stage transition emits one standard-envelope DB-outbox event with a deterministic (stage, stage version, `content_identity`) idempotency key (KERNEL-02 substrate), stage failures dead-letter item-scoped, and `python -m app.cli acquire-replay <raw_record_id> --assert-no-source-egress` replays every derived level from `raw` with zero source egress.
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
| `maturity` / `review_state` | knowledge standing / review posture | `STATE_AXES_CONTRACT.md` | never advanced or mutated on any existing artifact; the sole interaction is stamping the mandated initial non-authoritative posture on candidate artifacts the pipeline itself creates (§`candidate`) |

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
labels where available, chapter boundaries where available, an acquisition-method field (values
declared per source spec — e.g. YouTube declares `captions_manual` / `captions_auto` / `asr`; a
podcast source would declare its own, such as `publisher_transcript` / `asr`), and a quality note
(consumers may weigh acquisition methods differently). Normalization is deterministic: same
`raw` in, same `normalized` out. No LLM calls at this level.

### `extracted` — structured evidence, still source-bound

Extractor outputs (see §Extraction registry): structured statements about what the source
contains. Extractions are regenerable claims *about the source*, not knowledge: if the `raw`
content changes or an extractor improves, the level is re-run and replaced. Every extraction
carries the extractor id + version + model identity in lineage.

### `candidate` — queued for human triage

A candidate bundles selected extractions into the artifact shape the ingestion/triage policy
specifies — noting that the policy is itself docs-only, target-state: no runtime triage consumer
exists today, and the human review surface is the vault note itself. The candidate enters the
triage workflow at its initial state (`captured`) carrying the non-authoritative posture markers
policy §3 mandates for AI-generated content, with full provenance, written back through the
existing companion-note / vault mechanics named in the source spec. From this point the
ingestion/triage policy governs; the pipeline is done.

**Karakeep handoff extension (contract selected, runtime pending).** KMA-01 / issue #3372 fixes the
Mimer-side extension point as the shipped
`app.heimdal.candidate_projection.project_pending_candidates` path with its existing
`mimer.candidate_projector` cursor. A later implementation slice adds a source-discriminated
`reading_source_note` mapping with draft/review-required posture, deterministic first-write-wins
pathing, provenance survival, and WriteGuard materialization. It consumes only durable
`heimdal.observation.published.v1` evidence; it does not contact Karakeep, use companion capture, or
create another projector/cursor. See
`docs/KARAKEEP_MIMER_ACQUISITION/DEFINE_READING_SOURCE_AND_CANDIDATE_CONTRACT.md :: Additive Mimer candidate mapping`.

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

The declared input content type is **advisory-only by design**: `ExtractorSpec.input_content_type`
documents which normalized content type an extractor consumes, but the registry does not validate
it against the normalized payload. The current `normalized` shape (`NormalizedTranscript`) carries
no content-type discriminator to check it against, and only one normalized shape (transcripts)
exists today, so there is nothing to mismatch. Each extractor's own `run()` remains the fail-loud
boundary for a payload it cannot use. Enforcement is deferred, not accidental: revisit this once a
second normalized content type exists or pipeline wiring (KA-05 #2800 / KA-06 #2801) needs a
registry-level check.

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

- Advance triage state on any artifact, or mutate governance-bearing metadata (the fields
  `INGESTION_AND_TRIAGE_POLICY.md` §3 names) on any existing artifact. Stamping the mandated
  initial posture on candidate artifacts the pipeline itself creates (§`candidate`) is the sole
  exception.
- Promote anything, draft-or-otherwise, into `evergreen_note` / `synthesis_note` /
  `decision_record`.
- Create chunks, embeddings, or index entries directly — it hands normalized/extracted artifacts
  to the #2314 W3 spine through that epic's contracts.
- Contact the source: only plugins have egress.
