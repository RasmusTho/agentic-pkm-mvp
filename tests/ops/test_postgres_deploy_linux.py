"""Native deployment keeps YouTube bindings on dedicated consumer handles."""

from __future__ import annotations

import pytest

from app.ops.bws_secret_reader import BwsItemAbsent
from app.ops.host_secret_contract import DATABASE_CONSUMERS, youtube_runtime_consumers
from app.ops.host_secret_controller import HostSecretController, TerminalEvidence
from app.ops.postgres_deploy import DeployPlan, DeployReceipt, host_deploy_image_binding, vm_selected_values
from app.ops.postgres_deploy_linux import LinuxEffects, PostgresDeployError, _compose_env_value


class _Reader:
    def __init__(self) -> None:
        self.lookups: list[tuple[str, str]] = []

    def lookup(self, project: str, identity: str) -> str:
        self.lookups.append((project, identity))
        if identity == "dev/postgres.password":
            return "fixture-postgres-password"
        if identity == "dev/youtube.oauth-client-id":
            return "fixture-client-id"
        if identity == "dev/youtube.oauth-client-secret":
            return "fixture-client-secret"
        if identity == "dev/youtube.token-store-key":
            return "0" * 64
        raise BwsItemAbsent()


def test_youtube_nonprod_delivery_preserves_native_consumer_boundary() -> None:
    revision = "a" * 40
    consumers = (
        *DATABASE_CONSUMERS,
        "heimdal-api-ingress",
        *youtube_runtime_consumers("dev"),
    )
    plan = DeployPlan(
        "dev",
        revision,
        tuple(DATABASE_CONSUMERS.values()),
        consumers,
        False,
    )
    reader = _Reader()
    values = vm_selected_values(plan, reader)

    assert values["postgres-api"] == {"postgres.password": "fixture-postgres-password"}
    assert values["youtube-runtime-api"] == {
        "youtube.oauth-client-id": "fixture-client-id",
        "youtube.oauth-client-secret": "fixture-client-secret",
        "youtube.token-store-key": "0" * 64,
    }
    assert values["youtube-runtime-worker"] == values["youtube-runtime-api"]
    assert values["youtube-runtime-watcher"] == values["youtube-runtime-api"]
    assert all("youtube." not in value for value in values["postgres-api"])
    assert all(
        identity.startswith("dev/")
        for _project, identity in reader.lookups
        if identity.startswith("dev/youtube.")
    )


def test_test_recovery_v2_marker_accepts_legacy_candidate_upgrade(tmp_path) -> None:
    from uuid import uuid4

    from app.ops import postgres_deploy_host as host
    from app.ops.host_secret_controller import HostSecretController
    from app.ops.postgres_deploy import AuthorityCutover, TestRecoveryRequest

    controller = HostSecretController(tmp_path / "controller")
    controller.directory.mkdir(parents=True, mode=0o700)
    failed_operation_id = str(uuid4())
    failed_successor_operation_id = str(uuid4())
    next_operation_id = str(uuid4())
    digest = "sha256:" + "4" * 64
    old_plan = DeployPlan(
        "test", "d" * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, "heimdal-api-ingress"), False, digest, True,
    )
    current_plan = DeployPlan(
        "test", old_plan.revision, old_plan.services,
        (*old_plan.consumers, *youtube_runtime_consumers("test")),
        old_plan.ack_forward_only, old_plan.image_digest, old_plan.automatic,
    )
    authority = AuthorityCutover(
        "test-binding", "/srv/ygg/test-vault", "/srv/ygg/test-state",
    )
    source_request = TestRecoveryRequest(failed_operation_id, old_plan, authority)
    host._write_test_recovery_marker(
        controller, source_request, "ready", failed_successor_operation_id,
    )
    host._write_test_recovery_repair_marker(
        controller, source_request,
        failed_successor_operation_id=failed_successor_operation_id,
        candidate_plan=old_plan, next_operation_id=next_operation_id,
        instance_state_reconstructed=False,
    )
    host._write_test_recovery_repair_marker(
        controller, source_request,
        failed_successor_operation_id=failed_successor_operation_id,
        candidate_plan=current_plan, next_operation_id=next_operation_id,
        instance_state_reconstructed=True,
    )
    marker = host._read_test_recovery_marker(
        controller,
        TestRecoveryRequest(failed_operation_id, current_plan, authority),
    )
    assert marker is not None and marker["instance_state_reconstructed"] is True
    assert marker["repair"]["candidate_plan_object"] == current_plan


