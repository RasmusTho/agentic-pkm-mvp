from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

import app.cli as cli_module
import app.orchestrator.executor as executor_module
import app.orchestrator.runtime as runtime_module
import app.orchestrator.v2_runtime as v2_runtime_module
import app.planner.provider as planner_provider
from app.a2a.schema import new_response
from app.agents.panel.integration import handle_panel_update
from app.orchestrator.admission import PlanAdmissionError
from app.orchestrator.executor import MockPlanExecutor, StepContext, StepExecutionError
from app.orchestrator.handler import OrchestratorContext, handle_event
from app.orchestrator.mcp_tool_provider import MCPToolProvider
from app.orchestrator.runtime import Orchestrator
from app.orchestrator.v2_runtime import OrchestratorV2
from app.events.models import new_event
from app.events.types import ASK_QUERY_RECEIVED, INGEST_OBJECT_CREATED
from app.planner.provider import LLMPlanner, MockPlanner, PlannerInput, build_vault_append_steps
from app.planner.schema import Plan, PlanMetadata, PlanStep
from app.settings.panel_actions import PanelActionMapping

pytestmark = pytest.mark.not_pg


class _RecordingExecutor:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute_step(self, step: PlanStep, context: Any) -> dict[str, Any]:
        self.executed.append(step.id)
        if step.id == "append":
            return {
                "tool": "mcp.vault.append_note",
                "result": {"status": "ok", "receipt_ref": "executor:append"},
            }
        return {"step_id": step.id}


def _plan(steps: list[PlanStep], *, context: dict[str, Any] | None = None) -> Plan:
    return Plan(
        id="plan-mcp-admission-boundary",
        meta=PlanMetadata(
            goal="guard append admission",
            source_object_uuid="obj-mcp-admission",
            created_by="test",
        ),
        steps=steps,
        context=context or {},
    )


def _append_step(step_class: str | None) -> PlanStep:
    return PlanStep(
        id="append",
        kind="tool_call",
        description="Append a note",
        tool="mcp.vault.append_note",
        tool_args={"title": "A", "body": "B"},
        step_class=step_class,
    )


def _llm_append_payload() -> dict[str, Any]:
    args = {"title": "LLM append", "body": "Generated safely"}
    actor = "planner.writer.v1"
    return {
        "id": "plan-llm-append",
        "meta": {
            "goal": "append generated note",
            "source_object_uuid": "llm-append-object",
            "created_by": "planner.llm",
            "trace_id": None,
        },
        "steps": [
            {
                "id": "append-authority",
                "kind": "decision",
                "description": "Check append policy and WriteGuard",
                "tool": "mcp.vault.append_note",
                "tool_args": args,
                "depends_on": [],
                "agent_id": actor,
                "metadata": {"append_effect_step_id": "append"},
                "step_class": "authority_check",
                "reason": "Authorize the concrete append",
            },
            {
                "id": "append",
                "kind": "tool_call",
                "description": "Append generated note",
                "tool": "mcp.vault.append_note",
                "tool_args": args,
                "depends_on": ["append-authority"],
                "agent_id": actor,
                "metadata": {"authority_check_step_id": "append-authority"},
                "step_class": "governed_effect",
                "reason": "Persist the generated note",
            },
            {
                "id": "append-receipt",
                "kind": "note",
                "description": "Reference the executor result",
                "depends_on": ["append"],
                "metadata": {"receipt_from_step": "append"},
                "step_class": "receipt",
                "verify": "result:execution_result",
                "reason": "Retain the executor result reference",
            },
        ],
        "context": {},
        "goal": "append generated note",
        "tags": [],
    }


def _default_llm_append_plan(
    monkeypatch: pytest.MonkeyPatch,
    planner_input: PlannerInput,
) -> tuple[Plan, dict[str, str]]:
    captured: dict[str, str] = {}

    class _Client:
        def chat(self, name: str, pack: dict[str, Any], **_: Any) -> str:
            captured["system"] = pack["system"]
            return json.dumps(_llm_append_payload())

    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PLANNER_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setattr(planner_provider, "get_chat_client", lambda _intent: _Client())
    planner = planner_provider.get_planner()
    assert isinstance(planner, LLMPlanner)
    return planner.plan(planner_input), captured


