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
        lambda: ("c" * 64, ("api", "worker", "watcher"), ("api", "worker", "watcher"))
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
        lambda: ("c" * 64, ("api", "worker", "watcher"), ("api", "worker", "watcher"))
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
        lambda: ("c" * 64, ("api", "worker", "watcher"), ("api", "worker", "watcher"))
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
        lambda: ("c" * 64, ("api", "worker", "watcher"), ("api", "worker", "watcher"))
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
    "channel,expected_overlay",
    [("dev", "docker-compose.full-host-vault.yml"), ("test", "docker-compose.test-vault.yml")],
)
def test_source_compose_uses_exact_candidate_and_canonical_selected_vault_overlays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, channel: str, expected_overlay: str,
) -> None:
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import AuthorityCutover

    captured: dict[str, object] = {}
    candidate = SimpleNamespace(revision=REVISION, image_digest=DIGEST)
    selected = AuthorityCutover("vault-alpha", "/srv/vault-alpha", "/srv/instance-ownership")
    effects = linux.LinuxEffects(SimpleNamespace(channel=channel, root=tmp_path))

    def environment(cutover, selected_candidate):
        assert cutover is selected
        assert selected_candidate is candidate
        return {"BWS_DATABASE_TARGET": "local"}

    def command(argv, **kwargs):
        captured.update(argv=argv, env=kwargs["env"])
        return ""

    effects.environment = environment  # type: ignore[method-assign]
    monkeypatch.setattr(linux, "_command", command)

    effects.compose(
        "run", "--no-deps", "api", cutover=selected, candidate=candidate,
    )

    argv = captured["argv"]
    assert isinstance(argv, list)
    assert str(tmp_path / "docker-compose.full-host-vault.yml") in argv
    assert str(tmp_path / expected_overlay) in argv
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["VAULT_HOST_ROOT"] == selected.root
    assert env["DEPLOY_VAULT_CONTAINER_ROOT"] == selected.root


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
        lambda: ("c" * 64, ("api", "worker", "watcher"), ("api", "worker", "watcher"))
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

    effects.require_source_identity_candidate(plan, selected, acquire=True)
    assert events == ["source", "protocol", "pull"]


def test_runtime_snapshot_fences_stale_active_capture_and_model_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ops import postgres_deploy_linux as linux

    rows = []
    for index, service in enumerate(("api", "worker", "watcher", "heimdal-capture-watch"), 1):
        rows.append({
            "Id": f"{index:064x}",
            "Image": f"sha256:{index:064x}",
            "Config": {
                "Image": f"example/{service}:installed",
                "Env": ["EMBED_PROVIDER=ollama", "EMBED_MODEL=accepted"],
                "User": "501:20",
                "Labels": {
                    "com.docker.compose.project": "pkm-dev",
                    "com.docker.compose.service": service,
                    "com.docker.compose.oneoff": "False",
                },
            },
            "State": {"Status": "running"},
            "Mounts": [],
        })
    effects = linux.LinuxEffects(SimpleNamespace(channel="dev"))

    def command(argv, **_kwargs):
        return "\n".join(row["Id"] for row in rows) if argv[1:3] == ["ps", "--all"] else json.dumps(rows)

    monkeypatch.setattr(linux, "_command", command)
    monkeypatch.setattr(linux, "_capture_watch_configured", lambda _config: False)

    before, running, existing = effects.source_identity_runtime_snapshot()
    assert "heimdal-capture-watch" in running
    assert running == existing
    rows[0]["Config"]["Env"] = ["EMBED_PROVIDER=ollama", "EMBED_MODEL=drifted"]
    after, _running, _existing = effects.source_identity_runtime_snapshot()
    assert after != before
