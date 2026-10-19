from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ops.native_source_identity_persistence import (
    IdentityInventory,
    SourceIdentityPersistenceRefusal,
    run_ordinary_persistence,
    validate_receipt,
)


REVISION = "a" * 40


def _summary(**overrides: int) -> SimpleNamespace:
    values = {
        "scanned": 1,
        "ingested": 1,
        "errors": 0,
        "malformed": 0,
        "skipped_locked": 0,
        "skipped_invalid": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_operation_uses_only_ordinary_vault_alpha_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def ordinary(root: Path, **kwargs: object) -> SimpleNamespace:
        calls.append({"root": root, **kwargs})
        return _summary()

    monkeypatch.setattr("app.ingest.vault_alpha.run_vault_alpha_ingest", ordinary)
    receipt = run_ordinary_persistence(
        operation_id=str(uuid4()), channel="dev", revision=REVISION,
        vault_root=tmp_path,
        inventory_reader=lambda _root: IdentityInventory(1, 1, 0, 0, 0),
    )

    assert receipt["terminal_state"] == "committed"
    assert calls == [{
        "root": tmp_path,
        "max_notes": 0,
        "include_test_note": False,
        "force": True,
        "source_backed_rebuild": False,
    }]


def test_receipt_is_content_free_and_rejects_private_child_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    def noisy(_root: Path) -> SimpleNamespace:
        print("/private/source.md 00000000-0000-0000-0000-000000000001")
        print("secret child diagnostic", file=__import__("sys").stderr)
        return _summary()

    receipt = run_ordinary_persistence(
        operation_id=str(uuid4()), channel="test", revision=REVISION,
        vault_root=tmp_path, producer=noisy,
        inventory_reader=lambda _root: IdentityInventory(2, 2, 0, 0, 0),
    )
    assert capsys.readouterr() == ("", "")
    encoded = json.dumps(receipt, sort_keys=True)
    assert "/private" not in encoded
    assert "00000000" not in encoded
    assert set(receipt) == {
        "contract", "operation_id", "channel", "revision", "terminal_state",
        "eligible", "reason", "selected_count", "persisted_count",
        "missing_count", "invalid_count", "ambiguous_count", "producer_error_count",
    }
    with pytest.raises(SourceIdentityPersistenceRefusal):
        validate_receipt({**receipt, "private_path": "/private/source.md"})


def test_operation_is_idempotent_and_fail_closed_on_partial_or_concurrent_state(
    tmp_path: Path,
) -> None:
    calls = 0

    def partial(_root: Path) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return _summary(errors=1)

    operation_id = str(uuid4())
    first = run_ordinary_persistence(
        operation_id=operation_id, channel="dev", revision=REVISION,
        vault_root=tmp_path, producer=partial,
    )
    assert calls == 1
    assert first["terminal_state"] == "failed"
    assert first["eligible"] is False
    assert first["reason"] == "source_summary_incomplete"
    with pytest.raises(SourceIdentityPersistenceRefusal):
        run_ordinary_persistence(
            operation_id="not-an-operation", channel="dev", revision=REVISION,
            vault_root=tmp_path, producer=partial,
        )

    malformed = run_ordinary_persistence(
        operation_id=str(uuid4()), channel="dev", revision=REVISION,
        vault_root=tmp_path,
        producer=lambda _root: _summary(scanned="1"),  # type: ignore[arg-type]
    )
    assert malformed["terminal_state"] == "failed"
    assert malformed["reason"] == "source_summary_incomplete"

    partial_summary = run_ordinary_persistence(
        operation_id=str(uuid4()), channel="dev", revision=REVISION,
        vault_root=tmp_path, producer=lambda _root: _summary(scanned=2, ingested=1),
    )
    assert partial_summary["terminal_state"] == "failed"
    assert partial_summary["reason"] == "source_summary_incomplete"

    from app.ops.host_secret_controller import HostSecretController, TerminalEvidence

    controller = HostSecretController(tmp_path / "controller")
    with controller.source_persistence_operation(
        "dev", operation_id=operation_id,
    ) as (operation, resumed):
        assert resumed is False
        operation.prepare_mutation()
        operation.finish(TerminalEvidence(
            operation_id, "source-persistence", "dev", "failed", "remote-terminal",
        ))
    with controller.source_persistence_operation(
        "dev", operation_id=operation_id,
    ) as (operation, resumed):
        assert resumed is True
        assert operation.completed_result == "failed"
        operation.finish(TerminalEvidence(
            operation_id, "source-persistence", "dev", "failed", "remote-terminal",
        ))


def test_postwrite_eligibility_is_complete_and_content_free(tmp_path: Path) -> None:
    missing = run_ordinary_persistence(
        operation_id=str(uuid4()), channel="dev", revision=REVISION,
        vault_root=tmp_path, producer=lambda _root: _summary(),
        inventory_reader=lambda _root: IdentityInventory(3, 2, 1, 0, 0),
    )
    assert missing["terminal_state"] == "failed"
    assert missing["reason"] == "source_identity_ineligible"
    assert missing["missing_count"] == 1

    ambiguous = run_ordinary_persistence(
        operation_id=str(uuid4()), channel="dev", revision=REVISION,
        vault_root=tmp_path, producer=lambda _root: _summary(),
        inventory_reader=lambda _root: IdentityInventory(3, 3, 0, 0, 2),
    )
    assert ambiguous["terminal_state"] == "failed"
    assert ambiguous["reason"] == "source_identity_ambiguous"


def test_native_supervisor_accepts_only_the_fixed_source_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ops import postgres_deploy_linux as linux

    operation_id = str(uuid4())
    config = SimpleNamespace(channel="dev")
    calls = []
    committed = {
        "contract": "native-source-identity-persistence.v1",
        "operation_id": operation_id,
        "channel": "dev",
        "revision": REVISION,
        "terminal_state": "committed",
        "eligible": True,
        "reason": None,
        "selected_count": 1,
        "persisted_count": 1,
        "missing_count": 0,
        "invalid_count": 0,
        "ambiguous_count": 0,
        "producer_error_count": 0,
    }

    class Effects:
        def __init__(self, selected_config):
            assert selected_config is config

        def persist_source_identity(self, requested_id, revision, selected):
            calls.append((requested_id, revision, selected))
            return committed

    monkeypatch.setattr(linux.LinuxConfig, "load", lambda _channel: config)
    monkeypatch.setattr(linux, "LinuxEffects", Effects)
    supervisor = linux.DeploymentSupervisor(config)
    request = {
        "action": "source-identity-persist",
        "operation_id": operation_id,
        "revision": REVISION,
        "authority_cutover": {
            "binding_id": "vault-alpha",
            "root": "/srv/vault-alpha",
            "ownership_root": "/srv/instance-ownership",
        },
    }
    assert supervisor.request(request) == {"source_identity_persistence": committed}
    assert len(calls) == 1
    with pytest.raises(linux.PostgresDeployError):
        supervisor.request({**request, "private_path": "/srv/vault-alpha/private.md"})
    with pytest.raises(linux.PostgresDeployError):
        supervisor.request({**request, "operation_id": "not-a-uuid"})


@pytest.mark.parametrize(
    "quiesced,restore_ok",
    [(True, True), (False, True), (True, False)],
)
def test_linux_effect_holds_writer_fence_until_owned_worker_is_quiescent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quiesced: bool, restore_ok: bool,
) -> None:
    from contextlib import contextmanager

    from app.ops import native_source_bootstrap, postgres_deploy_linux as linux
    from app.ops.postgres_deploy import AuthorityCutover

    operation_id = str(uuid4())
    journal = SimpleNamespace(
        directory=tmp_path / "journal",
        channel="dev",
        read=lambda: SimpleNamespace(terminal_result="failed"),
    )
    config = SimpleNamespace(channel="dev", journal=journal, uid=501)
    effects = linux.LinuxEffects(config)
    events: list[str] = []

    @contextmanager
    def channel_lock(**_kwargs):
        events.append("lock")
        yield

    @contextmanager
    def reconcile_lock(**_kwargs):
        events.append("reconcile-lock")
        yield object()

    def compose(*args, **_kwargs):
        action = str(args[0])
        events.append(action)
        if action == "run":
            return json.dumps({
                "contract": "native-source-identity-persistence.v1",
                "operation_id": operation_id,
                "channel": "dev",
                "revision": REVISION,
                "terminal_state": "committed",
                "eligible": True,
                "reason": None,
                "selected_count": 1,
                "persisted_count": 1,
                "missing_count": 0,
                "invalid_count": 0,
                "ambiguous_count": 0,
                "producer_error_count": 0,
            })
        if action == "up" and not restore_ok:
            raise linux.PostgresDeployError()
        return ""

    effects.channel_lock = channel_lock  # type: ignore[method-assign]
    effects.failed_reconciliation_lock = reconcile_lock  # type: ignore[method-assign]
    effects.retire_reconciled_channel_lock = lambda *_args, **_kwargs: events.append("retire")  # type: ignore[method-assign]
    effects.compose = compose  # type: ignore[method-assign]
    monkeypatch.setattr(linux, "require_cutover_target_config", lambda *_args: None)
    monkeypatch.setattr(linux, "_capture_watch_configured", lambda _config: False)
    monkeypatch.setattr(native_source_bootstrap, "quiesce_owned_container", lambda *_args: quiesced)

    result = effects.persist_source_identity(
        operation_id, REVISION,
        AuthorityCutover("vault-alpha", "/srv/vault-alpha", "/srv/instance-ownership"),
    )
    if quiesced and restore_ok:
        assert result["terminal_state"] == "committed"
        assert events == ["lock", "stop", "run", "up", "reconcile-lock", "retire"]
    else:
        assert result["terminal_state"] == "failed"
        assert result["reason"] == "source_operation_conflict"
        if not quiesced:
            assert "up" not in events
        assert "retire" not in events
