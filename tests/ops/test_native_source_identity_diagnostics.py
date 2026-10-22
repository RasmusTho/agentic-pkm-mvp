from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from app.ops import native_source_identity_diagnostics as diagnostics


REVISION = "a" * 40
IDENTITY = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BINDING = "compatibility-binding"


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self.rows: list[Any] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, parameters: tuple[Any, ...] = ()) -> None:
        self.connection.queries.append((query, parameters))
        if query == "SHOW default_transaction_read_only":
            self.rows = [{"default_transaction_read_only": self.connection.read_only}]
        elif "WHERE source_ref = %s" in query:
            self.rows = list(self.connection.rows.get(parameters[0], ()))
        else:
            source_ref = parameters[2]
            self.rows = list(self.connection.global_rows.get(source_ref, ()))

    def fetchone(self) -> Any:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[Any]:
        return self.rows


class FakeConnection:
    def __init__(
        self,
        *,
        read_only: str = "on",
        rows: dict[str, tuple[Any, ...]] | None = None,
        global_rows: dict[str, tuple[Any, ...]] | None = None,
    ) -> None:
        self.read_only = read_only
        self.rows = rows or {}
        self.global_rows = global_rows or {}
        self.queries: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True


def _request(*observations: tuple[str, str]) -> dict[str, Any]:
    return {
        "contract": diagnostics.REQUEST_CONTRACT,
        "channel": "dev",
        "revision": REVISION,
        "observations": [
            {
                "source_ref": source_ref,
                "body_sha256": body_sha256,
                "source_version_sha256": hashlib.sha256(
                    f"{source_ref}:{body_sha256}".encode("utf-8"),
                ).hexdigest(),
            }
            for source_ref, body_sha256 in observations
        ],
    }


def _dependencies() -> tuple[Any, ...]:
    return (
        lambda value: value if value == IDENTITY else None,
        lambda value: value.strip(),
        lambda _connection, value: value,
        BINDING,
    )


def test_source_observation_worker_remains_network_none_without_database_transport() -> None:
    safe = (
        "docker", "create", "--network", "none", "-e", "PKM_ENVIRONMENT=dev",
        "--mount", "type=bind,source=/private,target=/private,readonly", "image",
    )
    assert diagnostics.validate_source_observation_create_argv(
        safe,
        image_environment=("PATH=/usr/bin",),
    ) == safe

    for unsafe in (
        ("docker", "create", "--network", "bridge", "image"),
        ("docker", "create", "--network", "none", "-e", "DATABASE_URL=private", "image"),
        ("docker", "create", "--network", "none", "--env-file", "/private", "image"),
        (
            "docker", "create", "--network", "none", "--mount",
            "type=bind,source=/private,target=/var/run/postgresql,readonly", "image",
        ),
        (
            "docker", "create", "--network", "none", "--mount",
            "type=bind,source=/private/db.sock,target=/private/db.sock,readonly",
            "--device", "/dev/private", "image",
        ),
        (
            "docker", "create", "--network", "none", "--mount",
            "type=bind,source=/private,target=/run/private-db,readonly", "image",
        ),
        ("docker", "create", "--network", "none", "-v", "/private:/private", "image"),
        ("docker", "create", "--network", "none", "--env=PGPASSFILE=/private", "image"),
        ("docker", "create", "--network", "none", "--network=bridge", "image"),
        ("docker", "create", "--network", "none", "--net=host", "image"),
    ):
        with pytest.raises(diagnostics.SourceIdentityDiagnosticRefusal):
            diagnostics.validate_source_observation_create_argv(
                unsafe,
                image_environment=("PATH=/usr/bin",),
            )

    with pytest.raises(diagnostics.SourceIdentityDiagnosticRefusal):
        diagnostics.validate_source_observation_create_argv(
            safe,
            image_environment=("DATABASE_URL=private",),
        )
    for key in ("PGPASSFILE", "PGSERVICEFILE", "PGSSLKEY"):
        with pytest.raises(diagnostics.SourceIdentityDiagnosticRefusal):
            diagnostics.validate_source_observation_create_argv(
                safe,
                image_environment=(f"{key}=/private",),
            )


