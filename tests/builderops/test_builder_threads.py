from __future__ import annotations

import hashlib
import json
import os
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
    BuilderThreadService,
    BuilderThreadValidationError,
)
from app.builderops.vault_queue import init_vault


VAULT_ID = "11111111-1111-4111-8111-111111111111"
OTHER_VAULT_ID = "22222222-2222-4222-8222-222222222222"
ACTOR = "agent:codex:test"
RECIPIENT = "agent:claude:test"
SOURCE_REFS = [{"type": "github_issue", "value": "4702"}]


def _service(tmp_path: Path) -> tuple[BuilderThreadService, Path]:
    vault = tmp_path / "builderops-vault"
    init_vault(vault)
    service = BuilderThreadService.initialize(
        vault, vault_id=VAULT_ID, adopt_existing=True
    )
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
            "*.json"
        )
    )


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
    BuilderThreadService.initialize(
        nested_vault, vault_id=OTHER_VAULT_ID, adopt_existing=True
    )
    parent_alias = tmp_path / "parent-alias"
    parent_alias.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(BuilderThreadValidationError, match="ancestor"):
        BuilderThreadService(
            parent_alias / "vault", expected_vault_id=OTHER_VAULT_ID
        ).health()

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
        BuilderThreadService.initialize(
            rogue, vault_id=VAULT_ID, adopt_existing=True
        )
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
    fixture = repository / "vault"
    init_vault(fixture)
    with pytest.raises(BuilderThreadValidationError, match="fixture"):
        BuilderThreadService.initialize(fixture, vault_id=VAULT_ID)


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
        changed_path = original.with_name(
            f"{hashlib.sha256(changed_bytes).hexdigest()}.json"
        )
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


def test_cli_round_trip_covers_complete_thread_surface(tmp_path: Path) -> None:
    vault = tmp_path / "builderops-vault"
    init_vault(vault)
    env = _env(tmp_path, vault)

    initialized = _run(
        ["builder-thread", "init", "--adopt-existing", "--json"], env
    )
    assert initialized.exit_code == 0

    created = _run(
        [
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
            "--source-ref",
            "github_issue:4702",
            "--json",
        ],
        env,
    )
    opened = json.loads(created.output)
    thread_id = opened["thread_id"]

    replied = _run(
        [
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
            "--source-ref",
            "github_issue:4702",
            "--json",
        ],
        env,
    )
    assert replied.exit_code == 0

    read = _run(["builder-thread", "read", thread_id, "--json"], env)
    assert json.loads(read.output)["state"] == "answered"
    listed = _run(["builder-thread", "list", "--json"], env)
    assert json.loads(listed.output)["threads"][0]["thread_id"] == thread_id
    inbox = _run(
        ["builder-inbox", "list", "--recipient", ACTOR, "--json"], env
    )
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
    unsafe_path = (
        vault
        / "builder-threads"
        / "threads"
        / thread_id
        / "entries"
        / f"{unsafe_hash}.json"
    )
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

    capture_barrier = Barrier(2)
    capture_kwargs = {
        "recipient_id": RECIPIENT,
        "subject": "One concurrent represented capture",
        "content": "Can two clients create this same represented question?",
        "actor_id": ACTOR,
        "source_refs": SOURCE_REFS,
    }

    def create_once() -> str:
        capture_barrier.wait()
        try:
            service.create_thread(**capture_kwargs)
        except BuilderThreadConflictError:
            return "conflict"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as pool:
        capture_results = list(pool.map(lambda _index: create_once(), (1, 2)))
    assert sorted(capture_results) == ["conflict", "created"]
    assert service.health()["thread_count"] == 2

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


