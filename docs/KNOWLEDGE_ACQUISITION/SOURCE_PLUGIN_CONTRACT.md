State: Specification (docs-authoring; target-state framing). Not implemented; YouTube is the first planned implementation.
Doc role: Capability contract
Authority: Defines the source-plugin interface for the Knowledge Acquisition Platform: identity, discovery, fetch, provenance, dedup, and sync-cursor semantics. Boundary-adapter classification is owned by `docs/INTEGRATION_FABRIC_CONTRACT.md`; acquisition sources do not cleanly fit any of its ten integration classes (class 6 Parser/OCR covers content extraction, not networked acquisition with discovery/egress/auth), so per that contract's own taxonomy rule this is flagged as a candidate new integration class for its owners to decide — this contract declares the equivalent contract fields in the meantime and does not extend the fabric taxonomy itself.

# Source Plugin Contract

A **source plugin** is the only YouTube-shaped (podcast-shaped, PDF-shaped, …) code in the
platform. Everything downstream of a plugin operates on source-agnostic artifacts. A plugin is an
External Boundary Fabric adapter: it has no semantic authority, produces ingestible content with
provenance, and never writes durable human meaning (`docs/INTEGRATION_FABRIC_CONTRACT.md`
§Authority rule).

## Plugin identity

Every plugin declares:

| Field | Meaning |
| --- | --- |
| `source_kind` | Stable identifier drawn from the `provenance.source_kind` vocabulary owned by `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md` / the taxonomy: reuse the existing value where one exists (e.g. `youtube_url`); a genuinely new source extends that vocabulary via an owner-doc edit, never by minting a token only here. |
| `capabilities` | Which optional operations it supports: `discover`, `captions`, `media`, `backfill`. A URL-only plugin may support none beyond `fetch`. |
| `egress_posture` | What the plugin talks to (hosts, auth mode: none / cookies / OAuth / API key) and its rate posture. Declared, not discovered — the operator can see every network dependency in one place. |
| `auth_degradation` | What still works when optional auth is absent or revoked. Authenticated capabilities MUST be degradable: their absence disables a capability, never the plugin. |

## Operations

Required:

- **`fetch(item_ref) → RawEvidence`** — acquire the content and metadata for one item (one video,
  one episode, one document). Output is the immutable Level-`raw` artifact defined in
  `REFINEMENT_PIPELINE_CONTRACT.md`, including full provenance and the plugin's `content_identity`
  (below). Fetch MUST be idempotent: re-fetching an unchanged item yields the same
  `content_identity`.

Optional (declared via `capabilities`):

- **`discover(cursor) → (item_refs, next_cursor)`** — enumerate new items from a followed
  collection (subscriptions, playlist, feed, directory). Discovery is metadata-only and cheap; it
  MUST NOT fetch content. The cursor is an opaque, durable, per-collection token (e.g. "newest
  published timestamp seen per channel feed") enabling incremental sync without re-enumeration.
- **`backfill(collection_ref) → item_refs`** — expensive full enumeration used rarely to repair
  gaps the incremental path missed. Separated from `discover` so cadence policy can differ
  (the convergent OSS pattern: cheap frequent incremental poll + rare full reconcile).

## Identity and dedup

- **`item_ref`** — source-native stable ID (YouTube video ID, podcast GUID, file content hash).
  Uniqueness scope is `(source_kind, item_ref)`.
- **`content_identity`** — hash of the acquired content itself. Distinguishes "same item, source
  re-fetched" (dedup: skip) from "same item, content changed upstream" (re-run refinement stages).
- Dedup is decided **before** fetch wherever the source allows it (discovery metadata), and always
  before refinement. An item already refined at the same `content_identity` is skipped with a
  trace, not silently.

## Provenance

Every artifact a plugin emits carries provenance, with each field group attributed to its actual
owner:

- **Note-level provenance block** — `source_kind`, source URL/locator, creator, publish date;
  vocabulary owned by `docs/CONTEXTUALIZATION_LAYER/LIFE_WIDE_ARTIFACT_TAXONOMY.md` /
  `ARTIFACT_METADATA_CONTRACT.md` and expressed as in the shipped vault templates.
- **Derivation fields** — where a derived artifact needs them, the fields
  `ARTIFACT_METADATA_CONTRACT.md` §11 defines (`source_refs`, `derived_from`,
  `derivation_method`, `generated_by`, `human_review`, `confidence`).
- **Acquisition lineage** — acquisition timestamp, acquisition method (values declared per source
  spec — consumers may weigh them differently), and plugin version; owned by
  `REFINEMENT_PIPELINE_CONTRACT.md` §Lineage.

Provenance is set at acquisition and never rewritten by later stages; stages append their own
lineage.

## What a plugin MUST NOT do

- Interpret content (no summarization, no extraction — that is the refinement pipeline's job).
- Write to the vault or companion notes (writeback is a pipeline stage with its own contract).
- Mutate triage state or any governance-bearing metadata (the fields
  `INGESTION_AND_TRIAGE_POLICY.md` §3 names).
- Hold authority over dedup outcomes (it supplies identity; the pipeline decides).
- Depend on another plugin.

## Adding a source

A new source is: one plugin implementation + one spec file in this directory naming its
`source_kind`, capabilities, egress posture, and any source-specific normalization notes. If adding
a source requires changing `REFINEMENT_PIPELINE_CONTRACT.md`, that is a contract defect to fix
explicitly — not a source-specific carve-out to add.
