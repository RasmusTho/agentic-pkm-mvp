from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from typing import Any

import pytest
from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_root
from app.builderops import builder_threads as builder_thread_module
from app.builderops.builder_threads import (
    BuilderThreadError,
    BuilderThreadConflictError,
    BuilderThreadPrivacyError,
    BuilderThreadService as ProductionBuilderThreadService,
    BuilderThreadValidationError,
)
from app.builderops.vault_queue import init_vault


VAULT_ID = "11111111-1111-4111-8111-111111111111"
OTHER_VAULT_ID = "22222222-2222-4222-8222-222222222222"
ACTOR = "agent:codex:test"
RECIPIENT = "agent:claude:test"
SOURCE_REFS = [{"type": "github_issue", "value": "4702"}]


class BuilderThreadService(ProductionBuilderThreadService):
    """Test client that retains a fresh request identity before each API call."""

    def create_thread(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("entry_id", str(uuid.uuid4()))
        return super().create_thread(**kwargs)

    def reply(self, thread_id: str, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("entry_id", str(uuid.uuid4()))
        return super().reply(thread_id, **kwargs)


def _service(tmp_path: Path) -> tuple[BuilderThreadService, Path]:
    vault = tmp_path / "builderops-vault"
    init_vault(vault)
    service = BuilderThreadService.initialize(vault, vault_id=VAULT_ID, adopt_existing=True)
    return service, vault


def _env(tmp_path: Path, vault: Path) -> dict[str, str]:
    return {
        "BUILDEROPS_VAULT_ROOT": str(vault),
        "BUILDEROPS_VAULT_ID": VAULT_ID,
        "BUILDEROPS_DB_PATH": str(tmp_path / "local" / "builderops.sqlite3"),
    }


def _run(args: list[str], env: dict[str, str]):
    return CliRunner().invoke(
        builderops_root,
        ["builderops", *args],
        env=env,
        catch_exceptions=False,
    )


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _entry_files(vault: Path, thread_id: str) -> list[Path]:
    return sorted(
        (vault / "builder-threads" / "threads" / thread_id / "entries").glob(
            "[0-9][0-9][0-9]/*.json"
        )
    )


def _vault_snapshot(vault: Path) -> dict[str, tuple[int, int, bytes | None]]:
    return {
        path.relative_to(vault).as_posix(): (
            path.lstat().st_mode,
            path.lstat().st_mtime_ns,
            path.read_bytes() if path.is_file() else None,
        )
        for path in sorted(vault.rglob("*"))
    }


def test_root_and_genesis_validation_fail_closed(tmp_path: Path) -> None:
    service, vault = _service(tmp_path)

    assert service.health()["ok"] is True
    genesis = vault / "builder-threads" / "genesis.json"
    before = (genesis.stat().st_mtime_ns, genesis.read_bytes())
    BuilderThreadService.initialize(vault, vault_id=VAULT_ID)
    assert (genesis.stat().st_mtime_ns, genesis.read_bytes()) == before
    with pytest.raises(BuilderThreadValidationError, match="vault identity"):
        BuilderThreadService(vault, expected_vault_id=OTHER_VAULT_ID).health()

    unattested = tmp_path / "unattested-builderops"
    init_vault(unattested)
    (unattested / "operator-note.md").write_text("human material\n", encoding="utf-8")
    with pytest.raises(BuilderThreadValidationError, match="unattested"):
        BuilderThreadService.initialize(unattested, vault_id=VAULT_ID)
    assert not (unattested / ".builderops" / "vault-genesis.json").exists()

    symlink = tmp_path / "vault-link"
    symlink.symlink_to(vault, target_is_directory=True)
    with pytest.raises(BuilderThreadValidationError, match="symlink"):
        BuilderThreadService(symlink, expected_vault_id=VAULT_ID).health()

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    nested_vault = real_parent / "vault"
    init_vault(nested_vault)
    BuilderThreadService.initialize(nested_vault, vault_id=OTHER_VAULT_ID, adopt_existing=True)
    parent_alias = tmp_path / "parent-alias"
    parent_alias.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(BuilderThreadValidationError, match="ancestor"):
        BuilderThreadService(parent_alias / "vault", expected_vault_id=OTHER_VAULT_ID).health()

    uninitialized = tmp_path / "uninitialized"
    uninitialized.mkdir()
    with pytest.raises(BuilderThreadValidationError, match="scaffold"):
        BuilderThreadService.initialize(uninitialized, vault_id=VAULT_ID)

    rogue = tmp_path / "rogue-builderops-vault"
    init_vault(rogue)
    rogue_threads = rogue / "builder-threads"
    rogue_threads.mkdir()
    (rogue_threads / "foreign.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(BuilderThreadValidationError, match="pre-genesis"):
        BuilderThreadService.initialize(rogue, vault_id=VAULT_ID, adopt_existing=True)
    assert not (rogue_threads / "genesis.json").exists()

    mimer = tmp_path / "mimer-vault"
    init_vault(mimer)
    (mimer / "_heimdal").mkdir()
    with pytest.raises(BuilderThreadValidationError, match="Mimer"):
        BuilderThreadService.initialize(mimer, vault_id=VAULT_ID)

    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".git").mkdir()
    (repository / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    fixture = repository / "ops" / "shared-builder"
    fixture.parent.mkdir(parents=True)
    init_vault(fixture)
    with pytest.raises(BuilderThreadValidationError, match="repository-nested"):
        BuilderThreadService.initialize(fixture, vault_id=VAULT_ID)


@pytest.mark.parametrize("genesis_state", ("root_only", "subsystem_only", "mismatch"))
def test_genesis_pair_refusal_is_non_mutating(tmp_path: Path, genesis_state: str) -> None:
    service, vault = _service(tmp_path)
    root_genesis = vault / ".builderops" / "vault-genesis.json"
    subsystem_genesis = vault / "builder-threads" / "genesis.json"
    if genesis_state == "root_only":
        subsystem_genesis.unlink()
    elif genesis_state == "subsystem_only":
        root_genesis.unlink()
    else:
        payload = json.loads(subsystem_genesis.read_bytes())
        payload["created_at"] = "2026-08-09T11:59:59Z"
        subsystem_genesis.write_bytes(_canonical_bytes(payload))
    before = _vault_snapshot(vault)

    with pytest.raises(BuilderThreadConflictError):
        BuilderThreadService.initialize(
            vault,
            vault_id=service.expected_vault_id,
            adopt_existing=True,
        )

    assert _vault_snapshot(vault) == before


@pytest.mark.parametrize("identity_state", ("wrong_pin", "mismatched_pair"))
def test_wrong_identity_never_cleans_committed_temp_twins(
    tmp_path: Path, identity_state: str
) -> None:
    service, vault = _service(tmp_path)
    opened = service.create_thread(
        recipient_id=RECIPIENT,
        subject=f"Preserve temp before {identity_state}",
        content="Must identity validation precede every recovery mutation?",
        actor_id=ACTOR,
        source_refs=SOURCE_REFS,
    )
    final = _entry_files(vault, opened["thread_id"])[0]
    temp = final.with_name(f".tmp-{final.stem}-{'a' * 32}")
    os.link(final, temp)
    expected_vault_id = VAULT_ID
    if identity_state == "wrong_pin":
        expected_vault_id = OTHER_VAULT_ID
    else:
        subsystem_genesis = vault / "builder-threads" / "genesis.json"
        payload = json.loads(subsystem_genesis.read_bytes())
        payload["created_at"] = "2026-08-09T11:59:59Z"
        subsystem_genesis.write_bytes(_canonical_bytes(payload))
    before = _vault_snapshot(vault)

    with pytest.raises(BuilderThreadError):
        ProductionBuilderThreadService(
            vault, expected_vault_id=expected_vault_id
        ).create_thread(
            recipient_id=RECIPIENT,
            subject="This write must not begin",
            content="The temp twin is immutable evidence until genesis is trusted.",
            actor_id=ACTOR,
            source_refs=SOURCE_REFS,
            entry_id="10101010-1010-4010-8010-101010101010",
        )

    assert temp.exists()
    assert _vault_snapshot(vault) == before


def test_preexisting_empty_thread_destination_is_untouched(
    tmp_path: Path,
) -> None:
    service, vault = _service(tmp_path)
    subject = "Refuse an existing empty destination"
    capture_key = builder_thread_module._capture_key(RECIPIENT, SOURCE_REFS, subject)
    thread_id = builder_thread_module._capture_thread_id(VAULT_ID, capture_key)
    destination = vault / "builder-threads" / "threads" / thread_id
    destination.mkdir()
    before = (destination.stat().st_ino, destination.stat().st_mtime_ns)

    with pytest.raises(BuilderThreadConflictError, match="destination already exists"):
        service.create_thread(
            recipient_id=RECIPIENT,
            subject=subject,
            content="A foreign empty destination must remain byte-for-byte untouched.",
            actor_id=ACTOR,
            source_refs=SOURCE_REFS,
        )

    assert list(destination.iterdir()) == []
    assert (destination.stat().st_ino, destination.stat().st_mtime_ns) == before


def test_validator_rejects_unknown_partial_conflict_and_sqlite_artifacts(
    tmp_path: Path,
) -> None:
    service, vault = _service(tmp_path)
    root = vault / "builder-threads"

    (root / "unknown.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(BuilderThreadValidationError, match="unknown artifact"):
        service.health()
    (root / "unknown.txt").unlink()

    partial = root / "threads" / ".tmp-incomplete"
    partial.write_text("partial", encoding="utf-8")
    with pytest.raises(BuilderThreadValidationError, match="incomplete artifact"):
        service.health()
    partial.unlink()

    conflict = root / "genesis (Mac mini conflicted copy 2026-08-09).json"
    conflict.write_text("{}\n", encoding="utf-8")
    with pytest.raises(BuilderThreadConflictError, match="conflict-copy"):
        service.health()
    conflict.unlink()

    opened = service.create_thread(
        recipient_id=RECIPIENT,
        subject="Validate synchronized bytes",
        content="Will the receiver reject a mismatched content-addressed filename?",
        actor_id=ACTOR,
        source_refs=SOURCE_REFS,
    )
    original = _entry_files(vault, opened["thread_id"])[0]
    mismatched = original.with_name(f"{'0' * 64}.json")
    original.rename(mismatched)
    with pytest.raises(BuilderThreadValidationError, match="artifact hash mismatch"):
        service.health()
    mismatched.rename(original)

    original_bytes = original.read_bytes()
    unknown_payload = json.loads(original_bytes)
    unknown_payload["unexpected"] = "field"
    unknown_bytes = _canonical_bytes(unknown_payload)
    unknown_path = original.with_name(f"{hashlib.sha256(unknown_bytes).hexdigest()}.json")
    original.unlink()
    unknown_path.write_bytes(unknown_bytes)
    with pytest.raises(BuilderThreadValidationError, match="unknown or missing"):
        service.health()
    unknown_path.unlink()
    original.write_bytes(original_bytes)

    entries_dir = original.parent.parent
    duplicate_slot = next(
        entries_dir / f"{index:03d}"
        for index in range(service.MAX_ENTRIES_PER_THREAD)
        if not (entries_dir / f"{index:03d}").exists()
    )
    duplicate_slot.mkdir()
    duplicate_path = duplicate_slot / original.name
    duplicate_path.write_bytes(original_bytes)
    with pytest.raises(BuilderThreadConflictError, match="duplicate entry_id"):
        service.health()
    duplicate_path.unlink()
    duplicate_slot.rmdir()

    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    linked = original.parent / f"{'f' * 64}.json"
    linked.symlink_to(outside)
    with pytest.raises(BuilderThreadValidationError, match="symlink"):
        service.health()
    linked.unlink()

    sqlite = vault / "unexpected.sqlite3"
    sqlite.write_bytes(b"SQLite format 3\x00" + b"\x00" * 512)
    with pytest.raises(BuilderThreadValidationError, match="SQLite"):
        service.health()


def test_malformed_field_types_and_hostile_filenames_fail_typed_and_redacted(
    tmp_path: Path,
) -> None:
    service, vault = _service(tmp_path)
    opened = service.create_thread(
        recipient_id=RECIPIENT,
        subject="Validate hostile envelope types",
        content="Does every malformed field fail through the typed boundary?",
        actor_id=ACTOR,
        source_refs=SOURCE_REFS,
    )
    original = _entry_files(vault, opened["thread_id"])[0]
    original_bytes = original.read_bytes()
    payload = json.loads(original_bytes)
    mutations: dict[str, Any] = {
        "actor_id": 7,
        "basis_hash": 7,
        "basis_hashes": {},
        "capture_key": 7,
        "content": [],
        "created_at": 7,
        "entry_id": 7,
        "entry_type": [],
        "parent_hash": 7,
        "privacy_class": 7,
        "reason_code": [],
        "recipient_id": 7,
        "reply_expected": "yes",
        "schema": 7,
        "source_refs": {},
        "subject": [],
        "target_hash": 7,
        "thread_id": 7,
        "vault_id": 7,
    }
    for field, malformed in mutations.items():
        changed = {**payload, field: malformed}
        changed_bytes = _canonical_bytes(changed)
        changed_path = original.with_name(f"{hashlib.sha256(changed_bytes).hexdigest()}.json")
        original.unlink()
        changed_path.write_bytes(changed_bytes)
        try:
            with pytest.raises(BuilderThreadError):
                service.health()
        finally:
            changed_path.unlink()
            original.write_bytes(original_bytes)

    hostile_value = "TOKEN=do-not-echo-this-value"
    hostile = vault / "builder-threads" / f"unknown-{hostile_value}"
    hostile.write_text("unsafe name\n", encoding="utf-8")
    with pytest.raises(BuilderThreadError) as raised:
        service.health()
    assert hostile_value not in str(raised.value)
    result = _run(["builder-inbox", "health", "--json"], _env(tmp_path, vault))
    assert result.exit_code != 0
    assert hostile_value not in result.output


def test_cli_round_trip_covers_complete_thread_surface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "builderops-vault"
    init_vault(vault)
    env = _env(tmp_path, vault)

    initialized = _run(["builder-thread", "init", "--adopt-existing", "--json"], env)
    assert initialized.exit_code == 0

    stamps = iter(
        (
            "2026-08-09T12:00:00Z",
            "2026-08-09T12:00:01Z",
            "2026-08-09T12:00:02Z",
            "2026-08-09T12:00:03Z",
            "2026-08-09T12:00:04Z",
            "2026-08-09T12:00:05Z",
            "2026-08-09T12:00:06Z",
            "2026-08-09T12:00:07Z",
        )
    )
    monkeypatch.setattr(builder_thread_module, "_stamp", lambda: next(stamps))
    create_args = [
        "builder-thread",
        "create",
        "--recipient",
        RECIPIENT,
        "--subject",
        "Choose the retry boundary",
        "--content",
        "Should the retry stop after the second typed refusal?",
        "--actor",
        ACTOR,
        "--entry-id",
        "66666666-6666-4666-8666-666666666666",
        "--source-ref",
        "github_issue:4702",
        "--json",
    ]
    created = _run(create_args, env)
    opened = json.loads(created.output)
    thread_id = opened["thread_id"]
    create_retry = _run(create_args, env)
    assert json.loads(create_retry.output)["entry_hash"] == opened["entry_hash"]

    reply_args = [
        "builder-thread",
        "reply",
        thread_id,
        "--recipient",
        ACTOR,
        "--content",
        "Yes; preserve the second refusal as evidence.",
        "--actor",
        RECIPIENT,
        "--parent-hash",
        opened["entry_hash"],
        "--reply-expected",
        "--entry-id",
        "77777777-7777-4777-8777-777777777777",
        "--source-ref",
        "github_issue:4702",
        "--json",
    ]
    replied = _run(reply_args, env)
    assert replied.exit_code == 0
    reply_payload = json.loads(replied.output)
    reply_retry = _run(reply_args, env)
    assert json.loads(reply_retry.output)["entry_hash"] == reply_payload["entry_hash"]

    read = _run(["builder-thread", "read", thread_id, "--json"], env)
    assert json.loads(read.output)["state"] == "answered"
    listed = _run(["builder-thread", "list", "--json"], env)
    assert json.loads(listed.output)["threads"][0]["thread_id"] == thread_id
    inbox = _run(["builder-inbox", "list", "--recipient", ACTOR, "--json"], env)
    assert json.loads(inbox.output)["threads"][0]["thread_id"] == thread_id

    closed = _run(
        [
            "builder-thread",
            "close",
            thread_id,
            "--actor",
            ACTOR,
            "--reason",
            "Resolved by the cited Issue decision.",
            "--json",
        ],
        env,
    )
    assert json.loads(closed.output)["state"] == "closed"
    archived = _run(
        ["builder-thread", "archive", thread_id, "--actor", ACTOR, "--json"],
        env,
    )
    assert json.loads(archived.output)["state"] == "archived"


def test_cli_json_failures_are_typed_bounded_and_retry_conflicts_do_not_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, vault = _service(tmp_path)
    env = _env(tmp_path, vault)
    args = [
        "builder-thread",
        "create",
        "--recipient",
        RECIPIENT,
        "--subject",
        "Durable caller request identity",
        "--content",
        "First request body.",
        "--actor",
        ACTOR,
        "--entry-id",
        "12121212-1212-4212-8212-121212121212",
        "--source-ref",
        "github_issue:4702",
        "--json",
    ]
    # The first successful result is deliberately treated as a lost acknowledgement.
    assert _run(args, env).exit_code == 0
    retry = _run(args, env)
    assert retry.exit_code == 0
    assert service.health()["artifact_count"] == 1

    missing_entry_id = _run(
        [
            item
            for item in args
            if item not in {"--entry-id", "12121212-1212-4212-8212-121212121212"}
        ],
        env,
    )
    assert missing_entry_id.exit_code == 1
    missing_entry_payload = json.loads(missing_entry_id.output)
    assert missing_entry_payload["ok"] is False
    assert missing_entry_payload["error"]["type"] == ("BuilderThreadValidationError")

    changed = args.copy()
    changed[changed.index("First request body.")] = "Changed replay body."
    failure = _run(changed, env)
    assert failure.exit_code == 1
    payload = json.loads(failure.output)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "BuilderThreadConflictError"
    assert len(payload["error"]["message"]) <= 240
    assert "Error:" not in failure.output
    assert service.health()["artifact_count"] == 1

    missing_root_env = {**env, "BUILDEROPS_VAULT_ROOT": ""}
    missing = _run(["builder-inbox", "health", "--json"], missing_root_env)
    assert missing.exit_code == 1
    assert json.loads(missing.output)["error"]["type"] == ("BuilderThreadValidationError")

    unknown = _run(["builder-thread", "does-not-exist", "--json"], env)
    assert unknown.exit_code == 1
    unknown_payload = json.loads(unknown.output)
    assert unknown_payload["ok"] is False
    assert unknown_payload["error"]["type"] == "BuilderThreadValidationError"
    assert "Error:" not in unknown.output

    private_marker = str(vault / "private-storage-detail")

    def fail_storage(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise OSError(f"injected failure at {private_marker}")

    monkeypatch.setattr(ProductionBuilderThreadService, "create_thread", fail_storage)
    storage_failure = _run(args, env)
    assert storage_failure.exit_code == 1
    storage_payload = json.loads(storage_failure.output)
    assert storage_payload == {
        "error": {
            "message": "Builder Thread storage operation failed",
            "type": "BuilderThreadStorageError",
        },
        "ok": False,
    }
    assert private_marker not in storage_failure.output
    assert "Traceback" not in storage_failure.output


def test_public_service_requires_request_identity_and_retries_exactly(
    tmp_path: Path,
) -> None:
    service, vault = _service(tmp_path)
    public = ProductionBuilderThreadService(vault, expected_vault_id=VAULT_ID)
    kwargs = {
        "recipient_id": RECIPIENT,
        "subject": "Require durable API request identity",
        "content": "Can a service caller safely reconcile a lost acknowledgement?",
        "actor_id": ACTOR,
        "source_refs": SOURCE_REFS,
    }
    with pytest.raises(BuilderThreadValidationError, match="caller-retained entry_id"):
        public.create_thread(**kwargs)
    entry_id = "14141414-1414-4414-8414-141414141414"
    opened = public.create_thread(**kwargs, entry_id=entry_id)
    exact = public.create_thread(**kwargs, entry_id=entry_id)
    assert exact["entry_hash"] == opened["entry_hash"]

    reply_kwargs = {
        "recipient_id": ACTOR,
        "content": "The API caller retained the request identity.",
        "actor_id": RECIPIENT,
        "parent_hash": opened["entry_hash"],
        "source_refs": SOURCE_REFS,
    }
    with pytest.raises(BuilderThreadValidationError, match="caller-retained entry_id"):
        public.reply(opened["thread_id"], **reply_kwargs)
    reply_id = "15151515-1515-4515-8515-151515151515"
    replied = public.reply(opened["thread_id"], **reply_kwargs, entry_id=reply_id)
    reply_retry = public.reply(opened["thread_id"], **reply_kwargs, entry_id=reply_id)
    assert reply_retry["entry_hash"] == replied["entry_hash"]
    assert public.health()["artifact_count"] == 2


def test_entry_id_is_unique_across_the_entire_vault(tmp_path: Path) -> None:
    service, vault = _service(tmp_path)
    entry_id = "16161616-1616-4616-8616-161616161616"
    first = service.create_thread(
        recipient_id=RECIPIENT,
        subject="First use of one request identity",
        content="This request identity belongs to exactly one contribution.",
        actor_id=ACTOR,
        source_refs=SOURCE_REFS,
        entry_id=entry_id,
    )
    with pytest.raises(BuilderThreadConflictError, match="entry_id replay conflict"):
        service.create_thread(
            recipient_id=RECIPIENT,
            subject="Changed semantics with the same request identity",
            content="This must not create a second represented thread.",
            actor_id=ACTOR,
            source_refs=SOURCE_REFS,
            entry_id=entry_id,
        )
    assert service.health()["thread_count"] == 1
    assert service.read_thread(first["thread_id"])["entry_count"] == 1

    second = service.create_thread(
        recipient_id=RECIPIENT,
        subject="A valid second request identity",
        content="The synchronized receiver must also enforce vault-wide uniqueness.",
        actor_id=ACTOR,
        source_refs=SOURCE_REFS,
    )
    second_path = _entry_files(vault, second["thread_id"])[0]
    second_payload = json.loads(second_path.read_bytes())
    second_payload["entry_id"] = entry_id
    duplicate_bytes = _canonical_bytes(second_payload)
    duplicate_path = second_path.with_name(
        f"{hashlib.sha256(duplicate_bytes).hexdigest()}.json"
    )
    second_path.unlink()
    duplicate_path.write_bytes(duplicate_bytes)
    with pytest.raises(BuilderThreadConflictError, match="duplicate entry_id across vault"):
        service.health()


def test_quarantine_preserves_bytes_and_redacts_unsafe_artifact(
    tmp_path: Path,
) -> None:
    service, vault = _service(tmp_path)
    opened = service.create_thread(
        recipient_id=RECIPIENT,
        subject="Check a bounded incident",
        content="Can the receiver quarantine an unsafe synchronized contribution?",
        actor_id=ACTOR,
        source_refs=SOURCE_REFS,
    )
    thread_id = opened["thread_id"]
    unsafe_payload = {
        **opened["entry"],
        "entry_id": "33333333-3333-4333-8333-333333333333",
        "entry_type": "reply",
        "actor_id": RECIPIENT,
        "recipient_id": ACTOR,
        "subject": None,
        "content": "Authorization: Bearer definitely-not-safe",
        "parent_hash": opened["entry_hash"],
        "capture_key": None,
    }
    unsafe_bytes = _canonical_bytes(unsafe_payload)
    unsafe_hash = hashlib.sha256(unsafe_bytes).hexdigest()
    entries_dir = vault / "builder-threads" / "threads" / thread_id / "entries"
    unsafe_slot = next(
        entries_dir / f"{index:03d}"
        for index in range(service.MAX_ENTRIES_PER_THREAD)
        if not (entries_dir / f"{index:03d}").exists()
    )
    unsafe_slot.mkdir()
    unsafe_path = unsafe_slot / f"{unsafe_hash}.json"
    unsafe_path.write_bytes(unsafe_bytes)

    with pytest.raises(BuilderThreadPrivacyError):
        service.read_thread(thread_id)
    before = unsafe_path.read_bytes()
    disposition = service.quarantine(
        thread_id,
        artifact_hash=unsafe_hash,
        actor_id=ACTOR,
        reason_code="credential_like_content",
    )

    assert unsafe_path.read_bytes() == before
    assert disposition["state"] == "quarantined"
    rendered = json.dumps(service.read_thread(thread_id), sort_keys=True)
    assert "definitely-not-safe" not in rendered
    assert unsafe_hash in rendered
    with pytest.raises(BuilderThreadConflictError, match="quarantine retry"):
        service.quarantine(
            thread_id,
            artifact_hash=unsafe_hash,
            actor_id=ACTOR,
            reason_code="privacy_misclassification",
        )


@pytest.mark.parametrize("unsafe_surface", ("privacy_and_source", "actor"))
def test_structural_quarantine_recovers_privacy_unsafe_identity_and_refs(
    tmp_path: Path, unsafe_surface: str
) -> None:
    service, vault = _service(tmp_path)
    opened = service.create_thread(
        recipient_id=RECIPIENT,
        subject=f"Quarantine unsafe {unsafe_surface}",
        content="Can structural recovery avoid rendering private synchronized fields?",
        actor_id=ACTOR,
        source_refs=SOURCE_REFS,
    )
    if unsafe_surface == "privacy_and_source":
        contribution = service.reply(
            opened["thread_id"],
            recipient_id=ACTOR,
            content="A contribution with unsafe structural metadata.",
            actor_id=RECIPIENT,
            parent_hash=opened["entry_hash"],
            source_refs=SOURCE_REFS,
        )
        secret_marker = "github_pat_abcdefghijklmnop"
        mutations: dict[str, Any] = {
            "privacy_class": "private",
            "source_refs": [{"type": "builderops_record", "value": secret_marker}],
        }
    else:
        contribution = service.close_thread(
            opened["thread_id"], actor_id=ACTOR, reason="Unsafe actor probe"
        )
        secret_marker = "github_pat_qrstuvwxyzabcd"
        mutations = {"actor_id": f"agent:{secret_marker}"}

    original_path = next(
        path
        for path in _entry_files(vault, opened["thread_id"])
        if path.stem == contribution["entry_hash"]
    )
    payload = json.loads(original_path.read_bytes())
    unsafe_bytes = _canonical_bytes({**payload, **mutations})
    unsafe_hash = hashlib.sha256(unsafe_bytes).hexdigest()
    unsafe_path = original_path.with_name(f"{unsafe_hash}.json")
    original_path.unlink()
    unsafe_path.write_bytes(unsafe_bytes)

    with pytest.raises(BuilderThreadPrivacyError):
        service.read_thread(opened["thread_id"])
    before = unsafe_path.read_bytes()
    recovered = service.quarantine(
        opened["thread_id"],
        artifact_hash=unsafe_hash,
        actor_id=ACTOR,
        reason_code="privacy_misclassification",
    )

    assert unsafe_path.read_bytes() == before
    assert recovered["quarantined_count"] == 1
    rendered = json.dumps(recovered, sort_keys=True)
    assert secret_marker not in rendered
    assert "docs/builderops/BUILDEROPS_VAULT_STORE.md" in rendered
    assert service.health()["ok"] is True


def test_structural_quarantine_redacts_unsafe_open_source_ref(
    tmp_path: Path,
) -> None:
    service, vault = _service(tmp_path)
    opened = service.create_thread(
        recipient_id=RECIPIENT,
        subject="Quarantine an unsafe open source",
        content="Can the root contribution be redacted without leaking its unsafe ref?",
        actor_id=ACTOR,
        source_refs=SOURCE_REFS,
    )
    old_thread_dir = vault / "builder-threads" / "threads" / opened["thread_id"]
    old_path = _entry_files(vault, opened["thread_id"])[0]
    payload = json.loads(old_path.read_bytes())
    secret_marker = "github_pat_openabcdefghijkl"
    unsafe_refs = [{"type": "builderops_record", "value": secret_marker}]
    capture_key = builder_thread_module._capture_key(RECIPIENT, unsafe_refs, payload["subject"])
    thread_id = builder_thread_module._capture_thread_id(VAULT_ID, capture_key)
    payload.update(
        {
            "capture_key": capture_key,
            "source_refs": unsafe_refs,
            "thread_id": thread_id,
        }
    )
    unsafe_bytes = _canonical_bytes(payload)
    unsafe_hash = hashlib.sha256(unsafe_bytes).hexdigest()
    slot_name = old_path.parent.name
    old_path.unlink()
    new_thread_dir = old_thread_dir.with_name(thread_id)
    old_thread_dir.rename(new_thread_dir)
    unsafe_path = new_thread_dir / "entries" / slot_name / f"{unsafe_hash}.json"
    unsafe_path.write_bytes(unsafe_bytes)

    with pytest.raises(BuilderThreadPrivacyError):
        service.read_thread(thread_id)
    before = unsafe_path.read_bytes()
    recovered = service.quarantine(
        thread_id,
        artifact_hash=unsafe_hash,
        actor_id=ACTOR,
        reason_code="credential_like_content",
    )

    assert unsafe_path.read_bytes() == before
    rendered = json.dumps(recovered, sort_keys=True)
    assert secret_marker not in rendered
    assert recovered["subject"] == "[quarantined]"
    assert recovered["source_refs"] == service.INCIDENT_SOURCE_REFS
    assert service.health()["ok"] is True


def test_concurrent_writers_and_replay_conflicts_converge_fail_closed(
    tmp_path: Path,
) -> None:
    service, _vault = _service(tmp_path)
    opened = service.create_thread(
        recipient_id=RECIPIENT,
        subject="Converge independent replies",
        content="Can two devices reply without a mutable sequence?",
        actor_id=ACTOR,
        source_refs=SOURCE_REFS,
    )

    def reply(index: int) -> dict[str, Any]:
        return BuilderThreadService(
            service.root,
            expected_vault_id=VAULT_ID,
        ).reply(
            opened["thread_id"],
            recipient_id=ACTOR,
            content=f"Independent reply {index}",
            actor_id=RECIPIENT,
            parent_hash=opened["entry_hash"],
            source_refs=SOURCE_REFS,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reply, (1, 2)))
    assert len({item["entry_hash"] for item in results}) == 2
    assert service.read_thread(opened["thread_id"])["state"] == "answered"

    replay_id = "44444444-4444-4444-8444-444444444444"
    first = service.reply(
        opened["thread_id"],
        recipient_id=ACTOR,
        content="Exact replay body",
        actor_id=RECIPIENT,
        parent_hash=opened["entry_hash"],
        source_refs=SOURCE_REFS,
        entry_id=replay_id,
    )
    exact = service.reply(
        opened["thread_id"],
        recipient_id=ACTOR,
        content="Exact replay body",
        actor_id=RECIPIENT,
        parent_hash=opened["entry_hash"],
        source_refs=SOURCE_REFS,
        entry_id=replay_id,
        created_at=first["entry"]["created_at"],
    )
    assert exact["entry_hash"] == first["entry_hash"]
    with pytest.raises(BuilderThreadConflictError, match="entry_id replay"):
        service.reply(
            opened["thread_id"],
            recipient_id=ACTOR,
            content="Different replay body",
            actor_id=RECIPIENT,
            parent_hash=opened["entry_hash"],
            source_refs=SOURCE_REFS,
            entry_id=replay_id,
            created_at=first["entry"]["created_at"],
        )


def test_cross_process_identical_capture_converges_on_one_thread(
    tmp_path: Path,
) -> None:
    service, vault = _service(tmp_path)
    env = {**os.environ, **_env(tmp_path, vault)}

    def create_process(index: int) -> subprocess.CompletedProcess[str]:
        entry_id = f"99999999-9999-4999-8999-{index:012d}"
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "app.builderops",
                "builderops",
                "builder-thread",
                "create",
                "--recipient",
                RECIPIENT,
                "--subject",
                "One cross-process capture",
                "--content",
                "Can independent client processes converge on one represented question?",
                "--actor",
                ACTOR,
                "--entry-id",
                entry_id,
                "--source-ref",
                "github_issue:4702",
                "--json",
            ],
            cwd=Path(__file__).parents[2],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(create_process, range(1, 5)))
    assert [item.returncode for item in results].count(0) == 1
    assert service.health()["thread_count"] == 1


def test_concurrent_exact_entry_retry_reserves_one_physical_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, vault = _service(tmp_path)
    opened = service.create_thread(
        recipient_id=RECIPIENT,
        subject="Converge one caller request identity",
        content="Can concurrent exact retries install exactly one envelope?",
        actor_id=ACTOR,
        source_refs=SOURCE_REFS,
    )
    barrier = Barrier(2)
    real_reserve = BuilderThreadService._reserve_entry_slot

    def synchronized_reserve(
        current: BuilderThreadService, entries_dir: Path, entry_id: str
    ) -> Path:
        barrier.wait(timeout=2)
        return real_reserve(current, entries_dir, entry_id)

    monkeypatch.setattr(BuilderThreadService, "_reserve_entry_slot", synchronized_reserve)
    kwargs = {
        "thread_id": opened["thread_id"],
        "recipient_id": ACTOR,
        "content": "One exact concurrent retry.",
        "actor_id": RECIPIENT,
        "parent_hash": opened["entry_hash"],
        "source_refs": SOURCE_REFS,
        "entry_id": "13131313-1313-4313-8313-131313131313",
        "created_at": "2026-08-09T12:02:00Z",
    }

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _index: BuilderThreadService(service.root, expected_vault_id=VAULT_ID).reply(
                    **kwargs
                ),
                (1, 2),
            )
        )

    assert len({item["entry_hash"] for item in results}) == 1
    assert len(_entry_files(vault, opened["thread_id"])) == 2
    assert service.health()["artifact_count"] == 2