def test_database_witness_has_no_source_mounts_and_enforces_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compose = yaml.safe_load(Path("docker-compose.yaml").read_text(encoding="utf-8"))
    service = compose["services"][diagnostics.DATABASE_WITNESS_SERVICE]
    assert "volumes" not in service
    assert service["read_only"] is True
    assert service["labels"] == {
        "com.agentic-pkm.mvr05.db-role": "non-client",
    }
    assert service["environment"] == {
        "PGOPTIONS": "-c default_transaction_read_only=on",
    }
    assert service["profiles"] == ["native-source-diagnostics"]
    assert diagnostics.closed_witness_environment({
        "DATABASE_URL": "private-dsn",
        "PGOPTIONS": "-c default_transaction_read_only=on",
        "VAULT_ROOT": "/private/source",
        "API_KEY": "private-key",
        "PATH": "/usr/bin",
    }) == {
        "DATABASE_URL": "private-dsn",
        "PGOPTIONS": "-c default_transaction_read_only=on",
        "PATH": "/usr/bin",
    }
    assert diagnostics.database_witness_compose_argv(("docker", "compose")) == (
        "docker", "compose", "run", "--rm", "--no-deps", "-T",
        diagnostics.DATABASE_WITNESS_SERVICE,
    )

    monkeypatch.setenv("PGOPTIONS", "-c default_transaction_read_only=on")
    source_ref = "/private/source"
    body_hash = hashlib.sha256(b"body").hexdigest()
    row = {
        "vault_binding_id": BINDING,
        "object_id": IDENTITY,
        "source_ref": source_ref,
        "payload": {"vault_uuid": IDENTITY, "text": "body"},
    }
    connection = FakeConnection(
        rows={source_ref: (row,)},
        global_rows={source_ref: (row,)},
    )
    receipt = diagnostics.run_database_witness(
        _request((source_ref, body_hash)),
        channel="dev",
        revision=REVISION,
        connection_factory=lambda: connection,
        dependencies=_dependencies(),
    )
    assert receipt["terminal_state"] == "observed"
    assert receipt["product_filesystem_complete_count"] == 1
    assert connection.queries[0][0] == "SHOW default_transaction_read_only"
    assert connection.closed is True


def test_production_diagnostic_reconciles_fixed_counts_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PGOPTIONS", "-c default_transaction_read_only=on")
    complete_ref = "/private/complete"
    absent_ref = "/private/absent"
    mismatch_ref = "/private/mismatch"
    body_hash = hashlib.sha256(b"body").hexdigest()
    complete = {
        "vault_binding_id": BINDING,
        "object_id": IDENTITY,
        "source_ref": complete_ref,
        "payload": {"vault_uuid": IDENTITY, "text": "body"},
    }
    mismatch = {**complete, "source_ref": mismatch_ref}
    connection = FakeConnection(
        rows={complete_ref: (complete,), mismatch_ref: (mismatch,)},
        global_rows={complete_ref: (complete,), mismatch_ref: (mismatch,)},
    )
    receipt = diagnostics.run_database_witness(
        _request(
            (complete_ref, body_hash),
            (absent_ref, body_hash),
            (mismatch_ref, hashlib.sha256(b"different").hexdigest()),
        ),
        channel="dev",
        revision=REVISION,
        connection_factory=lambda: connection,
        dependencies=_dependencies(),
    )
    assert set(receipt) == {
        "contract", "channel", "revision", "terminal_state", "reason",
        *diagnostics.COUNT_FIELDS,
    }
    assert receipt == {
        "contract": diagnostics.RECEIPT_CONTRACT,
        "channel": "dev",
        "revision": REVISION,
        "terminal_state": "observed",
        "reason": None,
        "selected_count": 3,
        "product_filesystem_complete_count": 1,
        "product_absent_count": 1,
        "product_conflict_count": 0,
        "locator_or_body_mismatch_count": 1,
        "duplicate_or_foreign_claim_count": 0,
    }


