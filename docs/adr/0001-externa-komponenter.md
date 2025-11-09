# ADR-0001: Externa komponenter
- Vi använder **Ollama** för lokal LLM.
- **faster-whisper + ffmpeg + yt-dlp** för transkribering.
- Retrieval: **BM25 + Embeddings** med rerank.
- Motivering: sekretess, kostnad, latens, offline-stöd.
- Alternativ: VLLM (avvaktar pga py/torch-kompat), managed APIs som fallback.
