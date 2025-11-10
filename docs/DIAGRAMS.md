# Diagram

Visual referenser för ingestion- och transcribe-flöden. Renderas som Mermaid och kan exporteras via `mmdc`.

<!-- SECTION:DIAGRAMS:BEGIN -->
## Ingestion → Index → QA
```mermaid
flowchart TD
    A[CLI Source\n(file/url/audio)] -->|normalize| B[Normalizer Agent\napp/agents/normalizer]
    B -->|classify| C[Classifier Agent\napp/agents/classifier]
    C -->|append_jsonl| D[Index Outbox\nINDEX_OUTBOX_PATH]
    D -->|fan-in| E[Hybrid Store\napp/retrieval/hybrid]
    E -->|hybrid_search| F[QA Agent\napp/agents/qa]
    F -->|enforce_quality| G[Guardrails\napp/quality/guardrails]
    G --> H[Answer + Sources]
    F -->|json_log/span| I[(Observability\napp/obs/log.py)]
```

## Transcribe pipeline
```mermaid
flowchart LR
    Y[URL/Fil] -->|yt-dlp| DL[Download Audio]
    DL -->|ffmpeg| WAV[16kHz wav]
    WAV -->|ASR (faster-whisper)| ASR[Segments + text]
    ASR -->|append_jsonl| OUT[Index Outbox\nkind=transcript]
    OUT --> STORE[Hybrid Store]
    ASR -->|return| CLI[CLI Response\n--json]
```

### Export till PNG/SVG
1. Installera Mermaid CLI lokalt: `npm install -g @mermaid-js/mermaid-cli`.
2. Kopiera blocket till en `.mmd`-fil eller använd `mmdc -i docs/diagrams/pipeline.mmd -o artifacts/pipeline.svg`.
3. `mmdc` läser även ur Markdown: `mmdc -i docs/DIAGRAMS.md -o artifacts/docs-diagrams.svg --page --scale 1`.
4. Lägg exporterade bilder i `docs/diagrams/` om de ska versionshanteras; CI behöver enbart källan.
<!-- SECTION:DIAGRAMS:END -->
