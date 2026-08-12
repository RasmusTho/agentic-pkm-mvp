State: Current capability contract. The `raw`, deterministic `normalized`, open `extracted`, and governed first-write-wins `candidate` levels are implemented. Issue #4111 makes normalized transcript anchors and successful extraction runs durable as StorePort-backed derived artifacts, enforces declared required/optional materialization policy, and writes every fresh re-extraction against an existing candidate as a versioned create-once proposal companion. Stage events, item-scoped dead-letters, and `python -m app.cli acquire-replay <raw_record_id> --assert-no-source-egress` remain the shipped replay/receipt boundary; replay starts from immutable `raw`, never from a transcript derivative.
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
contains. Extractions are durable, rebuildable claims *about the source*, not knowledge. Each
fresh run is immutable and carries raw/normalized ancestors, exact transcript anchors, extractor
id + version, model identity, output, timestamp, and provenance-event lineage. A newer run becomes
the current proposal input without overwriting a prior run or any human-visible artifact.
Normalized identities, ordinary extraction identities, and restart-cache keys include the
immutable `raw_record_id`; equal content bytes from distinct source items never share lineage.

### `candidate` — queued for human triage

A candidate bundles selected extractions into the artifact shape the ingestion/triage policy
specifies — noting that the policy is itself docs-only, target-state: no runtime triage consumer
exists today, and the human review surface is the vault note itself. The candidate enters the
triage workflow at its initial state (`captured`) carrying the non-authoritative posture markers
policy §3 mandates for AI-generated content, with full provenance, written back through the
existing companion-note / vault mechanics named in the source spec. From this point the
ingestion/triage policy governs; the pipeline is done.

The shipped YouTube candidate writer preserves its deterministic path with a candidate-specific
local create-once helper. Existing regular targets are durably observed before render and
WriteGuard. Missing targets render without exclusion, then WriteGuard authorizes invocation-local
parent preparation and one hidden raw-FD stage that is file-fsynced, closed once, atomically
published without replacement, and parent-fsynced. Concurrent same-target attempts let the local
filesystem select one winner; different targets and unrelated governed writes remain independent.
Pre-publication failure is retryable from `raw`, while a post-rename fence failure preserves the
complete target for the next durable probe. This is not a generic KnowledgePort contract, a global
`Sources/` bootstrap invariant, or a migration of the Karakeep/Heimdal writers described below.

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

### YouTube Source Note v2 materialization policy

The shipped YouTube acquisition and queued-drain paths enforce these rules:

- Before execution, the note profile declares every selected extractor as either
  `required_for_materialization` or `optional_for_materialization`. Failure never assigns or changes
  that classification after the fact.
- Valid `raw` and `normalized` evidence are always required. A required extractor failure preserves
  successful outputs, emits its item-scoped dead-letter, and prevents a new candidate from
  materializing.
- An optional extractor failure preserves all successful required evidence and emits a durable,
  independently rerunnable failure receipt. If no required extractor failed, the candidate may
  materialize with an explicit degraded marker that names the unavailable section and its rerun
  handle.
- A failure cannot erase successful evidence or an already materialized candidate. Candidate
  assembly is terminal only after the governed note write has materialized; otherwise it remains
  visibly rerunnable.

## Lineage and replay

Every derived artifact records: the `raw` record's `content_identity` it descends from, the stage
+ stage version + (for extractors) model identity that produced it, and a timestamp. Invariants:

- An ordinary stage run with unchanged inputs and unchanged stage version resolves its durable
  result as a no-op across process restart. An explicit re-extraction appends an immutable run and
  a versioned proposal companion.
- Improving a stage re-runs that stage and its descendants only — never re-acquisition, never a
  provenance rewrite. A freshly executed ordinary extractor-version upgrade against an existing
  candidate also writes a versioned proposal companion; it never disappears as an
  `already_exists` no-op.
- Normalized and extracted payloads are schema-valid MetadataBundles classified as derived
  projections. Replay may persist them but never reads them as source authority.
- Deleting every derived level and replaying from `raw` reproduces an equivalent result
  (rebuildable, consistent with the machine-mirror posture in
  `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md`).
- Replay no-egress enforcement is context-local at canonical YouTube metadata, caption, fetch, and
  ASR seams. Overlapping replays remain independently blocked while concurrent non-replay
  acquisition is unaffected.

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
