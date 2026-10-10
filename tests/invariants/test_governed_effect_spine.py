from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path
from typing import Any, Callable

import pytest

import app.eval.failure_capture as failure_capture_module
import app.orchestrator.executor as executor_module
import app.receipts.outbox_sources as receipt_sources
from app.governance.governed_write import GovernedWriteAdapter
from app.eval.failure_capture import (
    AuthorityReceiptPersistenceError,
    DRAFT_STATUS_PENDING,
    DRAFT_STATUS_PROMOTED,
    DRAFT_STATUS_REJECTED,
    draft_dead_letter_case,
    promote_draft,
    reconcile_pending_disposition_receipt,
    read_draft,
    reject_draft,
    PromotionDecisionError,
)
from app.mcp.vault_tools import append_note as production_append_note
from app.orchestrator.executor import MockPlanExecutor, StepContext, StepExecutionError
from app.orchestrator.runtime import Orchestrator
from app.orchestrator.v2_runtime import OrchestratorV2
from app.planner.provider import build_vault_append_steps
from app.planner.schema import Plan, PlanMetadata
from app.services.outbox import append_jsonl_record
from app.write_guard import WriteGuard
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter

pytestmark = pytest.mark.not_pg


def _plan() -> Plan:
    return Plan(
        id="governed-effect-spine-plan",
        meta=PlanMetadata(
            goal="append a governed note",
            source_object_uuid="governed-effect-spine-object",
            created_by="invariant-test",
            trace_id="trace-governed-effect-spine",
        ),
        steps=build_vault_append_steps(
            step_id="append",
            description="Append a governed note",
            tool_args={"title": "Governed note", "body": "body"},
            reason="Exercise the real governed append seam",
            agent_id="ask.v1",
        ),
    )


def _context(
    tmp_path: Path,
    *,
    grant: Any | None = None,
    trace_id: str = "trace-direct-governed-effect",
) -> StepContext:
    grants = {"append": grant} if grant is not None else {}
    return StepContext(
        plan_id="direct-governed-effect-plan",
        object_id="direct-governed-effect-object",
        trace_id=trace_id,
        metadata=PlanMetadata(
            goal="direct governed effect",
            source_object_uuid="direct-governed-effect-object",
            created_by="invariant-test",
        ),
        tool_settings={"mcp_vault_enable": True, "vault_root": str(tmp_path)},
        agent_id="ask.v1",
        governed_write_grants=grants,
    )


def _prepare_notification_replay_case(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    title: str,
    *,
    vault_root: Path | None = None,
    trace_id: str = "trace-direct-governed-effect",
) -> tuple[MockPlanExecutor, dict[str, str], Any, list[Path], Path, Path, list[int]]:
    outbox_path = tmp_path / "outbox.jsonl"
    effective_vault_root = vault_root or tmp_path
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    write_attempts = [0]
    append_calls: list[Path] = []

    def write_events(path: Path, records: list[Any]) -> None:
        write_attempts[0] += 1
        if write_attempts[0] == 2:
            raise OSError("injected notification persistence failure")
        for record in records:
            append_jsonl_record(path, record.model_dump(mode="json"), require_event_id=True)

    def append_note(**kwargs: Any) -> Path:
        note_path = production_append_note(**kwargs)
        append_calls.append(note_path)
        return note_path

    monkeypatch.setattr(executor_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda *_: None)
    monkeypatch.setattr(executor_module, "_write_outbox_events", write_events)
    monkeypatch.setattr(executor_module, "append_note", append_note)
    args = {"title": title, "body": "body"}
    grant = GovernedWriteAdapter().issue_decision_token(
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "ok"}),
        action="mcp.vault.append_note",
        write_class="vault_mcp_append",
        actor="ask.v1",
        resource=title,
    )
    executor = MockPlanExecutor()
    with pytest.raises(OSError, match="notification persistence failure"):
        executor._run_vault_append(
            args,
            _context(effective_vault_root, grant=grant, trace_id=trace_id),
            step_id="append",
        )
    original_note = append_calls[0]
    moved_note = effective_vault_root / "moved-note.md"
    original_note.rename(moved_note)
    executor_module._EFFECT_PATH_HINTS.clear()
    executor_module._EFFECT_ROOT_HINTS.clear()
    return executor, args, grant, append_calls, outbox_path, moved_note, write_attempts