def test_source_prepare_and_finalize_refence_canonical_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    note = root / "note.md"
    note.write_text("---\nuuid: not-a-uuid\n---\nbody\n", encoding="utf-8")
    observation = SimpleNamespace(path=note)
    policy = SimpleNamespace(registry_digest="b" * 64)

    from app.knowledge import profile_authority_store, write_ops
    from app.ops import native_source_identity_persistence

    monkeypatch.setattr(
        native_source_identity_persistence,
        "_registry_plan",
        lambda _root: (policy, (observation,)),
    )
    monkeypatch.setattr(
        native_source_identity_persistence,
        "registry_identity_inventory",
        lambda _root, _observations: native_source_identity_persistence.IdentityInventory(
            selected_count=1,
            persisted_count=0,
            missing_count=0,
            invalid_count=1,
            ambiguous_count=0,
        ),
    )
    monkeypatch.setattr(
        profile_authority_store,
        "is_profile_note_source_read_only",
        lambda *_args, **_kwargs: False,
    )
    original_snapshot = write_ops.read_recovery_snapshot_relative
    monkeypatch.setattr(
        write_ops,
        "read_recovery_snapshot_relative",
        original_snapshot,
    )

    prepare = diagnostics._source_capture(  # noqa: SLF001 - exact production seam
        root,
        source_ref_root="/accepted-vault",
        channel="dev",
        revision=REVISION,
    )
    assert set(prepare) == {
        "contract", "channel", "revision", "source_snapshot_sha256",
        "counts", "request",
    }
    assert prepare["counts"] == {
        "registry_selected_count": 1,
        "registry_persisted_count": 0,
        "registry_missing_count": 0,
        "registry_invalid_count": 1,
        "registry_ambiguous_count": 0,
        "authority_candidate_count": 1,
        "protected_authority_candidate_count": 0,
        "source_observation_unknown_count": 0,
    }
    assert len(prepare["request"]["observations"]) == 1
    assert prepare["request"]["observations"][0]["source_ref"] == (
        "/accepted-vault/note.md"
    )
    database_receipt = diagnostics._receipt(  # noqa: SLF001
        channel="dev",
        revision=REVISION,
        reason=None,
        counts={
            "selected_count": 1,
            "product_filesystem_complete_count": 0,
            "product_absent_count": 1,
            "product_conflict_count": 0,
            "locator_or_body_mismatch_count": 0,
            "duplicate_or_foreign_claim_count": 0,
        },
    )
    final = diagnostics.finalize_source_observation(
        prepare,
        database_receipt,
        vault_root=root,
        source_ref_root="/accepted-vault",
        channel="dev",
        revision=REVISION,
    )
    assert final["contract"] == diagnostics.SOURCE_RECEIPT_CONTRACT
    assert final["registry_selected_count"] == 1
    assert final["product_absent_count"] == 1

    note.write_text("---\nuuid: not-a-uuid\n---\nchanged\n", encoding="utf-8")
    with pytest.raises(diagnostics.SourceIdentityDiagnosticRefusal):
        diagnostics.finalize_source_observation(
            prepare,
            database_receipt,
            vault_root=root,
            source_ref_root="/accepted-vault",
            channel="dev",
            revision=REVISION,
        )


