# Pilot LangGraph Agent Test Suite

**TDD-First Test Suite for LangGraph Promotion Agent Pilot**

This directory contains a comprehensive test suite that defines the contract for a pilot LangGraph agent (Promotion) before implementation. Following Test-Driven Development (TDD), all tests are designed to **FAIL initially** since the implementation does not exist yet.

## Quick Start

```bash
# Run all 87 tests (expect 87 failures initially)
pytest tests/agents/pilot_agent/ -v

# Run by contract category
pytest tests/agents/pilot_agent/test_pilot_agent_state.py -v
pytest tests/agents/pilot_agent/test_pilot_agent_graph_topology.py -v
pytest tests/agents/pilot_agent/test_pilot_agent_nodes.py -v
pytest tests/agents/pilot_agent/test_pilot_agent_flag.py -v
pytest tests/agents/pilot_agent/test_pilot_agent_integration.py -v
```

## Test Suite Structure

| Module | Tests | Purpose |
|--------|-------|---------|
| `test_pilot_agent_state.py` | 17 | Agent state dataclass structure, serialization, validation |
| `test_pilot_agent_graph_topology.py` | 14 | LangGraph topology validation, reachability, telemetry |
| `test_pilot_agent_nodes.py` | 18 | Node behavior: state I/O, pure functions, error handling |
| `test_pilot_agent_flag.py` | 16 | Feature flag `LANGGRAPH_PILOT_AGENT` control & fallback |
| `test_pilot_agent_integration.py` | 22 | End-to-end: event input, telemetry, output, vault isolation |
| **Total** | **87** | **5 contract suites** |

## Contract Definitions

### 1. State Contract (17 tests)

The `PilotAgentState` dataclass must:
- Have 8 fields: `uuid`, `trace_id`, `budget`, `step_count`, `decision`, `executed_actions`, `error`, `messages`
- Serialize to/from JSON without data loss
- Validate types (uuid/trace_id are strings, budget/step_count are ints)
- Support optional fields (decision, error default to None)

### 2. Graph Topology Contract (14 tests)

The agent graph built via `build_agent_graph()` must:
- Have entry edge (START → some node)
- Have terminal edge (some node → END)
- Have all nodes reachable (no dead branches)
- Wrap every node with telemetry logger (entry/exit/latency)
- Reject invalid topologies (missing START/END, empty nodes)

### 3. Node Behavior Contract (18 tests)

