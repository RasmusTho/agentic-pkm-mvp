from __future__ import annotations

from app.agents.ask.state import AgentState as AskAgentState
from app.agents.base.graph import AgentState as GraphAgentState
from app.agents.panel_agent.state import PanelAgentState
from app.agents.runtime_state import (
    RUNTIME_STATE_CONTRACT_FIELDS,
    RuntimeStateModel,
    conforms_to_runtime_state_contract,
)
from app.components.reasoning.graph_builder import AgentStateBase


def test_shared_runtime_state_contract_fields() -> None:
    assert RUNTIME_STATE_CONTRACT_FIELDS == {
        "trace_id",
        "authority",
        "authority_basis",
        "proposal_id",
        "receipt_event_id",
    }

    state = RuntimeStateModel(
        trace_id="trace-1599",
        authority={"component": "test"},
        authority_basis="explicit-test-contract",
        proposal_id="proposal-1599",
        receipt_event_id="receipt-1599",
    )

    assert state.trace_id == "trace-1599"
    assert state.authority == {"component": "test"}
    assert state.authority_basis == "explicit-test-contract"
    assert state.proposal_id == "proposal-1599"
    assert state.receipt_event_id == "receipt-1599"


def test_existing_agent_states_conform_to_shared_contract() -> None:
    assert conforms_to_runtime_state_contract(AskAgentState)
    assert conforms_to_runtime_state_contract(GraphAgentState)
    assert conforms_to_runtime_state_contract(AgentStateBase)
    assert conforms_to_runtime_state_contract(PanelAgentState)

    ask_state = AskAgentState(
        query="runtime state?",
        trace_id="trace-ask",
        authority_basis="read-only",
        proposal_id="proposal-ask",
        receipt_event_id="receipt-ask",
    )

    graph_state: GraphAgentState = {
        "trace_id": "trace-graph",
        "authority_basis": "workflow-policy",
        "proposal_id": "proposal-graph",
        "receipt_event_id": "receipt-graph",
    }
    reasoning_state: AgentStateBase = {
        "trace_id": "trace-reasoning",
        "authority": {"component": "reasoning"},
        "authority_basis": "reasoning-facade",
    }

    assert ask_state.authority_basis == "read-only"
    assert graph_state["proposal_id"] == "proposal-graph"
    assert reasoning_state["authority"] == {"component": "reasoning"}