def test_production_coordinator_invokes_dual_actor_path_and_bounds_frames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_image = "sha256:" + "d" * 64
    owner_token = "f" * 32
    monkeypatch.setattr(diagnostics.secrets, "token_hex", lambda _size: owner_token)
    for key in diagnostics._SOURCE_CONFIGURATION_KEYS:  # noqa: SLF001
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("WATCHER_SCOPE_GLOB", "accepted/**/*.md")
    container_source_root = "/accepted-vault"
    source_environment = diagnostics._closed_source_environment(  # noqa: SLF001
        dict(diagnostics.os.environ),
        container_source_root=container_source_root,
    )
    source_prepare = diagnostics.source_observation_run_argv(
        mode="source-prepare",
        source_image=source_image,
        source_root=source_root,
        container_source_root=container_source_root,
        source_environment=source_environment,
        channel="dev",
        revision=REVISION,
        container_name=f"pkm-source-id-prepare-{REVISION[:12]}",
        owner_token=owner_token,
    )
    source_finalize = diagnostics.source_observation_run_argv(
        mode="source-finalize",
        source_image=source_image,
        source_root=source_root,
        container_source_root=container_source_root,
        source_environment=source_environment,
        channel="dev",
        revision=REVISION,
        container_name=f"pkm-source-id-finalize-{REVISION[:12]}",
        owner_token=owner_token,
    )
    request = _request(("/private/source", hashlib.sha256(b"body").hexdigest()))
    prepare = {
        "contract": diagnostics.SOURCE_PREPARE_CONTRACT,
        "channel": "dev",
        "revision": REVISION,
        "source_snapshot_sha256": "c" * 64,
        "counts": {
            "registry_selected_count": 1,
            "registry_persisted_count": 0,
            "registry_missing_count": 0,
            "registry_invalid_count": 1,
            "registry_ambiguous_count": 0,
            "authority_candidate_count": 1,
            "protected_authority_candidate_count": 0,
            "source_observation_unknown_count": 0,
        },
        "request": request,
    }
    database_receipt = diagnostics._receipt(  # noqa: SLF001
        channel="dev",
        revision=REVISION,
        reason=None,
        counts={
            "selected_count": 1,
            "product_filesystem_complete_count": 1,
            "product_absent_count": 0,
            "product_conflict_count": 0,
            "locator_or_body_mismatch_count": 0,
            "duplicate_or_foreign_claim_count": 0,
        },
    )
    final = {
        "contract": diagnostics.SOURCE_RECEIPT_CONTRACT,
        "channel": "dev",
        "revision": REVISION,
        "terminal_state": "observed",
        "reason": None,
        **prepare["counts"],
        **{field: database_receipt[field] for field in diagnostics.COUNT_FIELDS},
    }
    calls: list[tuple[tuple[str, ...], bytes, int]] = []

    def runner(
        argv: tuple[str, ...], *, input_bytes: bytes, max_output_bytes: int,
    ) -> bytes:
        calls.append((argv, input_bytes, max_output_bytes))
        if argv[:4] == ("docker", "image", "inspect", "--format"):
            if argv[4] == "{{json .Config.Env}}":
                return b'["PATH=/usr/bin"]'
            return source_image.encode("ascii")
        if "images" in argv:
            return source_image.encode("ascii")
        if argv == source_prepare:
            return json.dumps(prepare).encode("utf-8")
        if argv == diagnostics.database_witness_compose_argv(
            ("docker", "compose"),
            container_name=f"pkm-source-id-witness-{REVISION[:12]}",
            owner_token=owner_token,
        ):
            assert json.loads(input_bytes) == request
            return json.dumps(database_receipt).encode("utf-8")
        assert argv == source_finalize
        envelope = json.loads(input_bytes)
        assert envelope == {
            "prepare": prepare,
            "database_receipt": database_receipt,
        }
        return json.dumps(final).encode("utf-8")

    fenced: list[tuple[str, str]] = []
    receipt = diagnostics.run_production_diagnostic(
        source_image=source_image,
        source_root=source_root,
        container_source_root=container_source_root,
        compose_prefix=("docker", "compose"),
        channel="dev",
        revision=REVISION,
        child_runner=runner,
        container_absence=lambda name: fenced.append(("before", name)),
        container_cleanup=lambda name, _owner: fenced.append(("after", name)),
    )
    assert receipt == final
    assert [call[2] for call in calls] == [
        diagnostics.MAX_RECEIPT_BYTES,
        1024,
        1024,
        diagnostics.MAX_PRIVATE_FRAME_BYTES,
        diagnostics.MAX_RECEIPT_BYTES,
        diagnostics.MAX_RECEIPT_BYTES,
    ]
    assert [phase for phase, _name in fenced] == [
        "before", "after", "before", "after", "before", "after",
    ]
    assert "WATCHER_SCOPE_GLOB=accepted/**/*.md" in source_prepare
    assert f"target={container_source_root}" in next(
        item for item in source_prepare if item.startswith("type=bind,")
    )
    assert source_prepare[-1] == container_source_root


