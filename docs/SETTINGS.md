# SETTINGS

## Required
- DATABASE_URL: SQLAlchemy/psycopg URL. Example: postgresql+psycopg://app:app@127.0.0.1:15432/app
- SOT_VERSION: Current Source-of-Truth schema version. Example: 4.2

## LLM
- LLM_PROVIDER: ollama|openai|azureopenai|anthropic
- LLM_MODEL: default chat/model for non-reasoning prompts
- LLM_REASONING_MODEL: advanced model for deliberate reasoning
- OLLAMA_HOST: base URL to local server, default http://127.0.0.1:11434
- LLM_TIMEOUT_SECONDS: default 120

## Retrieval
- VECTOR_BACKEND: pgvector
- EMBED_MODEL: identifier string for embeddings (e.g. openai/text-embedding-3-large). Tests use a deterministic hashing-based embedding in code.
- BM25_BACKEND: bm25_lite

## Operational flags
- LOG_LEVEL: INFO|DEBUG
- FEATURE_REVIEW_AUTOPROMOTE: true|false (default true)
- FEATURE_REASONING_ON_REVIEW: true|false (default true)
- MAX_CHUNK_TOKENS: default 800
- CHUNK_OVERLAP_TOKENS: default 120

## Conventions
- All services read from environment first, then fall back to sensible defaults in app/settings.py and agent modules.
- Never check secrets into the repo. Use .env for local dev only.
