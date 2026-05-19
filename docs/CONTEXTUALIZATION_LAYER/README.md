State: Folder index for the Contextualization Layer docs (docs-only).
Doc role: Folder index
Authority: Lists the documents that make up the Contextualization Layer and the order in which they build on each other. Not normative on its own; authority lives in the individual documents.

# Contextualization Layer — Documents Index

This folder collects the docs that define the **Contextualization Layer**: the artifact classes, metadata contract, and companion-note pattern that the rest of the system builds context-handling on top of.

Each document here is intentionally narrow. None of them define a full ontology, governance / authority model, database schema, prompt template, or runtime implementation. Together they establish a shared vocabulary and a minimal contract surface that later capability specs and implementation lanes can attach to.

## Reading order

1. **[HUMAN_AND_AGENTIC_ARTIFACTS.md](HUMAN_AND_AGENTIC_ARTIFACTS.md)** — Initial artifact vocabulary. Names the three initial artifact classes (human knowledge, agentic memory, machine mirror), the bridge / assembly carve-out for context bundles, the "Markdown is the shared substrate, not the shared semantics" rule, durability tiers, and activation / use rights.
2. **[ARTIFACT_METADATA_CONTRACT.md](ARTIFACT_METADATA_CONTRACT.md)** — Minimal metadata contract. Names placement modes (inline frontmatter / companion metadata note / structured agentic artifact), shared minimal fields, and per-class metadata shapes for human knowledge, agentic memory, bridge / assembly (e.g. context bundles), and machine mirror artifacts.
3. **[COMPANION_NOTE_PATTERN.md](COMPANION_NOTE_PATTERN.md)** — Companion note pattern. Names placement options, required linkage fields, companion types, readability requirements, editability / conflict principles, and durability / sync posture for companion notes that absorb metadata the primary artifact should not carry.
4. **[ARTIFACT_LIFECYCLE_MODEL.md](ARTIFACT_LIFECYCLE_MODEL.md)** — Artifact lifecycle model. Names the lifecycle states, transitions, and class-specific applicability for human knowledge artifacts, agentic memory artifacts, bridge / assembly artifacts, machine mirror artifacts, and companion metadata notes. Separates lifecycle (state) from activation (use-right), the latter being deferred to a downstream contract.
5. **[EXAMPLE_FIXTURES.md](EXAMPLE_FIXTURES.md)** — Example fixtures. Provides concrete, instantiated examples of how the five artifact classes coexist in practice, using a three-day design scenario to walk through human knowledge, companion metadata, agentic memory, bridge / assembly, and machine mirror artifacts with example YAML and JSON.
6. **[CONTEXT_ACTIVATION_SEMANTICS.md](CONTEXT_ACTIVATION_SEMANTICS.md)** — Context activation semantics. Defines use-right semantics (`visible`, `retrievable`, `activatable`, `instructional`, `action_authorizing`) per artifact class and lifecycle state, the stale-but-visible vs activatable distinction, the unreviewed-memory hidden-authority guard, bridge-artifact assembly semantics, and recall explanation requirements.
7. **[LIFE_WIDE_ARTIFACT_TAXONOMY.md](LIFE_WIDE_ARTIFACT_TAXONOMY.md)** — Life-wide artifact taxonomy. Names the concrete artifact classes a life-wide PKM is expected to handle (ephemeral, operational, project, source, media, email, YouTube, contact, decision, reflection, evergreen, synthesis, companion, AI-suggestion, machine-mirror), and the conceptual separation between physical storage, human navigation, semantic artifact class, lifecycle, provenance, authority, and work relation. Docs-only; not a runtime contract.
8. **[MEDIA_ARTIFACT_CONTRACT.md](MEDIA_ARTIFACT_CONTRACT.md)** — Media artifact contract. Defines the five media artifact roles (`media_original`, `media_derivative`, `media_note`, `media_index`, `media_moc`), the recognized media subtypes (`personal_photo`, `project_evidence_photo`, `reference_image`, `screenshot`, `scan`, `receipt`, `manual`, `contract`), authority/provenance/privacy rules, metadata shape, and five representative examples. Extends Section 10 of the life-wide taxonomy into a dedicated contract surface. Docs-only.
9. **[INGESTION_AND_TRIAGE_POLICY.md](INGESTION_AND_TRIAGE_POLICY.md)** — Ingestion and triage policy. Defines the lifecycle state model (`captured`, `triaged`, `linked`, `promoted`, `archived`, `discarded`), per-pipeline capture-to-promotion flows for all major life-wide artifact classes (shopping, email, YouTube, books, photos/media, screenshots, receipts/scans, projects, evergreen, synthesis), and AI/governance boundaries for each transition. Docs-only.

## Cross-cutting concept contracts

These existing contracts under `docs/CONCEPTS/` remain authoritative for their own scope and are referenced from the layer documents above:

- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`
- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`
- `docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md`
- `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md`
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`

## What this folder is not

- Not a v6.0 capability spec breakdown; see the v6.0 capability specifications section of `docs/DOCS_INDEX.md` for those.
- Not a runtime implementation plan.
- Not a final on-disk layout decision.
