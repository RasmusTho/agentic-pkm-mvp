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
    selected_identity_inventory,
    validate_receipt,
)


REVISION = "a" * 40
DIGEST = "sha256:" + "b" * 64


def _instance_authority(tmp_path: Path, channel: str, vault_root: Path):
    from app.instance.instance_state import InstanceStateLayout
    from app.instance.ownership_ledger import LegacyOwner, OwnershipLedger
    from app.instance.runtime import InstanceRegistryRuntime
    from app.instance.vault_registry import VaultRegistration
    from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY

    state_root = tmp_path / f"{channel}-instance-state"
    state_root.mkdir(mode=0o700)
    ownership_root = tmp_path / f"{channel}-instance-ownership"
    runtime = InstanceRegistryRuntime(
        InstanceStateLayout.for_channel(state_root, channel),
        OwnershipLedger(ownership_root),
    )
    binding_id = f"binding-{channel}"
    vault_id = "00000000-0000-4000-8000-000000000001"
    local_instance_id = "00000000-0000-4000-8000-000000000002"
    runtime.registry.register(
        VaultRegistration(
            binding_id, f"path:{vault_root}", str(vault_root),
            vault_id, local_instance_id,
        ),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    runtime.ledger.bootstrap_legacy_owners(
        [LegacyOwner(channel, binding_id, vault_root)],
        inventory_complete=True,
        writers_drained=True,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    return state_root, ownership_root


def _map_fixed_container_mounts(
    monkeypatch: pytest.MonkeyPatch,
    *, state_root: Path,
    ownership_root: Path,
    selected_root: Path,
    legacy_root: bool,
) -> None:
    from app.config import paths as config_paths
    from app.instance import runtime as instance_runtime
    from app.ops import native_source_bootstrap, native_source_identity_persistence

    real_path = Path
    mounts = {
        "/app/instance-state": state_root,
        "/app/instance-ownership": ownership_root,
    }
    if legacy_root:
        mounts["/app/vault"] = selected_root

    def mounted_path(value):
        return mounts.get(str(value), real_path(value))

    monkeypatch.setattr(native_source_bootstrap, "Path", mounted_path)
    monkeypatch.setattr(instance_runtime, "Path", mounted_path)
    monkeypatch.setattr(native_source_identity_persistence, "Path", mounted_path)
    original_clean_path = config_paths._clean_path
    monkeypatch.setattr(
        config_paths,
        "_clean_path",
        lambda value: selected_root if legacy_root and value == "/app/vault"
        else original_clean_path(value),
    )


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


def test_inventory_accepts_producer_supported_uppercase_uuid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    note = tmp_path / "note.md"
    note.write_text("source", encoding="utf-8")
    upper = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
    monkeypatch.setattr(
        "app.ingest.vault_alpha.select_source_backed_rebuild_candidates",
        lambda _root: (note,),
    )
    monkeypatch.setattr(
        "app.knowledge.write_ops.read_recovery_snapshot_relative",
        lambda *_args, **_kwargs: ("source", ((1, 2, 3),)),
    )
    monkeypatch.setattr(
        "app.rebuildability.product_total_loss.parse_bounded_frontmatter",
        lambda _raw: ({"uuid": upper}, "source", None),
    )
    monkeypatch.setattr(
        "app.services.companion_note.read_companion",
        lambda _root, note_uuid: SimpleNamespace(uuid=note_uuid),
    )

    assert selected_identity_inventory(tmp_path) == IdentityInventory(1, 1, 0, 0, 0)


def test_inventory_refuses_same_path_snapshot_identity_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    note = tmp_path / "note.md"
    note.write_text("source", encoding="utf-8")
    calls = 0

    def snapshot(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return "source", ((1, 2, 3 if calls == 1 else 4),)

    monkeypatch.setattr(
        "app.ingest.vault_alpha.select_source_backed_rebuild_candidates",
        lambda _root: (note,),
    )
    monkeypatch.setattr("app.knowledge.write_ops.read_recovery_snapshot_relative", snapshot)
    monkeypatch.setattr(
        "app.rebuildability.product_total_loss.parse_bounded_frontmatter",
        lambda _raw: ({"uuid": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}, "source", None),
    )
    monkeypatch.setattr("app.services.companion_note.read_companion", lambda *_args: None)

    with pytest.raises(SourceIdentityPersistenceRefusal, match="source_operation_conflict"):
        selected_identity_inventory(tmp_path)


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

        def persist_source_identity(self, requested_id, revision, image_digest, selected):
            calls.append((requested_id, revision, image_digest, selected))
            return committed

    monkeypatch.setattr(linux.LinuxConfig, "load", lambda _channel: config)
    monkeypatch.setattr(linux, "LinuxEffects", Effects)
    supervisor = linux.DeploymentSupervisor(config)
    request = {
        "action": "source-identity-persist",
        "operation_id": operation_id,
        "revision": REVISION,
        "image_digest": DIGEST,
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
        if action == "start" and not restore_ok:
            raise linux.PostgresDeployError()
        return ""

    effects.channel_lock = channel_lock  # type: ignore[method-assign]
    effects.failed_reconciliation_lock = reconcile_lock  # type: ignore[method-assign]
    effects.retire_reconciled_channel_lock = lambda *_args, **_kwargs: events.append("retire")  # type: ignore[method-assign]
    effects.compose = compose  # type: ignore[method-assign]
    effects.qualify_source_identity_authority = lambda *_args: SimpleNamespace()  # type: ignore[method-assign]
    effects.source_identity_runtime_snapshot = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: linux.SourceIdentityRuntimeSnapshot(
            "c" * 64, "d" * 64, ("api", "watcher", "worker"),
            ("api", "watcher", "worker"), "/srv/vault-alpha",
            "docker-compose.full-host-vault.yml",
            (("DATABASE_URL", "postgresql+psycopg:///?host=db"),),
        )
    )
    effects.require_source_identity_candidate = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    monkeypatch.setattr(linux, "_capture_watch_configured", lambda _config: False)
    monkeypatch.setattr(native_source_bootstrap, "quiesce_owned_container", lambda *_args: quiesced)

    result = effects.persist_source_identity(
        operation_id, REVISION, DIGEST,
        AuthorityCutover("vault-alpha", "/srv/vault-alpha", "/srv/instance-ownership"),
    )
    if quiesced and restore_ok:
        assert result["terminal_state"] == "committed"
        assert events == ["lock", "stop", "run", "start", "reconcile-lock", "retire"]
    else:
        assert result["terminal_state"] == "failed"
        assert result["reason"] == "source_operation_conflict"
        if not quiesced:
            assert "start" not in events
        assert "retire" not in events


def test_linux_effect_refuses_preflight_binding_without_compose_effects(
    tmp_path: Path,
) -> None:
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import AuthorityCutover

    journal = SimpleNamespace(directory=tmp_path / "journal", channel="dev")
    effects = linux.LinuxEffects(SimpleNamespace(channel="dev", journal=journal, uid=501))
    mutations: list[tuple[object, ...]] = []
    effects.qualify_source_identity_authority = (  # type: ignore[method-assign]
        lambda *_args: (_ for _ in ()).throw(linux.PostgresDeployError())
    )
    effects.compose = lambda *args, **_kwargs: mutations.append(args) or ""  # type: ignore[method-assign]

    with pytest.raises(linux.PostgresDeployError):
        effects.persist_source_identity(
            str(uuid4()), REVISION, DIGEST,
            AuthorityCutover("unrelated-binding", "/srv/vault-alpha", "/srv/instance-ownership"),
        )
    assert mutations == []


def test_linux_effect_failed_lock_acquisition_has_zero_compose_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import AuthorityCutover

    operation_id = str(uuid4())
    journal = SimpleNamespace(
        directory=tmp_path / "journal", channel="dev",
        read=lambda: SimpleNamespace(terminal_result="failed"),
    )
    effects = linux.LinuxEffects(SimpleNamespace(channel="dev", journal=journal, uid=501))
    mutations: list[tuple[object, ...]] = []

    @contextmanager
    def refused_lock(**_kwargs):
        raise linux.PostgresDeployError()
        yield

    effects.channel_lock = refused_lock  # type: ignore[method-assign]
    effects.qualify_source_identity_authority = lambda *_args: SimpleNamespace()  # type: ignore[method-assign]
    effects.source_identity_runtime_snapshot = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: linux.SourceIdentityRuntimeSnapshot(
            "c" * 64, "d" * 64, ("api", "watcher", "worker"),
            ("api", "watcher", "worker"), "/srv/vault-alpha",
            "docker-compose.full-host-vault.yml",
            (("DATABASE_URL", "postgresql+psycopg:///?host=db"),),
        )
    )
    effects.require_source_identity_candidate = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    effects.compose = lambda *args, **_kwargs: mutations.append(args) or ""  # type: ignore[method-assign]
    monkeypatch.setattr(linux, "_capture_watch_configured", lambda _config: False)

    result = effects.persist_source_identity(
        operation_id, REVISION, DIGEST,
        AuthorityCutover("vault-alpha", "/srv/vault-alpha", "/srv/instance-ownership"),
    )
    assert result["terminal_state"] == "failed"
    assert result["reason"] == "source_operation_conflict"
    assert mutations == []


def test_cached_receipt_reconciles_only_matching_owned_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from app.ops import native_source_bootstrap, postgres_deploy_linux as linux
    from app.ops.postgres_deploy import AuthorityCutover

    operation_id = str(uuid4())
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    retained = {
        "contract": "native-source-identity-persistence.v1",
        "operation_id": operation_id, "channel": "dev", "revision": REVISION,
        "terminal_state": "failed", "eligible": False,
        "reason": "source_operation_conflict", "selected_count": 0,
        "persisted_count": 0, "missing_count": 0, "invalid_count": 0,
        "ambiguous_count": 0, "producer_error_count": 1,
    }
    receipt_path = journal_dir / f"dev-source-identity-{operation_id}.json"
    receipt_path.write_text(json.dumps(retained), encoding="utf-8")
    receipt_path.chmod(0o600)
    effects = linux.LinuxEffects(SimpleNamespace(
        channel="dev", journal=SimpleNamespace(directory=journal_dir, channel="dev"), uid=501,
    ))
    monkeypatch.setattr(linux, "_private_json", lambda path: json.loads(path.read_text()))
    owner = {
        "kind": "source-identity-persistence", "channel": "dev", "operation_id": operation_id,
    }
    events: list[str] = []

    @contextmanager
    def reconcile_lock(**kwargs):
        assert kwargs == {"expected_owner": owner}
        events.append("lock")
        yield object()

    effects.qualify_source_identity_authority = lambda *_args: events.append("qualify")  # type: ignore[method-assign]
    effects.source_identity_runtime_snapshot = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: linux.SourceIdentityRuntimeSnapshot(
            "c" * 64, "d" * 64, ("api", "watcher", "worker"),
            ("api", "watcher", "worker"), "/srv/vault-alpha",
            "docker-compose.full-host-vault.yml",
            (("DATABASE_URL", "postgresql+psycopg:///?host=db"),),
        )
    )
    effects.channel_lock_owner = lambda: (json.dumps(owner, sort_keys=True) + "\n").encode()  # type: ignore[method-assign]
    effects.failed_reconciliation_lock = reconcile_lock  # type: ignore[method-assign]
    effects.compose = lambda *args, **_kwargs: events.append(str(args[0])) or ""  # type: ignore[method-assign]
    effects.retire_reconciled_channel_lock = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: events.append("retire")
    )
    monkeypatch.setattr(linux, "_capture_watch_configured", lambda _config: False)
    monkeypatch.setattr(native_source_bootstrap, "quiesce_owned_container", lambda *_args: True)

    assert effects.persist_source_identity(
        operation_id, REVISION, DIGEST,
        AuthorityCutover("vault-alpha", "/srv/vault-alpha", "/srv/instance-ownership"),
    ) == retained
    assert events == ["qualify", "lock", "qualify", "start", "retire"]


