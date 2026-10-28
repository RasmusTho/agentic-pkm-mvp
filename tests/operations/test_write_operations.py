from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Request
import pytest

from app.agents.panel_agent import runtime as panel_runtime
from app.agents.panel_agent import graph as panel_graph
from app.chat.canvas_writer import CanvasWriter, GovernanceBearingMutationError
from app.chat.session_log import SessionLogWriter
from app.events.panel import (
    NoteRef,
    PanelActionMapping,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentPayload,
)
from app.knowledge.write_ops import read_note_text_with_version
from app.operations import (
    InMemoryReceiptStore,
    JsonReceiptStore,
    OperationContext,
    OperationExecutionKernel,
    OperationRequest,
    OperationStatus,
    PolicyDecision,
)
from app.operations.contracts import (
    ConvergenceState,
    OperationProvenance,
    ReceiptStatus,
    SourceEffectStatus,
)
from app.operations import write_operations as writes
from app.panel.confirmation import (
    ConfirmIdempotencyStore,
    ConfirmRequest,
    PanelConfirmationService,
    ProposalStore,
    StagedProposal,
)
from app.write_guard import WritesBlockedError
from tests.api._vault_test_helpers import bind_initialized_vault


@pytest.fixture
def bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> writes.WriteOperationServerConfig:
    root = tmp_path / "vault"
    root.mkdir()
    bind_initialized_vault(monkeypatch, root, store_dir=tmp_path)
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Inbox")
    monkeypatch.setenv("VAULT_SOURCES_DIR_REL", "Sources")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    monkeypatch.setenv("PANEL_AGENT_PIPELINE", "direct")
    monkeypatch.setenv("POLICY_ENFORCE", "0")
    monkeypatch.setattr(
        "app.orchestrator.executor.INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl")
    )
    # External cognition is irrelevant to the capture write/receipt contract.
    monkeypatch.setattr(writes.capture, "_offer_question_registration_proposal", lambda **_: None)
    note = root / "Notes" / "note.md"
    note.parent.mkdir()
    artifact_id = str(uuid4())
    note.write_text(f"---\nuuid: {artifact_id}\nkind: note\ntrust: human\n---\n\nOriginal body.\n")
    request = Request({"type": "http", "method": "POST", "headers": []})
    request.state.compatibility_write_root = root
    request.state.trace_id = "capture-trace"
    panel_graph._IDEMPOTENCY_GUARD._entries.clear()
    return writes.WriteOperationServerConfig(
        root,
        OperationContext("fixture-context", "generation-1"),
        "owner",
        note,
        artifact_id,
        request,
        PanelConfirmationService(ProposalStore(), ConfirmIdempotencyStore(), same_turn_ttl=0),
    )


def _request(
    config: writes.WriteOperationServerConfig,
    operation: str,
    *,
    request_id: str = "operation-1",
    arguments: dict[str, Any] | None = None,
    version: str | None = None,
) -> OperationRequest:
    existing = operation in {writes.UPDATE_OPERATION_ID, writes.PROPOSAL_APPLY_OPERATION_ID}
    if existing and version is None:
        _, version = read_note_text_with_version(config.note_path)  # type: ignore[arg-type]
    return OperationRequest(
        operation,
        request_id,
        config.context,
        targets=({"artifact_id": config.artifact_id},) if existing else (),
        arguments=arguments or {},
        expected_version=version,
        provenance=OperationProvenance("owner", "direct-test", "test"),
    )


def _run(
    config: writes.WriteOperationServerConfig,
    request: OperationRequest,
    *,
    kernel: OperationExecutionKernel | None = None,
):
    kernel = kernel or _kernel(config)
    delegation = {
        "active_context_ref": config.context.active_context_ref,
        "vault_generation": config.context.vault_generation,
        "operation_ids": [request.operation_id],
        "policy_version": "policy-1",
        "principal": "owner",
        "client": "test",
        "surface": "test",
        "receipt_ref": "delegation-1",
        "authority_class": "governed_effect",
        "target_ids": [config.artifact_id],
        "max_targets": 1,
        "allowed_effects": [request.operation_id],
        "expires_at": 4102444800,
        "revoked": False,
    }
    return kernel.execute(request, delegation)