def test_initial_thread_tree_is_atomically_visible_to_readers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _vault = _service(tmp_path)
    entered_publish = Event()
    release_publish = Event()
    real_publish = builder_thread_module._atomic_publish

    def paused_publish(path: Path, data: bytes) -> bool:
        payload = json.loads(data)
        if payload.get("entry_type") == "open":
            entered_publish.set()
            assert release_publish.wait(timeout=2)
        return real_publish(path, data)

    monkeypatch.setattr(builder_thread_module, "_atomic_publish", paused_publish)
    with ThreadPoolExecutor(max_workers=2) as pool:
        create_future = pool.submit(
            service.create_thread,
            recipient_id=RECIPIENT,
            subject="Atomic initial tree",
            content="Can a reader observe an incomplete final thread directory?",
            actor_id=ACTOR,
            source_refs=SOURCE_REFS,
        )
        assert entered_publish.wait(timeout=2)
        health_future = pool.submit(service.health)
        release_publish.set()
        assert create_future.result(timeout=2)["state"] == "open"
        assert health_future.result(timeout=2)["ok"] is True


def test_stale_dispositions_can_be_superseded_and_retries_conflict(
    tmp_path: Path,
) -> None:
    service, _vault = _service(tmp_path)
    opened = service.create_thread(
        recipient_id=RECIPIENT,
        subject="Supersede stale dispositions",
        content="Can a late contribution be included in a new disposition?",
        actor_id=ACTOR,
        source_refs=SOURCE_REFS,
    )
    service.close_thread(opened["thread_id"], actor_id=ACTOR, reason="Initial disposition")
    with pytest.raises(BuilderThreadConflictError, match="close retry"):
        service.close_thread(opened["thread_id"], actor_id=ACTOR, reason="Changed disposition")
    service.archive_thread(opened["thread_id"], actor_id=ACTOR)
    with pytest.raises(BuilderThreadConflictError, match="archive retry"):
        service.archive_thread(opened["thread_id"], actor_id=RECIPIENT)

    service.reply(
        opened["thread_id"],
        recipient_id=ACTOR,
        content="Late but valid reply",
        actor_id=RECIPIENT,
        parent_hash=opened["entry_hash"],
        source_refs=SOURCE_REFS,
    )
    assert service.read_thread(opened["thread_id"])["state"] == "needs_review"
    service.close_thread(opened["thread_id"], actor_id=ACTOR, reason="Updated disposition")
    archived = service.archive_thread(opened["thread_id"], actor_id=ACTOR)
    assert archived["state"] == "archived"
    assert service.health()["ok"] is True


