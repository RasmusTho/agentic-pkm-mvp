from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import app.panel.confirmation as confirm_module
from app.events.panel import (
    NoteRef,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentPayload,
    PanelRuntimeActionResult,
)
from app.observability.status_service import _get_panel_diagnostics
from app.panel.confirmation import (
    ConfirmIdempotencyStore,
    ConfirmRequest,
    ConfirmResponse,
    PanelConfirmationService,
    ProposalStore,
    StagedProposal,
)


def _intent(
    *,
    proposal_id: str = "prop-persist-1",
    artifact_id: str = "note-persist-1",
    action_label: str = "queue review",
) -> PanelIntentEvent:
    return PanelIntentEvent(
        trace_id=f"trace-{proposal_id}",
        payload=PanelIntentPayload(
            note=NoteRef(uuid=artifact_id, path="notes/persist.md"),
            panel=PanelInfo(panel_id=proposal_id, instruction="queue this for review"),
            actions=[
                PanelIntentAction(
                    id="queue_review",
                    label=action_label,
                    checked=True,
                )
            ],
        ),
    )


def _stage(
    store: ProposalStore,
    *,
    proposal_id: str = "prop-persist-1",
    artifact_id: str = "note-persist-1",
) -> None:
    store.stage(
        proposal_id,
        StagedProposal(
            artifact_id=artifact_id,
            intent_event=_intent(proposal_id=proposal_id, artifact_id=artifact_id),
            proposed_at=time.time() - 60,
            trace_id=f"trace-{proposal_id}",
            proposal_origin="test",
        ),
    )


def _request(
    *,
    proposal_id: str = "prop-persist-1",
    artifact_id: str = "note-persist-1",
    idempotency_key: str = "idem-persist-1",
) -> ConfirmRequest:
    return ConfirmRequest(
        proposal_id=proposal_id,
        artifact_id=artifact_id,
        action="confirm",
        idempotency_key=idempotency_key,
    )


def _runtime_result() -> MagicMock:
    result = MagicMock()
    result.actions = [
        PanelRuntimeActionResult(
            id="queue_review",
            label="queue review",
            checked=True,
            status="triggered",
        )
    ]
    result.emitted_events = [{"event": "panel.intent.executed"}]
    return result


def _stores(db_path: Path) -> tuple[ProposalStore, ConfirmIdempotencyStore]:
    return (
        ProposalStore(db_path, retention_seconds=3600),
        ConfirmIdempotencyStore(db_path, retention_seconds=3600),
    )


def test_staged_proposal_survives_restart_and_confirms(tmp_path: Path) -> None:
    db_path = tmp_path / "panel-confirmation.sqlite3"
    proposal_store, _ = _stores(db_path)
    _stage(proposal_store)

    restarted_proposals, restarted_idempotency = _stores(db_path)
    service = PanelConfirmationService(
        restarted_proposals,
        restarted_idempotency,
        same_turn_ttl=0,
    )

    assert restarted_proposals.get("prop-persist-1") is not None

    with patch.object(
        confirm_module,
        "execute_panel_intent",
        return_value=_runtime_result(),
    ) as execute:
        response = service.confirm(_request())

    assert execute.call_count == 1
    assert response.status == "executed"
    assert response.receipt is not None
    assert response.receipt_visibility == "durable_vault_visible"


def test_idempotency_keys_survive_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "panel-confirmation.sqlite3"
    proposal_store, idempotency_store = _stores(db_path)
    _stage(proposal_store)
    service = PanelConfirmationService(
        proposal_store,
        idempotency_store,
        same_turn_ttl=0,
    )
    request = _request(idempotency_key="idem-restart-replay")

    with patch.object(
        confirm_module,
        "execute_panel_intent",
        return_value=_runtime_result(),
    ) as execute:
        first = service.confirm(request)

    restarted_proposals, restarted_idempotency = _stores(db_path)
    restarted_service = PanelConfirmationService(
        restarted_proposals,
        restarted_idempotency,
        same_turn_ttl=0,
    )

    with patch.object(
        confirm_module,
        "execute_panel_intent",
        side_effect=AssertionError("idempotent replay must not execute"),
    ):
        replay = restarted_service.confirm(request)

    assert execute.call_count == 1
    assert replay == first


def test_recovery_never_executes(tmp_path: Path) -> None:
    db_path = tmp_path / "panel-confirmation.sqlite3"
    proposal_store, _ = _stores(db_path)
    _stage(proposal_store)

    with patch.object(confirm_module, "execute_panel_intent") as execute:
        recovered, _ = _stores(db_path)

    execute.assert_not_called()
    assert recovered.get("prop-persist-1") is not None


def test_unavailable_backing_reports_degraded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bad_db_path = tmp_path / "not-a-sqlite-file"
    bad_db_path.mkdir()
    proposal_store = ProposalStore(bad_db_path, retention_seconds=3600)
    idempotency_store = ConfirmIdempotencyStore(bad_db_path, retention_seconds=3600)

    _stage(proposal_store)
    response = ConfirmResponse(
        proposal_id="prop-persist-1",
        artifact_id="note-persist-1",
        status="executed",
        outcome="success",
        idempotency_key="idem-degraded",
    )
    idempotency_store.set("idem-degraded", response)

    assert proposal_store.get("prop-persist-1") is not None
    assert idempotency_store.get("idem-degraded") == response
    assert proposal_store.degraded is True
    assert idempotency_store.degraded is True

    monkeypatch.setattr(confirm_module, "_proposal_store", proposal_store)
    monkeypatch.setattr(confirm_module, "_idempotency_store", idempotency_store)

    posture = confirm_module.panel_staging_store_posture()
    diagnostics = _get_panel_diagnostics()

    assert posture["degraded"] is True
    assert posture["proposal_store_mode"] == "memory-degraded"
    assert diagnostics.staging_store_degraded is True
    assert diagnostics.staging_proposal_store_mode == "memory-degraded"
