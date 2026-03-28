# Pilot LangGraph Agent Test Suite - Contract Definitions

## Overview
This test suite defines the contract for a pilot LangGraph agent (Promotion) using Test-Driven Development (TDD). All tests are designed to FAIL initially since no implementation exists yet.

## Test Breakdown by Contract

### 1. Agent State Contract (test_pilot_agent_state.py) - 17 tests

Enforces the `PilotAgentState` dataclass structure and validation:

**Structure Tests (7)**:
- `test_state_has_uuid_field` - uuid field exists and is string
- `test_state_has_trace_id_field` - trace_id field exists and is string
- `test_state_has_budget_field` - budget field exists and is int
- `test_state_has_step_count_field` - step_count field exists and is int
- `test_state_has_decision_field` - decision field exists and is string|None
- `test_state_has_executed_actions_field` - executed_actions field exists and is list
- `test_state_has_error_field` - error field exists and is string|None

**Serialization Tests (4)**:
- `test_state_serializes_to_json` - state converts to JSON string
- `test_state_json_round_trip` - state survives JSON serialize/deserialize cycle
- `test_state_with_messages_serializes` - messages list serializes correctly
- `test_state_with_executed_actions_serializes` - action list preserves order

**Validation Tests (6)**:
- `test_state_requires_uuid` - raises TypeError if uuid missing
- `test_state_requires_trace_id` - raises TypeError if trace_id missing
- `test_state_budget_must_be_int` - raises TypeError for non-int budget
- `test_state_step_count_must_be_int` - raises TypeError for non-int step_count
- `test_state_optional_fields_default_correctly` - optional fields default to None/[]
- `test_state_all_fields_present` - all 8 required fields present in dataclass

### 2. Graph Topology Contract (test_pilot_agent_graph_topology.py) - 14 tests

Enforces correct LangGraph structure per `build_agent_graph`:

**Valid Topologies (4)**:
- `test_graph_requires_entry_node` - accepts "__start__" -> node edge
- `test_graph_requires_terminal_node` - accepts node -> "__end__" edge
- `test_graph_with_start_literal_accepted` - "__start__" literal works
- `test_graph_with_end_literal_accepted` - "__end__" literal works

**Invalid Topologies (3)**:
- `test_graph_rejects_no_entry_edge` - raises GraphTopologyError without START edge
- `test_graph_rejects_no_terminal_edge` - raises GraphTopologyError without END edge
- `test_graph_rejects_empty_nodes` - raises GraphTopologyError for empty nodes dict
- `test_graph_rejects_no_edges` - raises GraphTopologyError for empty edges list

**Reachability (3)**:
- `test_single_node_graph_is_reachable` - single node START->node->END is valid
- `test_linear_chain_all_reachable` - linear chain START->n1->n2->END is valid
- `test_branching_graph_reachable` - branching topology compiles without error

**Telemetry Wrapper (4)**:
- `test_telemetry_wrapper_logs_node_entry_exit` - logs contain "graph.node" markers
- `test_telemetry_wrapper_includes_trace_id` - trace_id visible in node logs
- `test_telemetry_wrapper_measures_latency` - "elapsed" timing in logs
- Graph compiles and executes without telemetry errors

### 3. Node Behavior Contract (test_pilot_agent_nodes.py) - 18 tests

Enforces that nodes are pure, independently testable functions:

**State I/O (5)**:
- `test_node_accepts_state` - node accepts PilotAgentState input
- `test_node_produces_modified_state` - node returns modified state
- `test_node_preserves_immutable_fields` - uuid/trace_id unchanged
- `test_node_can_update_decision` - decision field updatable
- `test_node_can_update_executed_actions` - action list appendable

**ReasoningFacade Calls (5)**:
- `test_node_calls_facade_chat` - node calls mock_reasoning_facade.chat()
- `test_node_calls_facade_structured` - node calls mock_reasoning_facade.structured()
- `test_node_calls_facade_tool_use` - node calls mock_reasoning_facade.tool_use()
- `test_node_passes_trace_id_to_facade` - trace_id passed to facade methods
- `test_node_does_not_call_raw_router` - node never calls LLMRouter directly

**Error Handling (6)**:
- `test_invalid_state_type_gracefully_degraded` - invalid state doesn't crash
- `test_missing_required_fields_recorded_as_error` - missing field → state.error set
- `test_facade_exception_recorded` - LLM timeout → error captured, not raised
- `test_node_increments_budget_on_execution` - budget decrements per step
- `test_node_stops_at_budget_zero` - zero budget → state.error = "budget_exhausted"
- `test_node_appends_to_messages` - message list grows per node

**Purity (2)**:
- `test_node_does_not_mutate_external_state` - input state unchanged after call
- `test_multiple_node_invocations_independent` - separate invocations don't interfere

### 4. Feature Flag Contract (test_pilot_agent_flag.py) - 16 tests

Enforces `LANGGRAPH_PILOT_AGENT` environment variable behavior:

**Activation (4)**:
- `test_promotion_agent_activates_with_flag` - "promotion" value activates agent
- `test_reviewer_agent_activates_with_flag` - "reviewer" value activates agent
- `test_flag_off_disables_pilot_agent` - "off" value disables agent
- `test_flag_unset_defaults_to_off` - missing env var → "off" behavior