def test_receiver_recomputes_capture_key_and_rejects_non_active_archive_target(
    tmp_path: Path,
) -> None:
    service, vault = _service(tmp_path)
    opened = service.create_thread(
        recipient_id=RECIPIENT,
        subject="Validate synchronized semantic lineage",
        content="Does the receiver derive identities rather than trust stored claims?",
        actor_id=ACTOR,
        source_refs=SOURCE_REFS,
    )
    open_path = next(
        path
        for path in _entry_files(vault, opened["thread_id"])
        if path.stem == opened["entry_hash"]
    )
    open_bytes = open_path.read_bytes()
    forged_open = json.loads(open_bytes)
    forged_open["capture_key"] = "0" * 64
    forged_open_bytes = _canonical_bytes(forged_open)
    forged_open_path = open_path.with_name(f"{hashlib.sha256(forged_open_bytes).hexdigest()}.json")
    open_path.unlink()
    forged_open_path.write_bytes(forged_open_bytes)
    with pytest.raises(BuilderThreadConflictError, match="capture key"):
        service.health()
    forged_open_path.unlink()
    open_path.write_bytes(open_bytes)

    first_close = service.close_thread(opened["thread_id"], actor_id=ACTOR, reason="First close")
    service.archive_thread(opened["thread_id"], actor_id=ACTOR)
    service.reply(
        opened["thread_id"],
        recipient_id=ACTOR,
        content="Late answer requires a fresh disposition.",
        actor_id=RECIPIENT,
        parent_hash=opened["entry_hash"],
        source_refs=SOURCE_REFS,
    )
    service.close_thread(opened["thread_id"], actor_id=ACTOR, reason="Superseding close")
    latest_archive = service.archive_thread(opened["thread_id"], actor_id=ACTOR)
    archive_path = next(
        path
        for path in _entry_files(vault, opened["thread_id"])
        if path.stem == latest_archive["entry_hash"]
    )
    archive_payload = json.loads(archive_path.read_bytes())
    archive_payload["target_hash"] = first_close["entry_hash"]
    forged_archive_bytes = _canonical_bytes(archive_payload)
    forged_archive_path = archive_path.with_name(
        f"{hashlib.sha256(forged_archive_bytes).hexdigest()}.json"
    )
    archive_path.unlink()
    forged_archive_path.write_bytes(forged_archive_bytes)
    with pytest.raises(BuilderThreadValidationError, match="active close"):
        service.health()