@pytest.mark.parametrize("channel", ["prod"])
def test_youtube_native_grants_are_not_declared_for_prod(channel: str) -> None:
    assert youtube_runtime_consumers(channel) == ()


@pytest.mark.parametrize("value", ["client$interpolated", "client'quoted", 'client"quoted', "client\\escaped", "client#comment", "client\nline"])
def test_youtube_compose_env_serialization_rejects_interpolation_and_quote_sentinels(value: str) -> None:
    with pytest.raises(PostgresDeployError):
        _compose_env_value(value)


def test_new_nonproduction_native_plan_requires_youtube_consumer_parity(tmp_path) -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    cfg = SimpleNamespace(channel="dev", root=tmp_path)
    effects = LinuxEffects(cfg)
    effects.operation_id = str(uuid4())
    legacy = DeployPlan(
        "dev", "a" * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, "heimdal-api-ingress"), False,
    )
    with pytest.raises(PostgresDeployError):
        effects.validate_plan(legacy)


def test_new_production_native_plan_keeps_legacy_consumer_shape(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace
    from uuid import uuid4
    from app.ops import postgres_deploy_linux as linux

    cfg = SimpleNamespace(channel="prod", root=tmp_path, uid=1000, gid=1000)
    effects = LinuxEffects(cfg)
    effects.operation_id = str(uuid4())
    monkeypatch.setattr(linux, "database_input_files", lambda _cfg: [tmp_path / "pin", tmp_path / "runtime"])
    monkeypatch.setattr(linux, "validate_database_inputs", lambda *_args: None)
    monkeypatch.setattr(linux, "require_file_protocol", lambda *_args: None)
    monkeypatch.setattr(effects, "qualify_authority_cutover", lambda _plan: None)
    plan = DeployPlan(
        "prod", "a" * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, "heimdal-api-ingress"), False,
    )
    effects.validate_plan(plan)


def test_retained_historical_nonproduction_plan_requires_exact_terminal_binding(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace
    from uuid import uuid4
    from app.ops import postgres_deploy_linux as linux

    revision = "a" * 40
    plan = DeployPlan(
        "dev", revision, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, "heimdal-api-ingress"), False,
    )
    operation_id = str(uuid4())

    class _Journal:
        def operation_request(self, selected_id):
            return ({"operation_id": selected_id}, plan)

        def operation_receipt(self, selected_id):
            return SimpleNamespace(terminal_result="committed")

    cfg = SimpleNamespace(channel="dev", root=tmp_path, uid=1000, gid=1000, journal=_Journal())
    effects = LinuxEffects(cfg)
    effects.operation_id = operation_id
    monkeypatch.setattr(linux, "database_input_files", lambda _cfg: [tmp_path / "pin", tmp_path / "runtime"])
    monkeypatch.setattr(linux, "validate_database_inputs", lambda *_args: None)
    monkeypatch.setattr(linux, "require_file_protocol", lambda *_args: None)
    monkeypatch.setattr(effects, "qualify_authority_cutover", lambda _plan: None)
    effects.validate_plan(plan)


