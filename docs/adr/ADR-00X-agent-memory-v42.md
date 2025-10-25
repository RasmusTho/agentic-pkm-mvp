# ADR: Agentminne v4.2
Beslut: Postgres-baserat minneslager med namngivna scopes, unified adapter API, transaktionell reflektion, minneskanter.
Motiv: enhetlig SoT, determinism, enkel TDD, lätt att gate:a promotion och routing.
Alternativ: separat KV/graph-store, extern weaviate/qdrant. Skjuts på framtiden.
Konsekvenser: enkel drift, bra spårbarhet, två indexklasser (btree+gin) och ett kantlager.
