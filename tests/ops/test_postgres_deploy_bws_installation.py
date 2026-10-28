from __future__ import annotations

from contextlib import contextmanager
import io
import json
import sys
import threading
from types import SimpleNamespace
import uuid

import pytest

from app.ops import bws_installation_transaction, postgres_deploy_linux


def test_source_installation_rpc_dispatches_only_dev_test_to_transaction(monkeypatch):
    monkeypatch.setattr(postgres_deploy_linux.os, "geteuid", lambda: 0)
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        bws_installation_transaction,
        "run_source_installation",
        lambda channel, request: calls.append((channel, request)) or {"accepted": True},
    )
    request = {"action": "source-installation", "operation_id": "opaque-to-rpc"}

    assert postgres_deploy_linux.rpc("dev", request) == {"accepted": True}
    assert postgres_deploy_linux.rpc("test", request) == {"accepted": True}
    assert calls == [("dev", request), ("test", request)]
    with pytest.raises(postgres_deploy_linux.PostgresDeployError):
        postgres_deploy_linux.rpc("prod", request)
    assert calls == [("dev", request), ("test", request)]


def test_native_profile_binds_post_start_observation_to_candidate_checkout(monkeypatch, tmp_path):
    candidate_root = tmp_path / "candidate"
    config = SimpleNamespace(channel="dev", root=tmp_path / "installed")
    ports = bws_installation_transaction._NativePorts()
    ports._config = config
    ports.caller_root = candidate_root
    caller_modules = [{"module": "app.ops.postgres_deploy_linux", "sha256": "a" * 64}]
    observed = {"profile": "candidate"}
    calls = []
    monkeypatch.setattr(
        bws_installation_transaction, "_source_modules",
        lambda selected_config, roots: calls.append((selected_config, roots)) or caller_modules,
    )
    monkeypatch.setattr(bws_installation_transaction, "_verify_candidate_checkout", lambda *_args: None)
    monkeypatch.setattr(
        bws_installation_transaction, "_profile_response",
        lambda channel, request: calls.append((channel, request)) or observed,
    )
    monkeypatch.setattr(
        bws_installation_transaction, "_bind_source_inventory",
        lambda profile, selected_config: profile,
    )

    request = {"action": "source-installation", "candidate_sha": "b" * 40}
    ports.verify_caller_sources(request)
    first = ports.profile("dev", request)
    second = ports.profile("dev", request)

    assert first is observed and second is observed
    assert calls[0] == (config, {"application": candidate_root,
                                "control": bws_installation_transaction._CONTROL_DIRECTORY})
    assert calls[1] == (
        "dev", {**request, "_caller_source_modules": caller_modules},
    )
    assert calls[2] == ("dev", request)


def test_rpc_cli_invocation_preserves_request_and_returns_redacted_transaction_result(monkeypatch):
    monkeypatch.setattr(postgres_deploy_linux.os, "geteuid", lambda: 0)
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        bws_installation_transaction,
        "run_source_installation",
        lambda channel, request: calls.append((channel, request)) or {"source_installation": {"status": "installed"}},
    )
    request = {"action": "source-installation", "operation_id": "operation-at-rpc-boundary"}

    for channel in ("dev", "test"):
        output = io.StringIO()
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(request) + "\n"))
        monkeypatch.setattr(sys, "stdout", output)
        assert postgres_deploy_linux.main(["rpc", channel]) == 0
        assert json.loads(output.getvalue()) == {
            "source_installation": {"status": "installed"},
        }

    assert calls == [("dev", request), ("test", request)]


def test_ordinary_rpc_keeps_shared_reservation_for_full_supervisor_call(monkeypatch):
    monkeypatch.setattr(postgres_deploy_linux.os, "geteuid", lambda: 0)
    state = {"active": False}

    @contextmanager
    def shared_reservation(channel):
        assert channel == "dev"
        assert state["active"] is False
        state["active"] = True
        try:
            yield
        finally:
            state["active"] = False

    monkeypatch.setattr("app.ops.bws_installation_admission.shared_caller_reservation", shared_reservation)
    monkeypatch.setattr(
        postgres_deploy_linux,
        "_rpc_via_supervisor",
        lambda channel, request: {"channel": channel, "action": request["action"],
                                 "reserved": state["active"]},
    )

    assert postgres_deploy_linux.rpc("dev", {"action": "status"}) == {
        "channel": "dev", "action": "status", "reserved": True,
    }
    assert state["active"] is False


def test_supervised_worker_keeps_shared_reservation_after_rpc_returns(monkeypatch):
    from app.ops import bws_installation_admission

    condition = threading.Condition()
    state = {"shared": 0}

    @contextmanager
    def shared_reservation(channel):
        assert channel == "test"
        with condition:
            state["shared"] += 1
        try:
            yield
        finally:
            with condition:
                state["shared"] -= 1
                condition.notify_all()

    def require_exclusive():
        with condition:
            if state["shared"]:
                raise RuntimeError("shared caller still active")

    class Effects:
        config = SimpleNamespace(channel="test")

        @contextmanager
        def channel_lock(self):
            yield

    monkeypatch.setattr(bws_installation_admission, "shared_caller_reservation", shared_reservation)
    operation = postgres_deploy_linux.SupervisedOperation(
        Effects(), str(uuid.uuid4()), plan=object(), bootstrap=False,
    )
    worker_entered = threading.Event()
    release_worker = threading.Event()

    def hold_worker():
        worker_entered.set()
        assert release_worker.wait(3)

    operation._run_locked = hold_worker
    # The service request handler owns a shared reservation while it starts
    # the worker, then returns pending and releases only its own reservation.
    with shared_reservation("test"):
        operation.thread.start()
        assert worker_entered.wait(3)
    assert state["shared"] == 1
    with pytest.raises(RuntimeError, match="shared caller still active"):
        require_exclusive()

    release_worker.set()
    assert operation.finished.wait(3)
    operation.thread.join(3)
    assert not operation.thread.is_alive()
    assert state["shared"] == 0
    require_exclusive()


