# System Settings — SoT v4.2

## Configuration Layers
1. **Environment variables** — runtime overrides  
2. **YAML context files** under `data/context/*` — declarative defaults  
3. **Database tables** — persistent truth (AMG/SetDB)

## Required Environment Variables
| Variable | Description | Example |
|-----------|--------------|----------|
| DATABASE_URL | Postgres connection string | postgresql+psycopg://app:app@127.0.0.1:15432/app |
| LLM_PROVIDER | Model backend | ollama |
| LLM_MODEL | Default model | llama3.1:8b |
| LLM_REASONING_MODEL | Reasoning model | deepseek-r1:8b |
| TRACE_MODE | Enables trace logs | true |

## Optional Variables
| Variable | Description | Default |
|-----------|--------------|----------|
| AGENT_LOG | Path for audit logs | /tmp/agent.log |
| VECTOR_DIM | Embedding vector dimensions | 1536 |
| MAX_CHUNK_SIZE | Chunking fallback token limit | 800 |
| CHUNK_OVERLAP | Overlap between chunks | 120 |
| RETENTION_DAYS | Default retention for transient objects | 90 |

## Config Files
| File | Purpose |
|------|----------|
| data/context/maturity.yaml | Defines maturity rules (seed → note → evergreen) |
| data/context/retrieval.yaml | Retrieval parameters for BM25/vector hybrid search |
| data/context/retention.yaml | Retention and pruning rules |
| data/context/agents.yaml | Runtime metadata for agents and event routing |

## Initialization
docker compose -f docker-compose.yaml up -d postgres
export DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app"
PYTHONPATH="$(pwd)" alembic upgrade head