def test_cached_receipt_retry_under_matching_lock_contention_has_no_writer_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import AuthorityCutover

    operation_id = str(uuid4())
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    retained = {
        "contract": "native-source-identity-persistence.v1", "operation_id": operation_id,
        "channel": "dev", "revision": REVISION, "terminal_state": "failed",
        "eligible": False, "reason": "source_operation_conflict", "selected_count": 0,
        "persisted_count": 0, "missing_count": 0, "invalid_count": 0,
        "ambiguous_count": 0, "producer_error_count": 1,
    }
    receipt_path = journal_dir / f"dev-source-identity-{operation_id}.json"
    receipt_path.write_text(json.dumps(retained), encoding="utf-8")
    receipt_path.chmod(0o600)
    effects = linux.LinuxEffects(SimpleNamespace(
        channel="dev", journal=SimpleNamespace(directory=journal_dir, channel="dev"), uid=501,
    ))
    monkeypatch.setattr(linux, "_private_json", lambda path: json.loads(path.read_text()))
    owner = {
        "kind": "source-identity-persistence", "channel": "dev", "operation_id": operation_id,
    }
    mutations: list[tuple[object, ...]] = []

    @contextmanager
    def contended(**_kwargs):
        raise linux.PostgresDeployError()
        yield

    effects.qualify_source_identity_authority = lambda *_args: SimpleNamespace()  # type: ignore[method-assign]
    effects.source_identity_runtime_snapshot = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: linux.SourceIdentityRuntimeSnapshot(
            "c" * 64, "d" * 64, ("api", "watcher", "worker"),
            ("api", "watcher", "worker"), "/srv/vault-alpha",
            "docker-compose.full-host-vault.yml",
            (("DATABASE_URL", "postgresql+psycopg:///?host=db"),),
        )
    )
    effects.channel_lock_owner = lambda: (json.dumps(owner, sort_keys=True) + "\n").encode()  # type: ignore[method-assign]
    effects.failed_reconciliation_lock = contended  # type: ignore[method-assign]
    effects.compose = lambda *args, **_kwargs: mutations.append(args) or ""  # type: ignore[method-assign]
    monkeypatch.setattr(linux, "_capture_watch_configured", lambda _config: False)

    with pytest.raises(linux.PostgresDeployError):
        effects.persist_source_identity(
            operation_id, REVISION, DIGEST,
            AuthorityCutover("vault-alpha", "/srv/vault-alpha", "/srv/instance-ownership"),
        )
    assert mutations == []


