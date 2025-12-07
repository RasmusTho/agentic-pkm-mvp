State: Planned / partially implemented. Align carefully with STATUS (SoT v4.10) before applying.
# Sekvens: PER
Plan: get/query(kind=procedural|semantic, scope=session|global)
Execute: put(kind=episodic, scope=session|object), audit
Reflect: transact {query episodic→derive semantic; upsert edges; update scorecards}; gate-policy körs före commit
