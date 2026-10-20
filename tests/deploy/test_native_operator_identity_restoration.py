from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import sys
import pytest

from app.ops import native_operator_identity_restoration as restoration
from app.ops.native_operator_identity_restoration import (
    OperatorIdentityRestorationRefusal,
    prepare_uuid_scalar_rewrite,
    validate_command,
    validate_receipt,
)


OLD = "legacy::11111111-1111-4111-8111-111111111111"
CANONICAL = "11111111-1111-4111-8111-111111111111"


def _command() -> dict[str, object]:
    return {
        "target_rel": "rewritten/example.md",
        "expected_old_scalar": OLD,
        "replacement_uuid": CANONICAL,
    }


def test_host_validation_imports_without_worker_yaml_dependency(tmp_path: Path) -> None:
    from scripts.postmerge_controller import copy_runtime_dependencies

    vendor = tmp_path / "vendor"
    copy_runtime_dependencies(vendor)
    root = Path(__file__).resolve().parents[2]
    program = """
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
vendor = Path(sys.argv[2])
sys.path[:0] = [str(root), str(vendor)]
import app.ops.postgres_deploy_host
from app.ops.native_operator_identity_restoration import validate_command

command = {
    "target_rel": "rewritten/example.md",
    "expected_old_scalar": "legacy::11111111-1111-4111-8111-111111111111",
    "replacement_uuid": "11111111-1111-4111-8111-111111111111",
}
assert validate_command(command) == command
assert "yaml" not in sys.modules
print(json.dumps({"host_import": True, "validated": True, "yaml_imported": False}, sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", program, str(root), str(vendor)],
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "host_import": True,
        "validated": True,
        "yaml_imported": False,
    }


def test_scalar_rewrite_changes_only_uuid_representation() -> None:
    raw = f"---\ntitle: Example\nuuid: '{OLD}'\ntags: [one]\n---\nbody\n"

    prepared = prepare_uuid_scalar_rewrite(
        raw, expected_old_scalar=OLD, replacement_uuid=CANONICAL,
    )

    assert prepared.candidate_text == raw.replace(f"'{OLD}'", f"'{CANONICAL}'")
    assert prepared.original_sha256 != prepared.candidate_sha256
    assert raw.endswith("---\nbody\n")


def test_operator_identity_restoration_preserves_identity_and_original(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    from app.knowledge import multiwriter
    from app.knowledge.multiwriter import NoteClass
    from app.vault import paths as vault_paths
    from app.write_guard import DEFAULT_WRITE_GUARD

    target = tmp_path / "rewritten" / "example.md"
    target.parent.mkdir()
    original = f"---\ntitle: Example\nuuid: '{OLD}'\n---\nbody\n"
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        multiwriter, "classify_note_in_vault", lambda *_args, **_kwargs: NoteClass.REWRITTEN,
    )
    monkeypatch.setattr(vault_paths, "get_vault_capture_note_rel", lambda _root: "Inbox/capture.md")
    monkeypatch.setattr(vault_paths, "get_vault_sources_dir_rel", lambda _root: "Sources")
    monkeypatch.setattr(
        restoration, "_prove_inventory_and_product", lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(restoration, "_prove_other_sources_preserved", lambda **_kwargs: None)
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "healthy"})

    receipt = restoration.run_worker(
        operation_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        revision="a" * 40,
        vault_root=tmp_path,
        command=_command(),
        connection=object(),
    )
    assert receipt["write_phase"] == "written"
    assert target.read_text(encoding="utf-8") == original.replace(OLD, CANONICAL)
    retained = list((target.parent / "_conflicts").glob("*.conflict"))
    assert retained and any(path.read_text(encoding="utf-8") == original for path in retained)


def test_operator_identity_restoration_guard_and_stale_cas_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    from app.knowledge import multiwriter
    from app.knowledge.multiwriter import NoteClass
    from app.vault import paths as vault_paths
    from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError

    target = tmp_path / "rewritten" / "example.md"
    target.parent.mkdir()
    original = f"---\nuuid: '{OLD}'\n---\nbody\n"
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        multiwriter, "classify_note_in_vault", lambda *_args, **_kwargs: NoteClass.REWRITTEN,
    )
    monkeypatch.setattr(vault_paths, "get_vault_capture_note_rel", lambda _root: "Inbox/capture.md")
    monkeypatch.setattr(vault_paths, "get_vault_sources_dir_rel", lambda _root: "Sources")
    monkeypatch.setattr(restoration, "_prove_other_sources_preserved", lambda **_kwargs: None)
    monkeypatch.setattr(
        restoration, "_prove_inventory_and_product", lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "safe_mode"})
    with pytest.raises(WritesBlockedError):
        restoration.run_worker(
            operation_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            revision="a" * 40, vault_root=tmp_path,
            command=_command(), connection=object(),
        )
    assert target.read_text(encoding="utf-8") == original

    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "healthy"})
    concurrent = original.replace("body", "human-current")

    def race(*_args, **_kwargs):
        target.write_text(concurrent, encoding="utf-8")
        return {}

    monkeypatch.setattr(restoration, "_prove_inventory_and_product", race)
    receipt = restoration.run_worker(
        operation_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        revision="a" * 40, vault_root=tmp_path,
        command=_command(), connection=object(),
    )
    assert receipt["write_phase"] == "indeterminate"
    assert target.read_text(encoding="utf-8") == concurrent


@pytest.mark.parametrize(
    ("old", "replacement"),
    [
        (CANONICAL, CANONICAL),
        ("22222222-2222-4222-8222-222222222222", CANONICAL),
    ],
)
def test_operator_identity_restoration_preserves_generic_never_overwrite_policy(
    old: str, replacement: str,
) -> None:
    raw = f"---\nuuid: {old}\n---\nbody\n"
    with pytest.raises(OperatorIdentityRestorationRefusal) as exc:
        prepare_uuid_scalar_rewrite(
            raw, expected_old_scalar=old, replacement_uuid=replacement,
        )
    assert exc.value.reason == "authority_refused"


def test_command_is_exact_and_dev_receipt_is_content_free() -> None:
    command = _command()
    assert validate_command(command) == command
    with pytest.raises(OperatorIdentityRestorationRefusal):
        validate_command({**command, "private_path": "/secret"})
    with pytest.raises(OperatorIdentityRestorationRefusal):
        validate_command({**command, "expected_old_scalar": "  "})

    receipt = {
        "contract": "native-operator-identity-restoration.v1",
        "operation_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "channel": "dev",
        "revision": "a" * 40,
        "result": "committed",
        "write_phase": "written",
        "cleanup": "complete",
        "reason": None,
        "automatic_producer_started": False,
        "automatic_deployment_started": False,
    }
    assert validate_receipt(receipt) == receipt
    with pytest.raises(OperatorIdentityRestorationRefusal):
        validate_receipt({**receipt, "channel": "test"})


def test_inventory_proof_derives_all_thirteen_sources_and_product_binding(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    from app.ingest import vault_alpha
    from app.knowledge import profile_authority_store, write_ops
    from app.objects import identity
    from app.services import companion_note, note_uuid

    candidates = [tmp_path / f"note-{index}.md" for index in range(13)]
    target = candidates[0]
    raw_by_rel = {
        path.name: (
            f"---\nuuid: {OLD}\n---\nbody\n" if path == target
            else f"---\nuuid: {index:08d}-1111-4111-8111-111111111111\n---\nother {index}\n"
        )
        for index, path in enumerate(candidates)
    }
    monkeypatch.setattr(vault_alpha, "select_source_backed_rebuild_candidates", lambda _root: candidates)
    monkeypatch.setattr(
        write_ops, "read_recovery_snapshot_relative",
        lambda relative, vault_root: (raw_by_rel[relative], (relative, "snapshot")),
    )
    monkeypatch.setattr(companion_note, "read_companion", lambda _root, declared: None)
    monkeypatch.setattr(profile_authority_store, "is_profile_note_source", lambda *_args: False)
    monkeypatch.setattr(note_uuid, "is_read_only_derived_artifact", lambda _frontmatter: False)
    monkeypatch.setattr(identity, "resolve_vault_uuid_with_connection", lambda *_args, **_kwargs: CANONICAL)

    from app.instance.binding_ids import COMPATIBILITY_BINDING_ID

    rows = [(
        COMPATIBILITY_BINDING_ID, CANONICAL, str(target),
        {"vault_uuid": CANONICAL, "text": "body"},
    )]

    class Cursor:
        def __init__(self) -> None:
            self.query = ""

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, query, _params=None):
            self.query = query

        def fetchone(self):
            return ("on",)

        def fetchall(self):
            return list(rows)

    class Connection:
        def cursor(self):
            return Cursor()

    snapshots = restoration._prove_inventory_and_product(
        Connection(), root=tmp_path, target=target,
        current=raw_by_rel[target.name], command=_command(),
    )
    assert tuple(snapshots) == tuple(path.name for path in candidates)
    raw_by_rel[candidates[1].name] = f"---\nuuid: {CANONICAL}\n---\npeer claim\n"
    with pytest.raises(OperatorIdentityRestorationRefusal):
        restoration._prove_inventory_and_product(
            Connection(), root=tmp_path, target=target,
            current=raw_by_rel[target.name], command=_command(),
        )
    raw_by_rel[candidates[1].name] = (
        "---\nuuid: 00000001-1111-4111-8111-111111111111\n---\nother 1\n"
    )
    rows.append((
        "foreign-binding", "22222222-2222-4222-8222-222222222222",
        str(target), {"vault_uuid": "22222222-2222-4222-8222-222222222222", "text": "body"},
    ))
    with pytest.raises(OperatorIdentityRestorationRefusal):
        restoration._prove_inventory_and_product(
            Connection(), root=tmp_path, target=target,
            current=raw_by_rel[target.name], command=_command(),
        )


def test_owned_container_validator_accepts_only_typed_dev_restoration_name() -> None:
    from app.ops.native_source_bootstrap import quiesce_owned_container

    operation = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    revision = "a" * 40
    calls: list[list[str]] = []

    def docker(command, **_kwargs):
        calls.append(command)
        return ""

    assert quiesce_owned_container(
        "dev", f"pkm-dev-operator-identity-restoration-{operation}",
        operation, revision, docker_command=docker,
    ) is True
    assert calls and calls[0][1:3] == ["ps", "--all"]
    assert quiesce_owned_container(
        "test", f"pkm-test-operator-identity-restoration-{operation}",
        operation, revision, docker_command=docker,
    ) is False


def test_host_entrypoint_uses_distinct_dev_operation_and_stdin_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    from app.ops import postgres_deploy_host as host
    from app.ops.host_secret_controller import HostSecretController

    state = tmp_path / "host-state"
    state.mkdir(mode=0o700)
    controller = HostSecretController(state)
    operation_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    command = _command()

    class Remote:
        def __init__(self, hostname):
            assert hostname == "ygg-dev"

        def restore_operator_source_identity(
            self, requested_id, revision, _digest, _selected, supplied, *,
            resume_unattempted,
        ):
            assert requested_id == operation_id
            assert supplied == command
            assert resume_unattempted is False
            return {
                "contract": "native-operator-identity-restoration.v1",
                "operation_id": operation_id,
                "channel": "dev",
                "revision": revision,
                "result": "committed",
                "write_phase": "written",
                "cleanup": "complete",
                "reason": None,
                "automatic_producer_started": False,
                "automatic_deployment_started": False,
            }

    monkeypatch.setattr(host, "HostSecretController", lambda: controller)
    monkeypatch.setattr(host, "SshDeployRemote", Remote)
    monkeypatch.setattr(host.sys, "stdin", io.StringIO(json.dumps(command)))
    result = host.main([
        "dev", "a" * 40, "--automatic", "--existing-secrets-only",
        "--restore-operator-source-identity", "--operation-id", operation_id,
        "--image-digest", "sha256:" + "1" * 64,
        "--authority-cutover-binding", "vault-alpha",
        "--authority-cutover-root", "/srv/vault-alpha",
        "--authority-cutover-ownership-root", "/srv/instance-ownership",
    ])
    assert result == 0
    records = [json.loads(line) for line in (state / "operations.jsonl").read_text().splitlines()]
    assert [record["kind"] for record in records] == [
        "operator-identity-restoration",
        "operator-identity-restoration",
        "operator-identity-restoration",
    ]
    assert [record["stage"] for record in records] == ["prepared", "sent", "committed"]


def test_host_entrypoint_retains_pending_lineage_until_cleanup_is_proven(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    from app.ops import postgres_deploy_host as host
    from app.ops.host_secret_controller import HostSecretController

    state = tmp_path / "host-state"
    state.mkdir(mode=0o700)
    controller = HostSecretController(state)
    operation_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    command = _command()

    class Remote:
        def __init__(self, hostname):
            assert hostname == "ygg-dev"

        def restore_operator_source_identity(self, _operation, revision, *_args, **_kwargs):
            return {
                "contract": "native-operator-identity-restoration.v1",
                "operation_id": operation_id, "channel": "dev", "revision": revision,
                "result": "unknown", "write_phase": "indeterminate",
                "cleanup": "retained", "reason": "writer_restore_failed",
                "automatic_producer_started": False,
                "automatic_deployment_started": False,
            }

    monkeypatch.setattr(host, "HostSecretController", lambda: controller)
    monkeypatch.setattr(host, "SshDeployRemote", Remote)
    monkeypatch.setattr(host.sys, "stdin", io.StringIO(json.dumps(command)))
    assert host.main([
        "dev", "a" * 40, "--automatic", "--existing-secrets-only",
        "--restore-operator-source-identity", "--operation-id", operation_id,
        "--image-digest", "sha256:" + "1" * 64,
        "--authority-cutover-binding", "vault-alpha",
        "--authority-cutover-root", "/srv/vault-alpha",
        "--authority-cutover-ownership-root", "/srv/instance-ownership",
    ]) == 78
    records = [json.loads(line) for line in (state / "operations.jsonl").read_text().splitlines()]
    assert [record["stage"] for record in records] == ["prepared", "sent"]


def test_host_reader_accepts_failed_dev_restoration_and_refuses_other_channels(
    tmp_path,
) -> None:
    from uuid import uuid4

    from app.ops.host_secret_controller import (
        HostSecretAdmissionError, HostSecretController, TerminalEvidence,
    )

    state = tmp_path / "host-state"
    state.mkdir(mode=0o700)
    controller = HostSecretController(state)
    failed_id = str(uuid4())
    with controller.operator_identity_restoration_operation(
        "dev", operation_id=failed_id,
    ) as (operation, resumed):
        assert resumed is False
        operation.prepare_mutation()
        operation.finish(TerminalEvidence(
            failed_id, "operator-identity-restoration", "dev", "failed", "remote-terminal",
        ))
    with controller.operator_identity_restoration_operation(
        "dev", operation_id=failed_id,
    ) as (operation, resumed):
        assert resumed is True and operation.completed_result == "failed"
    for channel in ("test", "prod"):
        with pytest.raises(HostSecretAdmissionError):
            with controller.admit("operator-identity-restoration", channel):
                pass
    with controller.operator_identity_restoration_operation(
        "dev", operation_id=str(uuid4()),
    ) as (operation, resumed):
        assert resumed is False
        operation.prepare_mutation()
