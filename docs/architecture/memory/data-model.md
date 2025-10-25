# Datamodell
Tabeller: agent_memories(agent, kind, key, scope, value, ts), agent_runs, agent_tasks, audit.
Nycklar: btree(agent,kind,key,scope), gin(value).
Minnestyper: episodiskt, semantiskt, proceduralt. Retention styrs via data/context/retention.yaml.