def test_vault_append_requires_r2_from_both_run_plan_entrypoints() -> None:
    for orchestrator_type in (Orchestrator, OrchestratorV2):
        for step_class in (None, "plain"):
            executor = _RecordingExecutor()
            with pytest.raises(PlanAdmissionError) as exc_info:
                orchestrator_type(executor=executor).run_plan(
                    _plan([_append_step(step_class)])
                )

            assert exc_info.value.rule == "R2"
            assert executor.executed == []


@pytest.mark.parametrize("orchestrator_type", (Orchestrator, OrchestratorV2))
def test_structural_append_rejects_a_mismatched_authority_check(
    orchestrator_type: type[Orchestrator] | type[OrchestratorV2],
) -> None:
    authority = PlanStep(
        id="authority",
        kind="decision",
        description="Check the append policy and WriteGuard",
        tool="mcp.vault.append_note",
        tool_args={"title": "different", "body": "B"},
        step_class="authority_check",
        metadata={"append_effect_step_id": "append"},
    )
    append = _append_step("plain")
    append.depends_on = ["authority"]
    append.metadata = {"authority_check_step_id": "authority"}
    receipt = PlanStep(
        id="receipt",
        kind="note",
        description="Reference the append result",
        step_class="receipt",
        depends_on=["append"],
        metadata={"receipt_from_step": "append"},
        verify="result:execution_result",
    )

    executor = _RecordingExecutor()
    with pytest.raises(PlanAdmissionError) as exc_info:
        orchestrator_type(executor=executor).run_plan(_plan([authority, append, receipt]))

    assert exc_info.value.rule == "R2"
    assert executor.executed == []


@pytest.mark.parametrize("orchestrator_type", (Orchestrator, OrchestratorV2))
@pytest.mark.parametrize(
    "mismatch",
    (
        "authority-tool",
        "missing-effect-authority-ref",
        "wrong-effect-authority-ref",
        "missing-authority-effect-ref",
        "wrong-authority-effect-ref",
        "receipt-class",
        "receipt-kind",
        "receipt-for-other-append",
    ),
)
def test_structural_append_rejects_invalid_authority_and_receipt_links(
    orchestrator_type: type[Orchestrator] | type[OrchestratorV2], mismatch: str
) -> None:
    args = {"title": "A", "body": "B"}
    authority = PlanStep(
        id="authority",
        kind="decision",
        description="Check the append policy and WriteGuard",
        tool="mcp.vault.append_note",
        tool_args=args,
        step_class="authority_check",
        metadata={"append_effect_step_id": "append"},
    )
    append = _append_step(None)
    append.tool_args = args
    append.depends_on = ["authority"]
    append.metadata = {"authority_check_step_id": "authority"}
    receipt = PlanStep(
        id="receipt",
        kind="note",
        description="Reference the append result",
        step_class="receipt",
        depends_on=["append"],
        metadata={"receipt_from_step": "append"},
        verify="result:execution_result",
    )
    steps = [authority, append, receipt]

    if mismatch == "authority-tool":
        authority.tool = "mcp.vault.read_note"
    elif mismatch == "missing-effect-authority-ref":
        append.metadata = {}
    elif mismatch == "wrong-effect-authority-ref":
        append.metadata = {"authority_check_step_id": "unknown-authority"}
    elif mismatch == "missing-authority-effect-ref":
        authority.metadata = {}
    elif mismatch == "wrong-authority-effect-ref":
        authority.metadata = {"append_effect_step_id": "other-append"}
    elif mismatch == "receipt-class":
        receipt.step_class = "plain"
    elif mismatch == "receipt-kind":
        receipt.kind = "decision"
        receipt.verify = "result:decision"
    elif mismatch == "receipt-for-other-append":
        other_authority = PlanStep(
            id="other-authority",
            kind="decision",
            description="Check the second append policy and WriteGuard",
            tool="mcp.vault.append_note",
            tool_args=args,
            step_class="authority_check",
            metadata={"append_effect_step_id": "other-append"},
        )
        other_append = PlanStep(
            id="other-append",
            kind="tool_call",
            description="Append a second note",
            tool="mcp.vault.append_note",
            tool_args=args,
            depends_on=["other-authority"],
            step_class="governed_effect",
            metadata={"authority_check_step_id": "other-authority"},
        )
        receipt.metadata = {"receipt_from_step": "other-append"}
        other_receipt = PlanStep(
            id="other-receipt",
            kind="note",
            description="Reference the second append result",
            step_class="receipt",
            depends_on=["other-append"],
            metadata={"receipt_from_step": "other-append"},
            verify="result:execution_result",
        )
        steps.extend([other_authority, other_append, other_receipt])

    executor = _RecordingExecutor()
    with pytest.raises(PlanAdmissionError) as exc_info:
        orchestrator_type(executor=executor).run_plan(_plan(steps))

    assert exc_info.value.rule == "R2", mismatch
    assert executor.executed == []


