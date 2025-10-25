# Developer Workflow — SoT v4.2

## Development Loop
1. Choose agent to work on (e.g. Deduper)
2. Write or extend its tests in `tests/agents/<agent>.py`
3. Run the test directly until green
4. Commit and push
5. When multiple agents work, validate with `tests/e2e/test_pipe_graph.py`

## Example
pytest -q tests/agents/test_deduper.py
pytest -q tests/e2e/test_pipe_graph.py

## Branch Strategy
- main → stable
- chore/ws-docs-consistency+langgraph-poc → active dev branch
- feature/* → short-lived branches

## Coding Discipline
- Deterministic: no randomness
- Explicit: every write must be visible in audit
- Transparent: logs include agent, action, trace_id
- Modular: agents are replaceable

## Debugging
tail -n 50 /tmp/agent.log
docker compose logs -f api
