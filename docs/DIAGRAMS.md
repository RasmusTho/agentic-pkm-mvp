# Diagrams

Visual references for the SoT v4.5 ingestion, store, and promotion flows. Rendered via Mermaid and exportable with `mmdc`.

<!-- SECTION:DIAGRAMS:BEGIN -->
## Ingestion → Stores → QA
```mermaid
flowchart LR
    CLI[CLI / API Source] -->|normalize| NORMALIZER[Normalizer Agent]
    NORMALIZER -->|save_object| OBJECTS[ObjectStore]
    OBJECTS -->|emit_outbox| OUTBOX[Index Outbox JSONL]
    OUTBOX -->|fan-in| VECTOR[VectorIndex]
    OUTBOX -->|provenance| REL[RelationIndex]
    VECTOR -->|hybrid_search| QA[QA Agent]
    QA -->|audit_log| AUDIT[Audit JSONL Buffer]
    QA -->|enforce_quality| GUARD[Guardrails]
    GUARD --> ANSWER[Answer + Sources]
```

## Promotion → Reasoning Prep
```mermaid
flowchart TD
    INTENT[promote.intent.created] --> PROMO[Promotion Agent]
    PROMO -->|validate cooldown| CHECK[Policy + cooldown]
    PROMO -->|update frontmatter| VAULT[ObjectStore]
    PROMO -->|emit provenance| REL2[RelationIndex]
    VAULT -->|emit_outbox=False| QUIET[(No loop)]
    PROMO -->|promote.done| OUTBOX2[Index Outbox]
    OUTBOX2 --> INDEXER[Index / Rerank Workers]
    REL2 --> REASON["Reasoning Layer (RDF/OWL draft)"]
```

### Export to PNG/SVG
1. Install Mermaid CLI locally: `npm install -g @mermaid-js/mermaid-cli`.
2. Copy a block into an `.mmd` file or run `mmdc -i docs/DIAGRAMS.md -o artifacts/docs-diagrams.svg --page --scale 1`.
3. Store exported images under `docs/diagrams/` if they should be versioned; CI only requires the source Markdown.
<!-- SECTION:DIAGRAMS:END -->