def _kernel(config: writes.WriteOperationServerConfig) -> OperationExecutionKernel:
    return OperationExecutionKernel(
        context_resolver=lambda _: True,
        policy_evaluator=lambda *_: PolicyDecision.allowed("policy-1"),
        handlers=writes.build_write_operation_handlers(config),
        receipt_store=InMemoryReceiptStore(),
        version_checker=lambda _: True,
        token_validator=lambda *_: True,
    )


def _stage(
    config: writes.WriteOperationServerConfig,
    *,
    proposal_id: str = "proposal-1",
    trust_verb: str = "APPLY",
    action_id: str = "promote",
) -> None:
    assert config.note_path is not None and config.confirmation_service is not None
    event = PanelIntentEvent(
        trace_id="panel-trace",
        payload=PanelIntentPayload(
            note=NoteRef(uuid=config.artifact_id, path=str(config.note_path)),
            panel=PanelInfo(panel_id=proposal_id, instruction="Apply the reviewed proposal"),
            actions=[
                PanelIntentAction(
                    id=action_id,
                    label=f"Promote this note {action_id}",
                    checked=True,
                    mapping=PanelActionMapping(
                        id=action_id,
                        intent_type="promotion",
                        downstream_event="promote.intent.created",
                        trust_verb=trust_verb,
                        params={"maturity": "evergreen"},
                    ),
                )
            ],
        ),
    )
    config.confirmation_service._proposals.stage(
        proposal_id,
        StagedProposal(artifact_id=config.artifact_id, intent_event=event, proposed_at=0),
    )


def _rule_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    # Use the real policy/graph, with an empty optional catalog so the explicit
    # legacy mapping is admissible. This does not stub execution or HKA.
    monkeypatch.setattr(panel_runtime, "load_panel_action_catalog", lambda: None)


def test_write_operations_invoke_only_governed_owner_entrypoints(bound, monkeypatch) -> None:
    observed: list[str] = []
    for owner, name in [
        (writes.capture, "capture_to_inbox"),
        (writes, "execute_plan_step"),
        (writes, "write_note_from_absolute"),
    ]:
        original = getattr(owner, name)

        def spy(*args, _fn=original, _name=name, **kwargs):
            observed.append(_name)
            return _fn(*args, **kwargs)

        monkeypatch.setattr(owner, name, spy)
    capture = _run(
        bound, _request(bound, writes.CAPTURE_OPERATION_ID, arguments={"text": "Remember this"})
    )
    create = _run(
        bound,
        _request(
            bound,
            writes.CREATE_OPERATION_ID,
            request_id="create",
            arguments={"kind": "note", "title": "Typed", "body": "Created via EXE"},
        ),
    )
    update = _run(
        bound,
        _request(
            bound,
            writes.UPDATE_OPERATION_ID,
            request_id="update",
            arguments={"body": "Changed body."},
        ),
    )
    assert [capture.status, create.status, update.status] == [
        OperationStatus.CONVERGENCE_PENDING
    ] * 3
    assert observed == [
        "capture_to_inbox",
        "execute_plan_step",
        "execute_plan_step",
        "execute_plan_step",
        "write_note_from_absolute",
    ]
    assert "Remember this" in (bound.vault_root / "Inbox/inbox.md").read_text()
    created = list((bound.vault_root / "_mcp").glob("*.md"))
    assert len(created) == 1 and "Created via EXE" in created[0].read_text()
    assert "Changed body." in bound.note_path.read_text()
    assert "trust: human" in bound.note_path.read_text()