def test_concurrent_disposition_conflict_can_be_explicitly_quarantined(
    tmp_path: Path,
) -> None:
    service, vault = _service(tmp_path)
    opened = service.create_thread(
        recipient_id=RECIPIENT,
        subject="Recover a concurrent disposition conflict",
        content="Can one exact conflicting close be quarantined without deletion?",
        actor_id=ACTOR,
        source_refs=SOURCE_REFS,
    )
    publish_barrier = Barrier(2)

    class SynchronizedCloseClient(BuilderThreadService):
        def __init__(self, root: Path, *, expected_vault_id: str):
            super().__init__(root, expected_vault_id=expected_vault_id)
            self._loads = 0

        def _load_thread(
            self, thread_id: str, *, structural_only: bool = False
        ) -> dict[str, Any]:
            loaded = super()._load_thread(thread_id, structural_only=structural_only)
            self._loads += 1
            if self._loads == 2:
                publish_barrier.wait(timeout=2)
            return loaded

    def close(reason: str) -> Exception | None:
        try:
            SynchronizedCloseClient(service.root, expected_vault_id=VAULT_ID).close_thread(
                opened["thread_id"], actor_id=ACTOR, reason=reason
            )
        except BuilderThreadError as exc:
            return exc
        return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(close, ("Concurrent A", "Concurrent B")))
    assert all(item is None or isinstance(item, BuilderThreadConflictError) for item in outcomes)

    with pytest.raises(BuilderThreadConflictError, match="multiple active close"):
        service.health()

    close_hashes = [
        path.stem
        for path in _entry_files(vault, opened["thread_id"])
        if json.loads(path.read_bytes())["entry_type"] == "close"
    ]
    assert len(close_hashes) == 2
    recovered = service.quarantine(
        opened["thread_id"],
        artifact_hash=close_hashes[0],
        actor_id=ACTOR,
        reason_code="concurrent_conflict",
    )
    assert recovered["state"] == "closed"
    assert service.health()["ok"] is True


