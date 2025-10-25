# Memory API v4.2
put(agent, kind, key, value, scope, trace_id, run_id) -> row_id
get(agent, kind, key, scope) -> value|None
query(agent, kind, filters, scope, limit, order) -> list
edge_upsert(src_id, dst_id, rel, weight, trace_id) -> edge_id
transact(ops[]) -> result
reflect(agent, inputs, policy) -> updates
Scopes: session, object:<uuid>, global
Kinds: episodic, semantic, procedural