def test_write_failures_preserve_conflict_denial_validation_and_ambiguity(
    bound, monkeypatch
) -> None:
    original_bytes = bound.note_path.read_bytes()
    stale = _run(
        bound,
        _request(bound, writes.UPDATE_OPERATION_ID, arguments={"body": "stale"}, version="old"),
    )
    invalid = _run(
        bound,
        _request(
            bound,
            writes.UPDATE_OPERATION_ID,
            arguments={"body": "---\ntrust: trusted\n---\nInjected"},
        ),
    )
    with monkeypatch.context() as patch:

        def deny(*_, **__):
            raise WritesBlockedError("locked", "test", "operation.artifact.update")

        patch.setattr(writes.DEFAULT_WRITE_GUARD, "assert_writes_allowed", deny)
        denied = _run(
            bound, _request(bound, writes.UPDATE_OPERATION_ID, arguments={"body": "denied"})
        )
    assert [stale.status, invalid.status, denied.status] == [
        OperationStatus.CONFLICTED,
        OperationStatus.INVALID,
        OperationStatus.REJECTED,
    ]
    assert bound.note_path.read_bytes() == original_bytes
    calls = []

    def uncertain(*args, **kwargs):
        calls.append(1)
        raise OSError("ack lost")

    monkeypatch.setattr(writes, "write_note_from_absolute", uncertain)
    kernel = _kernel(bound)
    req = _request(bound, writes.UPDATE_OPERATION_ID, arguments={"body": "uncertain"})
    ambiguous = _run(bound, req, kernel=kernel)
    assert ambiguous.status is OperationStatus.RECOVERY_REQUIRED
    assert _run(bound, req, kernel=kernel) == ambiguous and calls == [1]


def test_success_binds_effect_receipt_and_truthful_projection_state(bound) -> None:
    request = _request(bound, writes.UPDATE_OPERATION_ID, arguments={"body": "Updated."})
    outcome = _run(bound, request)
    assert outcome.status is OperationStatus.CONVERGENCE_PENDING
    assert outcome.provenance == request.provenance
    assert outcome.convergence.source_effect is SourceEffectStatus.COMMITTED
    assert outcome.convergence.store is ConvergenceState.REBUILD_REQUIRED
    assert outcome.convergence.index is ConvergenceState.REBUILD_REQUIRED
    assert outcome.convergence.link is ConvergenceState.REBUILD_REQUIRED
    assert outcome.receipt.status is ReceiptStatus.COMMITTED
    write = outcome.receipt.extensions["write"]
    source = write["source_receipt"]
    assert source["outcome"] == "written" and source["locator"]["path"] == "Notes/note.md"
    assert write["authority_receipt"]["source_receipt_ref"] == "fs_vault:write_note:Notes/note.md"
    assert write["authority_receipt"]["decision_token_id"] == write["decision_token"]["token_id"]
    assert write["input_version"] == request.expected_version
    assert write["resulting_version"] == read_note_text_with_version(bound.note_path)[1]
    events = [
        json.loads(line)
        for line in (bound.vault_root.parent / "outbox.jsonl").read_text().splitlines()
    ]
    assert events[-1]["payload"]["write"]["source_receipt"] == source


def test_panel_confirmation_write_is_versioned_and_failures_do_not_succeed(
    bound, monkeypatch
) -> None:
    _rule_catalog(monkeypatch)
    _stage(bound)
    request = _request(
        bound, writes.PROPOSAL_APPLY_OPERATION_ID, arguments={"proposal_id": "proposal-1"}
    )
    original_writer = panel_runtime.write_note_from_absolute
    receipts = []
    versions = []

    def writer(*args, **kwargs):
        versions.append(kwargs["expected_version"])
        receipt = original_writer(*args, **kwargs)
        receipts.append(receipt)
        return receipt

    monkeypatch.setattr(panel_runtime, "write_note_from_absolute", writer)
    outcome = _run(bound, request)
    assert outcome.status is OperationStatus.CONVERGENCE_PENDING
    assert versions == [request.expected_version]
    response = bound.confirmation_service._idempotency.get(request.request_id)
    assert response.source_receipt is receipts[0]
    assert outcome.receipt.extensions["write"]["source_receipt"] == asdict(receipts[0])

    _stage(bound, proposal_id="stale-proposal", action_id="stale-action")
    expected = read_note_text_with_version(bound.note_path)[1]
    bound.note_path.write_text(bound.note_path.read_text() + "Concurrent human edit.\n")
    unchanged = bound.note_path.read_bytes()
    failed = bound.confirmation_service.confirm(
        ConfirmRequest(
            proposal_id="stale-proposal",
            artifact_id=bound.artifact_id,
            action="confirm",
            idempotency_key="stale",
            expected_version=expected,
        ),
        vault_root=bound.vault_root,
    )
    assert failed.status == "conflicted" and failed.receipt is None
    assert bound.note_path.read_bytes() == unchanged and len(receipts) == 1

    _stage(bound, proposal_id="io-proposal", action_id="io-action")

    def failed_writer(*_, **__):
        raise OSError("source unavailable")

    monkeypatch.setattr(panel_runtime, "write_note_from_absolute", failed_writer)
    failed = bound.confirmation_service.confirm(
        ConfirmRequest(
            proposal_id="io-proposal",
            artifact_id=bound.artifact_id,
            action="confirm",
            idempotency_key="io",
            expected_version=read_note_text_with_version(bound.note_path)[1],
        ),
        vault_root=bound.vault_root,
    )
    assert failed.status == "recovery_required" and failed.receipt is None
    assert failed.source_state == "unknown" and bound.note_path.read_bytes() == unchanged