def test_atomic_publication_uses_fsynced_temp_and_no_overwrite_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _vault = _service(tmp_path)
    calls = {"fsync": 0, "link": 0}
    real_fsync = os.fsync
    real_link = os.link

    def observed_fsync(fd: int) -> None:
        calls["fsync"] += 1
        real_fsync(fd)

    def observed_link(src: Path | str, dst: Path | str) -> None:
        calls["link"] += 1
        real_link(src, dst)

    monkeypatch.setattr("app.builderops.builder_threads.os.fsync", observed_fsync)
    monkeypatch.setattr("app.builderops.builder_threads.os.link", observed_link)
    service.create_thread(
        recipient_id=RECIPIENT,
        subject="Observe atomic publication",
        content="Does publication fsync before and after the no-overwrite link?",
        actor_id=ACTOR,
        source_refs=SOURCE_REFS,
    )

    assert calls["link"] >= 1
    assert calls["fsync"] >= 3
    assert not list(service.root.rglob(".tmp-*"))


def test_atomic_publication_reports_final_directory_sync_failure_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_dir = tmp_path / "atomic"
    target_dir.mkdir()
    target = target_dir / "artifact.json"
    data = b'{"value":"complete"}\n'
    calls = 0
    real_sync = builder_thread_module._fsync_directory

    def fail_cleanup_sync(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected final directory sync failure")
        real_sync(path)

    monkeypatch.setattr(builder_thread_module, "_fsync_directory", fail_cleanup_sync)
    with pytest.raises(OSError, match="final directory sync"):
        builder_thread_module._atomic_publish(target, data)
    assert target.read_bytes() == data

    monkeypatch.setattr(builder_thread_module, "_fsync_directory", real_sync)
    assert builder_thread_module._atomic_publish(target, data) is False
    assert not list(target_dir.glob(".tmp-*"))


def test_create_acknowledgement_loss_reconciles_on_exact_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _vault = _service(tmp_path)
    calls = 0
    real_load = service._load_thread

    def fail_first_post_publish_readback(
        thread_id: str, *, structural_only: bool = False
    ) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected post-publication acknowledgement loss")
        return real_load(thread_id, structural_only=structural_only)

    kwargs = {
        "recipient_id": RECIPIENT,
        "subject": "Reconcile acknowledgement loss",
        "content": "Did the complete initial tree survive the lost acknowledgement?",
        "actor_id": ACTOR,
        "source_refs": SOURCE_REFS,
        "entry_id": "55555555-5555-4555-8555-555555555555",
        "created_at": "2026-08-09T12:00:00Z",
    }
    monkeypatch.setattr(service, "_load_thread", fail_first_post_publish_readback)
    with pytest.raises(OSError, match="acknowledgement loss"):
        service.create_thread(**kwargs)

    monkeypatch.setattr(service, "_load_thread", real_load)
    exact = service.create_thread(**kwargs)
    assert exact["state"] == "open"
    assert service.health()["thread_count"] == 1


def test_temp_unlink_failure_is_recovered_by_exact_writer_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, vault = _service(tmp_path)
    opened = service.create_thread(
        recipient_id=RECIPIENT,
        subject="Recover committed temp cleanup",
        content="Can an exact retry clean a committed temporary hard-link twin?",
        actor_id=ACTOR,
        source_refs=SOURCE_REFS,
    )
    real_unlink = Path.unlink

    def fail_entry_temp_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        if path.parent.parent.name == "entries" and path.name.startswith(".tmp-"):
            raise OSError("injected temp unlink failure")
        real_unlink(path, *args, **kwargs)

    reply_kwargs = {
        "thread_id": opened["thread_id"],
        "recipient_id": ACTOR,
        "content": "The installed final should be reconciled.",
        "actor_id": RECIPIENT,
        "parent_hash": opened["entry_hash"],
        "source_refs": SOURCE_REFS,
        "entry_id": "88888888-8888-4888-8888-888888888888",
        "created_at": "2026-08-09T12:01:00Z",
    }
    monkeypatch.setattr(Path, "unlink", fail_entry_temp_unlink)
    with pytest.raises(OSError, match="temp unlink failure"):
        service.reply(**reply_kwargs)
    assert list(vault.rglob(".tmp-*"))

    monkeypatch.setattr(Path, "unlink", real_unlink)
    exact = service.reply(**{**reply_kwargs, "created_at": "2026-08-09T12:01:01Z"})
    assert exact["state"] == "answered"
    assert not list(vault.rglob(".tmp-*"))


def test_concurrent_quarantine_conflict_fails_closed_and_is_recoverable(
    tmp_path: Path,
) -> None:
    service, vault = _service(tmp_path)
    opened = service.create_thread(
        recipient_id=RECIPIENT,
        subject="Converge quarantine decisions",
        content="Can contradictory incident decisions remain visibly conflicted?",
        actor_id=ACTOR,
        source_refs=SOURCE_REFS,
    )
    publish_barrier = Barrier(2)

    class SynchronizedQuarantineClient(BuilderThreadService):
        def __init__(self, root: Path, *, expected_vault_id: str):
            super().__init__(root, expected_vault_id=expected_vault_id)
            self._loads = 0

        def _load_thread(
            self, thread_id: str, *, structural_only: bool = False
        ) -> dict[str, Any]:
            loaded = super()._load_thread(thread_id, structural_only=structural_only)
            self._loads += 1
            if self._loads == 2:
                publish_barrier.wait(timeout=2)
            return loaded

    def quarantine(actor: str, reason: str) -> Exception | None:
        try:
            SynchronizedQuarantineClient(
                service.root, expected_vault_id=VAULT_ID
            ).quarantine(
                opened["thread_id"],
                artifact_hash=opened["entry_hash"],
                actor_id=actor,
                reason_code=reason,
            )
        except BuilderThreadError as exc:
            return exc
        return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda item: quarantine(*item),
                (
                    (ACTOR, "privacy_misclassification"),
                    (RECIPIENT, "credential_like_content"),
                ),
            )
        )
    assert all(item is None or isinstance(item, BuilderThreadConflictError) for item in outcomes)

    with pytest.raises(BuilderThreadConflictError, match="quarantine decisions"):
        service.health()

    quarantine_hashes = [
        path.stem
        for path in _entry_files(vault, opened["thread_id"])
        if json.loads(path.read_bytes())["entry_type"] == "quarantine"
    ]
    assert len(quarantine_hashes) == 2
    recovered = service.quarantine(
        opened["thread_id"],
        artifact_hash=quarantine_hashes[0],
        actor_id=ACTOR,
        reason_code="concurrent_conflict",
    )
    assert recovered["state"] == "quarantined"
    assert service.health()["ok"] is True