def _rewrite_authority_event(
    outbox_path: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    records = [
        json.loads(line)
        for line in outbox_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    authority_event = next(
        record
        for record in records
        if record["event"] == "governance.authority_receipt.recorded"
    )
    mutate(authority_event)
    outbox_path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


def _append_notification_event(
    outbox_path: Path,
    mutate: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    records = [
        json.loads(line)
        for line in outbox_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    authority_event = next(
        record
        for record in records
        if record["event"] == "governance.authority_receipt.recorded"
    )
    authority_payload = authority_event["payload"]
    effect_id = authority_payload["effect_id"]
    notification = {
        "event": "mcp.vault.append_note",
        "event_id": executor_module._event_id(effect_id, "notification"),
        "trace_id": authority_event["trace_id"],
        "source": "orchestrator.runtime",
        "payload": {
            "effect_id": effect_id,
            "note_path": authority_payload["execution_result"]["effect_result"]["note_path"],
            "authority_receipt": json.loads(json.dumps(authority_payload["authority_receipt"])),
        },
    }
    if mutate is not None:
        mutate(notification)
    records.append(notification)
    outbox_path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


def test_orchestrator_real_tool_requires_prevalidated_decision_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    append_calls: list[dict[str, Any]] = []

    def append_note(**kwargs: Any) -> Path:
        append_calls.append(kwargs)
        return tmp_path / "_mcp" / "unexpected.md"

    monkeypatch.setattr(executor_module, "append_note", append_note)

    with pytest.raises(StepExecutionError, match="DecisionToken"):
        MockPlanExecutor()._run_vault_append(
            {"title": "Governed note", "body": "body"},
            _context(tmp_path),
            step_id="append",
        )

    adapter = GovernedWriteAdapter()
    grant = adapter.issue_decision_token(
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "ok"}),
        action="mcp.vault.append_note",
        write_class="vault_mcp_append",
        actor="ask.v1",
        resource="another-target",
    )
    with pytest.raises(StepExecutionError, match="does not match effect request"):
        MockPlanExecutor()._run_vault_append(
            {"title": "Governed note", "body": "body"},
            _context(tmp_path, grant=grant),
            step_id="append",
        )

    assert append_calls == []


def test_orchestrator_real_tool_persists_authority_receipt_before_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[Any] = []
    note_path = tmp_path / "_mcp" / "governed-note.md"

    def append_note(**kwargs: Any) -> Path:
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text("simulated append", encoding="utf-8")
        return note_path

    monkeypatch.setattr(executor_module, "is_policy_enforced", lambda: False)
    monkeypatch.setattr(executor_module, "assert_tool_allowed", lambda *_: None)
    monkeypatch.setattr(executor_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda *_: None)
    monkeypatch.setattr(executor_module, "append_note", append_note)
    monkeypatch.setattr(
        executor_module,
        "_write_outbox_events",
        lambda _path, records: events.extend(records),
    )

    results = Orchestrator(
        tool_settings={"mcp_vault_enable": True, "vault_root": str(tmp_path)}
    ).run_plan(_plan())

    append_result = results[1]["result"]["result"]
    assert append_result["authority_receipt"]["outcome"] == "applied"
    assert append_result["decision_token"]["action"] == "mcp.vault.append_note"
    assert len(events) == 2
    receipt_event, notification_event = events
    assert receipt_event.event == "governance.authority_receipt.recorded"
    assert notification_event.event == "mcp.vault.append_note"
    assert receipt_event.payload["execution_result"]["receipt_ref"] == append_result["receipt_ref"]
    assert receipt_event.payload["authority_receipt"]["receipt_id"] == append_result["authority_receipt"]["receipt_id"]
    assert notification_event.payload["authority_receipt"]["receipt_id"] == append_result["authority_receipt"]["receipt_id"]


@pytest.mark.parametrize("failure_stage", ("authority_receipt", "notification"))
def test_partial_failure_reconciles_without_duplicate_mutation(
    failure_stage: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    append_calls: list[Path] = []
    write_attempts = 0
    def append_note(**kwargs: Any) -> Path:
        note_path = production_append_note(**kwargs)
        append_calls.append(note_path)
        return note_path

    def write_events(path: Path, records: list[Any]) -> None:
        nonlocal write_attempts
        write_attempts += 1
        if (
            failure_stage == "authority_receipt" and write_attempts == 1
        ) or (failure_stage == "notification" and write_attempts == 2):
            raise OSError(f"injected {failure_stage} persistence failure")
        for record in records:
            append_jsonl_record(path, record.model_dump(mode="json"), require_event_id=True)

    monkeypatch.setattr(executor_module, "is_policy_enforced", lambda: False)
    monkeypatch.setattr(executor_module, "assert_tool_allowed", lambda *_: None)
    monkeypatch.setattr(executor_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda *_: None)
    monkeypatch.setattr(executor_module, "append_note", append_note)
    monkeypatch.setattr(executor_module, "_write_outbox_events", write_events)

    orchestrator = Orchestrator(
        tool_settings={"mcp_vault_enable": True, "vault_root": str(tmp_path)}
    )
    with pytest.raises(OSError, match="persistence failure"):
        orchestrator.run_plan(_plan())

    results = orchestrator.run_plan(_plan())

    assert results[1]["status"] == "ok"
    assert len(append_calls) == 1
    assert results[1]["result"]["result"]["authority_receipt"]["outcome"] == "applied"
    assert write_attempts == (3 if failure_stage == "notification" else 3)


def test_v2_checkpoint_resume_restores_authority_for_partial_append_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A saved V2 authority step must not leave its resumed append ungated."""
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    append_calls: list[Path] = []
    write_attempts = 0

    def append_note(**kwargs: Any) -> Path:
        note_path = production_append_note(**kwargs)
        append_calls.append(note_path)
        return note_path

    def write_events(path: Path, records: list[Any]) -> None:
        nonlocal write_attempts
        write_attempts += 1
        if write_attempts == 1:
            raise OSError("injected authority receipt persistence failure")
        for record in records:
            append_jsonl_record(path, record.model_dump(mode="json"), require_event_id=True)

    class CheckpointMemory:
        data: dict[str, Any] | None = None

        def save_checkpoint(self, _key: str, checkpoint: dict[str, Any]) -> None:
            self.data = checkpoint

        def load_checkpoint(self, _key: str) -> dict[str, Any] | None:
            return self.data

    monkeypatch.setattr(executor_module, "is_policy_enforced", lambda: False)
    monkeypatch.setattr(executor_module, "assert_tool_allowed", lambda *_: None)
    monkeypatch.setattr(executor_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda *_: None)
    monkeypatch.setattr(executor_module, "append_note", append_note)
    monkeypatch.setattr(executor_module, "_write_outbox_events", write_events)

    checkpoint_store = CheckpointMemory()
    orchestrator = OrchestratorV2(
        checkpoint_store=checkpoint_store,
        checkpoint_interval=1,
        max_workers=1,
        tool_settings={"mcp_vault_enable": True, "vault_root": str(tmp_path)},
    )

    initial = orchestrator.run_plan(_plan())
    assert next(entry for entry in initial if entry["step_id"] == "append")["status"] == "error"
    assert checkpoint_store.data is not None
    saved_authority = checkpoint_store.data["step_results"]["append-authority"]
    original_token_id = saved_authority["governed_write"]["decision_token"]["token_id"]

    executor_module._EFFECT_PATH_HINTS.clear()
    executor_module._EFFECT_ROOT_HINTS.clear()
    resumed = OrchestratorV2(
        checkpoint_store=checkpoint_store,
        checkpoint_interval=1,
        max_workers=1,
        tool_settings={"mcp_vault_enable": True, "vault_root": str(tmp_path)},
    ).run_plan(_plan())
    append_result = next(entry for entry in resumed if entry["step_id"] == "append")
    assert append_result["status"] == "ok"
    assert append_result["result"]["result"]["decision_token"]["token_id"] == original_token_id
    assert len(append_calls) == 1
    assert len(list((tmp_path / "_mcp").glob("*.md"))) == 1
    assert write_attempts == 3


def test_restart_reconciliation_uses_environment_vault_root_after_hints_clear(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    vault_root = tmp_path / "configured-vault"
    vault_root.mkdir()
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("MCP_VAULT_ROOT", str(vault_root))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    write_attempts = 0

    def write_events(path: Path, records: list[Any]) -> None:
        nonlocal write_attempts
        write_attempts += 1
        if write_attempts == 1:
            raise OSError("injected authority receipt persistence failure")
        for record in records:
            append_jsonl_record(path, record.model_dump(mode="json"), require_event_id=True)

    monkeypatch.setattr(executor_module, "is_policy_enforced", lambda: False)
    monkeypatch.setattr(executor_module, "assert_tool_allowed", lambda *_: None)
    monkeypatch.setattr(executor_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda *_: None)
    monkeypatch.setattr(executor_module, "_write_outbox_events", write_events)

    orchestrator = Orchestrator(tool_settings={"mcp_vault_enable": True})
    with pytest.raises(OSError, match="authority receipt persistence failure"):
        orchestrator.run_plan(_plan())

    notes = list((vault_root / "_mcp").glob("*.md"))
    assert notes
    original_frontmatter, _ = load_frontmatter(notes[0].read_text(encoding="utf-8"))
    original_token_id = original_frontmatter["metadata"]["governed_authorization"]["token_id"]
    executor_module._EFFECT_PATH_HINTS.clear()
    executor_module._EFFECT_ROOT_HINTS.clear()

    results = Orchestrator(tool_settings={"mcp_vault_enable": True}).run_plan(_plan())

    assert results[1]["status"] == "ok"
    assert len(list((vault_root / "_mcp").glob("*.md"))) == 1
    retry_result = results[1]["result"]["result"]
    assert retry_result["decision_token"]["token_id"] == original_token_id
    assert retry_result["retry_decision_token"]["token_id"] != original_token_id


def test_restart_reconciliation_preserves_original_token_with_distinct_retry_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    write_attempts = 0

    def write_events(path: Path, records: list[Any]) -> None:
        nonlocal write_attempts
        write_attempts += 1
        if write_attempts == 1:
            raise OSError("injected authority receipt persistence failure")
        for record in records:
            append_jsonl_record(path, record.model_dump(mode="json"), require_event_id=True)

    monkeypatch.setattr(executor_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda *_: None)
    monkeypatch.setattr(executor_module, "_write_outbox_events", write_events)
    args = {"title": "Original authorization", "body": "body"}
    adapter = GovernedWriteAdapter()

    def grant() -> Any:
        return adapter.issue_decision_token(
            write_guard=WriteGuard(snapshot_fn=lambda: {"state": "ok"}),
            action="mcp.vault.append_note",
            write_class="vault_mcp_append",
            actor="ask.v1",
            resource=args["title"],
        )

    executor = MockPlanExecutor()
    with pytest.raises(OSError, match="authority receipt persistence failure"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant()), step_id="append")
    note = next((tmp_path / "_mcp").glob("*.md"))
    frontmatter, _ = load_frontmatter(note.read_text(encoding="utf-8"))
    original_token_id = frontmatter["metadata"]["governed_authorization"]["token_id"]
    executor_module._EFFECT_PATH_HINTS.clear()
    executor_module._EFFECT_ROOT_HINTS.clear()

    result = executor._run_vault_append(args, _context(tmp_path, grant=grant()), step_id="append")

    assert result["decision_token"]["token_id"] == original_token_id
    assert result["retry_decision_token"]["token_id"] != original_token_id
    records = [
        json.loads(record)
        for record in outbox_path.read_text(encoding="utf-8").splitlines()
        if record
    ]
    authority_event = next(
        record
        for record in records
        if record["event"] == "governance.authority_receipt.recorded"
    )
    assert authority_event["payload"]["decision_token"]["token_id"] == original_token_id
    assert (
        authority_event["payload"]["retry_decision_token"]["token_id"]
        != original_token_id
    )


@pytest.mark.parametrize(
    ("field", "mutated_value"),
    (
        ("valid", "yes"),
        ("contract_version", "governed_write_protocol.v999"),
        ("token_id", "decision_token_invalid"),
        ("decision_id", "policy_decision_invalid"),
        ("issued_at", "not-a-utc-timestamp"),
    ),
)
def test_reconciliation_rejects_malformed_recovered_decision_token(
    field: str,
    mutated_value: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Malformed recovered authorization cannot authorize a second append."""
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    write_attempts = 0
    append_calls: list[Path] = []

    def write_events(path: Path, records: list[Any]) -> None:
        nonlocal write_attempts
        write_attempts += 1
        if write_attempts == 1:
            raise OSError("injected authority receipt persistence failure")
        for record in records:
            append_jsonl_record(path, record.model_dump(mode="json"), require_event_id=True)

    def append_note(**kwargs: Any) -> Path:
        note_path = production_append_note(**kwargs)
        append_calls.append(note_path)
        return note_path

    monkeypatch.setattr(executor_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda *_: None)
    monkeypatch.setattr(executor_module, "_write_outbox_events", write_events)
    monkeypatch.setattr(executor_module, "append_note", append_note)
    args = {"title": "Malformed authorization", "body": "body"}
    adapter = GovernedWriteAdapter()
    grant = adapter.issue_decision_token(
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "ok"}),
        action="mcp.vault.append_note",
        write_class="vault_mcp_append",
        actor="ask.v1",
        resource=args["title"],
    )
    executor = MockPlanExecutor()
    with pytest.raises(OSError, match="authority receipt persistence failure"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant), step_id="append")

    note = append_calls[0]
    frontmatter, body = load_frontmatter(note.read_text(encoding="utf-8"))
    metadata = dict(frontmatter["metadata"])
    authorization = dict(metadata["governed_authorization"])
    authorization[field] = mutated_value
    metadata["governed_authorization"] = authorization
    frontmatter["metadata"] = metadata
    note.write_text(dump_frontmatter(frontmatter, body), encoding="utf-8")
    executor_module._EFFECT_PATH_HINTS.clear()
    executor_module._EFFECT_ROOT_HINTS.clear()

    with pytest.raises(StepExecutionError) as exc_info:
        executor._run_vault_append(args, _context(tmp_path, grant=grant), step_id="append")

    assert exc_info.value.error_type == "effect_reconciliation_conflict"
    assert len(append_calls) == 1
    assert len(list((tmp_path / "_mcp").glob("*.md"))) == 1
    assert write_attempts == 1