@pytest.mark.parametrize(
    "channel,selected_root,container_root,vault_overlay",
    [
        ("dev", "/srv/vault-alpha", "/srv/vault-alpha", "docker-compose.full-host-vault.yml"),
        ("test", "/srv/vault-alpha", "/srv/vault-alpha", "docker-compose.full-host-vault.yml"),
        ("dev", "/opt/retained-vault", "/app/vault", "docker-compose.legacy-vault.yml"),
        ("test", "/opt/retained-vault", "/app/vault", "docker-compose.legacy-vault.yml"),
    ],
)
def test_source_compose_uses_exact_candidate_and_canonical_selected_vault_overlays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, channel: str,
    selected_root: str, container_root: str, vault_overlay: str,
) -> None:
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import AuthorityCutover

    captured: dict[str, object] = {}
    candidate = SimpleNamespace(revision=REVISION, image_digest=DIGEST)
    selected = AuthorityCutover("vault-alpha", selected_root, "/srv/instance-ownership")
    effects = linux.LinuxEffects(SimpleNamespace(channel=channel, root=tmp_path))
    snapshot = linux.SourceIdentityRuntimeSnapshot(
        "c" * 64, "d" * 64, ("api", "watcher", "worker"),
        ("api", "watcher", "worker"), container_root, vault_overlay,
        (("DATABASE_URL", "postgresql+psycopg:///?host=db"),),
    )

    def environment(cutover, selected_candidate, installed_environment):
        assert cutover is selected
        assert selected_candidate is candidate
        assert installed_environment == snapshot.child_environment
        return {"BWS_DATABASE_TARGET": "local"}

    def command(argv, **kwargs):
        captured.update(argv=argv, env=kwargs["env"])
        return ""

    effects.environment = environment  # type: ignore[method-assign]
    monkeypatch.setattr(linux, "_command", command)

    effects.compose(
        "run", "--no-deps", "api", cutover=selected, candidate=candidate,
        source_snapshot=snapshot,
    )

    argv = captured["argv"]
    assert isinstance(argv, list)
    assert str(tmp_path / vault_overlay) in argv
    assert (str(tmp_path / "docker-compose.test-vault.yml") in argv) is (channel == "test")
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["VAULT_HOST_ROOT"] == selected.root
    assert env["DEPLOY_VAULT_CONTAINER_ROOT"] == container_root


@pytest.mark.parametrize("database_key", ["DATABASE_URL", "DB_DSN"])
def test_closed_helper_environment_accepts_only_semantically_equal_database_urls(
    database_key: str,
) -> None:
    from app.ops import postgres_deploy_linux as linux

    installed_url = (
        "postgresql+psycopg:///?host=db&port=5432&dbname=app_dev&user=app"
        "&sslmode=verify-full&sslrootcert=%2Frun%2Fsecrets%2Fca.pem"
    )
    resolved_url = (
        "postgresql+psycopg:///?sslrootcert=%2Frun%2Fsecrets%2Fca.pem&user=app"
        "&dbname=app_dev&port=5432&host=db&sslmode=verify-full"
    )
    installed = {database_key: installed_url, "LLM_PROVIDER": "ollama"}
    resolved = {database_key: resolved_url, "LLM_PROVIDER": "ollama"}

    assert dict(linux._closed_source_helper_environment(installed, resolved)) == installed


@pytest.mark.parametrize(
    "resolved",
    [
        {"DATABASE_URL": "postgresql+psycopg:///?host=db&port=5432&dbname=other&user=app"},
        {"DATABASE_URL": "postgresql+psycopg:///?host=db&port=5432&dbname=app_dev&user=app&sslmode=disable"},
        {"DATABASE_URL": "postgresql+psycopg:///?host=db&port=5432&dbname=app_dev&user=app&passfile=%2Fsecret"},
        {"DB_DSN": "postgresql+psycopg:///?host=db&port=5432&dbname=app_dev&user=app"},
        {"LLM_PROVIDER": "openai"},
    ],
)
def test_closed_helper_environment_refuses_database_or_key_authority_drift(
    resolved: dict[str, str],
) -> None:
    from app.ops import postgres_deploy_linux as linux

    installed = {
        "DATABASE_URL": (
            "postgresql+psycopg:///?host=db&port=5432&dbname=app_dev&user=app"
            "&sslmode=verify-full"
        ),
        "LLM_PROVIDER": "ollama",
    }
    with pytest.raises(linux.PostgresDeployError):
        linux._closed_source_helper_environment(installed, resolved)


