State: Legacy (archived); superseded by SoT v4.10 Reality-MVP.
# ADR-0001: External components (historical)

Historical decision: Prefer local providers (Ollama for LLM), faster-whisper/ffmpeg/yt-dlp for transcription, and BM25+embeddings retrieval.

Context in SoT v4.10:
- Current providers and defaults live in `docs/LLM.md`, `docs/LLM_BACKENDS.md`, and `docs/SYSTEM_DESIGN_v4.10.md`.
- Retrieval is hybrid search as documented in `docs/RETRIEVAL.md`.
- Transcription is not part of the Reality-MVP path.

Status: Kept for history only; refer to the SoT docs above for active choices and configuration.