def test_historical_terminal_reconciliation_preserves_old_consumer_fingerprint(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace
    from uuid import uuid4
    from app.ops import postgres_deploy_linux as linux

    operation_id = str(uuid4())
    historical = DeployPlan(
        "dev", "a" * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, "heimdal-api-ingress"),
        image_digest="sha256:" + "b" * 64, automatic=True,
    )
    current = DeployPlan(
        "dev", "a" * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, "heimdal-api-ingress", *youtube_runtime_consumers("dev")),
        image_digest="sha256:" + "b" * 64, automatic=True,
    )
    receipt = DeployReceipt(operation_id, "dev", "deploy", "aborted", "aborted")

    class _Journal:
        def read(self):
            return receipt

        def operation_receipt(self, selected_id):
            assert selected_id == operation_id
            return receipt

        def operation_request(self, selected_id):
            assert selected_id == operation_id
            return ({"operation_id": selected_id, "bootstrap": False}, historical)

        def bind_request(self, *_args, **_kwargs):
            raise AssertionError("historical readback must not rebind the request")

    config = SimpleNamespace(channel="dev", root=tmp_path, journal=_Journal())
    supervisor = linux.DeploymentSupervisor(config)
    monkeypatch.setattr(supervisor, "_require_current_config", lambda: None)
    response = supervisor._reconcile_failed(operation_id, current, False)

    assert response["receipt"] == receipt.payload()
    assert response["historical_plan"] == historical.payload()


def test_host_reconciliation_accepts_consumer_only_plan_upgrade(tmp_path) -> None:
    """Host admission keeps the old image binding while native readback owns history."""
    from uuid import uuid4

    controller = HostSecretController(tmp_path / "host")
    operation_id = str(uuid4())
    old = DeployPlan(
        "dev", "a" * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, "heimdal-api-ingress"), False,
        image_digest="sha256:" + "b" * 64, automatic=True,
    )
    current = DeployPlan(
        "dev", old.revision, old.services,
        (*old.consumers, *youtube_runtime_consumers("dev")), False,
        image_digest=old.image_digest, automatic=True,
    )
    old_binding = host_deploy_image_binding(old)
    current_binding = host_deploy_image_binding(current)
    assert old_binding != current_binding
    with controller.deploy_operation(
        "dev", allow_bootstrap=False, operation_id=operation_id,
        deploy_image_binding=old_binding,
    ) as (operation, _):
        operation.prepare_mutation()

    seen: list[str] = []

    def readback(selected_id: str, kind: str, target: str) -> TerminalEvidence:
        assert kind == "deploy" and target == "dev"
        seen.append(selected_id)
        return TerminalEvidence(selected_id, "deploy", "dev", "committed", "remote-terminal")

    controller.reconcile(
        readback,
        expected=("deploy", "dev", False),
        expected_deploy_image_binding=current_binding,
    )
    assert seen == [operation_id]


def test_historical_terminal_reconciliation_rejects_revision_change(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace
    from uuid import uuid4
    from app.ops import postgres_deploy_linux as linux

    operation_id = str(uuid4())
    historical = DeployPlan(
        "dev", "a" * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, "heimdal-api-ingress"),
        image_digest="sha256:" + "b" * 64, automatic=True,
    )
    changed = DeployPlan(
        "dev", "c" * 40, historical.services,
        (*historical.consumers, *youtube_runtime_consumers("dev")),
        image_digest=historical.image_digest, automatic=True,
    )
    receipt = DeployReceipt(operation_id, "dev", "deploy", "committed", "committed")

    class _Journal:
        def read(self):
            return receipt

        def operation_receipt(self, selected_id):
            return receipt

        def operation_request(self, selected_id):
            return ({"operation_id": selected_id, "bootstrap": False}, historical)

        def bind_request(self, *_args, **_kwargs):
            raise linux.PostgresDeployError()

    config = SimpleNamespace(channel="dev", root=tmp_path, journal=_Journal())
    supervisor = linux.DeploymentSupervisor(config)
    monkeypatch.setattr(supervisor, "_require_current_config", lambda: None)
    with pytest.raises(linux.PostgresDeployError):
        supervisor._reconcile_failed(operation_id, changed, False)