@pytest.mark.parametrize("orchestrator_type", (Orchestrator, OrchestratorV2))
def test_structural_append_rejects_nested_json_bool_integer_mismatch(
    orchestrator_type: type[Orchestrator] | type[OrchestratorV2],
) -> None:
    authority_args = {"title": "A", "body": "B", "metadata": {"x": 1}}
    append_args = {"title": "A", "body": "B", "metadata": {"x": True}}
    assert authority_args == append_args  # Python considers 1 and True equal.
    authority = PlanStep(
        id="authority",
        kind="decision",
        description="Check the append policy and WriteGuard",
        tool="mcp.vault.append_note",
        tool_args=authority_args,
        step_class="authority_check",
        metadata={"append_effect_step_id": "append"},
    )
    append = _append_step(None)
    append.tool_args = append_args
    append.depends_on = ["authority"]
    append.metadata = {"authority_check_step_id": "authority"}
    receipt = PlanStep(
        id="receipt",
        kind="note",
        description="Reference the append result",
        step_class="receipt",
        depends_on=["append"],
        metadata={"receipt_from_step": "append"},
        verify="result:execution_result",
    )

    executor = _RecordingExecutor()
    with pytest.raises(PlanAdmissionError) as exc_info:
        orchestrator_type(executor=executor).run_plan(
            _plan([authority, append, receipt])
        )

    assert exc_info.value.rule == "R2"
    assert executor.executed == []


@pytest.mark.parametrize("orchestrator_type", (Orchestrator, OrchestratorV2))
@pytest.mark.parametrize(
    ("actor_source", "context", "authority_agent_id", "authority_meta", "append_agent_id", "append_meta"),
    (
        (
            "explicit-vs-context",
            {"agent_id": "context-agent"},
            "explicit-agent",
            {},
            None,
            {},
        ),
        (
            "metadata-vs-context",
            {"agent_id": "context-agent"},
            None,
            {},
            None,
            {"agent_id": "append-agent"},
        ),
        (
            "metadata-vs-flow-default",
            {"flow_ids": ["ask"]},
            None,
            {},
            None,
            {"agent_id": "append-agent"},
        ),
    ),
)
def test_plan_entrypoints_reject_mismatched_effective_append_agents(
    orchestrator_type: type[Orchestrator] | type[OrchestratorV2],
    actor_source: str,
    context: dict[str, Any],
    authority_agent_id: str | None,
    authority_meta: dict[str, str],
    append_agent_id: str | None,
    append_meta: dict[str, str],
) -> None:
    args = {"title": "A", "body": "B"}
    authority = PlanStep(
        id="authority",
        kind="decision",
        description="Check policy and WriteGuard",
        tool="mcp.vault.append_note",
        tool_args=args,
        agent_id=authority_agent_id,
        step_class="authority_check",
        metadata={"append_effect_step_id": "append", **authority_meta},
    )
    append = _append_step(None)
    append.tool_args = args
    append.agent_id = append_agent_id
    append.depends_on = ["authority"]
    append.metadata = {"authority_check_step_id": "authority", **append_meta}
    receipt = PlanStep(
        id="receipt",
        kind="note",
        description="Reference the append result",
        step_class="receipt",
        depends_on=["append"],
        metadata={"receipt_from_step": "append"},
        verify="result:execution_result",
    )
    executor = _RecordingExecutor()

    with pytest.raises(PlanAdmissionError) as exc_info:
        orchestrator_type(executor=executor).run_plan(
            _plan([authority, append, receipt], context=context)
        )

    assert exc_info.value.rule == "R2", actor_source
    assert executor.executed == []