def test_single_quarantine_decision_cannot_be_neutralized_as_concurrent(
    tmp_path: Path,
) -> None:
    service, vault = _service(tmp_path)
    opened = service.create_thread(
        recipient_id=RECIPIENT,
        subject="Preserve one incident disposition",
        content="Can a lone quarantine remain authoritative within this projection?",
        actor_id=ACTOR,
        source_refs=SOURCE_REFS,
    )
    quarantined = service.quarantine(
        opened["thread_id"],
        artifact_hash=opened["entry_hash"],
        actor_id=ACTOR,
        reason_code="privacy_misclassification",
    )
    decision_hash = quarantined["entry_hash"]
    before = _vault_snapshot(vault)

    with pytest.raises(
        BuilderThreadValidationError,
        match="active sibling quarantine decisions",
    ):
        service.quarantine(
            opened["thread_id"],
            artifact_hash=decision_hash,
            actor_id=RECIPIENT,
            reason_code="concurrent_conflict",
        )

    assert _vault_snapshot(vault) == before
    reread = service.read_thread(opened["thread_id"])
    assert reread["state"] == "quarantined"
    open_entry = next(
        item
        for item in reread["entries"]
        if item.get("entry_type") == "open"
    )
    assert open_entry["quarantined"] is True
    assert "entry" not in open_entry
    assert reread["subject"] == "[quarantined]"
    assert service.health()["ok"] is True