def test_reconciliation_conflicting_note_is_indeterminate_and_never_appends(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    write_attempts = 0

    def write_events(path: Path, records: list[Any]) -> None:
        nonlocal write_attempts
        write_attempts += 1
        if write_attempts == 1:
            raise OSError("injected authority receipt persistence failure")
        for record in records:
            append_jsonl_record(path, record.model_dump(mode="json"), require_event_id=True)

    monkeypatch.setattr(executor_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda *_: None)
    monkeypatch.setattr(executor_module, "_write_outbox_events", write_events)
    args = {"title": "Conflicting note", "body": "body"}
    adapter = GovernedWriteAdapter()

    def new_grant() -> Any:
        return adapter.issue_decision_token(
            write_guard=WriteGuard(snapshot_fn=lambda: {"state": "ok"}),
            action="mcp.vault.append_note",
            write_class="vault_mcp_append",
            actor="ask.v1",
            resource=args["title"],
        )

    executor = MockPlanExecutor()
    with pytest.raises(OSError, match="authority receipt persistence failure"):
        executor._run_vault_append(args, _context(tmp_path, grant=new_grant()), step_id="append")
    note = next((tmp_path / "_mcp").glob("*.md"))
    note.write_text(note.read_text(encoding="utf-8").replace("\nbody\n", "\ntampered\n"), encoding="utf-8")
    executor_module._EFFECT_PATH_HINTS.clear()
    executor_module._EFFECT_ROOT_HINTS.clear()

    with pytest.raises(StepExecutionError, match="reconciliation is indeterminate"):
        executor._run_vault_append(args, _context(tmp_path, grant=new_grant()), step_id="append")

    assert len(list((tmp_path / "_mcp").glob("*.md"))) == 1


def test_reconciliation_permission_denied_read_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    write_attempts = 0
    append_calls: list[Path] = []

    def write_events(path: Path, records: list[Any]) -> None:
        nonlocal write_attempts
        write_attempts += 1
        if write_attempts == 1:
            raise OSError("injected authority receipt persistence failure")
        for record in records:
            append_jsonl_record(path, record.model_dump(mode="json"), require_event_id=True)

    def append_note(**kwargs: Any) -> Path:
        note_path = production_append_note(**kwargs)
        append_calls.append(note_path)
        return note_path

    monkeypatch.setattr(executor_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda *_: None)
    monkeypatch.setattr(executor_module, "_write_outbox_events", write_events)
    monkeypatch.setattr(executor_module, "append_note", append_note)
    args = {"title": "Unreadable note", "body": "body"}
    adapter = GovernedWriteAdapter()
    grant = adapter.issue_decision_token(
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "ok"}),
        action="mcp.vault.append_note",
        write_class="vault_mcp_append",
        actor="ask.v1",
        resource=args["title"],
    )
    executor = MockPlanExecutor()
    with pytest.raises(OSError, match="authority receipt persistence failure"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant), step_id="append")
    note = append_calls[0]
    original_read_text = Path.read_text

    def deny_note_read(path: Path, *read_args: Any, **read_kwargs: Any) -> str:
        if path == note:
            raise PermissionError("injected note read denial")
        return original_read_text(path, *read_args, **read_kwargs)

    monkeypatch.setattr(Path, "read_text", deny_note_read)
    with pytest.raises(StepExecutionError, match="reconciliation is indeterminate"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant), step_id="append")

    executor_module._EFFECT_PATH_HINTS.clear()
    executor_module._EFFECT_ROOT_HINTS.clear()
    with pytest.raises(StepExecutionError, match="reconciliation is indeterminate"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant), step_id="append")

    assert len(append_calls) == 1
    assert len(list((tmp_path / "_mcp").glob("*.md"))) == 1


