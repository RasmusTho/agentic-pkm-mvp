"""Heimdal interest model + in-flow/post-hoc steering tests -- Epic #3019
slice A18 (#3043).

Covers the governing Issue's four behavioral Acceptance Criteria:

- ``test_weight_edit_is_intent`` -- a hand-edited `interests.md` weight is
  explicit intent and outranks inference: an agent's derived-column update
  (running before or after the hand-edit) never overwrites the human's
  weight.
- ``test_inflow_append_is_durable`` -- "watch this" / "never this" from
  chat OR an item appends durably to `watchlist.md` / `never.md`; both
  transports produce the identical durable append, and the append survives
  process/object boundaries (re-read from disk).
- ``test_posthoc_steering_is_append_only`` -- "less of this" / "mute" /
  "wrong" append immutable lines to `steering.log.md`; prior lines are
  never rewritten or reordered by a later append.
- ``test_agent_columns_are_read_only_for_human`` -- the agent-authored
  `confidence`/`evidence`/`decay` columns never overwrite a human's
  `weights` edit, even when the human edit happens *between* two agent
  updates (simulating an Obsidian edit mid-cycle).

Every test exercises the real production write call sites
(`app.heimdal.interest_steering.*`, backed by
`app.heimdal.settings_notes.apply_agent_update` / `write_settings_note` /
`app.knowledge.write_ops.append_note_relative` +
`app.write_guard.WriteGuard`), mirroring
`tests/heimdal/test_settings_notes.py`'s temp-vault-fixture convention: no
network, no real Postgres, no real vault.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import multiprocessing
import os
from pathlib import Path
import queue
import re
import stat
import subprocess
import sys

import pytest

from app.heimdal import interest_steering as steering_module
from app.heimdal.interest_steering import (
    InterestDerivedUpdate,
    apply_interest_derived_updates,
    append_never,
    append_steering_log,
    append_watch,
    read_inflow_body,
    read_interests,
    read_steering_log_body,
    set_interest_weight,
    update_source_filters,
)
from app.heimdal.settings_notes import (
    NEVER_LIST,
    SOURCE_CONFIG,
    STEERING_LOG,
    WATCHLIST,
    note_rel_path,
    read_settings_note,
)
from app.knowledge.errors import KnowledgeCapabilityError
from app.knowledge import write_ops as write_ops_module
from app.write_guard import WriteGuard, WritesBlockedError

pytestmark = pytest.mark.not_pg


def _vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _blocking_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "safe_mode", "reason": "test-induced block"})


# ---------------------------------------------------------------------------
# AC: a hand-edited interests.md weight is explicit intent and outranks
# inference.
# ---------------------------------------------------------------------------


def test_weight_edit_is_intent(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    # 1. Agent runs its own inference first, seeding derived columns for an
    #    interest with no human weight yet.
    apply_interest_derived_updates(
        vault_root,
        [InterestDerivedUpdate(interest="battery_chemistry", confidence=0.4, decay=0.1)],
        write_guard=guard,
    )

    # 2. The human explicitly sets a weight -- this is intent, not
    #    inference, and must be recorded distinctly.
    set_interest_weight(vault_root, "battery_chemistry", 0.9, write_guard=guard)

    # 3. The agent re-runs inference and would, left unchecked, derive a
    #    lower confidence/weight-adjacent signal -- but it must not be able
    #    to touch `weights` at all; only the human-facing path can.
    apply_interest_derived_updates(
        vault_root,
        [InterestDerivedUpdate(interest="battery_chemistry", confidence=0.55, evidence=["obs-1", "obs-2"])],
        write_guard=guard,
    )

    note = read_interests(vault_root)
    assert note is not None
    # The human's explicit weight survives every subsequent agent inference
    # pass untouched -- it outranks inference.
    assert note.values["weights"]["battery_chemistry"] == 0.9
    # The agent-authored columns still update normally alongside it.
    assert note.values["confidence"]["battery_chemistry"] == 0.55
    assert note.values["evidence"]["battery_chemistry"] == ["obs-1", "obs-2"]
    assert note.values["decay"]["battery_chemistry"] == 0.1  # preserved from the first pass


def test_weight_edit_after_agent_inference_is_not_overwritten_by_later_inference(tmp_path: Path) -> None:
    """A hand-edit made directly on disk (the literal Obsidian-edit path,
    not this module's `set_interest_weight` convenience) is honored
    identically -- the invariant is about the note, not about which
    function wrote it."""
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    apply_interest_derived_updates(
        vault_root,
        [InterestDerivedUpdate(interest="northvolt", confidence=0.2)],
        write_guard=guard,
    )

    # Simulate a direct Obsidian edit: reparse, mutate `weights`, re-render.
    from app.heimdal.settings_notes import INTERESTS, parse_note, render_note

    rel_path = note_rel_path(INTERESTS)
    path = vault_root / rel_path
    text = path.read_text(encoding="utf-8")
    reparsed = parse_note(INTERESTS, text)
    reparsed.values["weights"] = {"northvolt": 0.75}
    path.write_text(render_note(reparsed), encoding="utf-8")

    apply_interest_derived_updates(
        vault_root,
        [InterestDerivedUpdate(interest="northvolt", confidence=0.85)],
        write_guard=guard,
    )

    on_disk = read_interests(vault_root)
    assert on_disk is not None
    assert on_disk.values["weights"] == {"northvolt": 0.75}
    assert on_disk.values["confidence"]["northvolt"] == 0.85


# ---------------------------------------------------------------------------
# AC: in-flow "watch this" / "never this" from chat or an item appends
# durably to watchlist.md / never.md.
# ---------------------------------------------------------------------------


def test_inflow_append_is_durable(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    chat_line = append_watch(vault_root, "sources/youtube:northvolt", source="chat", write_guard=guard)
    item_line = append_watch(vault_root, "sources/youtube:battery-tech", source="item", write_guard=guard)

    body = read_inflow_body(vault_root, "watch")
    # Both transports' lines are present, in append order, in the same note
    # -- the action is a transport onto the note, not a distinct capability.
    assert chat_line in body
    assert item_line in body
    assert body.index(chat_line) < body.index(item_line)

    # The append is durable: re-reading fresh from disk (new read, not the
    # in-memory return value) still finds both lines.
    rel_path = note_rel_path(WATCHLIST)
    reread = (vault_root / rel_path).read_text(encoding="utf-8")
    assert chat_line in reread
    assert item_line in reread


def test_never_this_from_item_appends_durably(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    line = append_never(vault_root, "sources/spam_feed", source="item", note="reported by user", write_guard=guard)

    assert "source=item" in line
    assert "spam_feed" in line
    body = read_inflow_body(vault_root, "never")
    assert line in body

    rel_path = note_rel_path(NEVER_LIST)
    assert (vault_root / rel_path).exists()


def test_inflow_append_from_chat_and_item_produce_identical_durable_shape(tmp_path: Path) -> None:
    """Either surface produces the same durable note append -- neither
    transport is privileged or shaped differently."""
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    fixed_time = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)
    chat_line = append_watch(vault_root, "same-target", source="chat", write_guard=guard, at=fixed_time)
    item_line = append_watch(vault_root, "same-target", source="item", write_guard=guard, at=fixed_time)

    # Only the declared transport differs; everything else about the line
    # shape is identical.
    assert chat_line.replace("source=chat", "source=item") == item_line


def test_inflow_append_honors_write_guard_block(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    with pytest.raises(WritesBlockedError):
        append_watch(vault_root, "blocked-target", source="chat", write_guard=_blocking_guard())
    assert read_inflow_body(vault_root, "watch") == ""


def test_injected_guard_is_preserved_through_append_seam(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    vault_root = _vault(tmp_path)
    injected_guard = _allowing_guard()
    seam_calls: list[tuple[object, object]] = []
    real_append = steering_module.append_note_relative

    def recording_append(note_rel_path, content, **kwargs):  # type: ignore[no-untyped-def]
        seam_calls.append((kwargs.get("write_guard"), kwargs.get("action")))
        return real_append(note_rel_path, content, **kwargs)

    monkeypatch.setattr(
        steering_module.DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": "safe_mode", "reason": "default guard must not be used"},
    )
    monkeypatch.setattr(steering_module, "append_note_relative", recording_append)

    append_watch(
        vault_root,
        "sources/youtube:northvolt",
        source="chat",
        write_guard=injected_guard,
    )
    append_steering_log(
        vault_root,
        "mute",
        "sources/spam_feed",
        source="item",
        operation_id="injected-guard-posthoc",
        write_guard=injected_guard,
    )

    assert seam_calls == [
        (injected_guard, steering_module.INFLOW_APPEND_WRITE_ACTION),
        (injected_guard, steering_module.POSTHOC_STEERING_WRITE_ACTION),
    ]


# ---------------------------------------------------------------------------
# AC: post-hoc "less of this" / "mute" / "wrong" append immutable lines to
# steering.log.md.
# ---------------------------------------------------------------------------


def test_posthoc_steering_is_append_only(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    line1 = append_steering_log(
        vault_root,
        "less_of_this",
        "sources/youtube:crypto",
        source="chat",
        operation_id="append-only-1",
        write_guard=guard,
    )
    line2 = append_steering_log(
        vault_root,
        "mute",
        "sources/spam_feed",
        source="item",
        operation_id="append-only-2",
        write_guard=guard,
    )
    line3 = append_steering_log(
        vault_root,
        "wrong",
        "battery_chemistry",
        source="chat",
        operation_id="append-only-3",
        note="misattributed",
        write_guard=guard,
    )

    body = read_steering_log_body(vault_root)
    # All three lines present, in append order.
    assert body.index(line1) < body.index(line2) < body.index(line3)

    # Immutability: re-reading after a third append does not change the
    # bytes of the first two lines already on disk (append-only, not
    # rewrite-in-place).
    assert line1 in body
    assert line2 in body

    # The frontmatter bookkeeping tracks count/last-appended without
    # touching the body's prior entries.
    note = read_settings_note(vault_root, STEERING_LOG)
    assert note is not None
    assert note.values["entry_count"] == 3


def test_posthoc_steering_prior_lines_survive_verbatim_across_appends(tmp_path: Path) -> None:
    """Stronger immutability check: capture the on-disk bytes after the
    first append, then assert those exact bytes are an unmodified prefix
    of the body after two more appends -- nothing was rewritten in place."""
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    append_steering_log(
        vault_root,
        "wrong",
        "target-a",
        source="chat",
        operation_id="verbatim-a",
        write_guard=guard,
    )
    rel_path = note_rel_path(STEERING_LOG)
    after_first = (vault_root / rel_path).read_text(encoding="utf-8")

    append_steering_log(
        vault_root,
        "mute",
        "target-b",
        source="item",
        operation_id="verbatim-b",
        write_guard=guard,
    )
    append_steering_log(
        vault_root,
        "less_of_this",
        "target-c",
        source="chat",
        operation_id="verbatim-c",
        write_guard=guard,
    )
    after_third = (vault_root / rel_path).read_text(encoding="utf-8")

    # The guarded bookkeeping patch rewrites frontmatter each time, but the
    # appended body *lines* from the first write must still appear verbatim
    # and in original order in the final body.
    first_line = [ln for ln in after_first.splitlines() if "target-a" in ln][0]
    assert first_line in after_third.splitlines()


def test_posthoc_steering_honors_write_guard_block(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    with pytest.raises(WritesBlockedError):
        append_steering_log(
            vault_root,
            "mute",
            "blocked-target",
            source="chat",
            operation_id="blocked-posthoc",
            write_guard=_blocking_guard(),
        )
    assert read_steering_log_body(vault_root) == ""


def test_concurrent_steering_log_appends_preserve_all_entries_and_bookkeeping(
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    writer_count = 12
    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(writer_count)
    results = context.Queue()
    start = datetime(2026, 7, 30, 9, 0, 0, tzinfo=timezone.utc)

    def append_one(index: int) -> None:
        barrier.wait()
        try:
            line = append_steering_log(
                vault_root,
                "wrong",
                f"target-{index}",
                source="chat",
                operation_id=f"concurrent-{index}",
                at=start + timedelta(microseconds=index),
                write_guard=_allowing_guard(),
            )
        except BaseException as exc:  # noqa: BLE001 - preserve child failure evidence
            results.put(("error", repr(exc)))
            raise
        results.put(("ok", line))

    processes = [context.Process(target=append_one, args=(index,)) for index in range(writer_count)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    assert all(process.exitcode == 0 for process in processes)

    child_results = []
    try:
        for _index in range(writer_count):
            child_results.append(results.get(timeout=2))
    except queue.Empty:
        pytest.fail("concurrent steering writer failed to return a result")
    assert all(status == "ok" for status, _value in child_results)
    lines = [value for _status, value in child_results]

    body = read_steering_log_body(vault_root)
    assert all(body.count(line) == 1 for line in lines)
    assert body.count('"operation_id":"concurrent-') == writer_count

    note = read_settings_note(vault_root, STEERING_LOG)
    assert note is not None
    assert note.values["entry_count"] == writer_count
    last_entry = [line for line in body.splitlines() if '"operation_id":' in line][-1]
    assert note.values["last_appended"] == last_entry.split("]", 1)[0].removeprefix("- [")


def test_steering_log_retry_recovers_interrupted_states(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    rel_path = note_rel_path(STEERING_LOG)
    log_path = vault_root / rel_path

    real_rename_noreplace = write_ops_module._atomic_rename_noreplace_at
    monkeypatch.setattr(
        write_ops_module,
        "_atomic_rename_noreplace_at",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("initial publish")),
    )
    with pytest.raises(RuntimeError, match="initial publish"):
        append_steering_log(
            vault_root,
            "wrong",
            "atomic-seed",
            source="chat",
            operation_id="recover-atomic-seed",
            write_guard=guard,
        )
    assert not log_path.exists()
    assert not list(log_path.parent.glob(".atomic-append-*.tmp"))
    monkeypatch.setattr(
        write_ops_module,
        "_atomic_rename_noreplace_at",
        real_rename_noreplace,
    )

    seed_recovered = append_steering_log(
        vault_root,
        "wrong",
        "atomic-seed",
        source="chat",
        operation_id="recover-atomic-seed",
        write_guard=guard,
    )
    assert read_steering_log_body(vault_root).count(seed_recovered) == 1

    # Simulate the legacy split transaction: the durable operation exists in
    # the body while frontmatter bookkeeping still reflects the prior state.
    bookkeeping_line = append_steering_log(
        vault_root,
        "mute",
        "bookkeeping-pending",
        source="item",
        operation_id="recover-bookkeeping",
        write_guard=guard,
    )
    stale = log_path.read_bytes()
    stale = stale.replace(b"entry_count: 2", b"entry_count: 1", 1)
    stale = re.sub(
        rb"last_appended: ['\"]?[^\r\n'\"]+['\"]?",
        b"last_appended: null",
        stale,
        count=1,
    )
    log_path.write_bytes(stale)
    bookkeeping_recovered = append_steering_log(
        vault_root,
        "mute",
        "bookkeeping-pending",
        source="item",
        operation_id="recover-bookkeeping",
        write_guard=guard,
    )
    assert bookkeeping_recovered == bookkeeping_line
    assert read_steering_log_body(vault_root).count(bookkeeping_line) == 1

    real_write_all = write_ops_module._write_all

    def write_partial_then_fail(fd: int, content: bytes) -> None:
        os.write(fd, content[: max(1, len(content) // 2)])
        raise RuntimeError("stage write")

    monkeypatch.setattr(
        write_ops_module,
        "_write_all",
        write_partial_then_fail,
    )
    with pytest.raises(RuntimeError, match="stage write"):
        append_steering_log(
            vault_root,
            "wrong",
            "stage-write",
            source="chat",
            operation_id="recover-stage-write",
            write_guard=guard,
        )
    assert '"operation_id":"recover-stage-write"' not in read_steering_log_body(vault_root)
    monkeypatch.setattr(write_ops_module, "_write_all", real_write_all)
    stage_write_recovered = append_steering_log(
        vault_root,
        "wrong",
        "stage-write",
        source="chat",
        operation_id="recover-stage-write",
        write_guard=guard,
    )

    real_fsync = write_ops_module.os.fsync
    fail_next_file_fsync = True

    def fail_stage_fsync(fd: int) -> None:
        nonlocal fail_next_file_fsync
        if fail_next_file_fsync and stat.S_ISREG(os.fstat(fd).st_mode):
            fail_next_file_fsync = False
            raise RuntimeError("stage fsync")
        real_fsync(fd)

    monkeypatch.setattr(write_ops_module.os, "fsync", fail_stage_fsync)
    with pytest.raises(RuntimeError, match="stage fsync"):
        append_steering_log(
            vault_root,
            "wrong",
            "stage-fsync",
            source="chat",
            operation_id="recover-stage-fsync",
            write_guard=guard,
        )
    monkeypatch.setattr(write_ops_module.os, "fsync", real_fsync)
    stage_fsync_recovered = append_steering_log(
        vault_root,
        "wrong",
        "stage-fsync",
        source="chat",
        operation_id="recover-stage-fsync",
        write_guard=guard,
    )

    real_replace = write_ops_module.os.replace
    monkeypatch.setattr(
        write_ops_module.os,
        "replace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("transaction replace")),
    )
    with pytest.raises(RuntimeError, match="transaction replace"):
        append_steering_log(
            vault_root,
            "wrong",
            "replace",
            source="chat",
            operation_id="recover-replace",
            write_guard=guard,
        )
    monkeypatch.setattr(write_ops_module.os, "replace", real_replace)
    replace_recovered = append_steering_log(
        vault_root,
        "wrong",
        "replace",
        source="chat",
        operation_id="recover-replace",
        write_guard=guard,
    )

    published = False

    def publish_then_mark(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal published
        result = real_replace(*args, **kwargs)
        published = True
        return result

    def fail_directory_fsync(fd: int) -> None:
        real_fsync(fd)
        if published and stat.S_ISDIR(os.fstat(fd).st_mode):
            raise RuntimeError("directory fsync")

    monkeypatch.setattr(write_ops_module.os, "replace", publish_then_mark)
    monkeypatch.setattr(write_ops_module.os, "fsync", fail_directory_fsync)
    with pytest.raises(RuntimeError, match="directory fsync"):
        append_steering_log(
            vault_root,
            "wrong",
            "directory-fsync",
            source="chat",
            operation_id="recover-directory-fsync",
            write_guard=guard,
        )
    monkeypatch.setattr(write_ops_module.os, "replace", real_replace)
    monkeypatch.setattr(write_ops_module.os, "fsync", real_fsync)
    directory_fsync_recovered = append_steering_log(
        vault_root,
        "wrong",
        "directory-fsync",
        source="chat",
        operation_id="recover-directory-fsync",
        write_guard=guard,
    )

    body = read_steering_log_body(vault_root)
    for recovered_line in (
        bookkeeping_recovered,
        stage_write_recovered,
        stage_fsync_recovered,
        replace_recovered,
        directory_fsync_recovered,
    ):
        assert body.count(recovered_line) == 1
    assert body.count('"operation_id":') == 6
    note = read_settings_note(vault_root, STEERING_LOG)
    assert note is not None
    assert note.values["entry_count"] == 6


def test_steering_log_bookkeeping_preserves_existing_body_bytes(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "first",
        source="chat",
        operation_id="byte-preservation-first",
        note="operation_id=impersonator\nsecond physical line",
        write_guard=guard,
    )

    path = vault_root / note_rel_path(STEERING_LOG)
    raw = path.read_bytes()
    closing = raw.index(b"\n---", 4) + len(b"\n---")
    original_body = raw[closing:].replace(b"\n", b"\r\n") + b"\r\n"
    path.write_bytes(raw[:closing] + original_body)

    append_steering_log(
        vault_root,
        "mute\nwith-newline",
        "second",
        source="item",
        operation_id="byte-preservation-second",
        write_guard=guard,
    )
    impersonator_line = append_steering_log(
        vault_root,
        "wrong",
        "third",
        source="chat",
        operation_id="impersonator",
        write_guard=guard,
    )
    updated = path.read_bytes()
    updated_closing = updated.index(b"\n---", 4) + len(b"\n---")
    assert updated[updated_closing:].startswith(original_body)
    assert updated.count(b'"operation_id":"byte-preservation-first"') == 1
    assert updated.count(b'"operation_id":"byte-preservation-second"') == 1
    assert updated.decode("utf-8").count(impersonator_line) == 1


def test_steering_log_reconciles_legacy_entries_during_upgrade(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "current-entry",
        source="chat",
        operation_id="upgrade-current",
        write_guard=guard,
    )

    path = vault_root / note_rel_path(STEERING_LOG)
    raw = path.read_bytes()
    closing = raw.index(b"\n---", 4) + len(b"\n---")
    legacy_line = (
        b"- [2026-07-01T09:00:00Z] verb=mute source=item "
        b"target='legacy-entry' | pre-operation-id\n"
    )
    path.write_bytes(raw[:closing] + raw[closing:] + legacy_line)

    append_steering_log(
        vault_root,
        "less_of_this",
        "new-entry",
        source="item",
        operation_id="upgrade-new",
        write_guard=guard,
    )

    updated = path.read_bytes()
    note = read_settings_note(vault_root, STEERING_LOG)
    assert note is not None
    assert note.values["entry_count"] == 3
    assert legacy_line in updated


def test_steering_log_atomic_bookkeeping_preserves_restrictive_metadata(
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "first",
        source="chat",
        operation_id="metadata-first",
        write_guard=guard,
    )

    path = vault_root / note_rel_path(STEERING_LOG)
    path.chmod(0o600)
    attribute: str | None = None
    if sys.platform == "darwin":
        attribute = "com.agentic-pkm.test"
        subprocess.run(
            ["/usr/bin/xattr", "-w", attribute, "preserve-me", str(path)],
            check=True,
        )
    elif hasattr(os, "setxattr"):
        attribute = "user.agentic_pkm_test"
        os.setxattr(path, attribute, b"preserve-me", follow_symlinks=False)

    append_steering_log(
        vault_root,
        "mute",
        "second",
        source="item",
        operation_id="metadata-second",
        write_guard=guard,
    )

    assert stat.S_IMODE(path.stat(follow_symlinks=False).st_mode) == 0o600
    if sys.platform == "darwin" and attribute is not None:
        result = subprocess.run(
            ["/usr/bin/xattr", "-p", attribute, str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stdout.rstrip("\n") == "preserve-me"
    elif attribute is not None:
        assert os.getxattr(path, attribute, follow_symlinks=False) == b"preserve-me"


def test_steering_log_rejects_symlink_aliases_before_mutation(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped_vault = tmp_path / "escaped-vault"
    escaped_vault.mkdir()
    (escaped_vault / "_heimdal").symlink_to(outside, target_is_directory=True)

    with pytest.raises(KnowledgeCapabilityError, match="symlink"):
        append_steering_log(
            escaped_vault,
            "wrong",
            "escaped",
            source="chat",
            operation_id="escaped-parent",
            write_guard=_allowing_guard(),
        )
    assert list(outside.iterdir()) == []

    alias_vault = tmp_path / "alias-vault"
    alias_vault.mkdir()
    append_steering_log(
        alias_vault,
        "wrong",
        "seed",
        source="chat",
        operation_id="alias-seed",
        write_guard=_allowing_guard(),
    )
    alias_path = alias_vault / note_rel_path(STEERING_LOG)
    referent = alias_path.with_name("steering-referent.md")
    alias_path.replace(referent)
    alias_path.symlink_to(referent.name)
    before = referent.read_bytes()

    with pytest.raises(KnowledgeCapabilityError, match="symlink"):
        append_steering_log(
            alias_vault,
            "mute",
            "aliased",
            source="item",
            operation_id="final-alias",
            write_guard=_allowing_guard(),
        )
    assert alias_path.is_symlink()
    assert referent.read_bytes() == before


def test_steering_log_case_aliases_share_one_lock(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    alias_root = vault_root.with_name(vault_root.name.swapcase())
    try:
        if not alias_root.samefile(vault_root):
            pytest.skip("filesystem is case-sensitive")
    except FileNotFoundError:
        pytest.skip("filesystem is case-sensitive")

    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(2)
    results = context.Queue()

    def append_one(root: Path, operation_id: str) -> None:
        barrier.wait()
        try:
            append_steering_log(
                root,
                "wrong",
                operation_id,
                source="chat",
                operation_id=operation_id,
                write_guard=_allowing_guard(),
            )
        except BaseException as exc:  # noqa: BLE001 - child evidence
            results.put(("error", repr(exc)))
            raise
        results.put(("ok", operation_id))

    processes = [
        context.Process(target=append_one, args=(vault_root, "case-original")),
        context.Process(target=append_one, args=(alias_root, "case-alias")),
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
    assert all(process.exitcode == 0 for process in processes)
    assert [results.get(timeout=2)[0] for _index in range(2)] == ["ok", "ok"]

    body = read_steering_log_body(vault_root)
    assert body.count('"operation_id":"case-original"') == 1
    assert body.count('"operation_id":"case-alias"') == 1
    note = read_settings_note(vault_root, STEERING_LOG)
    assert note is not None
    assert note.values["entry_count"] == 2


def test_steering_log_racing_aliases_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id="race-seed",
        write_guard=guard,
    )
    path = vault_root / note_rel_path(STEERING_LOG)
    parked = path.with_name("steering-parked.md")
    diverted = path.with_name("steering-diverted.md")
    diverted.write_text("diverted sentinel\n", encoding="utf-8")
    real_append = steering_module.append_note_relative

    def swap_final_component(*args, **kwargs):  # type: ignore[no-untyped-def]
        path.replace(parked)
        path.symlink_to(diverted.name)
        try:
            return real_append(*args, **kwargs)
        finally:
            path.unlink(missing_ok=True)
            parked.replace(path)

    monkeypatch.setattr(steering_module, "append_note_relative", swap_final_component)
    with pytest.raises(KnowledgeCapabilityError, match="non-symlink"):
        append_steering_log(
            vault_root,
            "mute",
            "must-not-divert",
            source="item",
            operation_id="racing-final",
            write_guard=guard,
        )
    assert diverted.read_text(encoding="utf-8") == "diverted sentinel\n"
    assert '"operation_id":"racing-final"' not in read_steering_log_body(vault_root)

    fresh_vault = tmp_path / "fresh-race-vault"
    fresh_vault.mkdir()
    outside = tmp_path / "race-outside"
    outside.mkdir()
    parked_parent = fresh_vault / "_heimdal-parked"
    swapped = False
    real_write_all = write_ops_module._write_all

    def swap_parent(stage_fd: int, content: bytes) -> None:
        nonlocal swapped
        real_write_all(stage_fd, content)
        if not swapped:
            swapped = True
            (fresh_vault / "_heimdal").replace(parked_parent)
            (fresh_vault / "_heimdal").symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(write_ops_module, "_write_all", swap_parent)
    with pytest.raises(KnowledgeCapabilityError, match="parent mapping changed"):
        append_steering_log(
            fresh_vault,
            "wrong",
            "must-not-escape",
            source="chat",
            operation_id="racing-parent",
            write_guard=guard,
        )
    assert list(outside.iterdir()) == []
    assert not list(parked_parent.glob(".atomic-append-*.tmp"))


def test_steering_log_metadata_clone_failure_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    append_steering_log(
        vault_root,
        "wrong",
        "first",
        source="chat",
        operation_id="clone-first",
        write_guard=_allowing_guard(),
    )
    path = vault_root / note_rel_path(STEERING_LOG)
    before = path.read_bytes()
    monkeypatch.setattr(
        write_ops_module,
        "_copy_access_metadata",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("metadata clone failed")),
    )

    with pytest.raises(RuntimeError, match="metadata clone failed"):
        append_steering_log(
            vault_root,
            "mute",
            "second",
            source="item",
            operation_id="clone-second",
            write_guard=_allowing_guard(),
        )
    assert path.read_bytes().count(b'"operation_id":"clone-second"') == 0
    note = read_settings_note(vault_root, STEERING_LOG)
    assert note is not None
    assert note.values["entry_count"] == 1
    assert before == path.read_bytes()


def test_steering_log_new_parent_is_durably_linked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    root_identity = (vault_root.stat().st_dev, vault_root.stat().st_ino)
    synced_directories: list[tuple[int, int]] = []
    real_fsync = write_ops_module.os.fsync

    def record_fsync(fd: int) -> None:
        current = os.fstat(fd)
        if stat.S_ISDIR(current.st_mode):
            synced_directories.append((current.st_dev, current.st_ino))
        real_fsync(fd)

    monkeypatch.setattr(write_ops_module.os, "fsync", record_fsync)
    append_steering_log(
        vault_root,
        "wrong",
        "fresh-parent",
        source="chat",
        operation_id="fresh-parent",
        write_guard=_allowing_guard(),
    )
    assert root_identity in synced_directories


def test_steering_log_retries_only_after_fencing_uncertain_parent_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    root_identity = (vault_root.stat().st_dev, vault_root.stat().st_ino)
    real_fsync = write_ops_module.os.fsync
    failed = False

    def fail_first_root_fsync(fd: int) -> None:
        nonlocal failed
        current = os.fstat(fd)
        if not failed and (current.st_dev, current.st_ino) == root_identity:
            failed = True
            raise RuntimeError("root directory fsync")
        real_fsync(fd)

    monkeypatch.setattr(write_ops_module.os, "fsync", fail_first_root_fsync)
    with pytest.raises(RuntimeError, match="root directory fsync"):
        append_steering_log(
            vault_root,
            "wrong",
            "uncertain-parent",
            source="chat",
            operation_id="uncertain-parent",
            write_guard=_allowing_guard(),
        )
    path = vault_root / note_rel_path(STEERING_LOG)
    assert not path.exists()

    monkeypatch.setattr(write_ops_module.os, "fsync", real_fsync)
    recovered = append_steering_log(
        vault_root,
        "wrong",
        "uncertain-parent",
        source="chat",
        operation_id="uncertain-parent",
        write_guard=_allowing_guard(),
    )
    assert read_steering_log_body(vault_root).count(recovered) == 1


def test_steering_log_rejects_hard_link_alias_before_replacement(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    path = vault_root / note_rel_path(STEERING_LOG)
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id="hard-link-seed",
        write_guard=_allowing_guard(),
    )
    alias = path.with_name("steering-hard-link.md")
    os.link(path, alias)
    before = path.read_bytes()

    with pytest.raises(KnowledgeCapabilityError, match="hard-link aliases"):
        append_steering_log(
            vault_root,
            "mute",
            "must-not-split",
            source="item",
            operation_id="hard-link-rejected",
            write_guard=_allowing_guard(),
        )
    assert path.read_bytes() == before
    assert alias.read_bytes() == before


def test_steering_log_operation_id_collision_fails_loud(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    first_line = append_steering_log(
        vault_root,
        "wrong",
        "first-target",
        source="chat",
        operation_id="collision",
        write_guard=guard,
    )
    before_collision = read_steering_log_body(vault_root)

    with pytest.raises(ValueError, match="operation_id collision"):
        append_steering_log(
            vault_root,
            "mute",
            "different-target",
            source="item",
            operation_id="collision",
            write_guard=guard,
        )

    after_collision = read_steering_log_body(vault_root)
    assert before_collision == after_collision
    assert after_collision.count(first_line) == 1


# ---------------------------------------------------------------------------
# AC: agent-authored confidence/evidence/decay columns do not overwrite
# human weight edits.
# ---------------------------------------------------------------------------


def test_agent_columns_are_read_only_for_human(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    set_interest_weight(vault_root, "solid_state_batteries", 0.6, write_guard=guard)
    apply_interest_derived_updates(
        vault_root,
        [
            InterestDerivedUpdate(
                interest="solid_state_batteries",
                confidence=0.3,
                evidence=["obs-x"],
                decay=0.05,
            )
        ],
        write_guard=guard,
    )

    note = read_interests(vault_root)
    assert note is not None
    assert note.values["weights"] == {"solid_state_batteries": 0.6}
    assert note.values["confidence"] == {"solid_state_batteries": 0.3}
    assert note.values["evidence"] == {"solid_state_batteries": ["obs-x"]}
    assert note.values["decay"] == {"solid_state_batteries": 0.05}

    # Repeated agent updates keep refining the derived columns without ever
    # requiring or accepting a `weights` argument -- there is no code path
    # in `apply_interest_derived_updates`/`InterestDerivedUpdate` that can
    # carry a weight value at all.
    apply_interest_derived_updates(
        vault_root,
        [InterestDerivedUpdate(interest="solid_state_batteries", confidence=0.65)],
        write_guard=guard,
    )
    updated = read_interests(vault_root)
    assert updated is not None
    assert updated.values["weights"] == {"solid_state_batteries": 0.6}  # untouched
    assert updated.values["confidence"] == {"solid_state_batteries": 0.65}  # refined


def test_interest_derived_update_has_no_weight_field() -> None:
    """Structural guarantee: `InterestDerivedUpdate` cannot carry a weight
    value at all -- there is no field to smuggle one through."""
    update = InterestDerivedUpdate(interest="x", confidence=0.5)
    assert not hasattr(update, "weight")
    assert not hasattr(update, "weights")


# ---------------------------------------------------------------------------
# Per-source filters (sources/*.md) -- reuses A14's SOURCE_CONFIG verbatim.
# ---------------------------------------------------------------------------


def test_update_source_filters_writes_per_source_note(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    update_source_filters(vault_root, "youtube", ["exclude:clickbait", "include:battery"], write_guard=guard)

    note = read_settings_note(vault_root, SOURCE_CONFIG, source_id="youtube")
    assert note is not None
    assert note.values["filters"] == ["exclude:clickbait", "include:battery"]
    assert note.values["source_id"] == "youtube"

    rel_path = note_rel_path(SOURCE_CONFIG, source_id="youtube")
    assert rel_path == "_heimdal/sources/youtube.md"


def test_update_source_filters_is_per_instance(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    update_source_filters(vault_root, "youtube", ["include:battery"], write_guard=guard)
    update_source_filters(vault_root, "podcast_x", ["exclude:ads"], write_guard=guard)

    youtube = read_settings_note(vault_root, SOURCE_CONFIG, source_id="youtube")
    podcast = read_settings_note(vault_root, SOURCE_CONFIG, source_id="podcast_x")
    assert youtube is not None and youtube.values["filters"] == ["include:battery"]
    assert podcast is not None and podcast.values["filters"] == ["exclude:ads"]