def test_structural_append_is_recognized_without_step_class_when_r2_is_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = {"title": "A", "body": "B"}
    authority = PlanStep(
        id="authority",
        kind="decision",
        description="Check the append policy and WriteGuard",
        tool="mcp.vault.append_note",
        tool_args=args,
        step_class="authority_check",
        metadata={"append_effect_step_id": "append"},
    )
    append = _append_step(None)
    append.tool_args = args
    append.depends_on = ["authority"]
    append.metadata = {"authority_check_step_id": "authority"}
    receipt = PlanStep(
        id="receipt",
        kind="note",
        description="Reference the append result",
        step_class="receipt",
        depends_on=["append"],
        metadata={"receipt_from_step": "append"},
        verify="result:execution_result",
    )

    monkeypatch.setattr(executor_module, "is_policy_enforced", lambda: False)
    monkeypatch.setattr(
        executor_module.DEFAULT_WRITE_GUARD,
        "assert_writes_allowed",
        lambda action: None,
    )
    executor = _RecordingExecutor()
    results = Orchestrator(executor=executor).run_plan(
        _plan([authority, append, receipt])
    )

    assert [entry["status"] for entry in results] == ["ok", "ok", "ok"]
    assert executor.executed == ["append"]
    assert results[-1]["result"]["receipt_ref"] == "executor:append"
    assert results[-1]["result"]["execution_result"] == results[1]["result"]


