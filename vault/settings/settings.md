---
uuid: "77232B90CAE14637A4E90A18DAF71DE4"
title: "System Settings"
origin: "local"
review_state: "processed"
trust: "own"
source_ref: "vault://settings/settings.md"
version: "0.1.0"
runtime:
  environment: "dev"
  database_url: "postgresql://app:app@localhost:15432/app"
  enable_outbox: true
  enable_tracing: true
ingest:
  active_vault_path: "vault"
  file_glob: ["**/*.md"]
  ignore_glob: ["**/.trash/**", "**/_archive/**"]
  write_policy: "write_on_diff"
index:
  bm25_enabled: true
  vector_enabled: true
  embedding_model: "deterministic-1536"
  min_confidence: 0.15
observability:
  otlp_endpoint: "http://localhost:4317"
  jaeger_ui: "http://localhost:16686"
  trace_level: "info"
events:
  catalog_path: "vault/events/catalog.yaml"
  sla_outbox_to_index_ms: 2000
---

# System Settings

Detta dokument är källsanning för körparametrar. Frontmatter ovan valideras i CI mot `schemas/system-settings.schema.json`.
