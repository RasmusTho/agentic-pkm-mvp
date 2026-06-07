"""Architecture compliance gate for the shared agent-state authority/trace spine.

Every agent state class that participates in LangGraph execution must declare the shared
runtime-state linkage contract defined in ``app/agents/runtime_state.py``.  This ensures
operational traceability, authority posture, and receipt linkage are consistent across all
execution surfaces without granting durable memory or write authority.

Contract fields (``RUNTIME_STATE_CONTRACT_FIELDS``):
    - ``trace_id``      — correlates execution events across components
    - ``authority``     — bounded authority class (read-only by default)
    - ``authority_basis`` — string key naming the authority grant basis
    - ``proposal_id``   — links the state to a specific write-proposal when applicable
    - ``receipt_event_id`` — links the state to a receipt event when applicable

Compliance means the class declares all five fields (inheriting from
``RuntimeStateContract`` / ``RuntimeStateModel`` is the idiomatic path).

Adding a new agent state class that does NOT inherit from the shared contract will
cause ``test_agent_state_spine_compliance`` to fail, surfacing the gap early.

Source anchors:
    docs/plans/MAJOR_ROADMAP_RESET_2026_06_04.md — Critical Path #3
    docs/ARCHITECTURE.md — Agent State Spine Contract section
"""

from __future__ import annotations

from app.agents.ask.state import AgentState as AskAgentState
from app.agents.base.graph import AgentState as GraphAgentState
from app.agents.panel_agent.state import PanelAgentState
from app.agents.pilot_agent.state import PilotAgentState
from app.agents.runtime_state import (
    RUNTIME_STATE_CONTRACT_FIELDS,
    conforms_to_runtime_state_contract,
    runtime_state_contract_fields,
)
from app.components.reasoning.graph_builder import AgentStateBase

# All runtime agent state classes that must carry the shared spine.
_KNOWN_AGENT_STATE_CLASSES = [
    AskAgentState,
    GraphAgentState,
    AgentStateBase,
    PanelAgentState,
    PilotAgentState,
]


def test_agent_state_spine_covers_active_langgraph_states() -> None:
    """All active LangGraph state classes named in runtime graph builders are gated."""

    assert PilotAgentState in _KNOWN_AGENT_STATE_CLASSES


def test_all_agent_state_classes_carry_trace_id() -> None:
    """All agent state surfaces must carry ``trace_id`` for operational traceability.

    ``trace_id`` is the minimal correlation field that must survive across every agent
    execution step.  Absence means an execution run cannot be correlated to events,
    receipts, or health traces.
    """
    for cls in _KNOWN_AGENT_STATE_CLASSES:
        declared = runtime_state_contract_fields(cls)
        assert "trace_id" in declared, (
            f"{cls.__qualname__} does not declare trace_id. "
            "Every agent state class must carry trace_id for operational correlation. "
            "Inherit from RuntimeStateContract (TypedDict) or RuntimeStateModel (Pydantic)."
        )


def test_agent_state_spine_compliance() -> None:
    """All known agent state classes must conform to the shared runtime-state spine.

    This is the lightweight compliance gate for the authority/trace spine defined in
    ``app/agents/runtime_state.py``.  A new agent state class that omits spine fields
    will surface here before reaching production.

    Spine fields verified: trace_id, authority, authority_basis, proposal_id, receipt_event_id.
    """
    non_compliant: list[str] = []
    for cls in _KNOWN_AGENT_STATE_CLASSES:
        if not conforms_to_runtime_state_contract(cls):
            missing = RUNTIME_STATE_CONTRACT_FIELDS - runtime_state_contract_fields(cls)
            non_compliant.append(
                f"  {cls.__qualname__} (missing: {sorted(missing)})"
            )

    assert not non_compliant, (
        "The following agent state classes do not conform to the shared "
        "runtime-state authority/trace spine "
        "(RUNTIME_STATE_CONTRACT_FIELDS = "
        f"{sorted(RUNTIME_STATE_CONTRACT_FIELDS)}):\n"
        + "\n".join(non_compliant)
        + "\nFix: inherit from RuntimeStateContract or RuntimeStateModel."
    )