def test_reconciliation_malformed_frontmatter_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    write_attempts = 0
    append_calls: list[Path] = []

    def write_events(path: Path, records: list[Any]) -> None:
        nonlocal write_attempts
        write_attempts += 1
        if write_attempts == 1:
            raise OSError("injected authority receipt persistence failure")
        for record in records:
            append_jsonl_record(path, record.model_dump(mode="json"), require_event_id=True)

    def append_note(**kwargs: Any) -> Path:
        note_path = production_append_note(**kwargs)
        append_calls.append(note_path)
        return note_path

    monkeypatch.setattr(executor_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda *_: None)
    monkeypatch.setattr(executor_module, "_write_outbox_events", write_events)
    monkeypatch.setattr(executor_module, "append_note", append_note)
    args = {"title": "Malformed note", "body": "body"}
    adapter = GovernedWriteAdapter()
    grant = adapter.issue_decision_token(
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "ok"}),
        action="mcp.vault.append_note",
        write_class="vault_mcp_append",
        actor="ask.v1",
        resource=args["title"],
    )
    executor = MockPlanExecutor()
    with pytest.raises(OSError, match="authority receipt persistence failure"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant), step_id="append")
    note = append_calls[0]
    note.write_text("---\ntitle: [\n---\n\nbody\n", encoding="utf-8")

    with pytest.raises(StepExecutionError, match="reconciliation is indeterminate"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant), step_id="append")

    executor_module._EFFECT_PATH_HINTS.clear()
    executor_module._EFFECT_ROOT_HINTS.clear()
    with pytest.raises(StepExecutionError, match="reconciliation is indeterminate"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant), step_id="append")

    assert len(append_calls) == 1
    assert len(list((tmp_path / "_mcp").glob("*.md"))) == 1


def test_reconciliation_inventory_enumeration_failure_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    mcp_dir = tmp_path / "_mcp"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    write_attempts = 0
    append_calls: list[Path] = []

    def write_events(path: Path, records: list[Any]) -> None:
        nonlocal write_attempts
        write_attempts += 1
        if write_attempts == 1:
            raise OSError("injected authority receipt persistence failure")
        for record in records:
            append_jsonl_record(path, record.model_dump(mode="json"), require_event_id=True)

    def append_note(**kwargs: Any) -> Path:
        note_path = production_append_note(**kwargs)
        append_calls.append(note_path)
        return note_path

    monkeypatch.setattr(executor_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda *_: None)
    monkeypatch.setattr(executor_module, "_write_outbox_events", write_events)
    monkeypatch.setattr(executor_module, "append_note", append_note)
    args = {"title": "Inventory failure", "body": "body"}
    adapter = GovernedWriteAdapter()
    grant = adapter.issue_decision_token(
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "ok"}),
        action="mcp.vault.append_note",
        write_class="vault_mcp_append",
        actor="ask.v1",
        resource=args["title"],
    )
    executor = MockPlanExecutor()
    with pytest.raises(OSError, match="authority receipt persistence failure"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant), step_id="append")
    executor_module._EFFECT_PATH_HINTS.clear()
    executor_module._EFFECT_ROOT_HINTS.clear()
    original_scandir = os.scandir

    def deny_inventory(path: Any) -> Any:
        if Path(path) == mcp_dir:
            raise PermissionError("injected vault inventory denial")
        return original_scandir(path)

    monkeypatch.setattr(executor_module.os, "scandir", deny_inventory)
    with pytest.raises(StepExecutionError, match="reconciliation is indeterminate"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant), step_id="append")

    assert len(append_calls) == 1
    assert append_calls[0].is_file()


def test_reconciliation_hint_effect_identity_conflict_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    write_attempts = 0
    append_calls: list[Path] = []

    def write_events(path: Path, records: list[Any]) -> None:
        nonlocal write_attempts
        write_attempts += 1
        if write_attempts == 1:
            raise OSError("injected authority receipt persistence failure")
        for record in records:
            append_jsonl_record(path, record.model_dump(mode="json"), require_event_id=True)

    def append_note(**kwargs: Any) -> Path:
        note_path = production_append_note(**kwargs)
        append_calls.append(note_path)
        return note_path

    monkeypatch.setattr(executor_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda *_: None)
    monkeypatch.setattr(executor_module, "_write_outbox_events", write_events)
    monkeypatch.setattr(executor_module, "append_note", append_note)
    args = {"title": "Hint identity conflict", "body": "body"}
    adapter = GovernedWriteAdapter()
    grant = adapter.issue_decision_token(
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "ok"}),
        action="mcp.vault.append_note",
        write_class="vault_mcp_append",
        actor="ask.v1",
        resource=args["title"],
    )
    executor = MockPlanExecutor()
    with pytest.raises(OSError, match="authority receipt persistence failure"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant), step_id="append")
    note = append_calls[0]
    effect_id = executor_module._effect_identity(
        "direct-governed-effect-plan",
        "append",
        args,
        vault_root=tmp_path,
    )
    note.write_text(
        note.read_text(encoding="utf-8").replace(effect_id, "orchestrator:changed-effect"),
        encoding="utf-8",
    )

    with pytest.raises(StepExecutionError, match="reconciliation is indeterminate"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant), step_id="append")

    assert len(append_calls) == 1
    assert len(list((tmp_path / "_mcp").glob("*.md"))) == 1


def test_restart_reconciliation_unreadable_outbox_replays_no_writer_effect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    write_attempts = 0
    append_calls: list[Path] = []

    def write_events(path: Path, records: list[Any]) -> None:
        nonlocal write_attempts
        write_attempts += 1
        if write_attempts == 2:
            raise OSError("injected notification persistence failure")
        for record in records:
            append_jsonl_record(path, record.model_dump(mode="json"), require_event_id=True)

    def append_note(**kwargs: Any) -> Path:
        note_path = production_append_note(**kwargs)
        append_calls.append(note_path)
        return note_path

    monkeypatch.setattr(executor_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda *_: None)
    monkeypatch.setattr(executor_module, "_write_outbox_events", write_events)
    monkeypatch.setattr(executor_module, "append_note", append_note)
    args = {"title": "Unreadable receipt", "body": "body"}
    adapter = GovernedWriteAdapter()
    grant = adapter.issue_decision_token(
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "ok"}),
        action="mcp.vault.append_note",
        write_class="vault_mcp_append",
        actor="ask.v1",
        resource=args["title"],
    )
    executor = MockPlanExecutor()
    with pytest.raises(OSError, match="notification persistence failure"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant), step_id="append")
    original_note = append_calls[0]
    moved_note = tmp_path / "moved-note.md"
    original_note.rename(moved_note)
    executor_module._EFFECT_PATH_HINTS.clear()
    executor_module._EFFECT_ROOT_HINTS.clear()
    lock_path = outbox_path.with_name(f".{outbox_path.name}.append.lock")
    original_open = Path.open

    def deny_receipt_lock(path: Path, *open_args: Any, **open_kwargs: Any) -> Any:
        if path.resolve() == lock_path.resolve():
            raise PermissionError("injected outbox receipt lock denial")
        return original_open(path, *open_args, **open_kwargs)

    monkeypatch.setattr(Path, "open", deny_receipt_lock)
    with pytest.raises(StepExecutionError, match="reconciliation is indeterminate"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant), step_id="append")

    assert len(append_calls) == 1
    assert moved_note.is_file()
    assert write_attempts == 2


