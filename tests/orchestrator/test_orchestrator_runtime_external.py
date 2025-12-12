from uuid import uuid4
from pathlib import Path

import pytest

from app.orchestrator.runtime import Orchestrator
from app.orchestrator.executor import StepExecutionError
from app.planner.schema import Plan, PlanMetadata, PlanStep, new_plan_id
from app.stores import get_object_store, reset_store_backends

pytestmark = pytest.mark.not_pg


def _build_external_plan(root: Path) -> Plan:
    return Plan(
        id=new_plan_id(),
        meta=PlanMetadata(goal="Ingest external folder", source_object_uuid=str(uuid4()), created_by="test"),
        steps=[
            PlanStep(
                id="ingest-external",
                kind="tool_call",
                description="Ingest external drop folder",
                tool="internal.ingest_external",
                tool_args={"root_dir": str(root)},
            )
        ],
        goal="Ingest external folder",
    )


def test_orchestrator_runs_external_ingest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()
    root = tmp_path / "external"
    root.mkdir()
    (root / "note.txt").write_text("orchestrator external ingest", encoding="utf-8")

    plan = _build_external_plan(root)
    orchestrator = Orchestrator()
    results = orchestrator.run_plan(plan)

    assert len(results) == 1
    assert results[0]["status"] == "ok"
    store = get_object_store()
    assert len(getattr(store, "_objects", {})) >= 1


def test_orchestrator_reports_tool_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()
    plan = Plan(
        id=new_plan_id(),
        meta=PlanMetadata(goal="Bad ingest", source_object_uuid=str(uuid4()), created_by="test"),
        steps=[
            PlanStep(
                id="ingest-external",
                kind="tool_call",
                description="Ingest external drop folder",
                tool="internal.ingest_external",
                tool_args={},  # missing required root_dir
            )
        ],
    )
    orchestrator = Orchestrator()
    results = orchestrator.run_plan(plan)
    assert len(results) == 1
    assert results[0]["status"] == "error"
