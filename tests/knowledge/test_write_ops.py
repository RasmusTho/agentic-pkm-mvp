from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import errno
import hashlib
import os
from pathlib import Path
import threading

import pytest

from app.knowledge import write_ops
from app.knowledge.contracts import WriteReceipt
from app.knowledge.errors import KnowledgeWriteConflict
from app.knowledge.settings import KnowledgeAdapter, KnowledgeSettings
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError
from tests.knowledge.candidate_create_oracles import (
    FdOracle as _FdOracle,
    assert_cleanup_fence as _assert_cleanup_fence,
    assert_exact_fd_ownership as _assert_exact_fd_ownership,
    assert_exact_stage_names as _assert_exact_stage_names,
    assert_hidden_stage_state,
    assert_stage_publication_order,
)


def test_default_vault_root_for_path_uses_filesystem_anchor(tmp_path: Path) -> None:
    note = tmp_path / "vault" / "Inbox" / "note.md"
    root = write_ops.default_vault_root_for_path(note)
    assert root == Path(note.anchor)


def test_read_note_text_with_version_hashes_exact_raw_bytes(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    raw = b"---\r\nuuid: crlf-note\r\n---\r\n\r\nBody\r\n"
    note.write_bytes(raw)

    text, version = write_ops.read_note_text_with_version(note)

    assert text.encode("utf-8") == raw
    assert version == hashlib.sha256(raw).hexdigest()


def test_write_note_from_absolute_resolves_locator_and_port(monkeypatch, tmp_path: Path) -> None:
    note = tmp_path / "vault" / "Inbox" / "note.md"
    captured: dict[str, object] = {}

    class FakePort:
        def write_note(self, locator, content):  # type: ignore[no-untyped-def]
            captured["locator_path"] = locator.path
            captured["locator_vault"] = locator.vault
            captured["content"] = content
            return WriteReceipt(operation="write_note", locator=locator, adapter="fake")

    def fake_resolve(**kwargs):  # type: ignore[no-untyped-def]
        captured["resolve_kwargs"] = kwargs
        return FakePort()

    monkeypatch.setattr(write_ops, "resolve_knowledge_port", fake_resolve)

    receipt = write_ops.write_note_from_absolute(note, "hello", vault_root=tmp_path / "vault")

    assert receipt.operation == "write_note"
    assert captured["locator_path"] == "Inbox/note.md"
    assert captured["locator_vault"] == "Vault"
    assert captured["content"] == "hello"
    assert captured["resolve_kwargs"] == {
        "vault_root": (tmp_path / "vault").resolve(),
        "settings": KnowledgeSettings(
            primary_adapter=KnowledgeAdapter.FS_VAULT,
            fallback_adapter=KnowledgeAdapter.OBSIDIAN_CLI,
            allow_fallback=False,
            strict_startup=False,
        ),
    }


def test_write_note_from_absolute_rejects_outside_vault_root_before_writing(
    monkeypatch, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside" / "note.md"
    outside.parent.mkdir(parents=True)
    outside.write_text("old", encoding="utf-8")
    vault.mkdir()
    monkeypatch.setattr(
        write_ops,
        "resolve_knowledge_port",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("port should not resolve")),
    )

    try:
        write_ops.write_note_from_absolute(outside, "new", vault_root=vault)
    except ValueError:
        pass
    else:
        raise AssertionError("outside path was accepted")

    assert outside.read_text(encoding="utf-8") == "old"


def test_write_note_from_absolute_rejects_symlink_escape(monkeypatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    escaped = outside / "note.md"
    escaped.write_text("old", encoding="utf-8")
    link = vault / "linked.md"
    link.symlink_to(escaped)
    monkeypatch.setattr(
        write_ops,
        "resolve_knowledge_port",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("port should not resolve")),
    )

    try:
        write_ops.write_note_from_absolute(link, "new", vault_root=vault)
    except ValueError:
        pass
    else:
        raise AssertionError("symlink escape was accepted")

    assert escaped.read_text(encoding="utf-8") == "old"


def test_absolute_helper_rejects_expected_version_through_source_symlink_alias(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    target = vault / "Sources" / "panel-source.md"
    target.parent.mkdir(parents=True)
    target.write_text("observed source", encoding="utf-8")
    alias = vault / "Notes" / "source-alias.md"
    alias.parent.mkdir()
    alias.symlink_to(Path("..") / "Sources" / target.name)
    _, expected_version = write_ops.read_note_text_with_version(alias)
    target.write_text("concurrent human source", encoding="utf-8")

    with pytest.raises(
        KnowledgeWriteConflict,
        match="expected-version write rejects aliased note locator",
    ):
        write_ops.write_note_from_absolute(
            alias,
            "stale watcher proposal",
            vault_root=vault,
            expected_version=expected_version,
        )

    assert target.read_text(encoding="utf-8") == "concurrent human source"
    assert alias.read_text(encoding="utf-8") == "concurrent human source"


def test_relative_helper_rejects_expected_version_through_source_symlink_alias(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    target = vault / "Sources" / "panel-source.md"
    target.parent.mkdir(parents=True)
    target.write_text("observed source", encoding="utf-8")
    alias = vault / "Notes" / "source-alias.md"
    alias.parent.mkdir()
    alias.symlink_to(Path("..") / "Sources" / target.name)
    _, expected_version = write_ops.read_note_text_with_version(alias)
    target.write_text("concurrent human source", encoding="utf-8")

    with pytest.raises(
        KnowledgeWriteConflict,
        match="expected-version write rejects aliased note locator",
    ):
        write_ops.write_note_relative(
            "Notes/source-alias.md",
            "stale watcher proposal",
            vault_root=vault,
            expected_version=expected_version,
        )

    assert target.read_text(encoding="utf-8") == "concurrent human source"
    assert alias.read_text(encoding="utf-8") == "concurrent human source"


def test_absolute_helper_rejects_rewritten_leaf_alias_swap(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    first = vault / "Notes" / "a.md"
    second = vault / "Notes" / "b.md"
    first.parent.mkdir(parents=True)
    first.write_text("same content", encoding="utf-8")
    second.write_text("same content", encoding="utf-8")
    _, expected_version = write_ops.read_note_text_with_version(first)
    first.unlink()
    first.symlink_to(second.name)

    with pytest.raises(
        KnowledgeWriteConflict,
        match="expected-version write rejects aliased note locator",
    ):
        write_ops.write_note_from_absolute(
            first,
            "stale proposal",
            vault_root=vault,
            expected_version=expected_version,
        )

    assert second.read_text(encoding="utf-8") == "same content"
    assert first.read_text(encoding="utf-8") == "same content"


def test_write_note_relative_uses_make_note_locator(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakePort:
        def write_note(self, locator, content):  # type: ignore[no-untyped-def]
            captured["path"] = locator.path
            captured["vault"] = locator.vault
            captured["content"] = content
            return WriteReceipt(operation="write_note", locator=locator, adapter="fake")

    monkeypatch.setattr(write_ops, "resolve_knowledge_port", lambda **kwargs: FakePort())

    receipt = write_ops.write_note_relative("Inbox/a.md", "body", vault_root=tmp_path)

    assert receipt.operation == "write_note"
    assert captured["path"] == "Inbox/a.md"
    assert captured["vault"] == "Vault"
    assert captured["content"] == "body"


@pytest.mark.parametrize("relative", [False, True])
def test_write_helpers_raise_with_staged_receipt_by_default(
    relative: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, WriteReceipt] = {}

    class FakePort:
        def write_note(self, locator, content, **kwargs):  # type: ignore[no-untyped-def]
            receipt = WriteReceipt(
                operation="write_note",
                locator=locator,
                adapter="fake",
                outcome="conflict_staged",
                conflict_artifact="Inbox/note.concurrent-save-test.md",
            )
            captured["receipt"] = receipt
            return receipt

    monkeypatch.setattr(write_ops, "resolve_knowledge_port", lambda **_kwargs: FakePort())

    with pytest.raises(KnowledgeWriteConflict, match="conflict staged") as exc_info:
        if relative:
            write_ops.write_note_relative(
                "Inbox/note.md",
                "proposal",
                vault_root=tmp_path,
                expected_version="stale",
            )
        else:
            note = tmp_path / "Inbox" / "note.md"
            write_ops.write_note_from_absolute(
                note,
                "proposal",
                vault_root=tmp_path,
                expected_version="stale",
            )

    assert exc_info.value.receipt is captured["receipt"]


@pytest.mark.parametrize("relative", [False, True])
def test_write_helpers_return_staged_receipt_only_for_explicitly_aware_caller(
    relative: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakePort:
        def write_note(self, locator, content, **kwargs):  # type: ignore[no-untyped-def]
            return WriteReceipt(
                operation="write_note",
                locator=locator,
                adapter="fake",
                outcome="conflict_staged",
                conflict_artifact="Inbox/note.concurrent-save-test.md",
            )

    monkeypatch.setattr(write_ops, "resolve_knowledge_port", lambda **_kwargs: FakePort())

    if relative:
        receipt = write_ops.write_note_relative(
            "Inbox/note.md",
            "proposal",
            vault_root=tmp_path,
            expected_version="stale",
            accept_staged_conflict=True,
        )
    else:
        receipt = write_ops.write_note_from_absolute(
            tmp_path / "Inbox" / "note.md",
            "proposal",
            vault_root=tmp_path,
            expected_version="stale",
            accept_staged_conflict=True,
        )

    assert receipt.outcome == "conflict_staged"
    assert receipt.conflict_artifact == "Inbox/note.concurrent-save-test.md"


def test_append_note_relative_uses_port_append(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakePort:
        def append_note(self, locator, content):  # type: ignore[no-untyped-def]
            captured["path"] = locator.path
            captured["vault"] = locator.vault
            captured["content"] = content
            return WriteReceipt(operation="append_note", locator=locator, adapter="fake")

    monkeypatch.setattr(write_ops, "resolve_knowledge_port", lambda **kwargs: FakePort())

    receipt = write_ops.append_note_relative("Inbox/log.md", "line\n", vault_root=tmp_path)

    assert receipt.operation == "append_note"
    assert captured["path"] == "Inbox/log.md"
    assert captured["vault"] == "Vault"
    assert captured["content"] == "line\n"


def test_append_note_relative_rejects_unhealthy_write_guard(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        write_ops,
        "resolve_knowledge_port",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("port should not resolve")),
    )
    guard = WriteGuard(lambda: {"state": "safe_mode", "reason": "test-induced block"})

    with pytest.raises(WritesBlockedError):
        write_ops.append_note_relative(
            "Inbox/log.md",
            "line\n",
            vault_root=tmp_path,
            write_guard=guard,
        )


def test_append_note_relative_enforces_default_guard(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        write_ops,
        "resolve_knowledge_port",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("port should not resolve")),
    )
    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": "safe_mode", "reason": "test-induced default block"},
    )

    with pytest.raises(WritesBlockedError) as exc_info:
        write_ops.append_note_relative("Inbox/log.md", "line\n", vault_root=tmp_path)

    assert exc_info.value.action == write_ops.KNOWLEDGE_WRITE_ACTION


def test_append_note_relative_allows_healthy_write_guard(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakePort:
        def append_note(self, locator, content):  # type: ignore[no-untyped-def]
            captured["path"] = locator.path
            captured["content"] = content
            return WriteReceipt(operation="append_note", locator=locator, adapter="fake")

    monkeypatch.setattr(write_ops, "resolve_knowledge_port", lambda **_kwargs: FakePort())
    guard = WriteGuard(lambda: {"state": "healthy", "reason": None})

    receipt = write_ops.append_note_relative(
        "Inbox/log.md",
        "line\n",
        vault_root=tmp_path,
        write_guard=guard,
    )

    assert receipt.operation == "append_note"
    assert captured == {"path": "Inbox/log.md", "content": "line\n"}


def test_advanced_uri_from_vault_path_inside_root(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    note = vault / "Inbox" / "a.md"
    uri = write_ops.advanced_uri_from_vault_path(note, vault_root=vault)
    assert "obsidian://advanced-uri" in uri
    assert "filepath=Inbox/a.md" in uri


def test_advanced_uri_from_vault_path_outside_root_falls_back_to_name(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    other = tmp_path / "outside.md"
    uri = write_ops.advanced_uri_from_vault_path(other, vault_root=vault)
    assert "obsidian://advanced-uri" in uri
    assert "filepath=outside.md" in uri


@pytest.mark.parametrize("existing_components", [0, 1, 2])
def test_candidate_create_once_owns_durable_parent_chain(
    existing_components: int,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    components = ("Sources", "Nested")
    cursor = vault
    for component in components[:existing_components]:
        cursor /= component
        cursor.mkdir()

    oracle = _FdOracle()
    oracle.install(monkeypatch)
    real_mkdir = os.mkdir
    real_fsync = os.fsync

    def traced_mkdir(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> None:
        oracle.events.append(("mkdir", os.fsdecode(path), dir_fd))
        real_mkdir(path, mode, dir_fd=dir_fd)

    def traced_fsync(fd: int) -> None:
        oracle.events.append(("fsync", fd))
        real_fsync(fd)

    monkeypatch.setattr(os, "mkdir", traced_mkdir)
    monkeypatch.setattr(os, "fsync", traced_fsync)
    guard_calls: list[str] = []
    guard = WriteGuard(lambda: {"state": "healthy"})
    real_assert = guard.assert_writes_allowed

    def tracked_assert(action: str) -> None:
        guard_calls.append(action)
        real_assert(action)

    guard.assert_writes_allowed = tracked_assert  # type: ignore[method-assign]

    with oracle.observe():
        result = write_ops.create_candidate_note_once(
            "Sources/Nested/candidate.md",
            "complete candidate",
            vault_root=vault,
            action="candidate.test",
            write_guard=guard,
        )

    assert result == "written"
    assert guard_calls == ["candidate.test"]
    assert (vault / "Sources/Nested/candidate.md").read_text(encoding="utf-8") == (
        "complete candidate"
    )

    def assert_parent_chain_fences(events: list[tuple[object, ...]]) -> None:
        for component in components:
            mkdir_index = next(
                index
                for index, event in enumerate(events)
                if event[0] == "mkdir" and event[1] == component
            )
            child_open_index = next(
                index
                for index, event in enumerate(events)
                if event[0] == "open" and event[1] == component
            )
            containing_fd = events[mkdir_index][2]
            matching_fsyncs = [
                index
                for index, event in enumerate(events)
                if event == ("fsync", containing_fd) and mkdir_index < index < child_open_index
            ]
            assert len(matching_fsyncs) == 1

    assert_parent_chain_fences(oracle.events)
    for component in components:
        mkdir_index = next(
            index
            for index, event in enumerate(oracle.events)
            if event[0] == "mkdir" and event[1] == component
        )
        child_open_index = next(
            index
            for index, event in enumerate(oracle.events)
            if event[0] == "open" and event[1] == component
        )
        containing_fd = oracle.events[mkdir_index][2]
        fsync_index = next(
            index
            for index, event in enumerate(oracle.events)
            if event == ("fsync", containing_fd) and mkdir_index < index < child_open_index
        )
        missing_fence = [event for index, event in enumerate(oracle.events) if index != fsync_index]
        with pytest.raises(AssertionError):
            assert_parent_chain_fences(missing_fence)
    _assert_exact_fd_ownership(oracle.opened, oracle.close_attempts, oracle.duplicates)
    assert oracle.active == {}
    directory_tokens = [token for token in oracle.opened if token[2] == "directory"]
    assert len(directory_tokens) >= 3
    for missing in (directory_tokens[0], directory_tokens[-2], directory_tokens[-1]):
        mutant_closes = [token for token in oracle.close_attempts if token != missing]
        with pytest.raises(AssertionError):
            _assert_exact_fd_ownership(oracle.opened, mutant_closes, [])


def test_candidate_create_once_publishes_fsynced_raw_stage_without_replace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    parent = vault / "Sources"
    parent.mkdir(parents=True)
    oracle = _FdOracle()
    oracle.install(monkeypatch)
    unrelated_fd = os.open(os.devnull, os.O_RDONLY)
    os.close(unrelated_fd)
    with oracle.observe():
        unrelated_fd = os.open(os.devnull, os.O_RDONLY)
        os.close(unrelated_fd)
    assert oracle.opened == []
    assert oracle.close_attempts == []
    assert oracle.active == {}
    real_write = os.write
    real_fsync = os.fsync
    real_publish = write_ops._atomic_rename_noreplace_at
    stage_fds: set[int] = set()
    file_fsyncs: list[int] = []
    publish_observations: list[tuple[str, str, bytes]] = []

    def partial_write(fd: int, payload: bytes) -> int:
        token = oracle.active.get(fd)
        if token is not None and token[2] == "stage":
            stage_fds.add(fd)
            payload = payload[:3]
        return real_write(fd, payload)

    def traced_fsync(fd: int) -> None:
        oracle.events.append(("fsync", fd))
        if fd in stage_fds:
            file_fsyncs.append(fd)
        real_fsync(fd)

    def traced_publish(
        source_dir_fd: int,
        source_name: str,
        destination_dir_fd: int,
        destination_name: str,
    ) -> None:
        assert source_dir_fd == destination_dir_fd
        assert not (parent / destination_name).exists()
        oracle.events.append(("publish", source_name, destination_name))
        publish_observations.append(
            (source_name, destination_name, (parent / source_name).read_bytes())
        )
        real_publish(
            source_dir_fd,
            source_name,
            destination_dir_fd,
            destination_name,
        )

    monkeypatch.setattr(os, "write", partial_write)
    monkeypatch.setattr(os, "fsync", traced_fsync)
    monkeypatch.setattr(write_ops, "_atomic_rename_noreplace_at", traced_publish)

    with oracle.observe():
        result = write_ops.create_candidate_note_once(
            "Sources/candidate.md",
            "complete candidate",
            vault_root=vault,
            action="candidate.test",
            write_guard=WriteGuard(lambda: {"state": "healthy"}),
        )

    assert result == "written"
    assert (parent / "candidate.md").read_bytes() == b"complete candidate"
    assert publish_observations == [
        (
            publish_observations[0][0],
            "candidate.md",
            b"complete candidate",
        )
    ]
    stage_names = [token[3] for token in oracle.opened if token[2] == "stage"]
    _assert_exact_stage_names(stage_names)
    assert file_fsyncs
    assert list(parent.glob(".candidate-stage-*")) == []
    assert_stage_publication_order(oracle.events)
    _assert_exact_fd_ownership(oracle.opened, oracle.close_attempts, oracle.duplicates)
    assert oracle.active == {}

    premature_publication = list(oracle.events)
    publish_event = next(event for event in premature_publication if event[0] == "publish")
    premature_publication.remove(publish_event)
    stage_open_index = next(
        index
        for index, event in enumerate(premature_publication)
        if event[0] == "open" and isinstance(event[4], tuple) and event[4][2] == "stage"
    )
    premature_publication.insert(stage_open_index + 1, publish_event)
    with pytest.raises(AssertionError):
        assert_stage_publication_order(premature_publication)

    # The test oracle must reject the false-green trace shapes seen in prior rounds.
    with pytest.raises(AssertionError):
        _assert_exact_fd_ownership(
            oracle.opened,
            [token for token in oracle.close_attempts if token and token[2] != "stage"],
            [],
        )
    with pytest.raises(AssertionError):
        _assert_exact_fd_ownership(
            oracle.opened,
            [*oracle.close_attempts, oracle.close_attempts[-1]],
            [],
        )
    reused = [(41, 1, "directory", "one"), (41, 2, "directory", "two")]
    with pytest.raises(AssertionError):
        _assert_exact_fd_ownership(reused, [reused[0]], [])
    with pytest.raises(AssertionError):
        _assert_exact_fd_ownership(
            oracle.opened,
            oracle.close_attempts,
            [("dup", oracle.opened[0][0], 99)],
        )
    actual_stage = stage_names[0]
    target_derived_mutants = [
        f".candidate-stage-candidate.md-{actual_stage.removeprefix('.candidate-stage-')}",
        f"{actual_stage}-candidate.md",
        f".candidate-stage-{actual_stage[-31:]}",
        f".candidate-stage-{actual_stage[-32:].upper()}",
    ]
    for mutant in target_derived_mutants:
        with pytest.raises(AssertionError):
            _assert_exact_stage_names([mutant])

    # A maximum-length canonical basename still publishes because the stage is fixed at 49 bytes.
    name_max = os.pathconf(parent, "PC_NAME_MAX")
    max_name = ("x" * (name_max - 3)) + ".md"
    assert len(max_name.encode("ascii")) == name_max
    with oracle.observe():
        assert (
            write_ops.create_candidate_note_once(
                f"Sources/{max_name}",
                "max-name candidate",
                vault_root=vault,
                action="candidate.test",
                write_guard=WriteGuard(lambda: {"state": "healthy"}),
            )
            == "written"
        )
    assert (parent / max_name).read_text(encoding="utf-8") == "max-name candidate"


def test_candidate_create_once_crash_boundaries_are_retryable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    parent = vault / "Sources"
    parent.mkdir(parents=True)
    relative = "Sources/retry.md"
    real_publish = write_ops._atomic_rename_noreplace_at

    def fail_before_publish(*_args: object) -> None:
        raise OSError(errno.EIO, "injected pre-publication failure")

    monkeypatch.setattr(write_ops, "_atomic_rename_noreplace_at", fail_before_publish)
    with pytest.raises(OSError, match="pre-publication"):
        write_ops.create_candidate_note_once(
            relative,
            "complete bytes",
            vault_root=vault,
            action="candidate.test",
            write_guard=WriteGuard(lambda: {"state": "healthy"}),
        )
    assert not (parent / "retry.md").exists()
    assert list(parent.glob(".candidate-stage-*")) == []

    old_remnant = parent / ".candidate-stage-00000000000000000000000000000000"
    old_remnant.write_bytes(b"old remnant")
    monkeypatch.setattr(write_ops, "_atomic_rename_noreplace_at", real_publish)
    assert (
        write_ops.create_candidate_note_once(
            relative,
            "complete bytes",
            vault_root=vault,
            action="candidate.test",
            write_guard=WriteGuard(lambda: {"state": "healthy"}),
        )
        == "written"
    )
    assert (parent / "retry.md").read_bytes() == b"complete bytes"
    assert old_remnant.read_bytes() == b"old remnant"

    renamed = False
    real_fsync = os.fsync

    def publish_then_mark(*args: object) -> None:
        nonlocal renamed
        real_publish(*args)  # type: ignore[arg-type]
        renamed = True

    def fail_post_rename_fsync(fd: int) -> None:
        if renamed:
            raise OSError(errno.EIO, "injected post-rename directory fsync")
        real_fsync(fd)

    monkeypatch.setattr(write_ops, "_atomic_rename_noreplace_at", publish_then_mark)
    monkeypatch.setattr(os, "fsync", fail_post_rename_fsync)
    with pytest.raises(OSError, match="post-rename"):
        write_ops.create_candidate_note_once(
            "Sources/post-rename.md",
            "durable candidate bytes",
            vault_root=vault,
            action="candidate.test",
            write_guard=WriteGuard(lambda: {"state": "healthy"}),
        )
    canonical = parent / "post-rename.md"
    assert canonical.read_bytes() == b"durable candidate bytes"
    monkeypatch.setattr(os, "fsync", real_fsync)
    assert write_ops.candidate_note_exists_durable(
        "Sources/post-rename.md",
        vault_root=vault,
    )
    assert canonical.read_bytes() == b"durable candidate bytes"


def test_candidate_create_once_loser_preserves_target_and_cleans_owned_stage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    parent = vault / "Sources"
    parent.mkdir(parents=True)
    target = parent / "winner.md"
    target.write_bytes(b"human winner")
    unrelated = parent / ".candidate-stage-11111111111111111111111111111111"
    unrelated.write_bytes(b"unrelated")
    unlinked: list[str] = []
    cleanup_events: list[tuple[object, ...]] = []
    real_unlink = os.unlink
    real_fsync = os.fsync
    real_stat = os.stat

    def traced_unlink(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        dir_fd: int | None = None,
    ) -> None:
        unlinked.append(os.fsdecode(path))
        real_unlink(path, dir_fd=dir_fd)
        cleanup_events.append(("unlink", os.fsdecode(path), dir_fd))

    def traced_fsync(fd: int) -> None:
        cleanup_events.append(("fsync", fd))
        real_fsync(fd)

    def traced_stat(
        path: str | bytes | int | os.PathLike[str] | os.PathLike[bytes],
        *,
        dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> os.stat_result:
        cleanup_events.append(("stat", os.fsdecode(path), dir_fd))
        return real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(os, "unlink", traced_unlink)
    monkeypatch.setattr(os, "fsync", traced_fsync)
    monkeypatch.setattr(os, "stat", traced_stat)
    result = write_ops.create_candidate_note_once(
        "Sources/winner.md",
        "loser bytes",
        vault_root=vault,
        action="candidate.test",
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )

    assert result == "already_exists"
    assert target.read_bytes() == b"human winner"
    assert unrelated.read_bytes() == b"unrelated"
    assert len(unlinked) == 1
    _assert_exact_stage_names(unlinked)
    hidden_names = [path.name for path in parent.glob(".candidate-stage-*")]
    assert_hidden_stage_state(
        hidden_names,
        sentinel_name=unrelated.name,
        expected_owned_count=0,
    )
    unlink_index = next(index for index, event in enumerate(cleanup_events) if event[0] == "unlink")
    _assert_cleanup_fence(cleanup_events[unlink_index:])
    assert cleanup_events[unlink_index + 2][0] == "stat"
    with pytest.raises(AssertionError):
        _assert_cleanup_fence(
            [event for event in cleanup_events[unlink_index:] if event[0] != "fsync"]
        )
    with pytest.raises(AssertionError):
        _assert_cleanup_fence(
            [
                cleanup_events[unlink_index + 1],
                cleanup_events[unlink_index],
                *cleanup_events[unlink_index + 2 :],
            ]
        )
    with pytest.raises(AssertionError):
        assert_hidden_stage_state(
            [*hidden_names, ".candidate-stage-22222222222222222222222222222222"],
            sentinel_name=unrelated.name,
            expected_owned_count=0,
        )
    with pytest.raises(AssertionError):
        assert_hidden_stage_state(
            [],
            sentinel_name=unrelated.name,
            expected_owned_count=0,
        )
    with pytest.raises(AssertionError):
        assert_hidden_stage_state(
            [".candidate-stage-22222222222222222222222222222222"],
            sentinel_name=unrelated.name,
            expected_owned_count=0,
        )


def test_candidate_create_once_real_same_target_race(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    parent = vault / "Sources"
    parent.mkdir(parents=True)
    oracle = _FdOracle()
    oracle.install(monkeypatch)
    real_publish = write_ops._atomic_rename_noreplace_at
    both_staged = threading.Barrier(2, timeout=5)

    def synchronized_real_publish(*args: object) -> None:
        both_staged.wait()
        real_publish(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(
        write_ops,
        "_atomic_rename_noreplace_at",
        synchronized_real_publish,
    )
    guard = WriteGuard(lambda: {"state": "healthy"})

    def contender(content: str) -> str:
        return write_ops.create_candidate_note_once(
            "Sources/race.md",
            content,
            vault_root=vault,
            action="candidate.test",
            write_guard=guard,
        )

    with oracle.observe():
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(contender, "contender one"),
                executor.submit(contender, "contender two"),
            ]
            results = [future.result(timeout=10) for future in futures]

    assert sorted(results) == ["already_exists", "written"]
    winner = (parent / "race.md").read_text(encoding="utf-8")
    assert winner in {"contender one", "contender two"}
    assert list(parent.glob(".candidate-stage-*")) == []
    _assert_exact_fd_ownership(oracle.opened, oracle.close_attempts, oracle.duplicates)
    assert oracle.active == {}
    stage_names = [token[3] for token in oracle.opened if token[2] == "stage"]
    assert len(stage_names) == 2
    _assert_exact_stage_names(stage_names)


def _assert_candidate_fault_outcome(outcome: object) -> None:
    assert isinstance(outcome, (OSError, RuntimeError))


@pytest.mark.parametrize(
    "fault",
    [
        "parent_mkdir",
        "parent_fsync",
        "parent_open",
        "root_close",
        "intermediate_close",
        "stage_open",
        "stage_zero_write",
        "stage_fsync",
        "stage_close",
        "publish",
        "cleanup_unlink",
        "cleanup_fsync",
        "loser_unlink",
        "loser_fsync",
        "winner_stat",
        "winner_nonregular",
        "post_rename_fsync",
        "final_parent_close",
    ],
)
def test_candidate_create_once_fault_matrix(
    fault: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    parent = vault / "Sources/Nested"
    parent.mkdir(parents=True)
    target = parent / "candidate.md"
    if fault in {"loser_unlink", "loser_fsync", "winner_stat"}:
        target.write_bytes(b"winner")
    elif fault == "winner_nonregular":
        target.mkdir()
    sentinel = parent / ".candidate-stage-11111111111111111111111111111111"
    sentinel.write_bytes(b"unrelated")

    oracle = _FdOracle()
    oracle.install(monkeypatch)
    real_mkdir = os.mkdir
    real_open = os.open
    real_write = os.write
    real_fsync = os.fsync
    real_close = os.close
    real_unlink = os.unlink
    real_stat = os.stat
    real_publish = write_ops._atomic_rename_noreplace_at
    stage_fd: int | None = None
    fd_labels: dict[int, str] = {}
    close_attempts: dict[str, int] = {}
    cleanup_events: list[tuple[object, ...]] = []
    unlink_succeeded = False
    publication_succeeded = False
    arms: dict[str, int] = {}

    def hit(arm: str, message: str) -> None:
        arms[arm] = arms.get(arm, 0) + 1
        raise OSError(errno.EIO, message)

    def faulting_mkdir(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> None:
        if fault == "parent_mkdir":
            hit("parent_mkdir", "parent mkdir fault")
        real_mkdir(path, mode, dir_fd=dir_fd)

    def faulting_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal stage_fd
        decoded = os.fsdecode(path)
        if fault == "parent_open" and decoded == "Sources":
            hit("parent_open", "parent open fault")
        if fault == "stage_open" and decoded.startswith(".candidate-stage-"):
            hit("stage_open", "stage open fault")
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        fd_labels[fd] = (
            "root"
            if dir_fd is None
            else "intermediate"
            if decoded == "Sources"
            else "final_parent"
            if decoded == "Nested"
            else "stage"
            if decoded.startswith(".candidate-stage-")
            else decoded
        )
        if decoded.startswith(".candidate-stage-"):
            stage_fd = fd
        return fd

    def faulting_write(fd: int, payload: bytes) -> int:
        if fault == "stage_zero_write" and fd == stage_fd:
            arms["stage_zero_write"] = arms.get("stage_zero_write", 0) + 1
            return 0
        return real_write(fd, payload)

    def faulting_fsync(fd: int) -> None:
        cleanup_events.append(("fsync", fd))
        if fault == "parent_fsync" and stage_fd is None:
            hit("parent_fsync", "parent fsync fault")
        if fault == "stage_fsync" and fd == stage_fd:
            hit("stage_fsync", "stage fsync fault")
        if fault == "cleanup_fsync" and unlink_succeeded:
            hit("cleanup_fsync", "cleanup fsync fault")
        if fault == "loser_fsync" and unlink_succeeded:
            hit("loser_fsync", "loser fsync fault")
        if fault == "post_rename_fsync" and publication_succeeded:
            hit("post_rename_fsync", "post-rename parent fsync fault")
        real_fsync(fd)

    def faulting_close(fd: int) -> None:
        label = fd_labels.pop(fd, "unknown")
        close_attempts[label] = close_attempts.get(label, 0) + 1
        if fault == "stage_close" and fd == stage_fd:
            real_close(fd)
            hit("stage_close", "stage close fault")
        if fault == f"{label}_close":
            real_close(fd)
            hit(fault, f"{label} close fault")
        real_close(fd)

    def faulting_publish(*args: object) -> None:
        nonlocal publication_succeeded
        if fault in {"publish", "cleanup_unlink", "cleanup_fsync"}:
            hit("publish", "publication fault")
        real_publish(*args)  # type: ignore[arg-type]
        publication_succeeded = True

    def faulting_unlink(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        dir_fd: int | None = None,
    ) -> None:
        nonlocal unlink_succeeded
        if fault == "cleanup_unlink":
            hit("cleanup_unlink", "cleanup unlink fault")
        if fault == "loser_unlink":
            hit("loser_unlink", "loser unlink fault")
        real_unlink(path, dir_fd=dir_fd)
        unlink_succeeded = True
        cleanup_events.append(("unlink", os.fsdecode(path), dir_fd))

    def faulting_stat(
        path: str | bytes | int | os.PathLike[str] | os.PathLike[bytes],
        *,
        dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> os.stat_result:
        if fault == "winner_stat" and path == "candidate.md":
            hit("winner_stat", "winner stat fault")
        if fault == "winner_nonregular" and path == "candidate.md":
            arms["winner_nonregular"] = arms.get("winner_nonregular", 0) + 1
        return real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(os, "mkdir", faulting_mkdir)
    monkeypatch.setattr(os, "open", faulting_open)
    monkeypatch.setattr(os, "write", faulting_write)
    monkeypatch.setattr(os, "fsync", faulting_fsync)
    monkeypatch.setattr(os, "close", faulting_close)
    monkeypatch.setattr(os, "unlink", faulting_unlink)
    monkeypatch.setattr(os, "stat", faulting_stat)
    monkeypatch.setattr(write_ops, "_atomic_rename_noreplace_at", faulting_publish)

    outcome: object
    with oracle.observe():
        try:
            outcome = write_ops.create_candidate_note_once(
                "Sources/Nested/candidate.md",
                "complete candidate",
                vault_root=vault,
                action="candidate.test",
                write_guard=WriteGuard(lambda: {"state": "healthy"}),
            )
        except (OSError, RuntimeError) as exc:
            outcome = exc
    _assert_candidate_fault_outcome(outcome)

    expected_arms = (
        {"publish": 1, fault: 1} if fault in {"cleanup_unlink", "cleanup_fsync"} else {fault: 1}
    )
    assert arms == expected_arms
    _assert_exact_fd_ownership(oracle.opened, oracle.close_attempts, oracle.duplicates)
    assert oracle.active == {}
    assert fd_labels == {}
    if fault in {
        "root_close",
        "intermediate_close",
        "stage_close",
        "final_parent_close",
    }:
        assert close_attempts[fault.removesuffix("_close")] == 1

    if fault in {"final_parent_close", "post_rename_fsync"}:
        assert target.read_bytes() == b"complete candidate"
    elif fault in {"loser_unlink", "loser_fsync", "winner_stat"}:
        assert target.read_bytes() == b"winner"
    elif fault == "winner_nonregular":
        assert target.is_dir()
    else:
        assert not target.exists()

    hidden_names = [path.name for path in parent.glob(".candidate-stage-*")]
    assert_hidden_stage_state(
        hidden_names,
        sentinel_name=sentinel.name,
        expected_owned_count=1 if fault in {"cleanup_unlink", "loser_unlink"} else 0,
    )
    assert sentinel.read_bytes() == b"unrelated"
    if unlink_succeeded:
        unlink_index = next(
            index for index, event in enumerate(cleanup_events) if event[0] == "unlink"
        )
        _assert_cleanup_fence(cleanup_events[unlink_index:])

    if fault in {
        "publish",
        "cleanup_unlink",
        "cleanup_fsync",
        "loser_unlink",
        "loser_fsync",
        "winner_stat",
        "winner_nonregular",
        "post_rename_fsync",
    }:
        for false_success in ("already_exists", "written"):
            with pytest.raises(AssertionError):
                _assert_candidate_fault_outcome(false_success)
