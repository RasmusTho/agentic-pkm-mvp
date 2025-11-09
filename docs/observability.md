# 7.0 Observability

## Loggformat (per nod)
```json
{"trace_id":"...","node":"retrieve","latency_ms":123,"token_in":512,"token_out":256,"rerank_scores":[...],"quality_flags":{"low_evidence":false}}
```

Dashboard (MVP)
- p50/p95 latens per nod
- felrate per nod
- iterationer per run
- topp source_ref
