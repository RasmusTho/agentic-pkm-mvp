# Diagram

Visual referenser för ingestion- och transcribe-flöden. Renderas som Mermaid och kan exporteras via `mmdc`.

<!-- SECTION:DIAGRAMS:BEGIN -->
## Ingestion → Index → QA
```mermaid
flowchart TD
    A["CLI Source<br/>(file/url/audio)"] -->|normalize| B["Normalizer Agent<br/>app/agents/normalizer"]
    B -->|classify| C["Classifier Agent<br/>app/agents/classifier"]
    C -->|append_jsonl| D["Index Outbox<br/>INDEX_OUTBOX_PATH"]
    D -->|fan-in| E["Hybrid Store<br/>app/retrieval/hybrid"]
    E -->|hybrid_search| F["QA Agent<br/>app/agents/qa"]
    F -->|enforce_quality| G["Guardrails<br/>app/quality/guardrails"]
    G --> H["Answer + Sources"]
    F -->|json_log / span| I[("Observability<br/>app/obs/log.py")]
```

## Transcribe pipeline
```mermaid
flowchart LR
    Y["URL or File"] -->|yt-dlp| DL["Download Audio"]
    DL -->|ffmpeg| WAV["16kHz wav"]
    WAV -->|ASR| ASR["Segments + text<br/>(faster-whisper)"]
    ASR -->|append_jsonl| OUT["Index Outbox<br/>kind=transcript"]
    OUT --> STORE["Hybrid Store"]
    ASR -->|return| CLI["CLI Response<br/>--json"]
```

### Export till PNG/SVG
1. Installera Mermaid CLI lokalt: `npm install -g @mermaid-js/mermaid-cli`.
2. Kopiera blocket till en `.mmd`-fil eller använd `mmdc -i docs/diagrams/pipeline.mmd -o artifacts/pipeline.svg`.
3. `mmdc` läser även ur Markdown: `mmdc -i docs/DIAGRAMS.md -o artifacts/docs-diagrams.svg --page --scale 1`.
4. Lägg exporterade bilder i `docs/diagrams/` om de ska versionshanteras; CI behöver enbart källan.
<!-- SECTION:DIAGRAMS:END -->
