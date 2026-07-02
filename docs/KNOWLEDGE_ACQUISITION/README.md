State: Specification directory (docs-authoring; target-state framing; filed via PR #2786). No implementation issues filed yet; issue extraction follows owner review via `feature-breakdown` / `docs-to-issue`.
Doc role: Capability specification directory
Authority: Defines the Knowledge Acquisition Platform capability boundary — source plugins, the acquisition refinement pipeline, and the extraction registry — and its reconciliation with existing owner contracts. It does not redefine ingestion/triage policy, the artifact taxonomy, state axes, promotion semantics, or the retrieval/embedding architecture; those remain with their owner docs.

# Knowledge Acquisition Platform

One reusable acquisition-and-refinement capability for external long-form sources, producing
derived, non-authoritative artifacts that conform to the **existing** triage, promotion, and
retrieval contracts (the triage policy is itself docs-only target-state; no runtime triage
consumer exists today). YouTube is the first source instance and the proving workload; podcasts, conference
talks, PDFs/articles, RSS, and local media archives are later instances of the same contracts —
not new architecture.

This is a platform spec, not a YouTube-importer spec. Everything YouTube-specific lives in exactly
one file (`YOUTUBE_SOURCE_SPEC.md`); everything else is source-agnostic by construction.

## Capability boundary

In scope:

- **Source plugins** — a uniform contract for discovering and fetching content from an external
  source with provenance, dedup identity, and an incremental-sync cursor
  (`SOURCE_PLUGIN_CONTRACT.md`).
- **Acquisition refinement pipeline** — the machine-side stages between "a source plugin fetched
  an item" and "candidate knowledge is queued for human triage": normalize → extract → candidate
  over plugin-fetched content (`REFINEMENT_PIPELINE_CONTRACT.md`; acquisition itself is a plugin
  operation, not a pipeline stage — only plugins have egress).
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
the load-bearing reconciliation; `REFINEMENT_PIPELINE_CONTRACT.md` §Axis disambiguation carries
the axis table and per-axis owners.

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

**Product / Runtime System** (spec only; this directory itself is CES practice surface). Classified
per `docs/architecture/SBS_OPERATING_MODEL.md` §4; the nearest current-to-target mapping analog is
the Watchers row ("source observation adapters" — EBF, SFC, DRI, OEF) in
`docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md`. SFC appears in that row for delivery/replay
semantics of observation events; for this platform those semantics are deliberately **not**
SFC-shaped: stage events ride the existing DB outbox under the correctness-kernel idempotency
invariants (`REFINEMENT_PIPELINE_CONTRACT.md` §Stage execution model), the `discover` sync cursor
is a plugin-local durable token rather than cross-device replication state, and file-sync is never
an execution bus. If acquisition state ever needs cross-device replication, that is an SFC
reconciliation to raise explicitly at that point.

- **EBF (primary)** — source plugins are External Boundary Fabric adapters. The SBS already places
  them here: EBF's enduring responsibility is "Boundary adapters for **sources**, providers, tools,
  editors, parsers, models, embeddings, and egress" (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md` §Level 2)
  — **no SBS reshaping is needed**. The only taxonomy gap is one level below the SBS:
  `docs/INTEGRATION_FABRIC_CONTRACT.md`'s ten integration classes do not yet cover networked
  acquisition (see `SOURCE_PLUGIN_CONTRACT.md`'s Authority header); that class decision belongs to
  the fabric contract's owners. The EBF boundary charter itself is Pending in
  `docs/boundaries/README.md`; its invariant — *external mechanisms do not become authority* —
  is already enforced by this spec's authority rules.
- **DRI** — `raw` / `normalized` / `extracted` artifacts are derived, rebuildable representations
  (write class: derived/rebuildable; never the only copy of meaning).
- **CAO** — extractors are non-side-effecting cognition producing proposals.
- **HKA / SIP / PDM** — touched only through existing contracts: the candidate companion note is a
  durable but **non-authority-bearing** vault write (write class: mechanical durable, through the
  governed vault-write mechanics — it carries `requires_review` and unreviewed posture, so it never
  constitutes accepted human knowledge); provenance/lineage per SIP contracts; machine-side records
  via StorePort (PDM).
- **GOV / MEM** — untouched: promotion and memory semantics stay with their owners.

Forbidden-dependency note (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md` Part 4): EBF provider/source
concepts must not leak into HKA/SIP/GOV semantics — plugin identity and acquisition mechanics stay
in EBF-owned artifacts; only vocabulary already owned by the taxonomy (`source_kind`) crosses.

Canonical control flow: `Capture / ingestion` (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md` §Canonical
control flows) — capture creates draft/unknown state, never canonical authority. Transition-debt
and fitness-rule impact of this docs-only PR: none; every Phase 2+ implementation issue carries its
own `SBS Impact` block per `SBS_OPERATING_MODEL.md` §5 (Definition of Ready).

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
| 0 | Research memo (`RESEARCH_2026-07.md`) | PR #2786 |
| 1 | Platform contracts (this directory) | PR #2786 |
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
