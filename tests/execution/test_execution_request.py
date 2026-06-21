from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from app.execution.execution_request import (
    CONTRACT_VERSION,
    ExecutionRequest,
    ExecutionResult,
)
from app.governance.governed_write import DecisionToken
from app.orchestrator.runtime import Orchestrator
from app.planner.schema import Plan, PlanMetadata, PlanStep

pytestmark = pytest.mark.not_pg


def _decision_token() -> DecisionToken:
    return DecisionToken(
        token_id="decision_token_1",
        decision_id="policy_decision_1",
        action="mcp.vault.append_note",
        write_class="vault_capture_append",
        actor="orchestrator.runtime",
        resource="Ask Summary",
        issued_at="2026-06-21T00:00:00Z",
    )


# --- AC1: one side-effect path accepts/produces an ExecutionRequest-shaped object ---


def test_execution_request_has_contract_adapter_shape() -> None:
    request = ExecutionRequest(
        side_effect="mcp.vault.append_note",
        actor="orchestrator.runtime",
        resource="Ask Summary",
        adapter="mcp.vault.append_note",
        trace_id="trace-1",
        args={"title": "Ask Summary", "body": "Hello"},
    )

    assert dataclasses.is_dataclass(request)
    field_names = {f.name for f in dataclasses.fields(request)}
    # Inputs section of docs/contracts/EXECUTION_REQUEST.md.
    assert {
        "side_effect",
        "actor",
        "resource",
        "adapter",
        "active_context_set",
        "decision_token",
        "dry_run",
        "preview",
        "trace_id",
        "args",
        "contract_version",
    } <= field_names
    assert request.contract_version == CONTRACT_VERSION


def test_execution_result_has_contract_adapter_shape() -> None:
    request = ExecutionRequest(
        side_effect="mcp.vault.append_note",
        actor="orchestrator.runtime",
        resource="Ask Summary",
        adapter="mcp.vault.append_note",
    )
    result = ExecutionResult(
        request=request,
        status="succeeded",
        effect_result={"status": "ok", "note_path": "/tmp/note.md"},
        receipt_ref="mcp.vault.append_note:/tmp/note.md",
        trace_id="trace-1",
    )

    assert dataclasses.is_dataclass(result)
    field_names = {f.name for f in dataclasses.fields(result)}
    # Outputs section of docs/contracts/EXECUTION_REQUEST.md.
    assert {
        "request",
        "status",
        "preview_result",
        "dry_run_result",
        "effect_result",
        "rollback_available",
        "rollback_result",
        "receipt_ref",
        "trace_id",
        "contract_version",
    } <= field_names
    assert result.contract_version == CONTRACT_VERSION


def test_execution_request_and_result_are_frozen() -> None:
    request = ExecutionRequest(
        side_effect="mcp.vault.append_note",
        actor="orchestrator.runtime",
        resource="Ask Summary",
        adapter="mcp.vault.append_note",
    )
    result = ExecutionResult(request=request, status="succeeded")

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.actor = "someone-else"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.status = "failed"  # type: ignore[misc]


# --- AC2: DecisionToken/authorization reference is represented (or documented null gap) ---


def test_execution_request_reuses_governance_decision_token() -> None:
    token = _decision_token()
    request = ExecutionRequest(
        side_effect="mcp.vault.append_note",
        actor="orchestrator.runtime",
        resource="Ask Summary",
        adapter="mcp.vault.append_note",
        decision_token=token,
    )

    # The DecisionToken type is reused from GOV, not redefined by EXE.
    assert request.decision_token is token
    assert isinstance(request.decision_token, DecisionToken)
    result = ExecutionResult(request=request, status="succeeded")
    assert result.decision_token is token


def test_execution_request_decision_token_defaults_to_null_transitional_gap() -> None:
    # Transitional gap documented in EXECUTION_REQUEST.md: the orchestrator does
    # not yet thread a DecisionToken, so the field is optional and defaults None.
    request = ExecutionRequest(
        side_effect="mcp.vault.append_note",
        actor="orchestrator.runtime",
        resource="Ask Summary",
        adapter="mcp.vault.append_note",
    )
    assert request.decision_token is None
    assert ExecutionResult(request=request, status="succeeded").decision_token is None


def test_execution_request_transitional_gap_is_documented() -> None:
    contract = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "contracts"
        / "EXECUTION_REQUEST.md"
    )
    text = contract.read_text(encoding="utf-8")
    assert "Transitional DecisionToken gap" in text
    assert "_run_vault_append" in text


# --- AC3: execution result links to trace/receipt visibility ---


def test_execution_result_links_trace_and_receipt() -> None:
    request = ExecutionRequest(
        side_effect="mcp.vault.append_note",
        actor="orchestrator.runtime",
        resource="Ask Summary",
        adapter="mcp.vault.append_note",
        trace_id="trace-xyz",
    )
    result = ExecutionResult(
        request=request,
        status="succeeded",
        effect_result={"status": "ok", "note_path": "/tmp/note.md"},
        receipt_ref="mcp.vault.append_note:/tmp/note.md",
        trace_id="trace-xyz",
    )

    assert result.trace_id == "trace-xyz"
    assert result.request.trace_id == "trace-xyz"
    assert result.receipt_ref == "mcp.vault.append_note:/tmp/note.md"


def test_wrapped_vault_append_still_writes_and_carries_trace(tmp_path: Path) -> None:
    """The EXE wrapper is additive: the real-vault write path is unchanged and
    its already-emitted tool-call events still carry the trace id."""
    orchestrator = Orchestrator(
        tool_settings={"mcp_vault_enable": True, "vault_root": tmp_path}
    )
    plan = Plan(
        id="plan-exe",
        meta=PlanMetadata(
            goal="Store note",
            source_object_uuid="obj-exe",
            created_by="tester",
            trace_id="trace-exe-1",
        ),
        steps=[
            PlanStep(
                id="step-1",
                kind="tool_call",
                description="Write vault note",
                tool="mcp.vault.append_note",
                tool_args={"title": "Ask Summary", "body": "Hello world"},
            )
        ],
    )

    results = orchestrator.run_plan(plan)

    assert len(results) == 1
    assert results[0]["status"] == "ok"
    note_path = Path(results[0]["result"]["result"]["note_path"])
    assert note_path.is_file()
