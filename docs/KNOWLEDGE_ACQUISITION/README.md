State: Specification directory (docs-authoring; target-state framing). No implementation issues filed yet; issue extraction follows owner review via `feature-breakdown` / `docs-to-issue`.
Doc role: Capability specification directory
Authority: Defines the Knowledge Acquisition Platform capability boundary — source plugins, the acquisition refinement pipeline, and the extraction registry — and its reconciliation with existing owner contracts. It does not redefine ingestion/triage policy, the artifact taxonomy, state axes, promotion semantics, or the retrieval/embedding architecture; those remain with their owner docs.

# Knowledge Acquisition Platform

One reusable acquisition-and-refinement capability for external long-form sources, producing
derived, non-authoritative artifacts that feed the **existing** triage, promotion, and retrieval
architecture. YouTube is the first source instance and the proving workload; podcasts, conference
talks, PDFs/articles, RSS, and local media archives are later instances of the same contracts —
not new architecture.

This is a platform spec, not a YouTube-importer spec. Everything YouTube-specific lives in exactly
one file (`YOUTUBE_SOURCE_SPEC.md`); everything else is source-agnostic by construction.

## Capability boundary

In scope:

- **Source plugins** — a uniform contract for discovering and fetching content from an external
  source with provenance, dedup identity, and an incremental-sync cursor
  (`SOURCE_PLUGIN_CONTRACT.md`).
- **Acquisition refinement pipeline** — the machine-side stages between "a source item exists" and
  "candidate knowledge is queued for human triage": acquire → normalize → extract → candidate
  (`REFINEMENT_PIPELINE_CONTRACT.md`).
- **Extraction registry** — an open, extensible set of extractors over normalized content. The
  initial extractors (summary, claims, entities, action items) are worked examples that prove the
  contract, **not** a definitive list.
- Replayability and provenance: raw acquired evidence is immutable and re-runnable through
  improved stages without re-acquisition.

Out of scope (owned elsewhere — this directory links, never restates):

| Concern | Owner |
| --- | --- |
| Triage states, promotion, AI/human authority boundaries | `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md` |
| Artifact classes, lifecycle values, authority flags | `docs/CONTEXTUALIZATION_LAYER/LIFE_WIDE_ARTIFACT_TAXONOMY.md`, `ARTIFACT_METADATA_CONTRACT.md` |
| `review_state` / `maturity` semantics | `docs/CONCEPTS/STATE_AXES_CONTRACT.md` |
| Trust and authority semantics | `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md` |
| Chunking, embeddings, vector/lexical indexing, retrieval | epic #2314 and its owner docs (`docs/EMBEDDINGS.md`, W3 chunk/metadata spine) |
| Event envelope, outbox mechanics | `docs/EVENTS.md` |
| Store abstraction | `docs/contracts/STORE_PORT.md`, `docs/ARCHITECTURE.md` |
| Companion note mechanics | `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` |
| External-boundary adapter classes (parser/OCR etc.) | `docs/INTEGRATION_FABRIC_CONTRACT.md` |

**The platform ends at `candidate`.** Everything downstream of candidate production — human
review, promotion into durable Human Knowledge artifacts, evergreen standing — is owned by the
ingestion/triage policy (§6 promotion path) and the state-axes contract. The platform never
promotes, never mutates governance-bearing metadata, and never authors human takeaways. This is
the load-bearing reconciliation: the widely-copied community pattern ("raw → … → evergreen" as one
pipeline) collapses machine processing depth into human knowledge standing; Yggdrasil already
separates those axes, and this spec keeps them separated.

## Reading order

1. This README.
2. `RESEARCH_2026-07.md` — Phase 0 research memo: 2026 ecosystem survey, gap analysis against the
   existing repo assets, and the two decided mechanism questions (caption acquisition, subscription
   discovery). Context, non-normative.
3. `SOURCE_PLUGIN_CONTRACT.md` — the source interface every acquisition source implements.
4. `REFINEMENT_PIPELINE_CONTRACT.md` — stages, derived artifacts, events, replay semantics, and
   the extraction registry.
5. `YOUTUBE_SOURCE_SPEC.md` — the first source instance and the Phase 2 vertical slice.

## SBS classification

**Product / Runtime System** (spec only; this directory itself is CES practice surface).

- **EBF** — source plugins are External Boundary Fabric adapters (source/parser class).
- **DRI** — normalized/extracted artifacts are derived, rebuildable representations.
- **CAO** — extractors are non-side-effecting cognition producing proposals.
- **HKA / SIP / PDM** — touched only through existing contracts (companion notes, provenance,
  store); no new authority surface.
- **GOV / MEM** — untouched: promotion and memory semantics stay with their owners.

Write class: docs/spec only in this directory. Canonical control flow: `Capture / ingestion`
(`docs/SYSTEM_BREAKDOWN_STRUCTURE.md` §Canonical control flows) — capture creates draft/unknown
state, never canonical authority.

## Relationship to epic #2314 (no parallel hubs)

- Extraction and normalization outputs are **inputs** to the #2314 W3 chunk/metadata spine; this
  platform introduces no vector store, no lexical index, no graph store, and no embedding identity.
- Indexing/retrieval of acquired content is gated on #2314 Gate 0 (ingest/index substrate
  verification). Acquisition itself (discover → normalize → candidate, companion-note writeback)
  does not depend on Gate 0 and can land first.
- Anything this spec needs from retrieval it consumes through #2314's contracts when they land.

## Phasing

| Phase | Deliverable | Lane |
| --- | --- | --- |
| 0 | Research memo (`RESEARCH_2026-07.md`) | this docs-authoring PR |
| 1 | Platform contracts (this directory) | this docs-authoring PR |
| 2 | Vertical slice: one explicit YouTube URL → metadata → caption-first transcript → normalized artifact → one extractor → candidate + companion note, replayable | `feature-breakdown` after owner review; implementation issues TCD-routed |
| 3 | Generalize: second source (e.g. podcast RSS or local media file) implements `SOURCE_PLUGIN_CONTRACT` unchanged | issues after Phase 2 acceptance |
| 4 | Continuous discovery: subscription/playlist sync, scheduling, dedup at scale | last, by design |

Phase 2 is the TCD milestone: if the slice holds (provenance preserved, replay succeeds, candidate
lands in the existing triage flow), the platform contracts are proven before any breadth is built.

## Non-goals

- No new maturity ladder, no new triage states, no new authority classes.
- No auto-promotion of anything, ever (triage policy governs).
- No new storage, index, or event substrate.
- No commercial transcript/ingestion API dependency (see research memo §Commercial services).
- No claim that any of this is shipped; current shipped reality is only what
  `RESEARCH_2026-07.md` §Existing assets describes.