def test_dormant_autonomous_edit_preserves_canvas_policy_and_installation_seal(bound) -> None:
    from app.api.app import app

    routes = tuple(app.routes)
    writes.build_write_operation_handlers(bound)
    assert tuple(app.routes) == routes
    assert not any("operations" in str(getattr(route, "path", "")) for route in routes)
    autonomous = _run(
        bound,
        _request(bound, writes.UPDATE_OPERATION_ID, arguments={"body": "Autonomous under GOV."}),
    )
    assert (
        autonomous.receipt.extensions["write"]["authority_receipt"]["action"]
        == "operation.artifact.update"
    )
    logs = SessionLogWriter(vault_root=bound.vault_root)
    session = logs.open_session(bound.note_path, "human-present")
    canvas = CanvasWriter(bound.vault_root, logs)
    canvas.apply_edit(session, "Human body edit.", "Applied in present session")
    assert (
        "Human body edit." in bound.note_path.read_text()
        and "trust: human" in bound.note_path.read_text()
    )
    with pytest.raises(GovernanceBearingMutationError):
        canvas.apply_edit(None, "No authority", "must refuse")
    with pytest.raises(GovernanceBearingMutationError):
        canvas.apply_edit(session, "---\ntrust: elevated\n---\n", "must refuse")
    scoped = Request(
        {
            "type": "http",
            "method": "POST",
            "headers": [(b"x-active-context-session", b"read-carrier")],
        }
    )
    scoped.state.compatibility_write_root = bound.vault_root
    refused = _run(
        replace(bound, capture_request=scoped),
        _request(bound, writes.CAPTURE_OPERATION_ID, arguments={"text": "must remain sealed"}),
    )
    assert refused.status is OperationStatus.REJECTED
    assert not (bound.vault_root / "Inbox/inbox.md").exists()


def test_committed_source_survives_projection_and_authority_receipt_failures(
    bound, monkeypatch
) -> None:
    _rule_catalog(monkeypatch)
    _stage(bound)

    def fail_refresh(*_, **__):
        raise OSError("companion unavailable")

    monkeypatch.setattr(panel_runtime, "_refresh_companion_hash", fail_refresh)
    request = _request(
        bound, writes.PROPOSAL_APPLY_OPERATION_ID, arguments={"proposal_id": "proposal-1"}
    )
    kernel = _kernel(bound)
    result = _run(bound, request, kernel=kernel)
    assert result.status is OperationStatus.RECOVERY_REQUIRED
    assert result.convergence.source_effect is SourceEffectStatus.COMMITTED
    assert result.receipt.extensions["write"]["source_receipt"]["outcome"] == "written"
    after = bound.note_path.read_bytes()
    assert _run(bound, request, kernel=kernel) == result
    assert bound.note_path.read_bytes() == after
    assert not panel_graph._IDEMPOTENCY_GUARD.seen_action(bound.artifact_id, "promote")

    monkeypatch.setattr(writes, "append_jsonl_outbox_event", lambda *_, **__: False)
    result = _run(
        bound,
        _request(
            bound,
            writes.UPDATE_OPERATION_ID,
            request_id="authority-unavailable",
            arguments={"body": "Source still commits."},
        ),
    )
    assert result.status is OperationStatus.RECOVERY_REQUIRED
    assert result.convergence.source_effect is SourceEffectStatus.COMMITTED
    assert result.receipt.status is ReceiptStatus.PENDING
    assert result.receipt.extensions["write"]["source_receipt"]["outcome"] == "written"
    assert "Source still commits." in bound.note_path.read_text()


