# Memory API
put(agent, kind, key, value, scope, trace_id) -> row_id
get(agent, kind, key, scope) -> value|None
query(agent, kind, filters, limit) -> list
reflect(agent, inputs) -> decisions/updates