@pytest.mark.parametrize("orchestrator_type", (Orchestrator, OrchestratorV2))
def test_plan_entrypoints_run_policy_and_write_guard_before_append(
    orchestrator_type: type[Orchestrator] | type[OrchestratorV2],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    args = {"title": "A", "body": "B"}
    steps = build_vault_append_steps(
        step_id="append",
        description="Append a note",
        tool_args=args,
        reason="Test the guarded append order",
        agent_id="ask.v1",
    )

    class _OrderedExecutor(_RecordingExecutor):
        def execute_step(self, step: PlanStep, context: Any) -> dict[str, Any]:
            events.append(step.id)
            return super().execute_step(step, context)

    original_executor = _OrderedExecutor()

    def assert_tool_allowed(agent_id: str | None, tool_id: str) -> None:
        events.append(f"policy:{agent_id}:{tool_id}")

    def assert_writes_allowed(action: str) -> None:
        events.append(f"write_guard:{action}")

    monkeypatch.setattr(executor_module, "is_policy_enforced", lambda: True)
    monkeypatch.setattr(executor_module, "assert_tool_allowed", assert_tool_allowed)
    monkeypatch.setattr(
        executor_module.DEFAULT_WRITE_GUARD,
        "assert_writes_allowed",
        assert_writes_allowed,
    )

    results = orchestrator_type(executor=original_executor).run_plan(
        _plan(steps)
    )

    assert [entry["status"] for entry in results] == ["ok", "ok", "ok"]
    assert events[0] == "policy:ask.v1:mcp.vault.append_note"
    assert events[1].startswith("write_guard:")
    assert events[2] == "append"
    assert results[-1]["result"]["execution_result"] == results[1]["result"]
    assert results[-1]["result"]["receipt_ref"] == "executor:append"


@pytest.mark.parametrize("orchestrator_type", (Orchestrator, OrchestratorV2))
def test_real_append_executor_emits_bound_receipt_after_policy_and_write_guard(
    orchestrator_type: type[Orchestrator] | type[OrchestratorV2],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def assert_tool_allowed(agent_id: str | None, tool_id: str) -> None:
        events.append(f"policy:{agent_id}:{tool_id}")

    def assert_writes_allowed(action: str) -> None:
        events.append(f"write_guard:{action}")

    def append_note(**_: Any) -> Any:
        events.append("append")
        return Path("/virtual-vault/_mcp/guarded-note.md")

    monkeypatch.setattr(executor_module, "is_policy_enforced", lambda: True)
    monkeypatch.setattr(executor_module, "assert_tool_allowed", assert_tool_allowed)
    monkeypatch.setattr(executor_module, "append_note", append_note)
    monkeypatch.setattr(executor_module, "_write_outbox_events", lambda *args: None)
    monkeypatch.setattr(
        executor_module.DEFAULT_WRITE_GUARD,
        "assert_writes_allowed",
        assert_writes_allowed,
    )

    plan = _plan(
        build_vault_append_steps(
            step_id="append",
            description="Append a note",
            tool_args={"title": "A", "body": "B"},
            reason="Exercise the admitted append path",
            agent_id="ask.v1",
        )
    )
    results = orchestrator_type(
        executor=MockPlanExecutor(),
        tool_settings={"mcp_vault_enable": True},
    ).run_plan(plan)

    assert [entry["status"] for entry in results] == ["ok", "ok", "ok"]
    assert events[0] == "policy:ask.v1:mcp.vault.append_note"
    assert events[1].startswith("write_guard:")
    assert events[2] == "policy:ask.v1:mcp.vault.append_note"
    assert events[3] == "append"
    append_executor_result = results[1]["result"]
    receipt_result = results[2]["result"]
    assert receipt_result["execution_result"] == append_executor_result
    assert receipt_result["receipt_ref"] == (
        "mcp.vault.append_note:/virtual-vault/_mcp/guarded-note.md"
    )


@pytest.mark.parametrize("orchestrator_type", (Orchestrator, OrchestratorV2))
def test_outbox_failure_after_append_has_no_executor_result_or_receipt(
    orchestrator_type: type[Orchestrator] | type[OrchestratorV2],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    persisted_path = tmp_path / "_mcp" / "append-before-outbox-error.md"
    append_calls: list[Path] = []
    executor_results: list[dict[str, Any]] = []
    executed_steps: list[str] = []

    def append_note(**_: Any) -> Path:
        persisted_path.parent.mkdir(parents=True, exist_ok=True)
        persisted_path.write_text("simulated append", encoding="utf-8")
        append_calls.append(persisted_path)
        return persisted_path

    def fail_outbox_write(*_: Any) -> None:
        raise OSError("injected outbox failure")

    original_execute_plan_step = executor_module.execute_plan_step

    def track_plan_step(executor: Any, step: PlanStep, context: Any) -> dict[str, Any]:
        executed_steps.append(step.id)
        result = original_execute_plan_step(executor, step, context)
        if step.id == "append":
            executor_results.append(result)
        return result

    monkeypatch.setattr(executor_module, "is_policy_enforced", lambda: False)
    monkeypatch.setattr(executor_module, "assert_tool_allowed", lambda *_: None)
    monkeypatch.setattr(executor_module, "append_note", append_note)
    monkeypatch.setattr(executor_module, "_write_outbox_events", fail_outbox_write)
    monkeypatch.setattr(
        executor_module.DEFAULT_WRITE_GUARD,
        "assert_writes_allowed",
        lambda action: None,
    )
    monkeypatch.setattr(runtime_module, "execute_plan_step", track_plan_step)
    monkeypatch.setattr(v2_runtime_module, "execute_plan_step", track_plan_step)

    plan = _plan(
        build_vault_append_steps(
            step_id="append",
            description="Append before an injected outbox failure",
            tool_args={"title": "A", "body": "B"},
            reason="Prove the append/outbox crash window",
            agent_id="ask.v1",
        )
    )
    orchestrator = orchestrator_type(
        executor=MockPlanExecutor(),
        tool_settings={"mcp_vault_enable": True, "vault_root": str(tmp_path)},
    )

    if orchestrator_type is Orchestrator:
        with pytest.raises(OSError, match="injected outbox failure"):
            orchestrator.run_plan(plan)
        results: list[dict[str, Any]] = []
    else:
        results = orchestrator.run_plan(plan)
        append_entry = next(entry for entry in results if entry["step_id"] == "append")
        assert append_entry["status"] == "error"
        assert "result" not in append_entry

    assert persisted_path.read_text(encoding="utf-8") == "simulated append"
    assert append_calls == [persisted_path]
    assert executor_results == []
    assert executed_steps == ["append-authority", "append"]
    assert all(entry["step_id"] != "append-receipt" for entry in results)


@pytest.mark.parametrize("orchestrator_type", (Orchestrator, OrchestratorV2))
@pytest.mark.parametrize("denial", ("policy", "write_guard"))
def test_plan_entrypoints_stop_append_when_authority_check_denies(
    orchestrator_type: type[Orchestrator] | type[OrchestratorV2],
    denial: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = _RecordingExecutor()
    if denial == "policy":
        monkeypatch.setattr(executor_module, "is_policy_enforced", lambda: True)

        def deny_policy(agent_id: str | None, tool_id: str) -> None:
            raise PermissionError("denied by test policy")

        monkeypatch.setattr(executor_module, "assert_tool_allowed", deny_policy)
    else:
        monkeypatch.setattr(executor_module, "is_policy_enforced", lambda: False)

        def deny_write_guard(action: str) -> None:
            raise RuntimeError("denied by test WriteGuard")

        monkeypatch.setattr(
            executor_module.DEFAULT_WRITE_GUARD,
            "assert_writes_allowed",
            deny_write_guard,
        )

    results = orchestrator_type(executor=executor).run_plan(
        _plan(
            build_vault_append_steps(
                step_id="append",
                description="Append a note",
                tool_args={"title": "A", "body": "B"},
                reason="Test authority denial",
                agent_id="ask.v1",
            )
        )
    )

    assert results[0]["status"] == "error"
    assert results[0]["error_type"] == (
        "policy_denied" if denial == "policy" else "write_guard_denied"
    )
    assert executor.executed == []


def test_direct_provider_call_refuses_before_local_or_remote_effect() -> None:
    local_calls: list[str] = []
    remote_calls: list[str] = []

    class _Remote:
        def execute_tool_call(self, **_: object) -> dict[str, object]:
            remote_calls.append("execute")
            return {"status": "unexpected"}

    class _Executor:
        def _invoke_tool(self, *args: object, **kwargs: object) -> dict[str, object]:
            local_calls.append("invoke")
            return {"status": "unexpected"}

    context = StepContext(
        plan_id="plan-direct-provider",
        object_id="obj-direct-provider",
        trace_id="trace-direct-provider",
        metadata=PlanMetadata(
            goal="direct provider refusal",
            source_object_uuid="obj-direct-provider",
            created_by="test",
        ),
        tool_settings={"mcp_remote_multiplex_enable": True},
        agent_id="ask.v1",
    )

    with pytest.raises(StepExecutionError) as exc_info:
        MCPToolProvider(remote_provider=_Remote()).execute_tool_call(
            tool_name="mcp.search.objects",
            tool_args={"query": "test"},
            context=context,
            step_id="direct",
            description="Direct provider invocation",
            executor=_Executor(),  # type: ignore[arg-type]
        )

    assert exc_info.value.error_type == "admission_required"
    assert local_calls == []
    assert remote_calls == []


class _CapturingOrchestrator(Orchestrator):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.last_results: list[dict[str, Any]] = []

    def run_plan(self, plan: Plan) -> list[dict[str, Any]]:
        self.last_results = super().run_plan(plan)
        return self.last_results


def _assert_append_chain(plan: Plan) -> PlanStep:
    append_steps = [
        step
        for step in plan.steps
        if step.kind == "tool_call" and step.tool == "mcp.vault.append_note"
    ]
    assert len(append_steps) == 1
    append = append_steps[0]
    authority_id = append.metadata.get("authority_check_step_id")
    authority = next(step for step in plan.steps if step.id == authority_id)
    receipt = next(
        step
        for step in plan.steps
        if step.metadata.get("receipt_from_step") == append.id
    )
    assert authority.kind == "decision"
    assert authority.step_class == "authority_check"
    assert authority.tool == append.tool
    assert authority.tool_args == append.tool_args
    assert authority.agent_id == append.agent_id
    assert authority.metadata.get("append_effect_step_id") == append.id
    assert authority.id in append.depends_on
    assert receipt.kind == "note"
    assert receipt.step_class == "receipt"
    assert append.id in receipt.depends_on
    assert receipt.verify == "result:execution_result"
    return append


@pytest.mark.parametrize("orchestrator_type", (Orchestrator, OrchestratorV2))
def test_default_llm_planner_append_chain_passes_admission_and_executes(
    orchestrator_type: type[Orchestrator] | type[OrchestratorV2],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, captured = _default_llm_append_plan(
        monkeypatch,
        PlannerInput(
            object_uuid="llm-append-object",
            goal="append generated note",
            text="source text",
        ),
    )
    assert "append_effect_step_id" in captured["system"]
    assert "authority_check_step_id" in captured["system"]
    assert "receipt_from_step" in captured["system"]
    assert "same effective actor" in captured["system"]
    assert "<=5 steps" in captured["system"]
    append = _assert_append_chain(plan)
    assert append.agent_id == "planner.writer.v1"

    monkeypatch.setattr(executor_module, "is_policy_enforced", lambda: False)
    monkeypatch.setattr(
        executor_module.DEFAULT_WRITE_GUARD,
        "assert_writes_allowed",
        lambda action: None,
    )
    executor = _RecordingExecutor()
    results = orchestrator_type(executor=executor).run_plan(plan)

    assert [entry["status"] for entry in results] == ["ok", "ok", "ok"]
    assert executor.executed == ["append"]
    by_id = {entry["step_id"]: entry for entry in results}
    assert by_id["append-receipt"]["result"]["execution_result"] == by_id["append"]["result"]
    assert by_id["append-receipt"]["result"]["receipt_ref"] == "executor:append"


def test_named_append_producers_and_call_paths_preserve_r2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    effects: list[str] = []
    appended: list[dict[str, Any]] = []

    def assert_tool_allowed(agent_id: str | None, tool_id: str) -> None:
        effects.append("policy")

    def assert_writes_allowed(action: str) -> None:
        effects.append("write_guard")

    def append_note(**kwargs: Any) -> Path:
        effects.append("append")
        appended.append(kwargs)
        return Path("/virtual-vault/append-result.md")

    monkeypatch.setattr(executor_module, "is_policy_enforced", lambda: False)
    monkeypatch.setattr(executor_module, "assert_tool_allowed", assert_tool_allowed)
    monkeypatch.setattr(executor_module, "append_note", append_note)
    monkeypatch.setattr(executor_module, "_write_outbox_events", lambda *args: None)
    monkeypatch.setattr(
        executor_module.DEFAULT_WRITE_GUARD,
        "assert_writes_allowed",
        assert_writes_allowed,
    )
    monkeypatch.setattr(planner_provider, "audit_log", lambda **_: None)
    monkeypatch.setattr("app.planner.events.get_planner", lambda: MockPlanner())
    monkeypatch.setenv("POLICY_ENFORCE", "0")
    monkeypatch.setenv("EVENT_ORCHESTRATOR_ENABLE", "1")
    monkeypatch.setenv("PANEL_EVENTS_ENABLE", "1")

    def ingest_handler(request: Any) -> Any:
        return new_response(
            sender="ingest-agent",
            recipient=request.sender,
            payload={"summary": "test summary", "status": "ok"},
            correlation_id=str(request.id),
            trace_id=request.trace_id,
        )

    def new_orchestrator() -> _CapturingOrchestrator:
        return _CapturingOrchestrator(
            executor=MockPlanExecutor(handlers={"ingest-agent": ingest_handler}),
            tool_settings={"mcp_vault_enable": True, "vault_root": str(tmp_path)},
        )

    def assert_bound_result(plan: Plan, results: list[dict[str, Any]]) -> None:
        append = _assert_append_chain(plan)
        by_id = {entry["step_id"]: entry for entry in results}
        receipt = next(
            step for step in plan.steps if step.metadata.get("receipt_from_step") == append.id
        )
        append_result = by_id[append.id]["result"]
        receipt_result = by_id[receipt.id]["result"]
        assert by_id[append.id]["status"] == "ok"
        assert receipt_result["execution_result"] == append_result
        assert receipt_result["receipt_ref"] == append_result["result"]["receipt_ref"]

    def assert_executes_bound_append(plan: Plan, orchestrator: _CapturingOrchestrator) -> None:
        start = len(effects)
        results = orchestrator.run_plan(plan)
        assert_bound_result(plan, results)
        assert effects[start:][-4:] == ["policy", "write_guard", "policy", "append"]

    planner_input = PlannerInput(
        object_uuid="producer-object",
        goal="produce a guarded append",
        text="source text",
    )
    mock_plan = MockPlanner().plan(planner_input)
    fallback_plan = LLMPlanner()._fallback_plan(planner_input, "test fallback")
    llm_plan, _ = _default_llm_append_plan(monkeypatch, planner_input)
    monkeypatch.setenv("CI", "1")
    monkeypatch.delenv("PLANNER_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    ci_plan = planner_provider.get_planner().plan(planner_input)
    flow_plan = MockPlanner().plan(
        planner_input.model_copy(
            update={
                "context": {
                    "flow_profiles": [
                        {
                            "flow_id": "test-append",
                            "suggested_patterns": [
                                {
                                    "name": "append",
                                    "steps": [
                                        {
                                            "target": "mcp:vault.append_note",
                                            "args": {"title": "Flow", "body": "Pattern"},
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            }
        )
    )

    from app.cli.smoke import _append_ask_plan, _append_plan, _ask_smoke_plan

    smoke_plans = [
        _append_plan("reality-object", tmp_path),
        _append_ask_plan("ASK smoke answer", tmp_path),
        _ask_smoke_plan("What is tested?", "ASK body", tmp_path),
    ]
    for producer_plan in [mock_plan, fallback_plan, llm_plan, ci_plan, flow_plan, *smoke_plans]:
        assert_executes_bound_append(producer_plan, new_orchestrator())

    for event_type, payload in (
        (INGEST_OBJECT_CREATED, {"uuid": "ingest-object", "content": "Ingest text"}),
        (ASK_QUERY_RECEIVED, {"object_id": "qa-object", "question": "Question?"}),
    ):
        orchestrator = new_orchestrator()
        start = len(effects)
        plan = handle_event(
            new_event(event_type=event_type, payload=payload),
            OrchestratorContext(
                settings={"event_orchestrator_enable": True},
                orchestrator=orchestrator,
            ),
        )
        assert_bound_result(plan, orchestrator.last_results)
        assert effects[start:][-4:] == ["policy", "write_guard", "policy", "append"]

    monkeypatch.setattr(
        "app.agents.panel.integration.upsert_executed_ids",
        lambda *args, **kwargs: None,
    )
    panel_orchestrator = new_orchestrator()
    panel_start = len(effects)
    panel_text = (
        "## AI-instruktion\nDo something.\n\n"
        "## AI-åtgärder\n- [ ] Guarded action\n"
    )
    panel_result = handle_panel_update(
        note_id="panel-note",
        old_markdown=panel_text,
        new_markdown=panel_text.replace("[ ]", "[x]"),
        ctx=OrchestratorContext(
            settings={"event_orchestrator_enable": True, "panel_events_enable": True},
            orchestrator=panel_orchestrator,
        ),
        action_mappings={
            "Guarded action": PanelActionMapping(
                text="Guarded action",
                event_type=ASK_QUERY_RECEIVED,
                payload_template={"question": "Panel question?", "object_id": "panel-note"},
            )
        },
    )
    assert panel_result.dispatch_count == 1
    assert len(panel_result.plans) == 1
    assert_bound_result(panel_result.plans[0], panel_orchestrator.last_results)
    assert effects[panel_start:][-4:] == ["policy", "write_guard", "policy", "append"]

    cli_orchestrators: list[Any] = []
    original_recording_orchestrator = cli_module._RecordingOrchestrator

    class _CliRecordingOrchestrator(original_recording_orchestrator):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.last_plan: Plan | None = None
            cli_orchestrators.append(self)

        def run_plan(self, plan: Plan) -> list[dict[str, Any]]:
            self.last_plan = plan
            return super().run_plan(plan)

    monkeypatch.setattr(cli_module, "_RecordingOrchestrator", _CliRecordingOrchestrator)
    cli_start = len(effects)
    cli_result = CliRunner().invoke(
        cli_module.cli,
        ["ask", "What is guarded?", "--vault-root", str(tmp_path), "--enable-mcp-vault"],
        env={"POLICY_ENFORCE": "0", "EVENT_ORCHESTRATOR_ENABLE": "1"},
    )
    assert cli_result.exit_code == 0, cli_result.output
    assert len(cli_orchestrators) == 1
    assert cli_orchestrators[0].last_plan is not None
    assert_bound_result(cli_orchestrators[0].last_plan, cli_orchestrators[0].last_results)
    assert effects[cli_start:][-4:] == ["policy", "write_guard", "policy", "append"]
    assert len(appended) == 12


def test_valid_append_and_read_only_plans_keep_supported_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(executor_module, "is_policy_enforced", lambda: False)
    monkeypatch.setattr(
        executor_module.DEFAULT_WRITE_GUARD,
        "assert_writes_allowed",
        lambda action: None,
    )
    append_steps = build_vault_append_steps(
        step_id="append",
        description="Append a note",
        tool_args={"title": "A", "body": "B"},
        reason="Verify the valid structural append chain",
    )
    read_only_plan = _plan(
        [
            PlanStep(
                id="search",
                kind="tool_call",
                description="Search objects",
                tool="mcp.search.objects",
                tool_args={"query": "test", "k": 1},
            )
        ]
    )
    for orchestrator_type in (Orchestrator, OrchestratorV2):
        append_results = orchestrator_type(executor=_RecordingExecutor()).run_plan(
            _plan(append_steps)
        )
        assert [entry["status"] for entry in append_results] == ["ok", "ok", "ok"]
        search_results = orchestrator_type(executor=MockPlanExecutor()).run_plan(read_only_plan)
        assert len(search_results) == 1
        assert search_results[0]["status"] == "ok"

    forged = _append_step(None)
    forged.metadata = {"authority_check": True, "receipt_ref": "caller-minted"}
    forged_plan = _plan([forged])
    for orchestrator_type in (Orchestrator, OrchestratorV2):
        with pytest.raises(PlanAdmissionError) as exc_info:
            orchestrator_type(executor=_RecordingExecutor()).run_plan(forged_plan)
        assert exc_info.value.rule == "R2"