def test_policy_fallback_never_emits_an_unadmitted_downstream_effect(bound, monkeypatch) -> None:
    _rule_catalog(monkeypatch)
    _stage(bound, trust_verb="SUGGEST")
    result = _run(
        bound,
        _request(
            bound, writes.PROPOSAL_APPLY_OPERATION_ID, arguments={"proposal_id": "proposal-1"}
        ),
    )
    assert result.status is OperationStatus.REJECTED
    assert result.receipt.extensions["write"]["effect_state"] == "panel_diagnostic_only"
    outbox = bound.vault_root.parent / "outbox.jsonl"
    assert all(
        json.loads(line).get("event") != "promote.intent.created"
        for line in outbox.read_text().splitlines()
    )


def test_source_identity_and_metadata_remain_with_their_owners(bound) -> None:
    request = _request(
        bound,
        writes.UPDATE_OPERATION_ID,
        arguments={"body": "body", "metadata": {"trust": "trusted"}},
    )
    assert _run(bound, request).status is OperationStatus.INVALID
    original = bound.note_path.read_text()
    bound.note_path.write_text(original.replace(bound.artifact_id, "different-identity"))
    request = _request(bound, writes.UPDATE_OPERATION_ID, arguments={"body": "must not apply"})
    assert _run(bound, request).status is OperationStatus.CONFLICTED
    assert "must not apply" not in bound.note_path.read_text()
    outside = bound.vault_root.parent / "outside.md"
    outside.write_text(original)
    alias = bound.vault_root / "alias.md"
    alias.symlink_to(outside)
    assert _run(replace(bound, note_path=alias), request).status is OperationStatus.REJECTED
    assert outside.read_text() == original


def test_replay_after_restart_never_repeats_a_committed_owner_write(
    bound, tmp_path, monkeypatch
) -> None:
    request = _request(bound, writes.UPDATE_OPERATION_ID, arguments={"body": "Once only."})
    store_path = tmp_path / "operations.json"
    kernel = _kernel(bound)
    kernel.receipt_store = JsonReceiptStore(store_path)
    first = _run(bound, request, kernel=kernel)
    assert first.status is OperationStatus.CONVERGENCE_PENDING

    def forbid(*_, **__):
        pytest.fail("replay must not invoke the writer")

    monkeypatch.setattr(writes, "write_note_from_absolute", forbid)
    resumed = _kernel(bound)
    resumed.receipt_store = JsonReceiptStore(store_path)
    assert _run(bound, request, kernel=resumed) == first


def test_lost_gov_or_kernel_receipt_preserves_the_known_source_receipt(bound, monkeypatch) -> None:
    request = _request(
        bound, writes.UPDATE_OPERATION_ID, arguments={"body": "Committed before receipt failure."}
    )
    with monkeypatch.context() as patch:

        def fail(*_, **__):
            raise OSError("GOV unavailable")

        patch.setattr(writes.GovernedWriteAdapter, "record_authority_receipt", fail)
        result = _run(bound, request)
    assert result.status is OperationStatus.RECOVERY_REQUIRED
    assert result.convergence.source_effect is SourceEffectStatus.COMMITTED
    assert result.receipt.extensions["write"]["source_receipt"]["outcome"] == "written"
    assert result.receipt.payload["effect_receipt_ref"] is None
    kernel = _kernel(bound)

    def lost(*_, **__):
        raise OSError("kernel ledger unavailable")

    monkeypatch.setattr(kernel.receipt_store, "finalize", lost)
    request = _request(
        bound,
        writes.UPDATE_OPERATION_ID,
        request_id="ledger-failure",
        arguments={"body": "Second explicit operation."},
    )
    result = _run(bound, request, kernel=kernel)
    assert result.status is OperationStatus.RECOVERY_REQUIRED
    assert result.convergence.source_effect is SourceEffectStatus.COMMITTED
    assert result.receipt.extensions["write"]["source_receipt"]["outcome"] == "written"
    assert result.receipt.status is ReceiptStatus.PENDING
    assert _run(bound, request, kernel=kernel).status is OperationStatus.RECOVERY_REQUIRED
