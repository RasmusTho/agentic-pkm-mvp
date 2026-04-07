State: Delivered (issue #360)
Doc role: Feature spec
Authority: Canonical spec for handler-registry routing in MockPlanExecutor. Implemented in app/orchestrator/executor.py.

<!-- A2A-ROUTING-01 -->
# Route Agent Calls Through Registered Handlers

Orchestrator-owned routing for supported `agent_call` recipients via an explicit handler registry.

## Behavior

`MockPlanExecutor` maintains an in-process handler registry mapping normalized agent names to `AgentHandler` callables:

```
AgentHandler = Callable[[AgentRequest], AgentResponse]
```

### Routing path for supported recipients

1. Agent-config permission check runs first (unchanged).
2. `send_agent_request(...)` emits `agent.request.created` audit event.
3. Recipient is looked up in the handler registry by normalized agent name.
4. Handler is called with the `AgentRequest`.
5. `emit_agent_response_event(...)` emits `agent.response.created` audit event.
6. Step result includes `agent`, `request_id`, and `response` (full model dump).

### Routing path for unsupported recipients

1. Agent-config permission check runs (unchanged).
2. `send_agent_request(...)` emits `agent.request.created` audit event.
3. No handler found in registry.
4. `emit_agent_error_event(...)` emits `agent.error.created` with `error_type="not_implemented"`.
5. `StepExecutionError` is raised with `error_type="not_implemented"` — step status becomes `error`.

## API

### `MockPlanExecutor.__init__(handlers=None)`

Optional `handlers` dict pre-populates the registry at construction time.

### `MockPlanExecutor.register_handler(agent_name, handler)`

Registers an in-process handler for a named recipient. Agent name is normalized (strips `prefix:` prefix) before storage.

## Constraints

- In-process posture only. No remote transport or queue semantics.
- Existing agent-config permission checks are preserved and run before handler dispatch.
- Handler registry lives on the executor instance, not globally.
- Handler must return an `AgentResponse`; callers are responsible for building the response.

## Source

- Implemented in: `app/orchestrator/executor.py`
- Tests: `tests/orchestrator/test_orchestrator_a2a_errors.py`, `tests/orchestrator/test_agent_config_enforcement.py`