def test_producer_completion_crash_resumes_cleanup_without_rerunning_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from app.ops import native_source_bootstrap, postgres_deploy_linux as linux
    from app.ops.postgres_deploy import AuthorityCutover

    operation_id = str(uuid4())
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    retained = {
        "contract": "native-source-identity-persistence.v1", "operation_id": operation_id,
        "channel": "dev", "revision": REVISION, "terminal_state": "committed",
        "eligible": True, "reason": None, "selected_count": 1, "persisted_count": 1,
        "missing_count": 0, "invalid_count": 0, "ambiguous_count": 0,
        "producer_error_count": 0,
    }
    producer_path = journal_dir / f"dev-source-identity-{operation_id}.producer.json"
    producer_path.write_text(json.dumps(retained), encoding="utf-8")
    producer_path.chmod(0o600)
    effects = linux.LinuxEffects(SimpleNamespace(
        channel="dev", journal=SimpleNamespace(directory=journal_dir, channel="dev"), uid=501,
    ))
    owner = {
        "kind": "source-identity-persistence", "channel": "dev", "operation_id": operation_id,
    }
    events: list[str] = []

    @contextmanager
    def reconcile_lock(**_kwargs):
        events.append("lock")
        yield object()

    monkeypatch.setattr(linux, "_private_json", lambda path: json.loads(path.read_text()))
    monkeypatch.setattr(
        linux, "_atomic_private_json",
        lambda path, payload: path.write_text(json.dumps(payload), encoding="utf-8"),
    )
    effects.qualify_source_identity_authority = lambda *_args: events.append("qualify")  # type: ignore[method-assign]
    effects.source_identity_runtime_snapshot = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: linux.SourceIdentityRuntimeSnapshot(
            "c" * 64, "d" * 64, ("api", "watcher", "worker"),
            ("api", "watcher", "worker"), "/srv/vault-alpha",
            "docker-compose.full-host-vault.yml",
            (("DATABASE_URL", "postgresql+psycopg:///?host=db"),),
        )
    )
    effects.channel_lock_owner = lambda: (json.dumps(owner, sort_keys=True) + "\n").encode()  # type: ignore[method-assign]
    effects.failed_reconciliation_lock = reconcile_lock  # type: ignore[method-assign]
    effects.compose = lambda *args, **_kwargs: events.append(str(args[0])) or ""  # type: ignore[method-assign]
    effects.retire_reconciled_channel_lock = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: events.append("retire")
    )
    monkeypatch.setattr(linux, "_capture_watch_configured", lambda _config: False)
    monkeypatch.setattr(native_source_bootstrap, "quiesce_owned_container", lambda *_args: True)

    result = effects.persist_source_identity(
        operation_id, REVISION, DIGEST,
        AuthorityCutover("vault-alpha", "/srv/vault-alpha", "/srv/instance-ownership"),
    )
    assert result == retained
    assert "run" not in events and "stop" not in events
    assert events == ["qualify", "lock", "qualify", "start", "retire"]


def test_candidate_helper_is_acquired_and_verified_before_writer_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ops import postgres_deploy_linux as linux
    from app.ops.pg_acceptance import IMAGE_REPOSITORY
    from app.ops.postgres_deploy import AuthorityCutover, DeployPlan

    selected = AuthorityCutover("vault-alpha", "/srv/vault-alpha", "/srv/instance-ownership")
    plan = DeployPlan(
        "dev", REVISION, ("api", "worker", "watcher"),
        ("postgres-db", "postgres-api", "postgres-worker", "postgres-watcher", "heimdal-api-ingress"),
        image_digest=DIGEST, authority_cutover=selected,
    )
    effects = linux.LinuxEffects(SimpleNamespace(channel="dev", root=tmp_path))
    events: list[str] = []
    monkeypatch.setattr(linux, "ensure_candidate_object", lambda *_args: events.append("source"))
    monkeypatch.setattr(linux, "require_file_protocol", lambda *_args: events.append("protocol"))
    effects.compose = lambda *args, **_kwargs: events.append(str(args[0])) or ""  # type: ignore[method-assign]
    monkeypatch.setattr(
        linux, "_command",
        lambda *_args, **_kwargs: json.dumps([{
            "Config": {"Labels": {"org.opencontainers.image.revision": REVISION}},
            "RepoDigests": [IMAGE_REPOSITORY + "@" + DIGEST],
        }]),
    )

    snapshot = linux.SourceIdentityRuntimeSnapshot(
        "c" * 64, "d" * 64, ("api", "watcher", "worker"),
        ("api", "watcher", "worker"), selected.root,
        "docker-compose.full-host-vault.yml",
        (("DATABASE_URL", "postgresql+psycopg:///?host=db"),),
    )
    effects.require_source_identity_candidate(
        plan, selected, acquire=True, source_snapshot=snapshot,
    )
    assert events == ["source", "protocol", "pull"]


def test_runtime_snapshot_fences_stale_active_capture_and_model_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import AuthorityCutover

    rows = []
    for index, service in enumerate(("api", "worker", "watcher", "heimdal-capture-watch"), 1):
        rows.append({
            "Id": f"{index:064x}",
            "Image": f"sha256:{index:064x}",
            "Config": {
                "Image": f"example/{service}:installed",
                "Env": [
                    "DATABASE_URL=postgresql+psycopg://app@db:5432/app_dev",
                    "EMBED_PROVIDER=ollama", "EMBED_MODEL=accepted",
                    "LLM_PROVIDER=ollama", "STORE_BACKEND=pg",
                    "VCS_REF=" + ("b" * 40), "BUILT_AT=installed-build",
                    "PKM_ENVIRONMENT=dev", "VAULT_HOST_ROOT=/srv/vault-alpha",
                    "VAULT_ROOT=/srv/vault-alpha", "VAULT_ROOT_DEV=/srv/vault-alpha",
                    "WATCHER_VAULT_PATH=/srv/vault-alpha",
                ],
                "User": "501:20",
                "Labels": {
                    "com.docker.compose.project": "pkm-dev",
                    "com.docker.compose.service": service,
                    "com.docker.compose.oneoff": "False",
                },
            },
            "State": {"Status": "running"},
            "Mounts": ([{
                "Type": "bind", "Source": "/srv/vault-alpha",
                "Destination": "/srv/vault-alpha", "RW": True,
            }] if service in {"api", "worker", "watcher"} else []),
        })
    (tmp_path / "config/deploy").mkdir(parents=True)
    (tmp_path / "tmp").mkdir()
    (tmp_path / "config/deploy/dev.env").write_text(
        "WATCHER_RUNTIME_ENV_FILE=./tmp/runtime.env\n"
        "VAULT_HOST_ROOT=/srv/vault-alpha\n"
    )
    (tmp_path / "config/runtime.defaults.env").write_text(
        "EMBED_PROVIDER=ollama\nEMBED_MODEL=accepted\nSTORE_BACKEND=pg\n"
    )
    (tmp_path / "tmp/runtime.env").write_text(
        "LLM_PROVIDER=ollama\nDATABASE_URL=postgresql+psycopg://app@db:5432/app_dev\n"
    )
    for name in (
        "docker-compose.yaml", "docker-compose.dev.yml", "docker-compose.bws.yml",
        "docker-compose.bws-external.yml", "docker-compose.full-host-vault.yml",
    ):
        (tmp_path / name).write_text("services: {}\n")
    effects = linux.LinuxEffects(SimpleNamespace(
        channel="dev", root=tmp_path, uid=501, gid=20,
        password_file=tmp_path / "password",
    ))

    def command(argv, **_kwargs):
        if argv[1:3] == ["ps", "--all"]:
            return "\n".join(row["Id"] for row in rows)
        if argv[1] == "compose":
            resolved = {
                entry.split("=", 1)[0]: entry.split("=", 1)[1]
                for entry in rows[0]["Config"]["Env"]
                if not entry.startswith(("VCS_REF=", "BUILT_AT="))
            }
            runtime = (tmp_path / "tmp/runtime.env").read_text()
            for key in ("LLM_FORCE_PROVIDER", "LLM_FORCE_MODEL"):
                for line in runtime.splitlines():
                    if line.startswith(key + "="):
                        resolved[key] = line.split("=", 1)[1]
            return json.dumps({"services": {"api": {"environment": resolved}}})
        return json.dumps(rows)

    monkeypatch.setattr(linux, "_command", command)
    monkeypatch.setattr(linux, "_capture_watch_configured", lambda _config: False)

    selected = AuthorityCutover("vault-alpha", "/srv/vault-alpha", "/srv/instance-ownership")
    before = effects.source_identity_runtime_snapshot(
        selected, require_running_capture=True,
    )
    assert "heimdal-capture-watch" in before.running_writers
    assert before.running_writers == before.existing_writers
    assert "VCS_REF" not in dict(before.child_environment)
    assert "BUILT_AT" not in dict(before.child_environment)
    assert before.unset_environment == ()
    (tmp_path / "tmp/runtime.env").write_text(
        "LLM_PROVIDER=ollama\n"
        "DATABASE_URL=postgresql+psycopg://app@db:5432/app_dev\n"
        "LLM_FORCE_PROVIDER=openai\nLLM_FORCE_MODEL=unexpected\n"
    )
    with pytest.raises(linux.PostgresDeployError):
        effects.source_identity_runtime_snapshot(
            selected, require_running_capture=True,
        )
    (tmp_path / "tmp/runtime.env").write_text(
        "LLM_PROVIDER=ollama\n"
        "DATABASE_URL=postgresql+psycopg://app@db:5432/app_dev\n"
    )
    for row in rows:
        row["Config"]["Env"] = [
            value.replace("EMBED_MODEL=accepted", "EMBED_MODEL=drifted")
            for value in row["Config"]["Env"]
        ]
    with pytest.raises(linux.PostgresDeployError):
        effects.source_identity_runtime_snapshot(
            selected, require_running_capture=True,
        )