def test_persisted_receipt_missing_authority_receipt_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executor, args, grant, append_calls, outbox_path, moved_note, write_attempts = (
        _prepare_notification_replay_case(monkeypatch, tmp_path, "Missing receipt")
    )
    _rewrite_authority_event(
        outbox_path,
        lambda event: event["payload"].pop("authority_receipt"),
    )

    with pytest.raises(StepExecutionError, match="reconciliation is indeterminate"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant), step_id="append")

    assert len(append_calls) == 1
    assert moved_note.is_file()
    assert write_attempts[0] == 2


def test_persisted_receipt_failed_outcome_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executor, args, grant, append_calls, outbox_path, moved_note, write_attempts = (
        _prepare_notification_replay_case(monkeypatch, tmp_path, "Failed receipt")
    )

    def mark_failed(event: dict[str, Any]) -> None:
        event["payload"]["authority_receipt"]["outcome"] = "failed"

    _rewrite_authority_event(outbox_path, mark_failed)

    with pytest.raises(StepExecutionError, match="reconciliation is indeterminate"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant), step_id="append")

    assert len(append_calls) == 1
    assert moved_note.is_file()
    assert write_attempts[0] == 2


def test_persisted_receipt_missing_effect_id_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executor, args, grant, append_calls, outbox_path, moved_note, write_attempts = (
        _prepare_notification_replay_case(monkeypatch, tmp_path, "Missing effect identity")
    )
    _rewrite_authority_event(
        outbox_path,
        lambda event: event["payload"].pop("effect_id"),
    )

    with pytest.raises(StepExecutionError, match="reconciliation is indeterminate"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant), step_id="append")

    assert len(append_calls) == 1
    assert moved_note.is_file()
    assert write_attempts[0] == 2


