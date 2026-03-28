# Expected Test Results - RED Phase (TDD)

## Summary

**All 87 tests should FAIL initially.** This is correct and expected in Test-Driven Development.

## Why All Tests Fail

### 1. Missing PilotAgentState Implementation

Tests in `test_pilot_agent_state.py` (17 tests) will fail because:
- `PilotAgentState` dataclass doesn't exist in the codebase
- Tests import it from `conftest.py` (defined only for testing, not production)
- Production code needs to define it in `app/agents/pilot/state.py`

**Example failure**:
```
ImportError: cannot import name 'PilotAgentState' from 'app.agents.pilot.state' (not found)
AttributeError: 'NoneType' object has no attribute 'uuid'
```

### 2. Missing Graph Implementation

Tests in `test_pilot_agent_graph_topology.py` (14 tests) will fail because:
- No agent graph definition exists
- `build_agent_graph()` will create graphs, but no nodes are defined
- Tests expect specific topology validation that production code must implement

**Example failure**:
```
AssertionError: graph is None
GraphTopologyError: [test_agent] graph must have at least one edge from START
```

### 3. Missing Node Implementations

Tests in `test_pilot_agent_nodes.py` (18 tests) will fail because:
- Node handler functions don't exist
- Tests can instantiate mock nodes but production nodes aren't defined
- The contract enforces what each node must do

**Example failure**:
```
AttributeError: 'NoneType' object is not callable
AssertionError: mock_reasoning_facade.chat.call_count == 0 (expected 1)
```

### 4. Flag Logic Not Implemented

Tests in `test_pilot_agent_flag.py` (16 tests) will pass partially but fail on:
- Reading from `os.environ` works (standard library)
- But tests checking fallback/validation logic need implementation
- Tests expect specific behavior not yet coded

**Example failure**:
```
AssertionError: False is not True
# When checking if invalid flag triggers fallback
```

### 5. Integration Not Wired

Tests in `test_pilot_agent_integration.py` (22 tests) will fail because:
- Agent doesn't connect to event pipeline
- Output events aren't emitted
- Agent isn't integrated with ObjectStore

**Example failure**:
```
AssertionError: 0 == 1 (expected 1 emitted event)
AssertionError: None is not None (output event not produced)
```

## Test Execution Output Example

```bash
$ pytest tests/agents/pilot_agent/ -v

tests/agents/pilot_agent/test_pilot_agent_state.py::TestPilotAgentStateStructure::test_state_has_uuid_field FAILED
tests/agents/pilot_agent/test_pilot_agent_state.py::TestPilotAgentStateStructure::test_state_has_trace_id_field FAILED
tests/agents/pilot_agent/test_pilot_agent_state.py::TestPilotAgentStateStructure::test_state_has_budget_field FAILED
tests/agents/pilot_agent/test_pilot_agent_state.py::TestPilotAgentStateStructure::test_state_has_step_count_field FAILED
tests/agents/pilot_agent/test_pilot_agent_state.py::TestPilotAgentStateStructure::test_state_has_decision_field FAILED
tests/agents/pilot_agent/test_pilot_agent_state.py::TestPilotAgentStateStructure::test_state_has_executed_actions_field FAILED
tests/agents/pilot_agent/test_pilot_agent_state.py::TestPilotAgentStateStructure::test_state_has_error_field FAILED
tests/agents/pilot_agent/test_pilot_agent_state.py::TestPilotAgentStateSerialization::test_state_serializes_to_json FAILED
tests/agents/pilot_agent/test_pilot_agent_state.py::TestPilotAgentStateSerialization::test_state_json_round_trip FAILED
tests/agents/pilot_agent/test_pilot_agent_state.py::TestPilotAgentStateSerialization::test_state_with_messages_serializes FAILED
tests/agents/pilot_agent/test_pilot_agent_state.py::TestPilotAgentStateSerialization::test_state_with_executed_actions_serializes FAILED
...

======================== 87 failed in 0.45s ========================
```

## This is EXPECTED and CORRECT

In Test-Driven Development:
1. **RED Phase**: All tests fail (you are here)
2. **GREEN Phase**: Implement code to make tests pass
3. **REFACTOR Phase**: Improve implementation while keeping tests green

## Debugging Failed Tests

To understand what each test expects, read:

1. **Test name**: Describes the behavior being tested
   ```python
   def test_state_serializes_to_json(self, state_factory):
       # Expects: state can be serialized to JSON string
   ```

2. **Test docstring** (in class):
   ```python
   class TestPilotAgentStateSerialization:
       """Verify state can be serialized to JSON and round-tripped."""
   ```

3. **Test body**: Shows exactly what's being asserted
   ```python
   state = state_factory()
   state_dict = asdict(state)
   json_str = json.dumps(state_dict)
   assert json_str is not None
   assert isinstance(json_str, str)
   ```

## Transition to GREEN Phase

Once implementation begins:
- Start with `test_pilot_agent_state.py` (foundational)
- Then `test_pilot_agent_graph_topology.py` (structure)
- Then `test_pilot_agent_nodes.py` (behavior)
- Then `test_pilot_agent_flag.py` (configuration)
- Finally `test_pilot_agent_integration.py` (end-to-end)

As tests pass, run:
```bash
pytest tests/agents/pilot_agent/ -v --tb=short
```

## Tracking Progress

Create a progress file to track which tests pass:
```bash
pytest tests/agents/pilot_agent/ -v > test_progress.txt
# Commit after each test passes
```

Expected progression:
- Start: 0 passing / 87 failing
- After state: 17 passing / 70 failing
- After graph: 31 passing / 56 failing
- After nodes: 49 passing / 38 failing
- After flag: 65 passing / 22 failing
- After integration: 87 passing / 0 failing (GREEN!)

## Notes

- Tests use mocks (no real LLM calls, no vault writes)
- Tests are fast (<100ms total for all 87)
- Tests are isolated (no database, no external services needed)
- Failures are informative (test name + assertion failure)

---

**Status**: RED Phase ✓
**Expected Result**: 87/87 tests FAIL
**This is correct.**