@pytest.mark.parametrize("drift", ["execution", "new-writer"])
def test_locked_admission_refuses_child_or_writer_drift_before_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: str,
) -> None:
    from contextlib import contextmanager

    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import AuthorityCutover

    operation_id = str(uuid4())
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    journal = SimpleNamespace(
        directory=journal_dir, channel="dev",
        read=lambda: SimpleNamespace(terminal_result="failed"),
    )
    effects = linux.LinuxEffects(SimpleNamespace(channel="dev", journal=journal, uid=501))
    selected = AuthorityCutover("vault-alpha", "/srv/vault-alpha", "/srv/instance-ownership")
    base = linux.SourceIdentityRuntimeSnapshot(
        "c" * 64, "d" * 64, ("api", "watcher", "worker"),
        ("api", "heimdal-capture-watch", "watcher", "worker"),
        selected.root, "docker-compose.full-host-vault.yml",
        (("DATABASE_URL", "postgresql+psycopg:///?host=db"), ("LLM_PROVIDER", "ollama")),
    )
    changed = linux.SourceIdentityRuntimeSnapshot(
        base.installed_fingerprint,
        "e" * 64 if drift == "execution" else base.execution_fingerprint,
        (("api", "heimdal-capture-watch", "watcher", "worker")
         if drift == "new-writer" else base.running_writers),
        base.existing_writers, base.container_root, base.vault_overlay,
        base.child_environment,
    )
    snapshots = iter((base, changed))
    effects.source_identity_runtime_snapshot = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: next(snapshots)
    )
    effects.qualify_source_identity_authority = lambda *_args: SimpleNamespace()  # type: ignore[method-assign]
    effects.require_source_identity_candidate = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    effects.channel_lock_owner = lambda: None  # type: ignore[method-assign]
    mutations: list[str] = []
    effects.compose = lambda *args, **_kwargs: mutations.append(str(args[0])) or ""  # type: ignore[method-assign]

    @contextmanager
    def lock(**_kwargs):
        yield

    effects.channel_lock = lock  # type: ignore[method-assign]
    effects.failed_reconciliation_lock = lock  # type: ignore[method-assign]
    monkeypatch.setattr(linux, "_atomic_private_json", lambda path, payload: path.write_text(json.dumps(payload)))

    result = effects.persist_source_identity(operation_id, REVISION, DIGEST, selected)
    assert result["terminal_state"] == "failed"
    assert result["reason"] == "source_operation_conflict"
    assert mutations == []


