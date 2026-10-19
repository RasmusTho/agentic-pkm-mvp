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
    effects = linux.LinuxEffects(SimpleNamespace(channel="dev", root=tmp_path))

    def command(argv, **_kwargs):
        return "\n".join(row["Id"] for row in rows) if argv[1:3] == ["ps", "--all"] else json.dumps(rows)

    monkeypatch.setattr(linux, "_command", command)
    monkeypatch.setattr(linux, "_capture_watch_configured", lambda _config: False)

    selected = AuthorityCutover("vault-alpha", "/srv/vault-alpha", "/srv/instance-ownership")
    before = effects.source_identity_runtime_snapshot(
        selected, require_running_capture=True,
    )
    assert "heimdal-capture-watch" in before.running_writers
    assert before.running_writers == before.existing_writers
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
    config = SimpleNamespace(channel="dev", root=tmp_path, journal=SimpleNamespace(
        directory=journal_dir, channel="dev"), uid=501)
    effects = linux.LinuxEffects(config)

    def command(argv, **_kwargs):
        if argv[1:3] == ["ps", "--all"]:
            return "\n".join(row["Id"] for row in rows)
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
    fresh.compose = lambda *args, **_kwargs: events.append(str(args[0])) or ""  # type: ignore[method-assign]
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


def test_separate_candidate_helper_reaches_real_worker_and_ordinary_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An old installed runtime can launch the reviewed helper without adoption."""
    import io
    from contextlib import contextmanager, redirect_stdout

    from app.ingest import vault_alpha as producer
    from app.ops import native_source_bootstrap, postgres_deploy_linux as linux
    from app.ops.postgres_deploy import AuthorityCutover, DeployPlan
    from app.stores import reset_memory_store_backend

    root = (tmp_path / "vault").resolve()
    root.mkdir()
    layout = root / "⚙️ System" / "vault.layout.md"
    layout.parent.mkdir()
    layout.write_text("---\ninclude_folders: [Notes]\n---\nLayout.\n")
    note = root / "Notes" / "candidate.md"
    note.parent.mkdir()
    note.write_text("---\ntrust: human\nreview_state: reviewed\n---\nCandidate body.\n")
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    reset_memory_store_backend()
    monkeypatch.setattr(producer, "classify_run", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(producer, "index_ingest_object", lambda **_kwargs: None)
    monkeypatch.setattr(producer, "append_jsonl", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(native_source_bootstrap, "preflight", lambda _selector: root)
    monkeypatch.setattr(native_source_bootstrap, "quiesce_owned_container", lambda *_args: True)

    operation_id = str(uuid4())
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    journal = SimpleNamespace(
        directory=journal_dir, channel="dev",
        read=lambda: SimpleNamespace(terminal_result="failed"),
    )
    effects = linux.LinuxEffects(SimpleNamespace(channel="dev", journal=journal, uid=501))
    selected = AuthorityCutover("vault-alpha", str(root), "/srv/instance-ownership")
    plan = DeployPlan(
        "dev", REVISION, ("api", "worker", "watcher"),
        ("postgres-db", "postgres-api", "postgres-worker", "postgres-watcher", "heimdal-api-ingress"),
        image_digest=DIGEST, authority_cutover=selected,
    )
    snapshot = linux.SourceIdentityRuntimeSnapshot(
        "c" * 64, "d" * 64, ("api", "watcher", "worker"),
        ("api", "watcher", "worker"), str(root),
        "docker-compose.full-host-vault.yml",
        (("DATABASE_URL", "postgresql+psycopg:///?host=db"),
         ("LLM_PROVIDER", "mock"), ("STORE_BACKEND", "memory")),
    )
    effects.qualify_source_identity_authority = lambda *_args: plan  # type: ignore[method-assign]
    effects.source_identity_runtime_snapshot = lambda *_args, **_kwargs: snapshot  # type: ignore[method-assign]
    candidate_checks: list[bool] = []
    effects.require_source_identity_candidate = (  # type: ignore[method-assign]
        lambda _plan, _selected, *, acquire, source_snapshot: candidate_checks.append(acquire)
    )
    events: list[str] = []

    @contextmanager
    def lock(**_kwargs):
        events.append("lock")
        yield object()

    effects.channel_lock = lock  # type: ignore[method-assign]
    effects.failed_reconciliation_lock = lock  # type: ignore[method-assign]
    effects.retire_reconciled_channel_lock = lambda *_args, **_kwargs: events.append("retire")  # type: ignore[method-assign]

    def compose(*args, **kwargs):
        action = str(args[0])
        events.append(action)
        if action != "run":
            return ""
        assert kwargs["candidate"] is plan
        assert kwargs["source_snapshot"] is snapshot
        module_index = args.index("app.ops.native_source_identity_persistence")
        worker_args = list(args[module_index + 1:module_index + 5])
        output = io.StringIO()
        with redirect_stdout(output):
            assert __import__(
                "app.ops.native_source_identity_persistence", fromlist=["worker_main"],
            ).worker_main(worker_args) == 0
        return output.getvalue()

    effects.compose = compose  # type: ignore[method-assign]

    receipt = effects.persist_source_identity(operation_id, REVISION, DIGEST, selected)
    assert receipt["terminal_state"] == "committed"
    assert receipt["eligible"] is True
    assert "uuid:" in note.read_text()
    assert candidate_checks == [True, False]
    assert "up" not in events