**Validation (4)**:
- `test_flag_value_promotion_valid` - "promotion" is in valid set
- `test_flag_value_reviewer_valid` - "reviewer" is in valid set
- `test_flag_value_off_valid` - "off" is in valid set
- `test_flag_value_invalid_warns` - invalid value → warning logged

**Runtime Behavior (4)**:
- `test_flag_can_be_changed_at_runtime` - flag changes respected on next read
- `test_flag_disabled_after_enable` - can toggle promotion → off
- `test_flag_not_cached_across_calls` - each call reads fresh env value
- `test_flag_changes_visible_immediately` - no delay in flag propagation

**Fallback (4)**:
- `test_invalid_flag_falls_back_to_off` - typo → "off" fallback
- `test_empty_flag_falls_back_to_off` - empty string → "off" fallback
- `test_case_insensitivity_or_warning` - handles case sensitivity gracefully
- `test_whitespace_handling` - strips/normalizes whitespace

### 5. Integration Contract (test_pilot_agent_integration.py) - 22 tests

Enforces end-to-end integration with outbox events and vault:

**Input Event Reception (5)**:
- `test_agent_receives_event_payload` - agent extracts payload from event
- `test_agent_extracts_note_uuid` - note_uuid extracted from payload
- `test_agent_extracts_trace_id_from_event` - trace_id propagated from event
- `test_agent_initializes_state_from_event` - state initialized from event fields
- `test_agent_handles_missing_optional_fields` - handles minimal event gracefully

**Telemetry Emission (6)**:
- `test_agent_includes_trace_id_in_telemetry` - trace_id in telemetry record
- `test_agent_includes_latency_in_telemetry` - latency_ms field present
- `test_agent_includes_token_count_in_telemetry` - tokens_in/tokens_out tracked
- `test_telemetry_includes_agent_name` - "promotion_pilot" identified
- `test_telemetry_includes_step_count` - execution step count recorded
- `test_telemetry_includes_error_if_present` - error field captures failures

**Output Event Production (6)**:
- `test_agent_emits_promotion_done_event` - "promotion.done" event created
- `test_output_event_has_canonical_envelope` - OutboxEvent schema followed
- `test_output_event_includes_decision_in_payload` - decision in payload
- `test_output_event_preserves_note_uuid` - note_uuid round-trips
- `test_output_event_includes_timestamp` - timestamp field present
- `test_output_event_maintains_trace_id` - trace_id preserved end-to-end

**Vault Non-Mutation (4)**:
- `test_agent_does_not_call_write_operations` - mock_store.save_object not called
- `test_agent_only_emits_events` - only event emission occurs
- `test_agent_decision_emitted_not_written` - decision in event, not vault
- `test_agent_action_emitted_not_executed` - actions recorded, not executed

**Complete Workflow (1)**:
- `test_complete_workflow_input_to_output` - event → state → output event chain

## Test Execution

Run all tests with:
```bash
pytest tests/agents/pilot_agent/ -v
```

Run by contract:
```bash
pytest tests/agents/pilot_agent/test_pilot_agent_state.py -v
pytest tests/agents/pilot_agent/test_pilot_agent_graph_topology.py -v
pytest tests/agents/pilot_agent/test_pilot_agent_nodes.py -v
pytest tests/agents/pilot_agent/test_pilot_agent_flag.py -v
pytest tests/agents/pilot_agent/test_pilot_agent_integration.py -v
```

## Expected Test Results

**All 87 tests should FAIL initially** because:
1. `PilotAgentState` dataclass doesn't exist yet
2. Agent graph builders and nodes don't exist yet
3. Feature flag logic not implemented
4. Integration with event pipeline incomplete

This is **correct and expected** in TDD. Tests define the contract; implementation follows.

## Implementation Checklist

After tests pass, implementation must:

- [ ] Define `PilotAgentState` dataclass with all 8 fields
- [ ] Implement `build_agent_graph()` with entry/terminal validation
- [ ] Create agent nodes (validate, reason, decide, apply)
- [ ] Implement `LANGGRAPH_PILOT_AGENT` flag handling
- [ ] Wire agent into event pipeline
- [ ] Ensure no direct vault mutations (events-only model)
- [ ] Capture telemetry (trace_id, latency, tokens)
- [ ] Emit canonical `OutboxEvent` envelopes

## Key Design Principles

1. **State-driven**: Agent state is the single source of truth
2. **Pure nodes**: Each node transforms state, no side effects
3. **Facade-only**: All LLM reasoning through ReasoningFacade
4. **Events-only**: No direct vault mutations, only event emission
5. **Traced**: Every operation carries trace_id for observability
6. **Budgeted**: Agent respects token/step budget, graceful shutdown
7. **Testable**: All components independently testable with mocks

## Files

```
tests/agents/pilot_agent/
├── __init__.py                          # Package marker
├── conftest.py                          # Shared fixtures
├── test_pilot_agent_state.py            # State contract (17 tests)
├── test_pilot_agent_graph_topology.py   # Graph structure (14 tests)
├── test_pilot_agent_nodes.py            # Node behavior (18 tests)
├── test_pilot_agent_flag.py             # Feature flag (16 tests)
├── test_pilot_agent_integration.py      # End-to-end (22 tests)
└── TEST_CONTRACTS.md                    # This file
```

**Total: 87 tests across 5 contract suites**