def test_exec_stop_post_holds_shared_reservation_through_cleanup(monkeypatch):
    state = {"active": False, "cleaned": False}

    @contextmanager
    def shared_reservation(channel):
        assert channel == "dev"
        assert state["active"] is False
        state["active"] = True
        try:
            yield
        finally:
            state["active"] = False

    class Effects:
        def __init__(self, _config):
            self.source = self
            self.config = type("Config", (), {"password_file": type("Password", (), {"exists": lambda _self: True})()})()

        def compose(self, *_args, **_kwargs):
            assert state["active"] is True
            return ""

        def quiescent(self):
            assert state["active"] is True
            return True

        def cleanup(self, *, all_consumers_stopped):
            assert state["active"] is True
            assert all_consumers_stopped is True
            state["cleaned"] = True

    monkeypatch.setattr("app.ops.bws_installation_admission.cleanup_must_skip", lambda _channel: False)
    monkeypatch.setattr("app.ops.bws_installation_admission.shared_caller_reservation", shared_reservation)
    monkeypatch.setattr(postgres_deploy_linux, "LinuxConfig", type("LinuxConfig", (), {"load": staticmethod(lambda _channel: object())}))
    monkeypatch.setattr(postgres_deploy_linux, "LinuxEffects", Effects)

    assert postgres_deploy_linux.main(["cleanup", "dev"]) == 0
    assert state == {"active": False, "cleaned": True}


def test_exec_stop_post_admission_contention_is_a_no_write_success(monkeypatch):
    state = {"loaded": False}

    @contextmanager
    def contended_reservation(_channel):
        raise RuntimeError("exclusive owner active")
        yield

    class Effects:
        def __init__(self, _config):
            state["loaded"] = True

    monkeypatch.setattr("app.ops.bws_installation_admission.cleanup_must_skip", lambda _channel: False)
    monkeypatch.setattr("app.ops.bws_installation_admission.shared_caller_reservation", contended_reservation)
    monkeypatch.setattr(postgres_deploy_linux, "LinuxConfig", type("LinuxConfig", (), {"load": staticmethod(lambda _channel: object())}))
    monkeypatch.setattr(postgres_deploy_linux, "LinuxEffects", Effects)

    assert postgres_deploy_linux.main(["cleanup", "test"]) == 0
    assert state["loaded"] is False


def test_source_profile_supervisor_requires_kernel_peer_credentials(monkeypatch):
    from app.ops import bws_installation_admission

    config = SimpleNamespace(channel="dev")
    supervisor = postgres_deploy_linux.DeploymentSupervisor(config)
    monkeypatch.setattr(supervisor, "_require_current_config", lambda: None)
    monkeypatch.setattr(bws_installation_admission, "cleanup_must_skip", lambda _channel: True)
    selected = {"profile": "synthetic"}
    monkeypatch.setattr(
        bws_installation_admission, "require_active_installation_owner",
        lambda channel, operation_id, candidate_sha, image_digest, *, peer_credentials:
        selected.update(channel=channel, operation_id=operation_id, candidate_sha=candidate_sha,
                        image_digest=image_digest, peer_credentials=peer_credentials),
    )
    def loaded_profile(_config, **kwargs):
        selected["caller_source_modules"] = kwargs.get("caller_source_modules")
        return {"profile": "synthetic"}

    monkeypatch.setattr(
        "app.ops.bws_installation_transaction.loaded_source_profile", loaded_profile,
    )
    request = {
        "action": "source-installation-profile",
        "operation_id": str(uuid.uuid4()),
        "candidate_sha": "a" * 40,
        "image_digest": "sha256:" + "b" * 64,
    }

    with pytest.raises(postgres_deploy_linux.PostgresDeployError):
        supervisor.request(request)
    with pytest.raises(postgres_deploy_linux.PostgresDeployError):
        supervisor.request({**request, "_peer_credentials": [123, 0, 0]})

    caller_modules = [{
        "module": "scripts.compose_env", "root": "application",
        "path": "scripts/compose_env.py", "sha256": "a" * 64, "mode": 0o644,
    }]
    result = supervisor.request({**request, "_peer_credentials": (123, 0, 0),
                                 "caller_source_modules": caller_modules})

    assert selected["peer_credentials"] == (123, 0, 0)
    assert selected["caller_source_modules"] == caller_modules
    assert result == {
        "source_installation_profile": {"profile": "synthetic"},
        "supervisor_idle": True,
        "exec_stop_post_no_write": True,
    }