def test_entry_bound_is_reserved_before_publication_and_129th_is_non_mutating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, vault = _service(tmp_path)
    opened = service.create_thread(
        recipient_id=RECIPIENT,
        subject="Enforce the entry bound before publication",
        content="Can concurrent writers leave exactly 128 healthy contributions?",
        actor_id=ACTOR,
        source_refs=SOURCE_REFS,
    )
    for index in range(service.MAX_ENTRIES_PER_THREAD - 2):
        service.reply(
            opened["thread_id"],
            recipient_id=ACTOR,
            content=f"Bounded reply {index}",
            actor_id=RECIPIENT,
            parent_hash=opened["entry_hash"],
            source_refs=SOURCE_REFS,
        )
    assert service.read_thread(opened["thread_id"])["entry_count"] == 127

    reserve_barrier = Barrier(2)
    real_reserve = BuilderThreadService._reserve_entry_slot

    def synchronized_reserve(
        current: BuilderThreadService, entries_dir: Path, entry_id: str
    ) -> Path:
        reserve_barrier.wait(timeout=2)
        return real_reserve(current, entries_dir, entry_id)

    monkeypatch.setattr(BuilderThreadService, "_reserve_entry_slot", synchronized_reserve)

    def overflow_reply(index: int) -> Exception | None:
        try:
            BuilderThreadService(service.root, expected_vault_id=VAULT_ID).reply(
                opened["thread_id"],
                recipient_id=ACTOR,
                content=f"Overflow reply {index}",
                actor_id=RECIPIENT,
                parent_hash=opened["entry_hash"],
                source_refs=SOURCE_REFS,
            )
        except Exception as exc:  # noqa: BLE001 - typed convergence asserted below
            return exc
        return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(overflow_reply, (1, 2)))
    assert outcomes.count(None) == 1
    assert sum(isinstance(item, BuilderThreadConflictError) for item in outcomes) == 1
    monkeypatch.setattr(BuilderThreadService, "_reserve_entry_slot", real_reserve)

    full = service.read_thread(opened["thread_id"])
    assert full["entry_count"] == service.MAX_ENTRIES_PER_THREAD
    assert full["entries_truncated"] is False
    assert service.health()["ok"] is True

    before = {
        path.relative_to(vault).as_posix(): (
            path.stat().st_mtime_ns,
            path.read_bytes(),
        )
        for path in vault.rglob("*")
        if path.is_file()
    }
    with pytest.raises(BuilderThreadConflictError, match="entry bound reached"):
        service.reply(
            opened["thread_id"],
            recipient_id=ACTOR,
            content="The sequential 129th contribution must not persist.",
            actor_id=RECIPIENT,
            parent_hash=opened["entry_hash"],
            source_refs=SOURCE_REFS,
        )
    after = {
        path.relative_to(vault).as_posix(): (
            path.stat().st_mtime_ns,
            path.read_bytes(),
        )
        for path in vault.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert len(_entry_files(vault, opened["thread_id"])) == 128
    assert service.health()["ok"] is True


def test_capture_gate_and_shared_non_sensitive_privacy_boundary(
    tmp_path: Path,
) -> None:
    service, _vault = _service(tmp_path)
    kwargs = {
        "recipient_id": RECIPIENT,
        "subject": "One represented question",
        "content": "Should this exact bounded question be answered once?",
        "actor_id": ACTOR,
        "source_refs": SOURCE_REFS,
    }
    service.create_thread(**kwargs)
    with pytest.raises(BuilderThreadConflictError, match="already represented"):
        service.create_thread(**kwargs)
    with pytest.raises(BuilderThreadValidationError, match="named recipient"):
        service.create_thread(**{**kwargs, "recipient_id": ""})
    with pytest.raises(BuilderThreadValidationError, match="reply_expected"):
        service.create_thread(**kwargs, reply_expected=False)

    unsafe = (
        "Authorization: Bearer token",
        "PATH=/usr/bin:/bin",
        "prefix TOKEN=value",
        "argv[0]=builder-thread",
        "stderr=private failure",
        "stderr: Traceback (most recent call last)",
        "Inspect /Users/private-owner/Library/Secrets",
        "path=/Users/private-owner/Library/Secrets",
        "see(/home/private-owner/secrets)",
        "file:///Volumes/PrivateVault/item",
        "%2FUsers%2Fprivate-owner%2FSecrets",
        "/root/.ssh/id_rsa",
        "/etc/ssh/id_rsa",
        "`/etc/passwd`",
        "path:/etc/passwd",
        "/single",
        "sys.argv was ['builder-thread', '--secret']",
        "sk-proj-abcdefghijklmnop",
        "github_pat_abcdefghijklmnop",
        "AKIAABCDEFGHIJKLMNOP",
    )
    for content in unsafe:
        with pytest.raises(BuilderThreadPrivacyError):
            service.create_thread(**{**kwargs, "subject": content, "content": content})
    with pytest.raises(BuilderThreadValidationError, match="exceeds"):
        service.create_thread(**{**kwargs, "subject": "Oversized", "content": "x" * 4_001})
    with pytest.raises(BuilderThreadValidationError, match="actor"):
        service.create_thread(**{**kwargs, "actor_id": "anonymous"})
    with pytest.raises(BuilderThreadPrivacyError, match="credential"):
        service.create_thread(**{**kwargs, "actor_id": "agent:ghp_abcdefghijklmnop"})
    with pytest.raises(BuilderThreadValidationError, match="unsafe source ref"):
        service.create_thread(
            **{
                **kwargs,
                "subject": "Typed source refs",
                "source_refs": [{"type": "github_issue", "value": "not-a-number"}],
            }
        )
    allowed = service.create_thread(
        **{
            **kwargs,
            "subject": "Authority-safe web reference",
            "content": "See https://example.com/docs/builder-thread for public context.",
        }
    )
    assert allowed["state"] == "open"


def test_inbox_is_bounded_read_only_and_idempotent(tmp_path: Path) -> None:
    service, vault = _service(tmp_path)
    opened = service.create_thread(
        recipient_id=RECIPIENT,
        subject="Read without reminders",
        content="Will an unchanged inbox scan leave the vault untouched?",
        actor_id=ACTOR,
        source_refs=SOURCE_REFS,
    )
    with pytest.raises(BuilderThreadValidationError, match="named parent recipient"):
        service.reply(
            opened["thread_id"],
            recipient_id=ACTOR,
            content="A foreign actor must not clear the inbox item.",
            actor_id="agent:other:actor",
            parent_hash=opened["entry_hash"],
            source_refs=SOURCE_REFS,
        )
    assert service.inbox(recipient_id=RECIPIENT)["count"] == 1

    valid_reply = service.reply(
        opened["thread_id"],
        recipient_id=ACTOR,
        content="A valid recipient-authored reply.",
        actor_id=RECIPIENT,
        parent_hash=opened["entry_hash"],
        source_refs=SOURCE_REFS,
    )
    reply_path = next(
        path
        for path in _entry_files(vault, opened["thread_id"])
        if path.stem == valid_reply["entry_hash"]
    )
    reply_bytes = reply_path.read_bytes()
    forged = json.loads(reply_bytes)
    forged["actor_id"] = "agent:other:actor"
    forged_bytes = _canonical_bytes(forged)
    forged_path = reply_path.with_name(f"{hashlib.sha256(forged_bytes).hexdigest()}.json")
    reply_path.unlink()
    forged_path.write_bytes(forged_bytes)
    with pytest.raises(BuilderThreadValidationError, match="named parent recipient"):
        service.health()
    forged_path.unlink()
    reply_path.write_bytes(reply_bytes)
    before = {
        path.relative_to(vault).as_posix(): (path.stat().st_mtime_ns, path.read_bytes())
        for path in vault.rglob("*")
        if path.is_file()
    }
    first = service.inbox(recipient_id=RECIPIENT)
    second = service.inbox(recipient_id=RECIPIENT)
    after = {
        path.relative_to(vault).as_posix(): (path.stat().st_mtime_ns, path.read_bytes())
        for path in vault.rglob("*")
        if path.is_file()
    }

    assert first == second
    assert first["snapshot_hash"]
    assert len(first["threads"]) <= service.MAX_LIST_THREADS
    assert before == after
