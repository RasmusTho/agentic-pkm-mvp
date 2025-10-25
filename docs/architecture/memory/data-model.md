# Datamodell v4.2
Tabeller:
agent_memories(id, agent, kind, key, scope, value, ts, trace_id, run_id)
memory_edges(id, src_id, dst_id, rel, weight, ts, trace_id)
agent_runs(id, agent, started_at, finished_at, trace_id, meta)
agent_tasks(id, agent, name, state, payload, ts)
audit(id, object_id, agent, action, ts, trace_id, details)
Index:
btree(agent,kind,key,scope), gin(value), btree(ts), btree(trace_id), btree(run_id)
Edges:
btree(src_id), btree(dst_id), btree(rel), btree(weight desc)