Each node must:
- Accept `PilotAgentState` input, return `PilotAgentState` output
- Call `ReasoningFacade` methods (not raw LLMRouter)
- Be independently testable with mocks
- Handle errors gracefully (capture in state.error, don't raise)
- Respect budget (decrement per execution, stop at zero)
- Preserve trace_id and immutable fields

### 4. Feature Flag Contract (16 tests)

The `LANGGRAPH_PILOT_AGENT` environment variable must:
- Accept values: `promotion`, `reviewer`, `off`
- Default to `off` if unset
- Support runtime changes (not cached)
- Warn on invalid values and fallback to `off`
- Handle whitespace/case sensitivity gracefully

### 5. Integration Contract (22 tests)

The agent must:
- Receive input from outbox event (extract uuid, trace_id, payload)
- Initialize state from event
- Emit structured telemetry (trace_id, latency_ms, token count)
- Produce canonical `OutboxEvent` output (`promotion.done`)
- **Never directly mutate vault** — only emit events
- Preserve trace_id end-to-end
- Handle complete workflow: event → state → output event

## Test Fixtures (conftest.py)

### `state_factory`
Factory for creating valid `PilotAgentState` instances with customizable fields.

```python
state = state_factory(uuid="n1", trace_id="t1", decision="promote")
```

### `mock_reasoning_facade`
Mock `ReasoningFacade` that:
- Returns deterministic responses (no LLM calls)
- Tracks method calls (assert_called_once, etc.)
- Simulates tool use, structured output, chat

### `mock_llm_router`
Mock `LLMRouter` for routing validation tests.

### `mock_store`
Mock object store for vault access tests (ensures no mutations).

### `mock_event_emitter`
Mock event sink that tracks emitted events without side effects.

## Expected Test Results

**All 87 tests should FAIL initially.**

This is **correct and expected** because:
1. `PilotAgentState` dataclass doesn't exist yet
2. Agent graph and nodes not implemented
3. Feature flag logic missing
4. Event pipeline integration incomplete

In TDD, tests come first (RED phase), then implementation (GREEN phase).

## Implementation Roadmap

After tests pass, implement:

1. **State** (`app/agents/pilot/state.py`)
   - Define `PilotAgentState` dataclass
   - All 8 required fields with proper types
   - Validation via `__post_init__`

2. **Graph** (`app/agents/pilot/graph.py`)
   - Use `build_agent_graph()` from `app.components.reasoning.graph_builder`
   - Define nodes: validate, reason, decide, apply
   - Wire edges: START → validate → reason → decide → END

3. **Nodes** (`app/agents/pilot/nodes.py`)
   - Implement each node as pure function
   - Call `ReasoningFacade` for reasoning
   - Handle errors, budget tracking
   - Update state immutably

4. **Flag Handler** (`app/agents/pilot/flag.py`)
   - Read `LANGGRAPH_PILOT_AGENT` at runtime
   - Validate and normalize values
   - Fallback to `off` on invalid
   - Not cached (fresh read each time)

5. **Integration** (`app/agents/pilot/integration.py`)
   - Hook into outbox event pipeline
   - Emit telemetry records
   - Produce `OutboxEvent` outputs
   - Ensure no vault mutations

## Test Philosophy

- **Single assertion focus**: Each test verifies one behavior
- **Mock external dependencies**: No real LLM, vault, or event emission
- **Isolation**: Tests don't depend on execution order
- **Clarity**: Test names describe the contract they enforce
- **Completeness**: Cover happy path, error cases, edge cases

## Key Design Principles

1. **State-Driven**: Agent state is the source of truth
2. **Pure Nodes**: Nodes don't have side effects
3. **Facade-Only**: All LLM through `ReasoningFacade`
4. **Events-Only**: No vault mutations, only event emission
5. **Traced**: Every operation carries trace_id
6. **Budgeted**: Respects token/step budget
7. **Testable**: All parts independently testable

## Debugging Failed Tests

When implementing, use:

```bash
# Verbose output with assertion details
pytest tests/agents/pilot_agent/ -vv

# Show print statements
pytest tests/agents/pilot_agent/ -s

# Stop at first failure
pytest tests/agents/pilot_agent/ -x

# Run specific test class
pytest tests/agents/pilot_agent/test_pilot_agent_state.py::TestPilotAgentStateSerialization -v

# Run specific test
pytest tests/agents/pilot_agent/test_pilot_agent_state.py::TestPilotAgentStateSerialization::test_state_json_round_trip -v
```

## Files

```
tests/agents/pilot_agent/
├── __init__.py                          # Package marker
├── conftest.py                          # Shared fixtures (100+ lines)
├── test_pilot_agent_state.py            # State contract (148 lines, 17 tests)
├── test_pilot_agent_graph_topology.py   # Graph topology (211 lines, 14 tests)
├── test_pilot_agent_nodes.py            # Node behavior (256 lines, 18 tests)
├── test_pilot_agent_flag.py             # Feature flag (134 lines, 16 tests)
├── test_pilot_agent_integration.py      # Integration (328 lines, 22 tests)
├── README.md                            # This file
└── TEST_CONTRACTS.md                    # Detailed contract definitions
```

**Total: 1077 lines of test code, 87 tests, 0 implementation lines**

## Integration with Existing Codebase

Tests assume:
- `ReasoningFacade` at `app.components.reasoning.facade`
- `build_agent_graph()` at `app.components.reasoning.graph_builder`
- Event schema from `app.events.schema`
- Existing promotion event types (PROMOTE_DONE, PROMOTE_ERROR)

## Contributing

When adding tests:
1. Maintain < 50 lines per test (single assertion focus)
2. Use clear naming: `test_<behavior>` describes the contract
3. Mock all external dependencies
4. Group related tests in classes
5. Document the contract enforced in docstrings

---

**Status**: RED (failing tests, no implementation)
**Last Updated**: 2026-03-27
**TDD Phase**: Phase 1 (contract definition)