def test_initial_thread_tree_is_atomically_visible_to_readers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _vault = _service(tmp_path)
    entered_rename = Event()
    release_rename = Event()
    real_rename = os.rename

    def paused_rename(source: Path | str, target: Path | str) -> None:
        entered_rename.set()
        assert release_rename.wait(timeout=2)
        real_rename(source, target)

    monkeypatch.setattr("app.builderops.builder_threads.os.rename", paused_rename)
    with ThreadPoolExecutor(max_workers=2) as pool:
        create_future = pool.submit(
            service.create_thread,
            recipient_id=RECIPIENT,
            subject="Atomic initial tree",
            content="Can a reader observe an incomplete final thread directory?",
            actor_id=ACTOR,
            source_refs=SOURCE_REFS,
        )
        assert entered_rename.wait(timeout=2)
        health_future = pool.submit(service.health)
        release_rename.set()
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
    service.close_thread(
        opened["thread_id"], actor_id=ACTOR, reason="Initial disposition"
    )
    with pytest.raises(BuilderThreadConflictError, match="close retry"):
        service.close_thread(
            opened["thread_id"], actor_id=ACTOR, reason="Changed disposition"
        )
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
    service.close_thread(
        opened["thread_id"], actor_id=ACTOR, reason="Updated disposition"
    )
    archived = service.archive_thread(opened["thread_id"], actor_id=ACTOR)
    assert archived["state"] == "archived"
    assert service.health()["ok"] is True


def test_concurrent_disposition_conflict_can_be_explicitly_quarantined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    real_publish = builder_thread_module._atomic_publish

    def synchronized_close_publish(path: Path, data: bytes) -> bool:
        payload = json.loads(data)
        if payload.get("entry_type") == "close":
            publish_barrier.wait(timeout=2)
        return real_publish(path, data)

    monkeypatch.setattr(
        builder_thread_module, "_atomic_publish", synchronized_close_publish
    )

    def close(reason: str) -> Exception | None:
        try:
            BuilderThreadService(
                service.root, expected_vault_id=VAULT_ID
            ).close_thread(opened["thread_id"], actor_id=ACTOR, reason=reason)
        except Exception as exc:  # noqa: BLE001 - assert typed convergence below
            return exc
        return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(close, ("Concurrent A", "Concurrent B")))
    assert any(isinstance(item, BuilderThreadConflictError) for item in outcomes)
    with pytest.raises(BuilderThreadConflictError, match="multiple active close"):
        service.health()

    monkeypatch.setattr(builder_thread_module, "_atomic_publish", real_publish)
    closes = []
    for path in _entry_files(vault, opened["thread_id"]):
        payload = json.loads(path.read_bytes())
        if payload["entry_type"] == "close":
            closes.append(path.stem)
    assert len(closes) == 2
    recovered = service.quarantine(
        opened["thread_id"],
        artifact_hash=closes[0],
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
    real_sync = builder_thread_module._fsync_directory

    def fail_first_post_rename_sync(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 7:
            raise OSError("injected post-rename acknowledgement loss")
        real_sync(path)

    kwargs = {
        "recipient_id": RECIPIENT,
        "subject": "Reconcile acknowledgement loss",
        "content": "Did the complete initial tree survive the lost acknowledgement?",
        "actor_id": ACTOR,
        "source_refs": SOURCE_REFS,
        "entry_id": "55555555-5555-4555-8555-555555555555",
        "created_at": "2026-08-09T12:00:00Z",
    }
    monkeypatch.setattr(
        builder_thread_module, "_fsync_directory", fail_first_post_rename_sync
    )
    with pytest.raises(OSError, match="acknowledgement loss"):
        service.create_thread(**kwargs)

    monkeypatch.setattr(builder_thread_module, "_fsync_directory", real_sync)
    exact = service.create_thread(**kwargs)
    assert exact["state"] == "open"
    assert service.health()["thread_count"] == 1


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
    )
    for content in unsafe:
        with pytest.raises(BuilderThreadPrivacyError):
            service.create_thread(**{**kwargs, "subject": content, "content": content})
    with pytest.raises(BuilderThreadValidationError, match="exceeds"):
        service.create_thread(
            **{**kwargs, "subject": "Oversized", "content": "x" * 4_001}
        )
    with pytest.raises(BuilderThreadValidationError, match="actor"):
        service.create_thread(**{**kwargs, "actor_id": "anonymous"})
    with pytest.raises(BuilderThreadPrivacyError, match="credential"):
        service.create_thread(
            **{**kwargs, "actor_id": "agent:ghp_abcdefghijklmnop"}
        )
    with pytest.raises(BuilderThreadValidationError, match="unsafe source ref"):
        service.create_thread(
            **{
                **kwargs,
                "subject": "Typed source refs",
                "source_refs": [{"type": "github_issue", "value": "not-a-number"}],
            }
        )


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