def test_cleanup_never_removes_a_container_with_foreign_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def status(
        argv: tuple[str, ...],
        *,
        input_bytes: bytes,
        max_output_bytes: int,
        timeout_seconds: float,
    ) -> tuple[int, bytes]:
        del input_bytes, max_output_bytes, timeout_seconds
        calls.append(argv)
        return 0, b"a" * 64 + b"\t" + b"0" * 32

    monkeypatch.setattr(diagnostics, "_run_bounded_status", status)
    with pytest.raises(diagnostics.SourceIdentityDiagnosticRefusal):
        diagnostics._cleanup_owned_container(  # noqa: SLF001
            f"pkm-source-id-witness-{REVISION[:12]}",
            "f" * 32,
        )
    assert len(calls) == 1
    assert calls[0][2] == "inspect"


def test_cleanup_removes_captured_id_and_never_foreign_name_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = "f" * 32
    owned_id = "a" * 64
    foreign_id = "b" * 64
    calls: list[tuple[str, ...]] = []
    responses = iter((
        (0, f"{owned_id}\t{owner}".encode("ascii")),
        (0, b""),
        (0, f"{foreign_id}\t{'0' * 32}".encode("ascii")),
    ))

    def status(
        argv: tuple[str, ...],
        *,
        input_bytes: bytes,
        max_output_bytes: int,
        timeout_seconds: float,
    ) -> tuple[int, bytes]:
        del input_bytes, max_output_bytes, timeout_seconds
        calls.append(argv)
        return next(responses)

    monkeypatch.setattr(diagnostics, "_run_bounded_status", status)
    with pytest.raises(diagnostics.SourceIdentityDiagnosticRefusal):
        diagnostics._cleanup_owned_container(  # noqa: SLF001
            f"pkm-source-id-witness-{REVISION[:12]}", owner,
        )
    assert calls[1] == (
        "docker", "container", "rm", "--force", owned_id,
    )
    assert foreign_id not in calls[1]


def test_public_receipt_rejects_incoherent_registry_partitions() -> None:
    payload = {
        "contract": diagnostics.SOURCE_RECEIPT_CONTRACT,
        "channel": "dev",
        "revision": REVISION,
        "terminal_state": "observed",
        "reason": None,
        "registry_selected_count": 999,
        "registry_persisted_count": 0,
        "registry_missing_count": 0,
        "registry_invalid_count": 1,
        "registry_ambiguous_count": 0,
        "authority_candidate_count": 1,
        "protected_authority_candidate_count": 0,
        "source_observation_unknown_count": 0,
        "selected_count": 1,
        "product_filesystem_complete_count": 1,
        "product_absent_count": 0,
        "product_conflict_count": 0,
        "locator_or_body_mismatch_count": 0,
        "duplicate_or_foreign_claim_count": 0,
    }
    with pytest.raises(diagnostics.SourceIdentityDiagnosticRefusal):
        diagnostics.validate_source_receipt(payload)