def test_configured_capture_producer_receipt_resumes_real_snapshot_cleanup_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from app.ops import native_source_bootstrap, postgres_deploy_linux as linux
    from app.ops.postgres_deploy import AuthorityCutover

    selected = AuthorityCutover("vault-alpha", "/srv/vault-alpha", "/srv/instance-ownership")
    services = ("api", "worker", "watcher", "heimdal-capture-watch")
    rows = []
    for index, service in enumerate(services, 1):
        rows.append({
            "Id": f"{index:064x}", "Image": f"sha256:{index:064x}",
            "Config": {
                "Image": f"example/{service}:installed",
                "Env": [
                    "DATABASE_URL=postgresql+psycopg://app@db:5432/app_dev",
                    "LLM_PROVIDER=ollama", "EMBED_PROVIDER=ollama",
                    "EMBED_MODEL=accepted", "STORE_BACKEND=pg",
                    "PKM_ENVIRONMENT=dev", "VAULT_HOST_ROOT=/srv/vault-alpha",
                    "VAULT_ROOT=/srv/vault-alpha", "VAULT_ROOT_DEV=/srv/vault-alpha",
                    "WATCHER_VAULT_PATH=/srv/vault-alpha",
                ],
                "User": "501:20", "Labels": {
                    "com.docker.compose.project": "pkm-dev",
                    "com.docker.compose.service": service,
                    "com.docker.compose.oneoff": "False",
                },
            },
            "State": {"Status": "exited"},
            "Mounts": ([{
                "Type": "bind", "Source": selected.root,
                "Destination": selected.root, "RW": True,
            }] if service != "heimdal-capture-watch" else []),
        })
    (tmp_path / "config/deploy").mkdir(parents=True)
    (tmp_path / "tmp").mkdir()
    (tmp_path / "config/deploy/dev.env").write_text(
        "WATCHER_RUNTIME_ENV_FILE=./tmp/runtime.env\n"
        "VAULT_HOST_ROOT=/srv/vault-alpha\n"
    )
    (tmp_path / "config/runtime.defaults.env").write_text(
        "EMBED_PROVIDER=ollama\nEMBED_MODEL=accepted\nSTORE_BACKEND=pg\n"
    )
    (tmp_path / "tmp/runtime.env").write_text(
        "LLM_PROVIDER=ollama\nDATABASE_URL=postgresql+psycopg://app@db:5432/app_dev\n"
    )
    for name in (
        "docker-compose.yaml", "docker-compose.dev.yml", "docker-compose.bws.yml",
        "docker-compose.bws-external.yml", "docker-compose.full-host-vault.yml",
    ):
        (tmp_path / name).write_text("services: {}\n")
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    config = SimpleNamespace(
        channel="dev", root=tmp_path, journal=SimpleNamespace(
            directory=journal_dir, channel="dev"), uid=501, gid=20,
        password_file=tmp_path / "password",
    )
    effects = linux.LinuxEffects(config)

    def command(argv, **_kwargs):
        if argv[1:3] == ["ps", "--all"]:
            return "\n".join(row["Id"] for row in rows)
        if argv[1] == "compose":
            resolved = {
                entry.split("=", 1)[0]: entry.split("=", 1)[1]
                for entry in rows[0]["Config"]["Env"]
            }
            return json.dumps({"services": {"api": {"environment": resolved}}})
        return json.dumps(rows)

    monkeypatch.setattr(linux, "_command", command)
    monkeypatch.setattr(linux, "_capture_watch_configured", lambda _config: True)
    snapshot = effects.source_identity_runtime_snapshot(
        selected, require_running_capture=False,
    )
    operation_id = str(uuid4())
    owner = {"kind": "source-identity-persistence", "channel": "dev", "operation_id": operation_id}
    request = {
        "contract": "native-source-identity-persistence-request.v2",
        "operation_id": operation_id, "channel": "dev", "revision": REVISION,
        "image_digest": DIGEST,
        "authority_cutover": {
            "binding_id": selected.binding_id, "root": selected.root,
            "ownership_root": selected.ownership_root,
        },
        "installed_fingerprint": snapshot.installed_fingerprint,
        "execution_fingerprint": snapshot.execution_fingerprint,
        "writers": list(services), "container_root": snapshot.container_root,
        "vault_overlay": snapshot.vault_overlay,
    }
    retained = {
        "contract": "native-source-identity-persistence.v1", "operation_id": operation_id,
        "channel": "dev", "revision": REVISION, "terminal_state": "committed",
        "eligible": True, "reason": None, "selected_count": 1, "persisted_count": 1,
        "missing_count": 0, "invalid_count": 0, "ambiguous_count": 0,
        "producer_error_count": 0,
    }
    (journal_dir / f"dev-source-identity-{operation_id}.request.json").write_text(json.dumps(request))
    (journal_dir / f"dev-source-identity-{operation_id}.producer.json").write_text(json.dumps(retained))

    fresh = linux.LinuxEffects(config)
    events: list[str] = []
    fresh.qualify_source_identity_authority = lambda *_args: events.append("qualify")  # type: ignore[method-assign]
    fresh.channel_lock_owner = lambda: (json.dumps(owner, sort_keys=True) + "\n").encode()  # type: ignore[method-assign]

    @contextmanager
    def cleanup_lock(**_kwargs):
        events.append("lock")
        yield object()

    fresh.failed_reconciliation_lock = cleanup_lock  # type: ignore[method-assign]
    def fresh_compose(*args, **_kwargs):
        action = str(args[0])
        if action == "config":
            resolved = {
                entry.split("=", 1)[0]: entry.split("=", 1)[1]
                for entry in rows[0]["Config"]["Env"]
            }
            return json.dumps({"services": {"api": {"environment": resolved}}})
        events.append(action)
        return ""

    fresh.compose = fresh_compose  # type: ignore[method-assign]
    fresh.retire_reconciled_channel_lock = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: events.append("retire")
    )
    monkeypatch.setattr(linux, "_private_json", lambda path: json.loads(path.read_text()))
    monkeypatch.setattr(
        linux, "_atomic_private_json",
        lambda path, payload: path.write_text(json.dumps(payload)),
    )
    monkeypatch.setattr(native_source_bootstrap, "quiesce_owned_container", lambda *_args: True)

    assert fresh.persist_source_identity(operation_id, REVISION, DIGEST, selected) == retained
    assert events == ["qualify", "lock", "qualify", "start", "retire"]