@pytest.mark.parametrize(
    ("mutation_id", "mutate"),
    [
        (
            "missing_receipt_id",
            lambda event: event["payload"]["authority_receipt"].pop("receipt_id"),
        ),
        (
            "mismatched_source_receipt_ref",
            lambda event: event["payload"]["authority_receipt"].update(
                source_receipt_ref="mcp.vault.append_note:append_note:/never-written.md"
            ),
        ),
        (
            "mismatched_execution_actor",
            lambda event: event["payload"]["execution_result"]["request"].update(
                actor="forged.actor"
            ),
        ),
        (
            "mismatched_execution_resource",
            lambda event: event["payload"]["execution_result"]["request"].update(
                resource="forged.resource"
            ),
        ),
        (
            "mismatched_effect_note_path",
            lambda event: event["payload"]["execution_result"]["effect_result"].update(
                note_path="/never-written.md"
            ),
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_persisted_receipt_mutated_accountability_linkage_is_indeterminate(
    mutation_id: str,
    mutate: Callable[[dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executor, args, grant, append_calls, outbox_path, moved_note, write_attempts = (
        _prepare_notification_replay_case(monkeypatch, tmp_path, f"Mutated {mutation_id}")
    )
    _rewrite_authority_event(outbox_path, mutate)

    with pytest.raises(StepExecutionError, match="reconciliation is indeterminate"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant), step_id="append")

    assert len(append_calls) == 1
    assert moved_note.is_file()
    assert write_attempts[0] == 2


@pytest.mark.parametrize(
    ("mutation_id", "mutate"),
    [
        (
            "mismatched_event_id",
            lambda event: event.update(event_id="forged-notification-event"),
        ),
        (
            "mismatched_note_path",
            lambda event: event["payload"].update(note_path="/never-written.md"),
        ),
        (
            "mismatched_authority_receipt",
            lambda event: event["payload"]["authority_receipt"].update(
                receipt_id="forged-receipt"
            ),
        ),
        (
            "mismatched_source",
            lambda event: event.update(source="forged.source"),
        ),
        (
            "missing_source",
            lambda event: event.pop("source"),
        ),
        (
            "mismatched_trace_id",
            lambda event: event.update(trace_id="forged-trace"),
        ),
        (
            "missing_trace_id",
            lambda event: event.pop("trace_id"),
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_persisted_notification_mutated_linkage_is_indeterminate(
    mutation_id: str,
    mutate: Callable[[dict[str, Any]], None],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executor, args, grant, append_calls, outbox_path, moved_note, write_attempts = (
        _prepare_notification_replay_case(monkeypatch, tmp_path, f"Mutated {mutation_id}")
    )
    _append_notification_event(outbox_path, mutate)

    with pytest.raises(StepExecutionError, match="reconciliation is indeterminate"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant), step_id="append")

    assert len(append_calls) == 1
    assert moved_note.is_file()
    assert write_attempts[0] == 2


def test_notification_only_replay_normalizes_backslash_resource(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    title = r"C:\Notes"
    executor, args, grant, append_calls, _outbox_path, moved_note, write_attempts = (
        _prepare_notification_replay_case(monkeypatch, tmp_path, title)
    )

    result = executor._run_vault_append(
        args,
        _context(tmp_path, grant=grant),
        step_id="append",
    )

    assert result["status"] == "ok"
    assert len(append_calls) == 1
    assert write_attempts[0] == 3
    assert moved_note.is_file()
    assert result["decision_token"]["resource"] == "C:/Notes"
    assert result["authority_receipt"]["resource"] == "C:/Notes"
    frontmatter, _body = load_frontmatter(moved_note.read_text(encoding="utf-8"))
    assert frontmatter["title"] == title


def test_notification_only_replay_preserves_durable_trace_across_retries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_trace_id = "trace-original-append"
    executor, args, grant, append_calls, outbox_path, moved_note, write_attempts = (
        _prepare_notification_replay_case(
            monkeypatch,
            tmp_path,
            "Durable trace replay",
            trace_id=original_trace_id,
        )
    )

    result = executor._run_vault_append(
        args,
        _context(tmp_path, grant=grant, trace_id="trace-notification-retry"),
        step_id="append",
    )

    records = [
        json.loads(line)
        for line in outbox_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    notification = next(
        record for record in records if record["event"] == "mcp.vault.append_note"
    )
    assert notification["event_id"] == executor_module._event_id(result["effect_id"], "notification")
    assert notification["source"] == "orchestrator.runtime"
    assert notification["trace_id"] == original_trace_id
    assert notification["payload"] == {
        "effect_id": result["effect_id"],
        "note_path": result["note_path"],
        "authority_receipt": result["authority_receipt"],
    }

    restarted_executor = MockPlanExecutor()
    replay_result = restarted_executor._run_vault_append(
        args,
        _context(tmp_path, grant=grant, trace_id="trace-follow-on-retry"),
        step_id="append",
    )

    assert replay_result["authority_receipt"] == result["authority_receipt"]
    assert len(append_calls) == 1
    assert moved_note.is_file()
    assert write_attempts[0] == 3
    final_records = [
        json.loads(line)
        for line in outbox_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(
        [record for record in final_records if record["event"] == "mcp.vault.append_note"]
    ) == 1


def test_notification_only_replay_canonicalizes_literal_backslash_vault_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / r"vault\name"
    vault_root.mkdir()
    executor, args, grant, append_calls, _outbox_path, moved_note, write_attempts = (
        _prepare_notification_replay_case(
            monkeypatch,
            tmp_path,
            "Literal backslash vault",
            vault_root=vault_root,
        )
    )

    result = executor._run_vault_append(
        args,
        _context(vault_root, grant=grant),
        step_id="append",
    )

    assert result["status"] == "ok"
    assert len(append_calls) == 1
    assert write_attempts[0] == 3
    assert moved_note.is_file()
    assert "vault/name/_mcp/" in result["note_path"]
    assert r"vault\name/_mcp/" not in result["note_path"]
    assert result["receipt_ref"] == f"mcp.vault.append_note:{result['note_path']}"
    assert result["authority_receipt"]["source_receipt_ref"] == (
        f"mcp.vault.append_note:append_note:{result['note_path']}"
    )


def test_reconciliation_parses_writer_format_losslessly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    write_attempts = 0

    def write_events(path: Path, records: list[Any]) -> None:
        nonlocal write_attempts
        write_attempts += 1
        if write_attempts == 1:
            raise OSError("injected authority receipt persistence failure")
        for record in records:
            append_jsonl_record(path, record.model_dump(mode="json"), require_event_id=True)

    monkeypatch.setattr(executor_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda *_: None)
    monkeypatch.setattr(executor_module, "_write_outbox_events", write_events)
    args = {"title": "Title --- with delimiter", "body": "\n\nleading body"}
    adapter = GovernedWriteAdapter()
    grant = lambda: adapter.issue_decision_token(
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "ok"}),
        action="mcp.vault.append_note",
        write_class="vault_mcp_append",
        actor="ask.v1",
        resource=args["title"],
    )
    executor = MockPlanExecutor()
    with pytest.raises(OSError, match="authority receipt persistence failure"):
        executor._run_vault_append(args, _context(tmp_path, grant=grant()), step_id="append")
    executor_module._EFFECT_PATH_HINTS.clear()
    executor_module._EFFECT_ROOT_HINTS.clear()

    result = executor._run_vault_append(args, _context(tmp_path, grant=grant()), step_id="append")

    assert result["status"] == "ok"
    assert len(list((tmp_path / "_mcp").glob("*.md"))) == 1


def test_reconciliation_requires_exact_metadata_and_content_not_body_substring(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    args = {
        "title": "Arbitrary proof",
        "body": "body",
    }
    effect_id = executor_module._effect_identity(
        "direct-governed-effect-plan",
        "append",
        args,
        vault_root=tmp_path,
    )
    existing = production_append_note(
        title=args["title"],
        body=f"wrong body containing governed_effect_id: {effect_id}",
        metadata={"untrusted_text": "arbitrary note"},
        vault_root=tmp_path,
    )
    adapter = GovernedWriteAdapter()
    grant = adapter.issue_decision_token(
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "ok"}),
        action="mcp.vault.append_note",
        write_class="vault_mcp_append",
        actor="ask.v1",
        resource=args["title"],
    )
    monkeypatch.setattr(executor_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda *_: None)

    result = MockPlanExecutor()._run_vault_append(
        args,
        _context(tmp_path, grant=grant),
        step_id="append",
    )

    assert Path(result["note_path"]) != existing
    assert len(list((tmp_path / "_mcp").glob("*.md"))) == 2
    frontmatter, body = load_frontmatter(Path(result["note_path"]).read_text(encoding="utf-8"))
    assert frontmatter["metadata"]["governed_effect_id"] == result["effect_id"]
    assert body.rstrip() == args["body"]


def test_same_process_same_effect_calls_are_serialized_without_duplicate_writer_effect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setattr(executor_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda *_: None)
    args = {"title": "Concurrent governed note", "body": "body"}
    adapter = GovernedWriteAdapter()

    def run_once(_: int) -> dict[str, Any]:
        grant = adapter.issue_decision_token(
            write_guard=WriteGuard(snapshot_fn=lambda: {"state": "ok"}),
            action="mcp.vault.append_note",
            write_class="vault_mcp_append",
            actor="ask.v1",
            resource=args["title"],
        )
        return MockPlanExecutor()._run_vault_append(
            args,
            _context(tmp_path, grant=grant),
            step_id="append",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run_once, (1, 2)))

    assert all(result["status"] == "ok" for result in results)
    assert len(list((tmp_path / "_mcp").glob("*.md"))) == 1


def test_eval_capture_disposition_uses_production_governed_chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Human eval disposition uses GOV token + state-owner receipt + GOV receipt.

    Candidate creation is exercised separately from the disposition. Both
    production promote/reject entrypoints bind the reviewer, action, write
    class, and exact draft resource before changing the candidate status; a
    mismatched token is refused before any note mutation.
    """
    outbox_path = tmp_path / "eval-disposition-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    golden_path = Path("docs/eval/classification_golden.yaml")
    golden_before = golden_path.read_bytes()

    for index, (decide, expected_status, actor) in enumerate(
        (
            (promote_draft, DRAFT_STATUS_PROMOTED, "human:promoter"),
            (reject_draft, DRAFT_STATUS_REJECTED, "human:reviewer"),
        )
    ):
        vault = tmp_path / f"vault-{index}"
        vault.mkdir()
        draft = draft_dead_letter_case(
            vault_root=vault,
            topic="ingest.vault.changed",
            reason="schema_violation:missing_required_field",
            event_id=f"evt-{index}",
            payload={"event_id": f"evt-{index}"},
            trace_id=f"trace-{index}",
            write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}),
        )
        assert draft is not None and draft.draft_path is not None
        assert draft.status == DRAFT_STATUS_PENDING

        decision = decide(vault, draft.draft_id, decided_by=actor)
        assert decision.decision == ("promote" if expected_status == DRAFT_STATUS_PROMOTED else "reject")
        assert decision.authority_receipt is not None
        assert decision.authority_receipt.actor == actor
        assert decision.authority_receipt.resource == draft.draft_path
        assert decision.authority_receipt.write_class == "eval_draft_disposition"
        assert decision.authority_receipt.action.endswith(decision.decision)

        persisted = read_draft(vault, draft.draft_id)
        assert persisted is not None
        assert persisted.status == expected_status
        assert persisted.decided_by == actor

    records = [
        json.loads(line)
        for line in outbox_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    disposition_events = [
        record
        for record in records
        if record["event"] == "governance.authority_receipt.recorded"
        and record["source"] == "eval.failure_capture"
    ]
    assert len(disposition_events) == 2
    for event in disposition_events:
        payload = event["payload"]
        token = payload["decision_token"]
        policy = payload["policy_decision"]
        state_owner_receipt = payload["state_owner_receipt"]
        authority = payload["authority_receipt"]
        assert policy["source"] == "human_review"
        assert token["actor"] in {"human:promoter", "human:reviewer"}
        assert token["action"].endswith(payload["decision"])
        assert token["write_class"] == "eval_draft_disposition"
        assert token["resource"] == authority["resource"]
        assert authority["decision_token_id"] == token["token_id"]
        assert authority["actor"] == token["actor"]
        assert authority["outcome"] == "applied"
        assert authority["source_receipt_ref"]
        assert state_owner_receipt["operation"] == "write_note"
        assert state_owner_receipt["locator"]["path"] == authority["resource"]

    # A candidate disposition never edits golden-set membership.
    assert golden_path.read_bytes() == golden_before

    mismatch_vault = tmp_path / "vault-mismatch"
    mismatch_vault.mkdir()
    mismatch = draft_dead_letter_case(
        vault_root=mismatch_vault,
        topic="ingest.vault.changed",
        reason="schema_violation:missing_required_field",
        event_id="evt-mismatch",
        payload={"event_id": "evt-mismatch"},
        trace_id="trace-mismatch",
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}),
    )
    assert mismatch is not None and mismatch.draft_path is not None
    mismatch_path = mismatch_vault / mismatch.draft_path
    before = mismatch_path.read_bytes()
    adapter = failure_capture_module._GOVERNED_WRITE_ADAPTER
    real_issue = adapter.issue_human_decision_token

    def issue_mismatched_token(**kwargs: Any) -> Any:
        grant = real_issue(**kwargs)
        bad_token = replace(grant.decision_token, resource="other-draft.md")
        return replace(grant, decision_token=bad_token)

    monkeypatch.setattr(adapter, "issue_human_decision_token", issue_mismatched_token)
    with pytest.raises(PromotionDecisionError, match="GOV refused"):
        promote_draft(mismatch_vault, mismatch.draft_id, decided_by="human:bad-token")
    assert mismatch_path.read_bytes() == before
    unchanged = read_draft(mismatch_vault, mismatch.draft_id)
    assert unchanged is not None and unchanged.status == DRAFT_STATUS_PENDING


def test_eval_capture_receipt_pending_reconciles_without_second_status_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A sink fault after mutation is recoverable through one durable receipt."""
    outbox_path = tmp_path / "eval-disposition-reconcile-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "pg")
    vault = tmp_path / "vault-reconcile"
    vault.mkdir()
    write_guard = WriteGuard(snapshot_fn=lambda: {"state": "healthy"})
    draft = draft_dead_letter_case(
        vault_root=vault,
        topic="ingest.vault.changed",
        reason="schema_violation:missing_required_field",
        event_id="evt-reconcile",
        payload={"event_id": "evt-reconcile"},
        trace_id="trace-reconcile",
        write_guard=write_guard,
    )
    assert draft is not None and draft.draft_path is not None

    real_write = failure_capture_module.write_note_relative
    writes: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def count_write(*args: Any, **kwargs: Any) -> Any:
        writes.append((args, kwargs))
        return real_write(*args, **kwargs)

    monkeypatch.setattr(failure_capture_module, "write_note_relative", count_write)
    real_append = failure_capture_module.append_jsonl_outbox_event
    append_attempts = 0

    def fail_receipt_sink_once(*args: Any, **kwargs: Any) -> bool:
        nonlocal append_attempts
        append_attempts += 1
        if append_attempts == 1:
            raise OSError("fault injection after status mutation")
        return real_append(*args, **kwargs)

    monkeypatch.setattr(
        failure_capture_module,
        "append_jsonl_outbox_event",
        fail_receipt_sink_once,
    )
    db_attempts = 0

    def fail_db_sink_once(*args: Any, **kwargs: Any) -> str:
        nonlocal db_attempts
        db_attempts += 1
        if db_attempts == 1:
            raise OSError("fault injection for the configured DB sink")
        return "db-receipt-event"

    monkeypatch.setattr(failure_capture_module, "write_outbox_event", fail_db_sink_once)

    with pytest.raises(AuthorityReceiptPersistenceError, match="could not be persisted"):
        promote_draft(
            vault,
            draft.draft_id,
            decided_by="human:reconcile",
            write_guard=write_guard,
        )

    terminal = read_draft(vault, draft.draft_id)
    assert terminal is not None
    assert terminal.status == DRAFT_STATUS_PROMOTED
    assert terminal.decided_by == "human:reconcile"
    assert terminal.decision_token is not None
    original_token_id = terminal.decision_token.token_id
    assert len(writes) == 1
    assert append_attempts == 1
    assert db_attempts == 1

    # The configured DB source is healthy but empty on recovery, so first-time
    # reconciliation remains allowed to emit the missing receipt.
    outbox_path.touch()
    monkeypatch.setattr(receipt_sources, "_read_db_outbox_records", lambda: [])
    recovered = reconcile_pending_disposition_receipt(vault, draft.draft_id)
    assert recovered.decision == "promote"
    assert recovered.authority_receipt is not None
    assert recovered.authority_receipt.actor == "human:reconcile"
    assert recovered.authority_receipt.decision_token_id == original_token_id
    assert len(writes) == 1
    assert append_attempts == 2
    assert db_attempts == 2

    records = [
        json.loads(line)
        for line in outbox_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    matching = [
        record
        for record in records
        if record["event"] == "governance.authority_receipt.recorded"
        and record["payload"]["draft_id"] == draft.draft_id
    ]
    assert len(matching) == 1
    assert matching[0]["event_id"] == matching[0]["payload"]["disposition_id"]
    assert matching[0]["payload"]["decision_token"]["token_id"] == original_token_id
    assert (
        matching[0]["payload"]["authority_receipt"]["decision_token_id"]
        == original_token_id
    )
    assert matching[0]["payload"]["authority_receipt"]["actor"] == "human:reconcile"

    replay = reconcile_pending_disposition_receipt(vault, draft.draft_id)
    assert replay.authority_receipt is not None
    assert replay.authority_receipt.receipt_id == recovered.authority_receipt.receipt_id
    assert len(writes) == 1
    assert append_attempts == 2


def test_eval_capture_acknowledges_when_jsonl_sink_survives_db_write_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """One durable configured receipt sink is enough to acknowledge disposition."""
    outbox_path = tmp_path / "partial-eval-disposition-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "pg")
    vault = tmp_path / "vault-partial-sink"
    vault.mkdir()
    draft = draft_dead_letter_case(
        vault_root=vault,
        topic="ingest.vault.changed",
        reason="schema_violation:missing_required_field",
        event_id="evt-partial-sink",
        payload={"event_id": "evt-partial-sink"},
        trace_id="trace-partial-sink",
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}),
    )
    assert draft is not None

    db_attempts = 0

    def fail_db_sink(*_args: Any, **_kwargs: Any) -> str:
        nonlocal db_attempts
        db_attempts += 1
        raise OSError("fault injection for configured DB sink")

    monkeypatch.setattr(failure_capture_module, "write_outbox_event", fail_db_sink)
    decision = promote_draft(
        vault,
        draft.draft_id,
        decided_by="human:partial-sink",
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}),
    )

    assert decision.authority_receipt is not None
    assert decision.authority_receipt.actor == "human:partial-sink"
    assert db_attempts == 1
    terminal = read_draft(vault, draft.draft_id)
    assert (
        terminal is not None
        and terminal.status == DRAFT_STATUS_PROMOTED
        and terminal.decision_token is not None
    )
    records = [
        json.loads(line)
        for line in outbox_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    matching = [
        record
        for record in records
        if record.get("event") == "governance.authority_receipt.recorded"
        and record.get("payload", {}).get("draft_id") == draft.draft_id
    ]
    assert len(matching) == 1
    assert (
        matching[0]["payload"]["authority_receipt"]["decision_token_id"]
        == terminal.decision_token.token_id
    )


def test_eval_capture_reconciliation_fails_closed_when_db_receipt_source_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An unreadable configured DB cannot be mistaken for an empty receipt source."""
    outbox_path = tmp_path / "unavailable-db-receipt.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "pg")
    vault = tmp_path / "vault-unavailable-db"
    vault.mkdir()
    write_guard = WriteGuard(snapshot_fn=lambda: {"state": "healthy"})
    draft = draft_dead_letter_case(
        vault_root=vault,
        topic="ingest.vault.changed",
        reason="schema_violation:missing_required_field",
        event_id="evt-unavailable-db",
        payload={"event_id": "evt-unavailable-db"},
        trace_id="trace-unavailable-db",
        write_guard=write_guard,
    )
    assert draft is not None

    writes: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    real_write = failure_capture_module.write_note_relative

    def count_write(*args: Any, **kwargs: Any) -> Any:
        writes.append((args, kwargs))
        return real_write(*args, **kwargs)

    def fail_jsonl(*_args: Any, **_kwargs: Any) -> bool:
        raise OSError("JSONL unavailable")

    def fail_db(*_args: Any, **_kwargs: Any) -> str:
        raise OSError("DB unavailable")

    monkeypatch.setattr(failure_capture_module, "write_note_relative", count_write)
    monkeypatch.setattr(failure_capture_module, "append_jsonl_outbox_event", fail_jsonl)
    monkeypatch.setattr(failure_capture_module, "write_outbox_event", fail_db)
    monkeypatch.setattr(receipt_sources, "_read_db_outbox_records", lambda: None)

    with pytest.raises(AuthorityReceiptPersistenceError, match="could not be persisted"):
        promote_draft(
            vault,
            draft.draft_id,
            decided_by="human:unavailable-db",
            write_guard=write_guard,
        )

    with pytest.raises(
        AuthorityReceiptPersistenceError,
        match="configured DB receipt source is unavailable",
    ):
        outbox_path.touch()
        reconcile_pending_disposition_receipt(vault, draft.draft_id)

    terminal = read_draft(vault, draft.draft_id)
    assert terminal is not None and terminal.status == DRAFT_STATUS_PROMOTED
    assert len(writes) == 1
    assert outbox_path.read_text(encoding="utf-8") == ""


@pytest.mark.parametrize(
    "tamper",
    [
        "outcome",
        "decision_token_id",
        "state_owner_outcome",
        "state_owner_writer",
        "contract_version",
        "contract_version_missing",
    ],
)
def test_eval_capture_reconciliation_rejects_tampered_persisted_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tamper: str,
) -> None:
    """A matching event is usable only when its durable receipt is applied and bound."""
    outbox_path = tmp_path / f"tampered-{tamper}.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    vault = tmp_path / f"vault-tampered-{tamper}"
    vault.mkdir()
    write_guard = WriteGuard(snapshot_fn=lambda: {"state": "healthy"})
    draft = draft_dead_letter_case(
        vault_root=vault,
        topic="ingest.vault.changed",
        reason="schema_violation:missing_required_field",
        event_id=f"evt-tampered-{tamper}",
        payload={"event_id": f"evt-tampered-{tamper}"},
        trace_id=f"trace-tampered-{tamper}",
        write_guard=write_guard,
    )
    assert draft is not None
    promote_draft(
        vault,
        draft.draft_id,
        decided_by="human:tamper-check",
        write_guard=write_guard,
    )

    records = [
        json.loads(line)
        for line in outbox_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    matching = [
        record
        for record in records
        if record.get("payload", {}).get("draft_id") == draft.draft_id
    ]
    assert len(matching) == 1
    payload = matching[0]["payload"]
    receipt = payload["authority_receipt"]
    if tamper == "outcome":
        receipt["outcome"] = "failed"
    elif tamper == "decision_token_id":
        receipt["decision_token_id"] = "tampered-token"
    elif tamper == "state_owner_outcome":
        payload["state_owner_receipt"]["outcome"] = "failed"
    elif tamper == "state_owner_writer":
        payload["state_owner_receipt"]["writer_identity"] = "attacker"
    elif tamper == "contract_version":
        receipt["contract_version"] = "unsupported-governed-write-contract"
    elif tamper == "contract_version_missing":
        receipt.pop("contract_version")
    else:
        pytest.fail(f"unexpected tamper value: {tamper}")
    outbox_path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    with pytest.raises(
        AuthorityReceiptPersistenceError,
        match="does not match the terminal draft",
    ):
        reconcile_pending_disposition_receipt(vault, draft.draft_id)


def test_eval_capture_reconciliation_discovers_db_only_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A durable DB receipt is replayed instead of reconstructing a second receipt."""
    outbox_path = tmp_path / "db-only-receipt.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    vault = tmp_path / "vault-db-only-receipt"
    vault.mkdir()
    write_guard = WriteGuard(snapshot_fn=lambda: {"state": "healthy"})
    draft = draft_dead_letter_case(
        vault_root=vault,
        topic="ingest.vault.changed",
        reason="schema_violation:missing_required_field",
        event_id="evt-db-only-receipt",
        payload={"event_id": "evt-db-only-receipt"},
        trace_id="trace-db-only-receipt",
        write_guard=write_guard,
    )
    assert draft is not None
    promoted = promote_draft(
        vault,
        draft.draft_id,
        decided_by="human:db-replay",
        write_guard=write_guard,
    )
    assert promoted.authority_receipt is not None
    records = [
        json.loads(line)
        for line in outbox_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    matching = [
        record
        for record in records
        if record.get("payload", {}).get("draft_id") == draft.draft_id
    ]
    assert len(matching) == 1
    db_record = matching[0]
    outbox_path.unlink()
    monkeypatch.setattr(receipt_sources, "_read_db_outbox_records", lambda: [db_record])

    writes: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    real_write = failure_capture_module.write_note_relative

    def count_write(*args: Any, **kwargs: Any) -> Any:
        writes.append((args, kwargs))
        return real_write(*args, **kwargs)

    monkeypatch.setattr(failure_capture_module, "write_note_relative", count_write)
    recovered = reconcile_pending_disposition_receipt(vault, draft.draft_id)

    assert recovered.authority_receipt is not None
    assert recovered.authority_receipt.receipt_id == promoted.authority_receipt.receipt_id
    assert recovered.authority_receipt.decision_token_id == (
        promoted.authority_receipt.decision_token_id
    )
    assert writes == []
    assert not outbox_path.exists()