def test_bounded_child_timeout_starts_before_stdin_is_consumed() -> None:
    started = time.monotonic()
    with pytest.raises(diagnostics.SourceIdentityDiagnosticRefusal):
        diagnostics._run_bounded_child(  # noqa: SLF001 - adversarial subprocess seam
            (sys.executable, "-c", "import time; time.sleep(5)"),
            input_bytes=b"x" * diagnostics.MAX_PRIVATE_FRAME_BYTES,
            max_output_bytes=1024,
            timeout_seconds=0.1,
        )
    assert time.monotonic() - started < 2.0


def test_worker_main_coordinate_calls_concrete_production_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_image = "sha256:" + "e" * 64
    captured: dict[str, Any] = {}
    receipt = {
        "contract": diagnostics.SOURCE_RECEIPT_CONTRACT,
        "channel": "dev",
        "revision": REVISION,
        "terminal_state": "observed",
        "reason": None,
        "registry_selected_count": 1,
        "registry_persisted_count": 0,
        "registry_missing_count": 0,
        "registry_invalid_count": 1,
        "registry_ambiguous_count": 0,
        "authority_candidate_count": 1,
        "protected_authority_candidate_count": 0,
        "source_observation_unknown_count": 0,
        "selected_count": 1,
        "product_filesystem_complete_count": 0,
        "product_absent_count": 1,
        "product_conflict_count": 0,
        "locator_or_body_mismatch_count": 0,
        "duplicate_or_foreign_claim_count": 0,
    }

    def run(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return receipt

    monkeypatch.setattr(diagnostics, "run_production_diagnostic", run)
    assert diagnostics.worker_main([
        "coordinate", "dev", REVISION, source_image, str(tmp_path),
        "/accepted-vault",
    ]) == 0
    assert captured == {
        "source_image": source_image,
        "source_root": tmp_path,
        "container_source_root": "/accepted-vault",
        "compose_prefix": (
            "docker", "compose", "--profile", "native-source-diagnostics",
        ),
        "channel": "dev",
        "revision": REVISION,
    }
    assert json.loads(capsys.readouterr().out) == receipt


def test_database_witness_refuses_unreachable_or_nonreadonly_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(("/private/source", hashlib.sha256(b"body").hexdigest()))
    monkeypatch.setenv("PGOPTIONS", "-c default_transaction_read_only=on")

    for factory in (
        lambda: (_ for _ in ()).throw(RuntimeError("private")),
        lambda: FakeConnection(read_only="off"),
    ):
        receipt = diagnostics.run_database_witness(
            request,
            channel="dev",
            revision=REVISION,
            connection_factory=factory,
            dependencies=_dependencies(),
        )
        assert receipt == {
            "contract": diagnostics.RECEIPT_CONTRACT,
            "channel": "dev",
            "revision": REVISION,
            "terminal_state": "refused",
            "reason": "database_witness_refused",
            **{field: 0 for field in diagnostics.COUNT_FIELDS},
        }

    monkeypatch.setenv("PGOPTIONS", "-c statement_timeout=1000")
    assert diagnostics.run_database_witness(
        request,
        channel="dev",
        revision=REVISION,
        connection_factory=lambda: FakeConnection(),
        dependencies=_dependencies(),
    )["terminal_state"] == "refused"

    malformed = {**request, "unexpected": "private"}
    assert diagnostics.run_database_witness(
        malformed,
        channel="dev",
        revision=REVISION,
        connection_factory=lambda: FakeConnection(),
        dependencies=_dependencies(),
    )["terminal_state"] == "refused"

    with pytest.raises(diagnostics.SourceIdentityDiagnosticRefusal):
        diagnostics.validate_receipt({
            "contract": diagnostics.RECEIPT_CONTRACT,
            "channel": "dev",
            "revision": REVISION,
            "terminal_state": "refused",
            "reason": "database_witness_refused",
            **{field: 0 for field in diagnostics.COUNT_FIELDS},
            "unexpected": 1,
        })
