State: ADR (historical).
# ADR: Agentminne v1
Beslut: Postgres JSONB + GIN för minneslager. Enkelt API via adapter. PER-hook för reflect.
Konsekvenser: låg komplexitet, god spårbarhet, enkel TDD. Uppgradering till extern kv/stream möjligt senare.