@pytest.mark.parametrize("channel", ["dev", "test"])
@pytest.mark.parametrize("legacy_root", [False, True])
def test_separate_candidate_helper_reaches_real_worker_and_ordinary_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    channel: str, legacy_root: bool,
) -> None:
    """An old installed runtime can launch the reviewed helper without adoption."""
    import io
    import os
    from contextlib import redirect_stdout
    import subprocess

    from app.ingest import vault_alpha as producer
    from app.ops import native_source_bootstrap, postgres_deploy_linux as linux
    from app.ops.postgres_deploy import AuthorityCutover
    from app.ops.pg_acceptance import IMAGE_REPOSITORY
    from app.stores.memory import MemoryObjectStore

    root = (tmp_path / "vault").resolve()
    root.mkdir()
    layout = root / "⚙️ System" / "vault.layout.md"
    layout.parent.mkdir()
    layout.write_text(
        "---\nsystem_folder: '⚙️ System'\ninbox_folder: '📥 Inbox'\n"
        "desk_folder: '🛠️ Workbench'\ninclude_folders: [Notes]\n---\nLayout.\n"
    )
    note = root / "Notes" / "candidate.md"
    note.parent.mkdir()
    note.write_text("---\ntrust: human\nreview_state: reviewed\n---\nCandidate body.\n")
    settings = root / "settings"
    settings.mkdir()
    for name in ("paths.md", "workflow.md", "design-handoff.md", "companion-ui.md"):
        (settings / name).write_text("---\n---\n")
    (settings / "vault.md").write_text(
        "---\nvaultId: 00000000-0000-4000-8000-000000000001\n---\n"
    )
    (settings / "local.md").write_text(
        "---\nlocalInstanceId: 00000000-0000-4000-8000-000000000002\n---\n"
    )
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    container_root = "/app/vault" if legacy_root else str(root)
    monkeypatch.setenv("PKM_ENVIRONMENT", channel)
    monkeypatch.setenv("VAULT_ROOT", container_root)
    monkeypatch.setenv("VCS_REF", REVISION)
    monkeypatch.setenv("BUILT_AT", "candidate-build")
    monkeypatch.setattr(producer, "classify_run", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(producer, "get_object_store", lambda: MemoryObjectStore())
    monkeypatch.setattr(producer, "resolve_canonical_object_id", lambda value: value)
    monkeypatch.setattr(producer, "index_ingest_object", lambda **_kwargs: None)
    monkeypatch.setattr(producer, "append_jsonl", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(producer, "_ingest_single", lambda *_args, **_kwargs: None)
    guard_actions: list[str] = []

    class HealthyGuard:
        def assert_writes_allowed(self, action: str) -> None:
            guard_actions.append(action)

    guard = HealthyGuard()
    monkeypatch.setattr("app.services.note_uuid.DEFAULT_WRITE_GUARD", guard)
    monkeypatch.setattr("app.write_guard.DEFAULT_WRITE_GUARD", guard)
    monkeypatch.setattr("app.services.companion_note.DEFAULT_WRITE_GUARD", guard)
    state_root, ownership_root = _instance_authority(tmp_path, channel, root)
    _map_fixed_container_mounts(
        monkeypatch,
        state_root=state_root,
        ownership_root=ownership_root,
        selected_root=root,
        legacy_root=legacy_root,
    )
    monkeypatch.setattr(native_source_bootstrap, "quiesce_owned_container", lambda *_args: True)

    operation_id = str(uuid4())
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(mode=0o700)
    journal = SimpleNamespace(
        directory=journal_dir, channel=channel,
        read=lambda: SimpleNamespace(terminal_result="failed"),
    )
    checkout = tmp_path / "checkout"
    deploy = checkout / "config" / "deploy"
    deploy.mkdir(parents=True)
    runtime_env = checkout / "runtime.env"
    database_url = (
        "postgresql+psycopg:///?host=db&port=5432&dbname="
        + ("app_dev" if channel == "dev" else "app_test")
        + "&user=app"
    )
    (deploy / f"{channel}.env").write_text(
        f"WATCHER_RUNTIME_ENV_FILE={runtime_env}\n"
        f"VAULT_HOST_ROOT={root}\n"
        f"INSTANCE_OWNERSHIP_HOST_STATE_DIR={ownership_root}\n"
        f"DATABASE_URL={database_url}\n"
    )
    runtime_env.write_text(
        f"LLM_PROVIDER=mock\nDATABASE_URL={database_url}\n"
        f"VAULT_ROOT={root}\nWATCHER_VAULT_PATH={root}\n"
    )
    (checkout / "config" / "runtime.defaults.env").write_text(
        "EMBED_PROVIDER=mock\nEMBED_MODEL=accepted\nSTORE_BACKEND=pg\n"
    )
    for name in (
        "docker-compose.yaml", f"docker-compose.{channel}.yml", "docker-compose.bws.yml",
        "docker-compose.legacy-vault.yml" if legacy_root else "docker-compose.full-host-vault.yml",
        *(('docker-compose.test-vault.yml',) if channel == "test" else ()),
    ):
        (checkout / name).write_text("services: {}\n")
    config = SimpleNamespace(
        channel=channel, root=checkout, journal=journal,
        uid=os.getuid(), gid=os.getgid(), password_file=tmp_path / "password",
        runtime_env_file=runtime_env,
    )
    effects = linux.LinuxEffects(config)
    selected = AuthorityCutover(f"binding-{channel}", str(root), str(ownership_root))
    installed = {
        "DATABASE_URL": database_url,
        "LLM_PROVIDER": "mock",
        "EMBED_PROVIDER": "mock",
        "EMBED_MODEL": "accepted",
        "STORE_BACKEND": "pg",
        "PKM_ENVIRONMENT": channel,
        "VAULT_HOST_ROOT": str(root),
        "VAULT_ROOT": container_root,
        "WATCHER_VAULT_PATH": container_root,
    }
    rows = []
    for index, service in enumerate(("api", "worker", "watcher"), 1):
        rows.append({
            "Id": f"{index:064x}",
            "Image": f"sha256:{index:064x}",
            "Config": {
                "Image": f"example/{service}:installed",
                "Env": [
                    *[f"{key}={value}" for key, value in installed.items()],
                    "POSTGRES_PASSWORD", "PGPASSWORD", "OPTIONAL_PROVIDER",
                    "VCS_REF", "BUILT_AT",
                ],
                "User": f"{os.getuid()}:{os.getgid()}",
                "Labels": {
                    "com.docker.compose.project": f"pkm-{channel}",
                    "com.docker.compose.service": service,
                    "com.docker.compose.oneoff": "False",
                },
            },
            "State": {"Status": "running"},
            "Mounts": [
                {"Type": "bind", "Source": str(root), "Destination": container_root, "RW": True},
                {"Type": "bind", "Source": str(ownership_root),
                 "Destination": "/app/instance-ownership", "RW": True},
                {"Type": "volume", "Source": str(state_root),
                 "Destination": "/app/instance-state", "Name": f"pkm-{channel}_instance-state"},
            ],
        })
    candidate_checks: list[str] = []
    events: list[str] = []
    worker_statuses: list[int] = []

    def command(argv, **kwargs):
        if argv[:2] == ["docker", "ps"]:
            return "\n".join(row["Id"] for row in rows)
        if argv[:3] == ["docker", "inspect", "--type"]:
            return json.dumps(rows)
        if argv[:3] == ["docker", "volume", "inspect"]:
            return json.dumps([{"Mountpoint": str(state_root)}])
        if argv[:3] == ["docker", "image", "inspect"]:
            candidate_checks.append("inspect")
            return json.dumps([{
                "Config": {"Labels": {"org.opencontainers.image.revision": REVISION}},
                "RepoDigests": [IMAGE_REPOSITORY + "@" + DIGEST],
            }])
        assert argv[:2] == ["docker", "compose"]
        action = next(
            value for value in ("config", "pull", "stop", "run", "start")
            if value in argv
        )
        events.append(action)
        environment = kwargs["env"]
        if action == "config":
            resolved = {key: environment[key] for key in installed}
            return json.dumps({"services": {"api": {"environment": resolved}}})
        if action != "run":
            return ""
        assert environment["APP_IMAGE_TAG"] == REVISION
        assert environment["APP_IMAGE_DIGEST_SUFFIX"] == "@" + DIGEST
        environment_selectors = {
            argv[index + 1] for index, value in enumerate(argv[:-1]) if value == "-e"
        }
        environment_keys = {value for value in environment_selectors if "=" not in value}
        assert "VCS_REF" not in environment_keys
        assert "BUILT_AT" not in environment_keys
        optional_unsets = {"POSTGRES_PASSWORD", "PGPASSWORD", "OPTIONAL_PROVIDER"}
        assert optional_unsets <= environment_keys
        assert not optional_unsets & environment.keys()
        bootstrap = next(
            value.split("=", 1)[1] for value in argv
            if value.startswith("NATIVE_SOURCE_BOOTSTRAP=")
        )
        monkeypatch.setenv("OPTIONAL_PROVIDER", "candidate-image-default")
        for key in environment_keys:
            if key in environment:
                monkeypatch.setenv(key, environment[key])
            else:
                monkeypatch.delenv(key, raising=False)
        assert "OPTIONAL_PROVIDER" not in os.environ
        monkeypatch.setenv("NATIVE_SOURCE_BOOTSTRAP", bootstrap)
        monkeypatch.setenv("VCS_REF", REVISION)
        monkeypatch.setenv("BUILT_AT", "candidate-build")
        module_index = argv.index("app.ops.native_source_identity_persistence")
        worker_args = list(argv[module_index + 1:module_index + 5])
        output = io.StringIO()
        with redirect_stdout(output):
            status = __import__(
                "app.ops.native_source_identity_persistence", fromlist=["worker_main"],
            ).worker_main(worker_args)
        worker_statuses.append(status)
        assert status == 0
        return output.getvalue()

    real_run = subprocess.run

    def run(argv, **kwargs):
        if len(argv) > 2 and "require_existing_authority_binding" in argv[2]:
            if os.geteuid() != 0:
                kwargs.pop("extra_groups")
            return real_run(argv, **kwargs)
        return real_run(argv, **kwargs)

    monkeypatch.setattr(linux, "_command", command)
    monkeypatch.setattr(linux.subprocess, "run", run)
    monkeypatch.setattr(linux, "ensure_candidate_object", lambda *_args: candidate_checks.append("source"))
    monkeypatch.setattr(linux, "require_file_protocol", lambda *_args: candidate_checks.append("protocol"))
    monkeypatch.setattr(linux, "_capture_watch_configured", lambda _config: False)

    receipt = effects.persist_source_identity(operation_id, REVISION, DIGEST, selected)
    assert receipt["terminal_state"] == "committed", (
        receipt, events, candidate_checks, worker_statuses,
    )
    assert receipt["eligible"] is True
    assert "uuid:" in note.read_text()
    assert candidate_checks == [
        "source", "protocol", "inspect",
        "source", "protocol", "inspect",
    ]
    assert "ensure uuid" in guard_actions
    final_snapshot = effects.source_identity_runtime_snapshot(
        selected, require_running_capture=True,
    )
    assert not {"POSTGRES_PASSWORD", "PGPASSWORD", "OPTIONAL_PROVIDER"} & {
        key for key, _value in final_snapshot.child_environment
    }
    assert set(final_snapshot.unset_environment) == {
        "POSTGRES_PASSWORD", "PGPASSWORD", "OPTIONAL_PROVIDER",
    }
    assert "up" not in events


@pytest.mark.parametrize("channel", ["dev", "test"])
@pytest.mark.parametrize("legacy_root", [False, True])
def test_real_preflight_retains_channel_and_selected_topology(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, channel: str, legacy_root: bool,
) -> None:
    from app.ops import native_source_bootstrap

    selected = (tmp_path / channel / "vault").resolve()
    selected.mkdir(parents=True)
    container_root = Path("/app/vault") if legacy_root else selected
    state_root, ownership_root = _instance_authority(tmp_path, channel, selected)
    _map_fixed_container_mounts(
        monkeypatch,
        state_root=state_root,
        ownership_root=ownership_root,
        selected_root=selected,
        legacy_root=legacy_root,
    )
    monkeypatch.setenv("NATIVE_SOURCE_BOOTSTRAP", f"{channel}:{REVISION}")
    monkeypatch.setenv("PKM_ENVIRONMENT", channel)
    monkeypatch.setenv("VCS_REF", REVISION)
    monkeypatch.setenv("BUILT_AT", "candidate-build")
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("VAULT_ROOT", str(container_root))
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(container_root))

    assert native_source_bootstrap.preflight(
        f"{channel}:{REVISION}",
    ) == selected


@pytest.mark.parametrize("channel", ["dev", "test"])
@pytest.mark.parametrize("legacy_root", [False, True])
@pytest.mark.parametrize(
    "drift",
    [
        "helper-revision", "missing-helper-revision",
        "runtime-channel", "missing-runtime-channel",
        "binding", "missing-binding",
    ],
)
def test_real_worker_preflight_refuses_wrong_helper_runtime_or_binding_before_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, channel: str,
    legacy_root: bool, drift: str,
) -> None:
    from app.ops import native_source_identity_persistence

    root = (tmp_path / "vault").resolve()
    wrong_root = (tmp_path / "other-vault").resolve()
    root.mkdir()
    wrong_root.mkdir()
    marker = root / "source.md"
    marker.write_text("---\ntrust: human\n---\nunchanged\n")
    state_root, ownership_root = _instance_authority(tmp_path, channel, root)
    _map_fixed_container_mounts(
        monkeypatch,
        state_root=state_root,
        ownership_root=ownership_root,
        selected_root=root,
        legacy_root=legacy_root,
    )
    container_root = "/app/vault" if legacy_root else str(root)
    monkeypatch.setenv("NATIVE_SOURCE_BOOTSTRAP", f"{channel}:{REVISION}")
    monkeypatch.setenv("PKM_ENVIRONMENT", channel)
    monkeypatch.setenv("VCS_REF", REVISION)
    monkeypatch.setenv("BUILT_AT", "candidate-build")
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("VAULT_ROOT", container_root)
    monkeypatch.setenv("WATCHER_VAULT_PATH", container_root)
    if drift == "helper-revision":
        monkeypatch.setenv("VCS_REF", "b" * 40)
    elif drift == "missing-helper-revision":
        monkeypatch.delenv("VCS_REF")
    elif drift == "runtime-channel":
        monkeypatch.setenv("PKM_ENVIRONMENT", "test" if channel == "dev" else "dev")
    elif drift == "missing-runtime-channel":
        monkeypatch.delenv("PKM_ENVIRONMENT")
    elif drift == "binding":
        monkeypatch.setenv("VAULT_ROOT", str(wrong_root))
        monkeypatch.setenv("WATCHER_VAULT_PATH", str(wrong_root))
    else:
        monkeypatch.delenv("VAULT_ROOT")
        monkeypatch.delenv("WATCHER_VAULT_PATH")
    producer_calls: list[Path] = []
    monkeypatch.setattr(
        native_source_identity_persistence, "run_ordinary_persistence",
        lambda **kwargs: producer_calls.append(kwargs["vault_root"]),
    )
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for selected in (root, wrong_root)
        for path in selected.rglob("*")
        if path.is_file()
    }

    assert native_source_identity_persistence.worker_main([
        str(uuid4()), channel, REVISION, container_root,
    ]) == 78
    assert producer_calls == []
    assert {
        path.relative_to(tmp_path): path.read_bytes()
        for selected in (root, wrong_root)
        for path in selected.rglob("*")
        if path.is_file()
    } == before
