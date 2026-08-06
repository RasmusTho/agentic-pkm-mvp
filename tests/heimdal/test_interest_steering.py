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
import json
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
from app.knowledge.errors import KnowledgeCapabilityError, KnowledgeWriteConflict
from app.knowledge import write_ops as write_ops_module
from app.write_guard import WriteGuard, WritesBlockedError

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def _isolated_atomic_append_host_fence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host_temp_root = tmp_path / "host-temp"
    host_temp_root.mkdir()
    monkeypatch.setattr(
        steering_module.tempfile,
        "gettempdir",
        lambda: os.fspath(host_temp_root),
    )
    monkeypatch.setenv(
        "DESIGN_HANDOFF_APP_LOCAL_SETTINGS",
        str(tmp_path / "app-local-state" / "app-local.md"),
    )


def _host_fence_root() -> Path:
    return Path(os.environ["DESIGN_HANDOFF_APP_LOCAL_SETTINGS"]).parent


def _host_witness_paths(vault_root: Path) -> tuple[Path, ...]:
    lock_root = Path(steering_module.tempfile.gettempdir()) / (
        "agentic-pkm-heimdal-locks"
    )
    with write_ops_module._open_atomic_append_authority(
        vault_root,
        note_rel_path(STEERING_LOG),
    ) as authority:
        return tuple(
            lock_root
            / f"{steering_module.hashlib.sha256(key.encode('utf-8')).hexdigest()}.lock"
            for key in authority.host_state_keys
        )


def _host_route_paths(vault_root: Path) -> tuple[Path, Path, Path]:
    lock_root = Path(steering_module.tempfile.gettempdir()) / (
        "agentic-pkm-heimdal-locks"
    )
    with write_ops_module._open_atomic_append_authority(
        vault_root,
        note_rel_path(STEERING_LOG),
    ) as authority:
        token = steering_module.hashlib.sha256(
            authority.route_key.encode("utf-8")
        ).hexdigest()
    return (
        _host_fence_root() / f".heimdal-atomic-route-{token}.state",
        _host_fence_root() / f".heimdal-atomic-route-{token}.swap",
        lock_root / f"{token}.lock",
    )


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


def test_steering_log_unicode_line_separator_remains_one_structured_record(
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    first = append_steering_log(
        vault_root,
        "wrong",
        "before\u2028after",
        source="chat",
        operation_id="unicode-separator-first",
        write_guard=guard,
    )
    second = append_steering_log(
        vault_root,
        "mute",
        "next-entry",
        source="item",
        operation_id="unicode-separator-second",
        write_guard=guard,
    )

    body = read_steering_log_body(vault_root)
    assert "\\u2028" in first
    assert body.count(first) == 1
    assert body.count(second) == 1
    note = read_settings_note(vault_root, STEERING_LOG)
    assert note is not None
    assert note.values["entry_count"] == 2


def test_steering_log_malformed_frontmatter_fails_without_mutation(
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id="malformed-frontmatter-seed",
        write_guard=guard,
    )
    path = vault_root / note_rel_path(STEERING_LOG)
    raw = path.read_bytes()
    closing = raw.index(b"\n---", 4)
    malformed = b"---\nprivate_marker: [unterminated\n" + raw[closing:]
    path.write_bytes(malformed)

    with pytest.raises(ValueError, match="malformed YAML frontmatter"):
        append_steering_log(
            vault_root,
            "mute",
            "must-not-publish",
            source="item",
            operation_id="malformed-frontmatter-rejected",
            write_guard=guard,
        )

    assert path.read_bytes() == malformed
    assert b"malformed-frontmatter-rejected" not in malformed


def test_steering_log_rejects_unterminated_countable_record_without_mutation(
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id="unterminated-seed",
        write_guard=guard,
    )
    path = vault_root / note_rel_path(STEERING_LOG)
    malformed = path.read_bytes().removesuffix(b"\n")
    path.write_bytes(malformed)

    with pytest.raises(RuntimeError, match="unterminated steering log entry"):
        append_steering_log(
            vault_root,
            "mute",
            "must-not-concatenate",
            source="item",
            operation_id="unterminated-rejected",
            write_guard=guard,
        )

    assert path.read_bytes() == malformed
    assert b"unterminated-rejected" not in malformed


def test_steering_log_rejects_unterminated_human_body_tail_without_mutation(
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id="unterminated-human-seed",
        write_guard=guard,
    )
    path = vault_root / note_rel_path(STEERING_LOG)
    malformed = path.read_bytes() + b"Human-authored tail without newline"
    path.write_bytes(malformed)

    with pytest.raises(RuntimeError, match="unterminated steering log"):
        append_steering_log(
            vault_root,
            "mute",
            "must-not-concatenate",
            source="item",
            operation_id="unterminated-human-rejected",
            write_guard=guard,
        )

    assert path.read_bytes() == malformed
    assert b"unterminated-human-rejected" not in malformed


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
    assert len(list(log_path.parent.glob(".atomic-append-*"))) == 1
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
    assert not list(log_path.parent.glob(".atomic-append-*"))

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

    real_exchange = write_ops_module._atomic_exchange_at
    monkeypatch.setattr(
        write_ops_module,
        "_atomic_exchange_at",
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
    monkeypatch.setattr(write_ops_module, "_atomic_exchange_at", real_exchange)
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
        result = real_exchange(*args, **kwargs)
        published = True
        return result

    def fail_directory_fsync(fd: int) -> None:
        real_fsync(fd)
        if published and stat.S_ISDIR(os.fstat(fd).st_mode):
            raise RuntimeError("directory fsync")

    monkeypatch.setattr(write_ops_module, "_atomic_exchange_at", publish_then_mark)
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
    monkeypatch.setattr(write_ops_module, "_atomic_exchange_at", real_exchange)
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


def test_steering_log_retry_sweeps_process_crash_stage_to_root_recovery(
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    context = multiprocessing.get_context("fork")

    def crash_after_durable_stage() -> None:
        write_ops_module._publish_recovery_snapshot = (  # type: ignore[method-assign]
            lambda *_args, **_kwargs: os._exit(91)
        )
        append_steering_log(
            vault_root,
            "wrong",
            "crash-stage",
            source="chat",
            operation_id="crash-stage-retry",
            write_guard=_allowing_guard(),
        )

    process = context.Process(target=crash_after_durable_stage)
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 91
    parent = vault_root / "_heimdal"
    assert len(list(parent.glob(".atomic-append-*.stage"))) == 1

    durable_line = append_steering_log(
        vault_root,
        "wrong",
        "crash-stage",
        source="chat",
        operation_id="crash-stage-retry",
        write_guard=_allowing_guard(),
    )

    assert not list(parent.glob(".atomic-append-*"))
    assert read_steering_log_body(vault_root).count(durable_line) == 1
    recovery = vault_root / "_conflicts"
    assert any("owned-stage" in path.name for path in recovery.iterdir())


def test_steering_log_first_host_state_namespace_fsyncs_its_parent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    parent_identity = tmp_path.stat()
    real_fsync = write_ops_module.os.fsync
    parent_fsynced = False

    def record_fsync(fd: int) -> None:
        nonlocal parent_fsynced
        observed = os.fstat(fd)
        if (
            observed.st_dev == parent_identity.st_dev
            and observed.st_ino == parent_identity.st_ino
        ):
            parent_fsynced = True
        real_fsync(fd)

    monkeypatch.setattr(write_ops_module.os, "fsync", record_fsync)
    append_steering_log(
        vault_root,
        "wrong",
        "durable-host-namespace",
        source="chat",
        operation_id="durable-host-namespace",
        write_guard=_allowing_guard(),
    )

    assert parent_fsynced
    assert list(_host_fence_root().glob(".heimdal-atomic-append-*.state"))
    assert not (_host_fence_root() / "heimdal-atomic-append-fences").exists()


def test_steering_log_retry_reconciles_crash_precommitted_exchange_intent(
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id="intent-crash-seed",
        write_guard=guard,
    )
    context = multiprocessing.get_context("fork")

    def crash_after_intent_before_exchange() -> None:
        write_ops_module._atomic_exchange_at = (  # type: ignore[method-assign]
            lambda *_args, **_kwargs: os._exit(92)
        )
        append_steering_log(
            vault_root,
            "mute",
            "intent-crash",
            source="item",
            operation_id="intent-crash-proposal",
            write_guard=_allowing_guard(),
        )

    process = context.Process(target=crash_after_intent_before_exchange)
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 92
    states = list(_host_fence_root().glob(".heimdal-atomic-append-*.state"))
    assert states
    assert any(json.loads(path.read_text())["state"] == "active" for path in states)

    durable_line = append_steering_log(
        vault_root,
        "mute",
        "intent-crash",
        source="item",
        operation_id="intent-crash-proposal",
        write_guard=guard,
    )

    assert read_steering_log_body(vault_root).count(durable_line) == 1
    assert all(json.loads(path.read_text())["state"] == "clean" for path in states)


@pytest.mark.parametrize("replace_vault_root", [False, True])
def test_steering_log_crash_with_app_local_namespace_loss_remains_blocked(
    tmp_path: Path,
    replace_vault_root: bool,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id=f"app-loss-{replace_vault_root}-seed",
        write_guard=guard,
    )
    host_root = _host_fence_root()
    parked_host_root = tmp_path / f"parked-app-state-{replace_vault_root}"
    parked_vault_root = tmp_path / "parked-vault-after-crash"
    witness_paths = _host_witness_paths(vault_root)
    context = multiprocessing.get_context("fork")

    def crash_after_exchange_and_replace_app_state() -> None:
        def replace_namespaces_before_clean(*_args: object) -> None:
            host_root.replace(parked_host_root)
            host_root.mkdir()
            if replace_vault_root:
                vault_root.replace(parked_vault_root)
                vault_root.mkdir()
            os._exit(93)

        write_ops_module._complete_host_atomic_append_intent = (  # type: ignore[method-assign]
            replace_namespaces_before_clean
        )
        append_steering_log(
            vault_root,
            "mute",
            "crash-after-app-state-loss",
            source="item",
            operation_id=f"app-loss-{replace_vault_root}-proposal",
            write_guard=_allowing_guard(),
        )

    process = context.Process(target=crash_after_exchange_and_replace_app_state)
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 93

    parked_states = list(
        parked_host_root.glob(".heimdal-atomic-append-*.state")
    )
    assert parked_states
    assert all(
        json.loads(path.read_text())["state"] == "active" for path in parked_states
    )
    assert all(
        json.loads(path.read_text())["state"] == "active"
        for path in witness_paths
    )
    assert not list(host_root.glob(".heimdal-atomic-append-*.state"))

    expected_failure = (
        "app-local route changed"
        if replace_vault_root
        else "app-local state is missing"
    )
    with pytest.raises(KnowledgeWriteConflict, match=expected_failure):
        append_steering_log(
            vault_root,
            "mute",
            "crash-after-app-state-loss",
            source="item",
            operation_id=f"app-loss-{replace_vault_root}-proposal",
            write_guard=guard,
        )

    durable_root = parked_vault_root if replace_vault_root else vault_root
    durable = (durable_root / note_rel_path(STEERING_LOG)).read_text(encoding="utf-8")
    assert durable.count(f'"operation_id":"app-loss-{replace_vault_root}-proposal"') == 1
    if replace_vault_root:
        assert not (vault_root / note_rel_path(STEERING_LOG)).exists()
    assert not list(host_root.glob(".heimdal-atomic-append-*.state"))


def test_steering_log_crash_with_host_witness_loss_remains_blocked(
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id="witness-loss-seed",
        write_guard=guard,
    )
    witness_paths = _host_witness_paths(vault_root)
    parked_witnesses = tuple(
        tmp_path / f"parked-host-witness-{index}.lock"
        for index, _path in enumerate(witness_paths)
    )
    context = multiprocessing.get_context("fork")

    def crash_after_exchange_and_replace_witnesses() -> None:
        def replace_witnesses_before_clean(*_args: object) -> None:
            for witness, parked in zip(
                witness_paths,
                parked_witnesses,
                strict=True,
            ):
                witness.replace(parked)
            os._exit(94)

        write_ops_module._complete_host_atomic_append_intent = (  # type: ignore[method-assign]
            replace_witnesses_before_clean
        )
        append_steering_log(
            vault_root,
            "mute",
            "crash-after-witness-loss",
            source="item",
            operation_id="witness-loss-proposal",
            write_guard=_allowing_guard(),
        )

    process = context.Process(target=crash_after_exchange_and_replace_witnesses)
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 94
    states = list(_host_fence_root().glob(".heimdal-atomic-append-*.state"))
    assert states
    assert all(json.loads(path.read_text())["state"] == "active" for path in states)
    assert all(
        json.loads(path.read_text())["state"] == "active"
        for path in parked_witnesses
    )

    with pytest.raises(KnowledgeWriteConflict, match="host witness is missing"):
        append_steering_log(
            vault_root,
            "mute",
            "crash-after-witness-loss",
            source="item",
            operation_id="witness-loss-proposal",
            write_guard=guard,
        )

    durable = (vault_root / note_rel_path(STEERING_LOG)).read_text(encoding="utf-8")
    assert durable.count('"operation_id":"witness-loss-proposal"') == 1
    assert all(path.exists() and path.stat().st_size == 0 for path in witness_paths)


def test_steering_log_clean_state_recovers_after_temporary_witness_loss(
    tmp_path: Path,
) -> None:
    isolated_temp_root = Path(steering_module.tempfile.gettempdir())
    assert isolated_temp_root == tmp_path / "host-temp"
    unrelated_lock_root = tmp_path / "unrelated-host-temp" / (
        "agentic-pkm-heimdal-locks"
    )
    unrelated_lock_root.mkdir(parents=True)
    unrelated_sentinel = unrelated_lock_root / "unrelated-live-resource.lock"
    unrelated_sentinel.write_text("held elsewhere\n", encoding="utf-8")

    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id="clean-witness-loss-seed",
        write_guard=guard,
    )
    state_paths = sorted(_host_fence_root().glob(".heimdal-atomic-append-*.state"))
    assert len(state_paths) == 2
    assert all(json.loads(path.read_text())["state"] == "clean" for path in state_paths)

    witness_paths = _host_witness_paths(vault_root)
    lock_root = witness_paths[0].parent
    for path in lock_root.iterdir():
        path.unlink()
    lock_root.rmdir()

    durable_line = append_steering_log(
        vault_root,
        "mute",
        "after-clean-witness-loss",
        source="item",
        operation_id="clean-witness-loss-proposal",
        write_guard=guard,
    )

    assert read_steering_log_body(vault_root).count(durable_line) == 1
    assert all(path.exists() and path.stat().st_size > 0 for path in witness_paths)
    assert len(list(_host_fence_root().glob(".heimdal-atomic-append-*.state"))) == 2
    assert unrelated_sentinel.read_text(encoding="utf-8") == "held elsewhere\n"


def test_steering_log_incomplete_clean_state_without_witness_remains_blocked(
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id="incomplete-clean-seed",
        write_guard=guard,
    )
    state_paths = sorted(_host_fence_root().glob(".heimdal-atomic-append-*.state"))
    assert len(state_paths) == 2
    witness_paths = _host_witness_paths(vault_root)
    lock_root = witness_paths[0].parent
    for path in lock_root.iterdir():
        path.unlink()
    lock_root.rmdir()
    state_paths[0].unlink()

    with pytest.raises(KnowledgeWriteConflict, match="app-local state is missing"):
        append_steering_log(
            vault_root,
            "mute",
            "after-incomplete-clean",
            source="item",
            operation_id="incomplete-clean-proposal",
            write_guard=guard,
        )

    assert '"operation_id":"incomplete-clean-proposal"' not in read_steering_log_body(
        vault_root
    )


@pytest.mark.parametrize("crash_point", ["active-app", "clean-witness"])
def test_steering_log_active_state_dominates_clean_interleaving(
    tmp_path: Path,
    crash_point: str,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id=f"state-dominance-{crash_point}-seed",
        write_guard=guard,
    )
    context = multiprocessing.get_context("fork")

    def crash_between_inventory_writes() -> None:
        real_app_write = write_ops_module._write_host_append_state
        real_witness_write = write_ops_module._write_host_witness_state

        def crash_before_active_app_write(*args: object) -> None:
            payload = args[3]
            if isinstance(payload, dict) and payload.get("state") == "active":
                os._exit(95)
            real_app_write(*args)  # type: ignore[arg-type]

        def crash_before_clean_witness_write(*args: object) -> None:
            payload = args[1]
            if isinstance(payload, dict) and payload.get("state") == "clean":
                os._exit(96)
            real_witness_write(*args)  # type: ignore[arg-type]

        if crash_point == "active-app":
            write_ops_module._write_host_append_state = (  # type: ignore[method-assign]
                crash_before_active_app_write
            )
        else:
            write_ops_module._write_host_witness_state = (  # type: ignore[method-assign]
                crash_before_clean_witness_write
            )
        append_steering_log(
            vault_root,
            "mute",
            "inventory-write-interleaving",
            source="item",
            operation_id=f"state-dominance-{crash_point}-proposal",
            write_guard=_allowing_guard(),
        )

    process = context.Process(target=crash_between_inventory_writes)
    process.start()
    process.join(timeout=10)
    assert process.exitcode == (95 if crash_point == "active-app" else 96)

    durable_line = append_steering_log(
        vault_root,
        "mute",
        "inventory-write-interleaving",
        source="item",
        operation_id=f"state-dominance-{crash_point}-proposal",
        write_guard=guard,
    )

    assert read_steering_log_body(vault_root).count(durable_line) == 1
    states = list(_host_fence_root().glob(".heimdal-atomic-append-*.state"))
    assert states
    assert all(json.loads(path.read_text())["state"] == "clean" for path in states)
    assert all(
        json.loads(path.read_text())["state"] == "clean"
        for path in _host_witness_paths(vault_root)
    )


@pytest.mark.parametrize(
    "substitution",
    ["unlink", "valid", "malformed", "hard-link"],
)
def test_steering_log_app_state_substitution_before_clean_never_receipts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    substitution: str,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id=f"app-record-substitution-{substitution}-seed",
        write_guard=guard,
    )
    real_complete = write_ops_module._complete_host_atomic_append_intent

    def substitute_app_record_before_clean(*args: object) -> None:
        state_path = next(
            _host_fence_root().glob(".heimdal-atomic-append-*.state")
        )
        original = state_path.read_bytes()
        if substitution == "unlink":
            state_path.unlink()
        elif substitution == "valid":
            payload = json.loads(original)
            payload["transaction"] = "foreign-clean-transaction"
            state_path.write_text(
                json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        elif substitution == "malformed":
            state_path.write_text("{malformed", encoding="utf-8")
        else:
            parked = tmp_path / "parked-app-record.state"
            linked = tmp_path / "linked-app-record.state"
            state_path.replace(parked)
            linked.write_bytes(original)
            os.link(linked, state_path)
        real_complete(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(
        write_ops_module,
        "_complete_host_atomic_append_intent",
        substitute_app_record_before_clean,
    )
    with pytest.raises((KnowledgeWriteConflict, KnowledgeCapabilityError)):
        append_steering_log(
            vault_root,
            "mute",
            "substituted-app-record",
            source="item",
            operation_id=f"app-record-substitution-{substitution}-proposal",
            write_guard=guard,
        )

    durable = (vault_root / note_rel_path(STEERING_LOG)).read_text(encoding="utf-8")
    assert durable.count(
        f'"operation_id":"app-record-substitution-{substitution}-proposal"'
    ) == 1
    assert all(
        json.loads(path.read_text())["state"] in {"active", "indeterminate"}
        for path in _host_witness_paths(vault_root)
    )


@pytest.mark.parametrize("mismatch", ["transaction", "payload"])
def test_steering_log_paired_clean_state_mismatch_blocks_before_active(
    tmp_path: Path,
    mismatch: str,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id=f"paired-clean-mismatch-{mismatch}-seed",
        write_guard=guard,
    )
    state_path = next(_host_fence_root().glob(".heimdal-atomic-append-*.state"))
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    if mismatch == "transaction":
        payload["transaction"] = "foreign-clean-transaction"
    else:
        payload["target_digest"] = "0" * 64
    state_path.write_text(
        json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(KnowledgeWriteConflict, match="paired host state"):
        append_steering_log(
            vault_root,
            "mute",
            "paired-clean-mismatch",
            source="item",
            operation_id=f"paired-clean-mismatch-{mismatch}-proposal",
            write_guard=guard,
        )

    durable = (vault_root / note_rel_path(STEERING_LOG)).read_text(encoding="utf-8")
    assert f'"operation_id":"paired-clean-mismatch-{mismatch}-proposal"' not in durable


def test_steering_log_app_state_substitution_at_active_transition_blocks(
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
        operation_id="active-transition-substitution-seed",
        write_guard=guard,
    )
    real_prepare = write_ops_module._prepare_host_atomic_append_intent

    def substitute_immediately_before_active(*args: object, **kwargs: object) -> None:
        state_path = next(
            _host_fence_root().glob(".heimdal-atomic-append-*.state")
        )
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        payload["transaction"] = "foreign-before-active"
        state_path.write_text(
            json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        real_prepare(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        write_ops_module,
        "_prepare_host_atomic_append_intent",
        substitute_immediately_before_active,
    )
    with pytest.raises(KnowledgeWriteConflict, match="paired host state"):
        append_steering_log(
            vault_root,
            "mute",
            "active-transition-substitution",
            source="item",
            operation_id="active-transition-substitution-proposal",
            write_guard=guard,
        )

    durable = (vault_root / note_rel_path(STEERING_LOG)).read_text(encoding="utf-8")
    assert '"operation_id":"active-transition-substitution-proposal"' not in durable


def test_steering_log_app_state_exchange_proves_displaced_record(
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
        operation_id="state-exchange-proof-seed",
        write_guard=guard,
    )
    real_exchange = write_ops_module._atomic_host_state_exchange_at
    substituted = False

    def substitute_after_snapshot_then_exchange(*args: object) -> None:
        nonlocal substituted
        if not substituted:
            substituted = True
            fence_fd = args[0]
            state_name = args[1]
            assert isinstance(fence_fd, int)
            assert isinstance(state_name, str)
            state_fd = os.open(state_name, os.O_RDWR, dir_fd=fence_fd)
            try:
                raw = os.read(state_fd, 1024 * 1024)
                payload = json.loads(raw)
                payload["transaction"] = "foreign-after-snapshot"
                replacement = (
                    json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n"
                ).encode("utf-8")
                os.ftruncate(state_fd, 0)
                os.lseek(state_fd, 0, os.SEEK_SET)
                os.write(state_fd, replacement)
                os.fsync(state_fd)
            finally:
                os.close(state_fd)
        real_exchange(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(
        write_ops_module,
        "_atomic_host_state_exchange_at",
        substitute_after_snapshot_then_exchange,
    )
    with pytest.raises(KnowledgeWriteConflict, match="state changed during transition"):
        append_steering_log(
            vault_root,
            "mute",
            "state-exchange-proof",
            source="item",
            operation_id="state-exchange-proof-proposal",
            write_guard=guard,
        )

    assert substituted
    durable = (vault_root / note_rel_path(STEERING_LOG)).read_text(encoding="utf-8")
    assert '"operation_id":"state-exchange-proof-proposal"' not in durable


@pytest.mark.parametrize("replacement", ["lock-file", "lock-root"])
def test_steering_log_live_lock_authority_replacement_never_receipts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    replacement: str,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id=f"live-{replacement}-seed",
        write_guard=guard,
    )
    witness_paths = _host_witness_paths(vault_root)
    lock_root = witness_paths[0].parent
    parked_lock_root = tmp_path / "parked-live-lock-root"
    parked_witness = tmp_path / "parked-live-lock-file"
    real_complete = write_ops_module._complete_host_atomic_append_intent

    def replace_lock_authority_before_clean(*args: object) -> None:
        if replacement == "lock-root":
            lock_root.replace(parked_lock_root)
            lock_root.mkdir()
        else:
            witness_paths[0].replace(parked_witness)
            witness_paths[0].touch(mode=0o600)
        real_complete(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(
        write_ops_module,
        "_complete_host_atomic_append_intent",
        replace_lock_authority_before_clean,
    )
    with pytest.raises(KnowledgeWriteConflict, match="host witness authority changed"):
        append_steering_log(
            vault_root,
            "mute",
            "live-lock-replacement",
            source="item",
            operation_id=f"live-{replacement}-proposal",
            write_guard=guard,
        )

    monkeypatch.setattr(
        write_ops_module,
        "_complete_host_atomic_append_intent",
        real_complete,
    )
    with pytest.raises(KnowledgeWriteConflict, match="host witness is missing"):
        append_steering_log(
            vault_root,
            "mute",
            "live-lock-replacement",
            source="item",
            operation_id=f"live-{replacement}-proposal",
            write_guard=guard,
        )
    durable = (vault_root / note_rel_path(STEERING_LOG)).read_text(encoding="utf-8")
    assert durable.count(f'"operation_id":"live-{replacement}-proposal"') == 1


def test_steering_log_original_snapshot_unlink_retains_bounded_full_copy(
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
        operation_id="original-unlink-seed",
        write_guard=guard,
    )
    target = vault_root / note_rel_path(STEERING_LOG)
    original = target.read_bytes()
    real_retain = write_ops_module._retain_latest_original_snapshot

    def unlink_original_before_retention(
        recovery_fd: int,
        entry: object,
        **kwargs: object,
    ) -> object:
        assert isinstance(entry, write_ops_module._RecoveryEntry)
        os.unlink(entry.name, dir_fd=recovery_fd)
        os.fsync(recovery_fd)
        return real_retain(recovery_fd, entry, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        write_ops_module,
        "_retain_latest_original_snapshot",
        unlink_original_before_retention,
    )
    with pytest.raises(
        KnowledgeWriteConflict,
        match="recovery retirement became indeterminate",
    ):
        append_steering_log(
            vault_root,
            "mute",
            "unlink-original-snapshot",
            source="item",
            operation_id="original-unlink-proposal",
            write_guard=guard,
        )

    stable_name = write_ops_module._latest_original_recovery_name(
        note_rel_path(STEERING_LOG)
    )
    assert (vault_root / "_conflicts" / stable_name).read_bytes() == original
    assert target.read_text(encoding="utf-8").count(
        '"operation_id":"original-unlink-proposal"'
    ) == 1


@pytest.mark.parametrize("mutation", ["unlink", "substitute"])
def test_steering_log_latest_original_loss_before_cleanup_preserves_prior_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id=f"latest-loss-{mutation}-seed",
        write_guard=guard,
    )
    target = vault_root / note_rel_path(STEERING_LOG)
    original = target.read_bytes()
    sentinel = b"unrelated latest-original replacement\n"
    real_retain = write_ops_module._retain_latest_original_snapshot

    def retain_then_remove_name(
        recovery_fd: int,
        entry: object,
        **kwargs: object,
    ) -> object:
        retained = real_retain(recovery_fd, entry, **kwargs)  # type: ignore[arg-type]
        assert isinstance(retained, write_ops_module._RecoveryEntry)
        os.unlink(retained.name, dir_fd=recovery_fd)
        if mutation == "substitute":
            replacement_fd = os.open(
                retained.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=recovery_fd,
            )
            try:
                os.write(replacement_fd, sentinel)
                os.fsync(replacement_fd)
            finally:
                os.close(replacement_fd)
        os.fsync(recovery_fd)
        return retained

    monkeypatch.setattr(
        write_ops_module,
        "_retain_latest_original_snapshot",
        retain_then_remove_name,
    )
    with pytest.raises(
        KnowledgeWriteConflict,
        match="recovery retirement became indeterminate",
    ):
        append_steering_log(
            vault_root,
            "mute",
            "latest-original-loss",
            source="item",
            operation_id=f"latest-loss-{mutation}-proposal",
            write_guard=guard,
        )

    recovery = vault_root / "_conflicts"
    assert any(path.read_bytes() == original for path in recovery.iterdir())
    if mutation == "substitute":
        stable_name = write_ops_module._latest_original_recovery_name(
            note_rel_path(STEERING_LOG)
        )
        assert (recovery / stable_name).read_bytes() == sentinel
    assert target.read_text(encoding="utf-8").count(
        f'"operation_id":"latest-loss-{mutation}-proposal"'
    ) == 1


def test_steering_log_latest_original_loss_during_final_receipt_preserves_prior_bytes(
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
        operation_id="latest-receipt-loss-seed",
        write_guard=guard,
    )
    target = vault_root / note_rel_path(STEERING_LOG)
    original = target.read_bytes()
    stable_name = write_ops_module._latest_original_recovery_name(
        note_rel_path(STEERING_LOG)
    )
    real_complete = write_ops_module._complete_host_atomic_append_intent

    def complete_then_unlink_latest(*args: object, **kwargs: object) -> None:
        real_complete(*args, **kwargs)  # type: ignore[arg-type]
        recovery_fd = args[2]
        assert isinstance(recovery_fd, int)
        os.unlink(stable_name, dir_fd=recovery_fd)
        os.fsync(recovery_fd)

    monkeypatch.setattr(
        write_ops_module,
        "_complete_host_atomic_append_intent",
        complete_then_unlink_latest,
    )
    with pytest.raises(KnowledgeWriteConflict, match="receipt became indeterminate"):
        append_steering_log(
            vault_root,
            "mute",
            "latest-original-receipt-loss",
            source="item",
            operation_id="latest-receipt-loss-proposal",
            write_guard=guard,
        )

    recovery = vault_root / "_conflicts"
    assert any(path.read_bytes() == original for path in recovery.iterdir())
    assert target.read_text(encoding="utf-8").count(
        '"operation_id":"latest-receipt-loss-proposal"'
    ) == 1


def test_steering_log_active_inode_state_blocks_same_root_relocation(
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id="inode-relocation-seed",
        write_guard=guard,
    )
    context = multiprocessing.get_context("fork")

    def crash_after_exchange() -> None:
        write_ops_module._complete_host_atomic_append_intent = (  # type: ignore[method-assign]
            lambda *_args, **_kwargs: os._exit(97)
        )
        append_steering_log(
            vault_root,
            "mute",
            "inode-relocation",
            source="item",
            operation_id="inode-relocation-proposal",
            write_guard=_allowing_guard(),
        )

    process = context.Process(target=crash_after_exchange)
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 97

    relocated_root = tmp_path / "relocated-vault"
    vault_root.replace(relocated_root)
    with pytest.raises(KnowledgeWriteConflict, match="host state is invalid"):
        append_steering_log(
            relocated_root,
            "mute",
            "inode-relocation",
            source="item",
            operation_id="inode-relocation-proposal",
            write_guard=guard,
        )
    durable = (relocated_root / note_rel_path(STEERING_LOG)).read_text(
        encoding="utf-8"
    )
    assert durable.count('"operation_id":"inode-relocation-proposal"') == 1


def test_steering_log_conflicting_active_transactions_across_aliases_block(
    tmp_path: Path,
) -> None:
    real_root = tmp_path / "cross-alias-vault"
    real_root.mkdir()
    lexical_root = tmp_path / "cross-alias-link"
    lexical_root.symlink_to(real_root, target_is_directory=True)
    guard = _allowing_guard()
    append_steering_log(
        lexical_root,
        "wrong",
        "seed",
        source="chat",
        operation_id="cross-alias-active-seed",
        write_guard=guard,
    )

    state_paths = list(_host_fence_root().glob(".heimdal-atomic-append-*.state"))
    witness_paths = list(_host_witness_paths(lexical_root))
    keys = sorted(
        json.loads(path.read_text(encoding="utf-8"))["path_lock_key"]
        for path in state_paths
    )
    transaction_by_key = {
        key: ("active-transaction-a" if index == 0 else "active-transaction-b")
        for index, key in enumerate(keys)
    }
    for path in [*state_paths, *witness_paths]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["state"] = "active"
        payload["transaction"] = transaction_by_key[payload["path_lock_key"]]
        path.write_text(
            json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    with pytest.raises(KnowledgeWriteConflict, match="conflicting transactions"):
        append_steering_log(
            lexical_root,
            "mute",
            "cross-alias-active",
            source="item",
            operation_id="cross-alias-active-proposal",
            write_guard=guard,
        )
    durable = (real_root / note_rel_path(STEERING_LOG)).read_text(encoding="utf-8")
    assert '"operation_id":"cross-alias-active-proposal"' not in durable


def test_steering_log_nonwritable_original_fails_before_publication(
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id="nonwritable-original-seed",
        write_guard=guard,
    )
    target = vault_root / note_rel_path(STEERING_LOG)
    original = target.read_bytes()
    recovery = vault_root / "_conflicts"
    prior_recovery = {path.name: path.read_bytes() for path in recovery.iterdir()}
    target.chmod(0o400)
    try:
        with pytest.raises(KnowledgeCapabilityError, match="writable before publication"):
            append_steering_log(
                vault_root,
                "mute",
                "nonwritable-original",
                source="item",
                operation_id="nonwritable-original-proposal",
                write_guard=guard,
            )
    finally:
        target.chmod(0o600)

    assert target.read_bytes() == original
    assert {path.name: path.read_bytes() for path in recovery.iterdir()} == prior_recovery


def test_steering_log_latest_original_retention_is_bounded(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "first",
        source="chat",
        operation_id="bounded-original-first",
        write_guard=guard,
    )
    first_complete = (vault_root / note_rel_path(STEERING_LOG)).read_bytes()
    append_steering_log(
        vault_root,
        "mute",
        "second",
        source="item",
        operation_id="bounded-original-second",
        write_guard=guard,
    )
    stable = list(
        (vault_root / "_conflicts").glob(
            ".steering-append-latest-original-*.md.conflict"
        )
    )
    assert len(stable) == 1
    assert stable[0].read_bytes() == first_complete


def test_steering_log_preexisting_latest_original_substitution_blocks_rotation(
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "first",
        source="chat",
        operation_id="prior-slot-substitution-first",
        write_guard=guard,
    )
    append_steering_log(
        vault_root,
        "mute",
        "second",
        source="item",
        operation_id="prior-slot-substitution-second",
        write_guard=guard,
    )
    target = vault_root / note_rel_path(STEERING_LOG)
    before_third = target.read_bytes()
    recovery = vault_root / "_conflicts"
    stable_name = write_ops_module._latest_original_recovery_name(
        note_rel_path(STEERING_LOG)
    )
    stable = recovery / stable_name
    authentic = stable.read_bytes()
    parked = recovery / ".parked-authentic-latest-original"
    stable.replace(parked)
    sentinel = b"unrelated preexisting latest-original content\n"
    stable.write_bytes(sentinel)

    with pytest.raises(KnowledgeWriteConflict, match="reconciliation is required"):
        append_steering_log(
            vault_root,
            "boost",
            "third",
            source="item",
            operation_id="prior-slot-substitution-third",
            write_guard=guard,
        )

    assert target.read_bytes() == before_third
    assert stable.read_bytes() == sentinel
    assert parked.read_bytes() == authentic


def test_steering_log_latest_original_substitution_during_rotation_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "first",
        source="chat",
        operation_id="live-slot-substitution-first",
        write_guard=guard,
    )
    append_steering_log(
        vault_root,
        "mute",
        "second",
        source="item",
        operation_id="live-slot-substitution-second",
        write_guard=guard,
    )
    recovery = vault_root / "_conflicts"
    stable_name = write_ops_module._latest_original_recovery_name(
        note_rel_path(STEERING_LOG)
    )
    stable = recovery / stable_name
    authentic = stable.read_bytes()
    parked = recovery / ".parked-live-authentic-latest-original"
    sentinel = b"unrelated live latest-original content\n"
    real_retain = write_ops_module._retain_latest_original_snapshot

    def substitute_before_rotation(
        recovery_fd: int,
        entry: object,
        **kwargs: object,
    ) -> object:
        os.rename(
            stable_name,
            parked.name,
            src_dir_fd=recovery_fd,
            dst_dir_fd=recovery_fd,
        )
        replacement_fd = os.open(
            stable_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=recovery_fd,
        )
        try:
            os.write(replacement_fd, sentinel)
            os.fsync(replacement_fd)
        finally:
            os.close(replacement_fd)
        os.fsync(recovery_fd)
        return real_retain(recovery_fd, entry, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        write_ops_module,
        "_retain_latest_original_snapshot",
        substitute_before_rotation,
    )
    with pytest.raises(
        KnowledgeWriteConflict,
        match="recovery retirement became indeterminate",
    ):
        append_steering_log(
            vault_root,
            "boost",
            "third",
            source="item",
            operation_id="live-slot-substitution-third",
            write_guard=guard,
        )

    assert stable.read_bytes() == sentinel
    assert parked.read_bytes() == authentic
    assert (vault_root / note_rel_path(STEERING_LOG)).read_text(
        encoding="utf-8"
    ).count('"operation_id":"live-slot-substitution-third"') == 1


def test_steering_log_retry_recovers_crash_after_latest_original_rotation(
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id="post-rotation-crash-seed",
        write_guard=guard,
    )
    context = multiprocessing.get_context("fork")

    def crash_before_clean_state() -> None:
        write_ops_module._complete_host_atomic_append_intent = (  # type: ignore[method-assign]
            lambda *_args, **_kwargs: os._exit(98)
        )
        append_steering_log(
            vault_root,
            "mute",
            "post-rotation-crash",
            source="item",
            operation_id="post-rotation-crash-proposal",
            write_guard=_allowing_guard(),
        )

    process = context.Process(target=crash_before_clean_state)
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 98

    target = vault_root / note_rel_path(STEERING_LOG)
    assert target.read_text(encoding="utf-8").count(
        '"operation_id":"post-rotation-crash-proposal"'
    ) == 1
    durable_line = append_steering_log(
        vault_root,
        "mute",
        "post-rotation-crash",
        source="item",
        operation_id="post-rotation-crash-proposal",
        write_guard=guard,
    )
    assert durable_line
    assert target.read_text(encoding="utf-8").count(
        '"operation_id":"post-rotation-crash-proposal"'
    ) == 1
    states = list(_host_fence_root().glob(".heimdal-atomic-append-*.state"))
    assert states
    assert all(json.loads(path.read_text())["state"] == "clean" for path in states)


def test_steering_log_missing_post_rotation_original_cannot_look_pre_rotation(
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id="missing-post-rotation-seed",
        write_guard=guard,
    )
    target = vault_root / note_rel_path(STEERING_LOG)
    seed_bytes = target.read_bytes()
    context = multiprocessing.get_context("fork")

    def crash_before_clean_state() -> None:
        write_ops_module._complete_host_atomic_append_intent = (  # type: ignore[method-assign]
            lambda *_args, **_kwargs: os._exit(101)
        )
        append_steering_log(
            vault_root,
            "mute",
            "missing-post-rotation",
            source="item",
            operation_id="missing-post-rotation-proposal",
            write_guard=_allowing_guard(),
        )

    process = context.Process(target=crash_before_clean_state)
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 101
    assert target.read_text(encoding="utf-8").count(
        '"operation_id":"missing-post-rotation-proposal"'
    ) == 1

    recovery = vault_root / "_conflicts"
    stable_name = write_ops_module._latest_original_recovery_name(
        note_rel_path(STEERING_LOG)
    )
    stable = recovery / stable_name
    assert stable.read_bytes() == seed_bytes
    stable.unlink()
    recovery_fd = os.open(recovery, os.O_RDONLY)
    try:
        os.fsync(recovery_fd)
    finally:
        os.close(recovery_fd)

    with pytest.raises(KnowledgeWriteConflict, match="reconciliation is required"):
        append_steering_log(
            vault_root,
            "mute",
            "missing-post-rotation",
            source="item",
            operation_id="missing-post-rotation-proposal",
            write_guard=guard,
        )
    states = list(_host_fence_root().glob(".heimdal-atomic-append-*.state"))
    assert states
    assert all(
        json.loads(path.read_text())["state"] == "indeterminate" for path in states
    )


def test_steering_log_initial_create_retry_recovers_active_precommit_crash(
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    target = vault_root / note_rel_path(STEERING_LOG)
    context = multiprocessing.get_context("fork")

    def crash_after_active_precommit() -> None:
        real_prepare = write_ops_module._prepare_host_atomic_append_intent

        def prepare_then_exit(*args: object, **kwargs: object) -> None:
            real_prepare(*args, **kwargs)  # type: ignore[arg-type]
            os._exit(99)

        write_ops_module._prepare_host_atomic_append_intent = (  # type: ignore[method-assign]
            prepare_then_exit
        )
        append_steering_log(
            vault_root,
            "wrong",
            "initial-precommit-crash",
            source="chat",
            operation_id="initial-precommit-crash-proposal",
            write_guard=_allowing_guard(),
        )

    process = context.Process(target=crash_after_active_precommit)
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 99
    assert not target.exists()

    durable_line = append_steering_log(
        vault_root,
        "wrong",
        "initial-precommit-crash",
        source="chat",
        operation_id="initial-precommit-crash-proposal",
        write_guard=guard,
    )
    assert durable_line
    assert target.read_text(encoding="utf-8").count(
        '"operation_id":"initial-precommit-crash-proposal"'
    ) == 1
    states = list(_host_fence_root().glob(".heimdal-atomic-append-*.state"))
    assert states
    assert all(json.loads(path.read_text())["state"] == "clean" for path in states)


def test_steering_log_missing_published_initial_target_cannot_look_prepublication(
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    target = vault_root / note_rel_path(STEERING_LOG)
    context = multiprocessing.get_context("fork")

    def crash_before_clean_state() -> None:
        write_ops_module._complete_host_atomic_append_intent = (  # type: ignore[method-assign]
            lambda *_args, **_kwargs: os._exit(102)
        )
        append_steering_log(
            vault_root,
            "wrong",
            "published-initial-target",
            source="chat",
            operation_id="published-initial-target-first",
            write_guard=_allowing_guard(),
        )

    process = context.Process(target=crash_before_clean_state)
    process.start()
    process.join(timeout=10)
    assert process.exitcode == 102
    assert target.read_text(encoding="utf-8").count(
        '"operation_id":"published-initial-target-first"'
    ) == 1

    target.unlink()
    parent_fd = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)

    with pytest.raises(KnowledgeWriteConflict, match="reconciliation is required"):
        append_steering_log(
            vault_root,
            "mute",
            "later-operation",
            source="item",
            operation_id="published-initial-target-second",
            write_guard=guard,
        )
    assert not target.exists()
    states = list(_host_fence_root().glob(".heimdal-atomic-append-*.state"))
    assert states
    assert all(
        json.loads(path.read_text())["state"] == "indeterminate" for path in states
    )


@pytest.mark.parametrize("fail_write", [1, 2, 3, 4])
def test_steering_log_multi_alias_state_write_failure_never_false_receipts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fail_write: int,
) -> None:
    real_root = tmp_path / "state-write-vault"
    real_root.mkdir()
    lexical_root = tmp_path / "state-write-alias"
    lexical_root.symlink_to(real_root, target_is_directory=True)
    guard = _allowing_guard()
    append_steering_log(
        lexical_root,
        "wrong",
        "seed",
        source="chat",
        operation_id=f"state-write-{fail_write}-seed",
        write_guard=guard,
    )
    real_write_state = write_ops_module._write_host_append_state
    writes = 0
    failed = False

    def fail_indexed_state_write(*args: object) -> None:
        nonlocal writes, failed
        writes += 1
        if writes == fail_write and not failed:
            failed = True
            raise OSError("indexed host state write failure")
        real_write_state(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(
        write_ops_module,
        "_write_host_append_state",
        fail_indexed_state_write,
    )
    with pytest.raises((OSError, KnowledgeWriteConflict)):
        append_steering_log(
            lexical_root,
            "mute",
            "indexed-state-write",
            source="item",
            operation_id=f"state-write-{fail_write}-proposal",
            write_guard=guard,
        )

    assert failed
    body = read_steering_log_body(real_root)
    proposal_count = body.count(f'"operation_id":"state-write-{fail_write}-proposal"')
    assert proposal_count == (0 if fail_write <= 2 else 1)
    monkeypatch.setattr(write_ops_module, "_write_host_append_state", real_write_state)
    if fail_write <= 2:
        durable_line = append_steering_log(
            lexical_root,
            "mute",
            "indexed-state-write",
            source="item",
            operation_id=f"state-write-{fail_write}-proposal",
            write_guard=guard,
        )
        assert read_steering_log_body(real_root).count(durable_line) == 1
    else:
        with pytest.raises(KnowledgeWriteConflict, match="reconciliation is required"):
            append_steering_log(
                lexical_root,
                "mute",
                "indexed-state-write",
                source="item",
                operation_id=f"state-write-{fail_write}-proposal",
                write_guard=guard,
            )


def test_steering_log_held_app_local_authority_blocks_namespace_swap_receipt(
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
        operation_id="host-authority-swap-seed",
        write_guard=guard,
    )
    host_root = _host_fence_root()
    parked_host_root = host_root.with_name("app-local-state-parked")
    real_complete = write_ops_module._complete_host_atomic_append_intent

    def replace_host_authority_before_clean(*args: object) -> None:
        host_root.replace(parked_host_root)
        host_root.mkdir()
        real_complete(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(
        write_ops_module,
        "_complete_host_atomic_append_intent",
        replace_host_authority_before_clean,
    )
    with pytest.raises(KnowledgeWriteConflict, match="host state authority changed"):
        append_steering_log(
            vault_root,
            "mute",
            "host-authority-swap",
            source="item",
            operation_id="host-authority-swap-proposal",
            write_guard=guard,
        )

    parked_states = list(
        parked_host_root.glob(".heimdal-atomic-append-*.state")
    )
    assert parked_states
    assert all(json.loads(path.read_text())["state"] == "active" for path in parked_states)
    assert not list(host_root.glob(".heimdal-atomic-append-*.state"))


def test_steering_log_exchange_race_retains_every_version_and_blocks_retry(
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
        operation_id="exchange-race-seed",
        write_guard=guard,
    )
    real_exchange = write_ops_module._atomic_exchange_at
    racing_line = b"- [2026-08-06T10:00:00Z] verb=mute source=item target='racer'\n"

    def append_racer_then_exchange(
        first_dir_fd: int,
        first_name: str,
        second_dir_fd: int,
        second_name: str,
    ) -> None:
        racer_fd = os.open(first_name, os.O_WRONLY | os.O_APPEND, dir_fd=first_dir_fd)
        try:
            os.write(racer_fd, racing_line)
            os.fsync(racer_fd)
        finally:
            os.close(racer_fd)
        real_exchange(first_dir_fd, first_name, second_dir_fd, second_name)

    monkeypatch.setattr(write_ops_module, "_atomic_exchange_at", append_racer_then_exchange)
    with pytest.raises(KnowledgeWriteConflict, match="exchange raced"):
        append_steering_log(
            vault_root,
            "mute",
            "proposal",
            source="item",
            operation_id="exchange-race-proposal",
            write_guard=guard,
        )

    recovery = vault_root / "_conflicts"
    assert any(racing_line in path.read_bytes() for path in recovery.iterdir())
    monkeypatch.setattr(write_ops_module, "_atomic_exchange_at", real_exchange)
    with pytest.raises(KnowledgeWriteConflict, match="reconciliation is required"):
        append_steering_log(
            vault_root,
            "mute",
            "proposal",
            source="item",
            operation_id="exchange-race-proposal",
            write_guard=guard,
        )


def test_steering_log_idempotent_retry_revalidates_before_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    durable_line = append_steering_log(
        vault_root,
        "wrong",
        "retry-race",
        source="chat",
        operation_id="retry-race-operation",
        write_guard=guard,
    )
    path = vault_root / note_rel_path(STEERING_LOG)
    before = path.read_bytes()
    real_mapping = write_ops_module._require_atomic_append_mapping
    mapping_calls = 0

    def remove_operation_at_final_revalidation(*args: object) -> None:
        nonlocal mapping_calls
        mapping_calls += 1
        if mapping_calls == 2:
            path.write_bytes(before.replace(durable_line.encode("utf-8"), b"", 1))
        real_mapping(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(
        write_ops_module,
        "_require_atomic_append_mapping",
        remove_operation_at_final_revalidation,
    )
    with pytest.raises(KnowledgeWriteConflict, match="target changed"):
        append_steering_log(
            vault_root,
            "wrong",
            "retry-race",
            source="chat",
            operation_id="retry-race-operation",
            write_guard=guard,
        )


def test_steering_log_idempotent_retry_rejects_pathname_inode_aba(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    durable_line = append_steering_log(
        vault_root,
        "wrong",
        "retry-aba",
        source="chat",
        operation_id="retry-aba-operation",
        write_guard=guard,
    )
    path = vault_root / note_rel_path(STEERING_LOG)
    real_exchange = write_ops_module._atomic_exchange_at
    raced = False

    def replace_same_bytes_then_exchange(
        first_dir_fd: int,
        first_name: str,
        second_dir_fd: int,
        second_name: str,
    ) -> None:
        nonlocal raced
        if not raced:
            raced = True
            original = os.stat(first_name, dir_fd=first_dir_fd, follow_symlinks=False)
            payload_fd = os.open(first_name, os.O_RDONLY, dir_fd=first_dir_fd)
            try:
                payload = os.read(payload_fd, original.st_size + 1)
            finally:
                os.close(payload_fd)
            os.rename(
                first_name,
                ".retry-aba-original",
                src_dir_fd=first_dir_fd,
                dst_dir_fd=first_dir_fd,
            )
            replacement_fd = os.open(
                first_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                stat.S_IMODE(original.st_mode),
                dir_fd=first_dir_fd,
            )
            try:
                os.write(replacement_fd, payload)
                os.fsync(replacement_fd)
            finally:
                os.close(replacement_fd)
        real_exchange(first_dir_fd, first_name, second_dir_fd, second_name)

    monkeypatch.setattr(
        write_ops_module,
        "_atomic_exchange_at",
        replace_same_bytes_then_exchange,
    )
    with pytest.raises(KnowledgeWriteConflict):
        append_steering_log(
            vault_root,
            "wrong",
            "retry-aba",
            source="chat",
            operation_id="retry-aba-operation",
            write_guard=guard,
        )

    monkeypatch.setattr(write_ops_module, "_atomic_exchange_at", real_exchange)
    with pytest.raises(KnowledgeWriteConflict, match="reconciliation is required"):
        append_steering_log(
            vault_root,
            "wrong",
            "retry-aba",
            source="chat",
            operation_id="retry-aba-operation",
            write_guard=guard,
        )
    assert durable_line in (path.parent / ".retry-aba-original").read_text(
        encoding="utf-8"
    )


def test_steering_log_post_exchange_parent_remap_is_indeterminate(
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
        operation_id="post-exchange-remap-seed",
        write_guard=guard,
    )
    parent = vault_root / "_heimdal"
    parked = vault_root / "_heimdal-parked"
    real_exchange = write_ops_module._atomic_exchange_at

    def exchange_then_remap(*args: object) -> None:
        real_exchange(*args)  # type: ignore[arg-type]
        parent.replace(parked)
        parent.mkdir()

    monkeypatch.setattr(write_ops_module, "_atomic_exchange_at", exchange_then_remap)
    with pytest.raises(KnowledgeWriteConflict, match="mapping indeterminate"):
        append_steering_log(
            vault_root,
            "mute",
            "remapped",
            source="item",
            operation_id="post-exchange-remap-proposal",
            write_guard=guard,
        )

    recovery = vault_root / "_conflicts"
    assert any("indeterminate" in path.name for path in recovery.iterdir())
    monkeypatch.setattr(write_ops_module, "_atomic_exchange_at", real_exchange)
    with pytest.raises(KnowledgeWriteConflict, match="reconciliation is required"):
        append_steering_log(
            vault_root,
            "mute",
            "remapped",
            source="item",
            operation_id="post-exchange-remap-proposal",
            write_guard=guard,
        )


@pytest.mark.parametrize("remap", ["root", "recovery"])
def test_steering_log_post_exchange_authority_replacement_keeps_external_fence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    remap: str,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id=f"{remap}-remap-seed",
        write_guard=guard,
    )
    real_exchange = write_ops_module._atomic_exchange_at
    parked_root = tmp_path / "parked-vault"
    parked_recovery = vault_root / "_conflicts-parked"

    def exchange_then_replace_authority(*args: object) -> None:
        real_exchange(*args)  # type: ignore[arg-type]
        if remap == "root":
            vault_root.replace(parked_root)
            vault_root.mkdir()
        else:
            (vault_root / "_conflicts").replace(parked_recovery)
            (vault_root / "_conflicts").mkdir()

    monkeypatch.setattr(
        write_ops_module,
        "_atomic_exchange_at",
        exchange_then_replace_authority,
    )
    with pytest.raises(KnowledgeWriteConflict, match="mapping indeterminate"):
        append_steering_log(
            vault_root,
            "mute",
            "authority-remap",
            source="item",
            operation_id=f"{remap}-remap-proposal",
            write_guard=guard,
        )

    fence_root = _host_fence_root()
    states = list(fence_root.glob(".heimdal-atomic-append-*.state"))
    assert states
    assert any(json.loads(path.read_text())["state"] == "indeterminate" for path in states)
    monkeypatch.setattr(write_ops_module, "_atomic_exchange_at", real_exchange)
    with pytest.raises(KnowledgeWriteConflict, match="reconciliation is required"):
        append_steering_log(
            vault_root,
            "mute",
            "authority-remap",
            source="item",
            operation_id=f"{remap}-remap-proposal",
            write_guard=guard,
        )

    durable_root = parked_root if remap == "root" else vault_root
    durable = (durable_root / note_rel_path(STEERING_LOG)).read_text(encoding="utf-8")
    assert durable.count(f'"operation_id":"{remap}-remap-proposal"') == 1


def test_steering_log_symlinked_root_retarget_cannot_escape_lexical_fence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root_a = tmp_path / "vault-a"
    root_b = tmp_path / "vault-b"
    root_a.mkdir()
    root_b.mkdir()
    lexical_root = tmp_path / "vault-alias"
    lexical_root.symlink_to(root_a, target_is_directory=True)
    guard = _allowing_guard()
    append_steering_log(
        lexical_root,
        "wrong",
        "seed",
        source="chat",
        operation_id="symlink-root-seed",
        write_guard=guard,
    )
    real_exchange = write_ops_module._atomic_exchange_at

    def exchange_then_retarget(*args: object) -> None:
        real_exchange(*args)  # type: ignore[arg-type]
        lexical_root.unlink()
        lexical_root.symlink_to(root_b, target_is_directory=True)

    monkeypatch.setattr(write_ops_module, "_atomic_exchange_at", exchange_then_retarget)
    with pytest.raises(KnowledgeWriteConflict, match="mapping indeterminate"):
        append_steering_log(
            lexical_root,
            "mute",
            "retargeted-root",
            source="item",
            operation_id="symlink-root-proposal",
            write_guard=guard,
        )

    monkeypatch.setattr(write_ops_module, "_atomic_exchange_at", real_exchange)
    with pytest.raises(KnowledgeWriteConflict, match="reconciliation is required"):
        append_steering_log(
            lexical_root,
            "mute",
            "retargeted-root",
            source="item",
            operation_id="symlink-root-proposal",
            write_guard=guard,
        )
    assert not (root_b / "_heimdal").exists()
    durable = (root_a / note_rel_path(STEERING_LOG)).read_text(encoding="utf-8")
    assert durable.count('"operation_id":"symlink-root-proposal"') == 1


@pytest.mark.parametrize("retirement_role", ["displaced", "retired"])
def test_steering_log_retirement_never_deletes_substituted_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    retirement_role: str,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id=f"retirement-{retirement_role}-seed",
        write_guard=guard,
    )
    real_move = write_ops_module._move_entry_to_recovery
    substituted_name: str | None = None
    sentinel = b"must survive retirement race\n"

    def move_then_substitute(
        source_fd: int,
        source_name: str,
        expected: os.stat_result,
        recovery_fd: int,
        destination_name: str,
    ) -> os.stat_result:
        nonlocal substituted_name
        retained = real_move(
            source_fd,
            source_name,
            expected,
            recovery_fd,
            destination_name,
        )
        role_matches = (
            retirement_role == "displaced" and "-displaced-" in destination_name
        ) or (
            retirement_role == "retired" and "-retired-" in destination_name
        )
        if substituted_name is None and role_matches:
            substituted_name = destination_name
            os.rename(
                destination_name,
                f".parked-{retirement_role}",
                src_dir_fd=recovery_fd,
                dst_dir_fd=recovery_fd,
            )
            sentinel_fd = os.open(
                destination_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=recovery_fd,
            )
            try:
                os.write(sentinel_fd, sentinel)
                os.fsync(sentinel_fd)
            finally:
                os.close(sentinel_fd)
        return retained

    monkeypatch.setattr(
        write_ops_module,
        "_move_entry_to_recovery",
        move_then_substitute,
    )
    with pytest.raises(KnowledgeWriteConflict, match="retirement"):
        append_steering_log(
            vault_root,
            "mute",
            "retirement-race",
            source="item",
            operation_id=f"retirement-{retirement_role}-proposal",
            write_guard=guard,
        )

    assert substituted_name is not None
    assert (vault_root / "_conflicts" / substituted_name).read_bytes() == sentinel


@pytest.mark.parametrize("remap", ["target", "parent", "root", "recovery"])
def test_steering_log_retirement_window_remap_fails_with_durable_host_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    remap: str,
) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    append_steering_log(
        vault_root,
        "wrong",
        "seed",
        source="chat",
        operation_id=f"retirement-remap-{remap}-seed",
        write_guard=guard,
    )
    target = vault_root / note_rel_path(STEERING_LOG)
    parent = target.parent
    recovery = vault_root / "_conflicts"
    parked_root = tmp_path / "retirement-parked-root"
    real_retire = write_ops_module._retire_recovery_entry
    remapped = False

    def retire_then_remap(*args: object) -> None:
        nonlocal remapped
        real_retire(*args)  # type: ignore[arg-type]
        if remapped:
            return
        remapped = True
        if remap == "target":
            target.replace(parent / ".retirement-target-parked")
            target.write_bytes(b"sentinel replacement\n")
        elif remap == "parent":
            parent.replace(vault_root / "_heimdal-parked")
            parent.mkdir()
        elif remap == "root":
            vault_root.replace(parked_root)
            vault_root.mkdir()
        else:
            recovery.replace(vault_root / "_conflicts-parked")
            recovery.mkdir()

    monkeypatch.setattr(
        write_ops_module,
        "_retire_recovery_entry",
        retire_then_remap,
    )
    with pytest.raises(KnowledgeWriteConflict, match="receipt became indeterminate"):
        append_steering_log(
            vault_root,
            "mute",
            "retirement-remap",
            source="item",
            operation_id=f"retirement-remap-{remap}-proposal",
            write_guard=guard,
        )

    states = list(_host_fence_root().glob(".heimdal-atomic-append-*.state"))
    assert states
    assert all(json.loads(path.read_text())["state"] == "indeterminate" for path in states)
    if remap == "target":
        assert target.read_bytes() == b"sentinel replacement\n"

    monkeypatch.setattr(write_ops_module, "_retire_recovery_entry", real_retire)
    with pytest.raises(KnowledgeWriteConflict, match="reconciliation is required"):
        append_steering_log(
            vault_root,
            "mute",
            "retirement-remap",
            source="item",
            operation_id=f"retirement-remap-{remap}-proposal",
            write_guard=guard,
        )


def test_steering_log_final_mapping_remap_after_clean_state_is_refenced(
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
        operation_id="final-mapping-remap-seed",
        write_guard=guard,
    )
    parked_root = tmp_path / "final-mapping-parked-root"
    real_mapping = write_ops_module._require_atomic_append_mapping
    mapping_calls = 0

    def remap_at_second_receipt_proof(*args: object) -> None:
        nonlocal mapping_calls
        mapping_calls += 1
        if mapping_calls == 5:
            vault_root.replace(parked_root)
            vault_root.mkdir()
        real_mapping(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(
        write_ops_module,
        "_require_atomic_append_mapping",
        remap_at_second_receipt_proof,
    )
    with pytest.raises(KnowledgeWriteConflict, match="receipt became indeterminate"):
        append_steering_log(
            vault_root,
            "mute",
            "final-mapping-remap",
            source="item",
            operation_id="final-mapping-remap-proposal",
            write_guard=guard,
        )

    states = list(_host_fence_root().glob(".heimdal-atomic-append-*.state"))
    assert states
    assert all(json.loads(path.read_text())["state"] == "indeterminate" for path in states)


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
    path.chmod(0o6750)
    attribute: str | None = None
    acl_before: bytes | None = None
    if sys.platform == "darwin":
        attribute = "com.agentic-pkm.test"
        subprocess.run(
            ["/usr/bin/xattr", "-w", attribute, "preserve-me", str(path)],
            check=True,
        )
        subprocess.run(
            ["/bin/chmod", "+a", "everyone allow read", str(path)],
            check=True,
        )
        acl_fd = os.open(path, os.O_RDONLY)
        try:
            acl_before = write_ops_module._darwin_acl_text(acl_fd)
        finally:
            os.close(acl_fd)
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

    assert stat.S_IMODE(path.stat(follow_symlinks=False).st_mode) == 0o6750
    if sys.platform == "darwin" and attribute is not None:
        result = subprocess.run(
            ["/usr/bin/xattr", "-p", attribute, str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stdout.rstrip("\n") == "preserve-me"
        acl_fd = os.open(path, os.O_RDONLY)
        try:
            assert write_ops_module._darwin_acl_text(acl_fd) == acl_before
        finally:
            os.close(acl_fd)
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

    with write_ops_module._open_atomic_append_authority(
        vault_root,
        note_rel_path(STEERING_LOG),
    ) as original_authority:
        original_route_key = original_authority.route_key
    with write_ops_module._open_atomic_append_authority(
        alias_root,
        note_rel_path(STEERING_LOG),
    ) as alias_authority:
        alias_route_key = alias_authority.route_key
    assert original_route_key == alias_route_key

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


def test_steering_log_equivalent_root_spellings_share_durable_authority(
    tmp_path: Path,
) -> None:
    real_root = tmp_path / "equivalent-root-vault"
    real_root.mkdir()
    alias_root = tmp_path / "equivalent-root-alias"
    alias_root.symlink_to(real_root, target_is_directory=True)

    with write_ops_module._open_atomic_append_authority(
        real_root,
        note_rel_path(STEERING_LOG),
    ) as real_authority:
        real_keys = real_authority.host_state_keys
    with write_ops_module._open_atomic_append_authority(
        alias_root,
        note_rel_path(STEERING_LOG),
    ) as alias_authority:
        alias_keys = alias_authority.host_state_keys
    assert real_keys == alias_keys

    guard = _allowing_guard()
    first = append_steering_log(
        real_root,
        "wrong",
        "real-spelling",
        source="chat",
        operation_id="equivalent-root-real",
        write_guard=guard,
    )
    second = append_steering_log(
        alias_root,
        "mute",
        "alias-spelling",
        source="item",
        operation_id="equivalent-root-alias",
        write_guard=guard,
    )

    body = read_steering_log_body(real_root)
    assert body.count(first) == 1
    assert body.count(second) == 1
    assert len(list(_host_fence_root().glob(".heimdal-atomic-append-*.state"))) == 2
    assert len(list(_host_fence_root().glob(".heimdal-atomic-route-*.state"))) == 2


@pytest.mark.parametrize("missing_copy", ["app-local", "temporary"])
def test_steering_log_route_binding_recovers_one_copy_and_still_blocks_retarget(
    tmp_path: Path,
    missing_copy: str,
) -> None:
    root_a = tmp_path / f"route-copy-{missing_copy}-a"
    root_b = tmp_path / f"route-copy-{missing_copy}-b"
    root_a.mkdir()
    root_b.mkdir()
    alias_root = tmp_path / f"route-copy-{missing_copy}-alias"
    alias_root.symlink_to(root_a, target_is_directory=True)
    guard = _allowing_guard()
    append_steering_log(
        alias_root,
        "wrong",
        "seed",
        source="chat",
        operation_id=f"route-copy-{missing_copy}-seed",
        write_guard=guard,
    )
    route_state, route_swap, route_witness = _host_route_paths(alias_root)
    if missing_copy == "app-local":
        route_state.unlink()
        route_swap.unlink()
    else:
        route_witness.unlink()

    recovered_line = append_steering_log(
        alias_root,
        "mute",
        "recovered-copy",
        source="item",
        operation_id=f"route-copy-{missing_copy}-recovered",
        write_guard=guard,
    )
    assert read_steering_log_body(root_a).count(recovered_line) == 1
    assert route_state.stat().st_size > 0
    assert route_swap.exists()
    assert route_witness.stat().st_size > 0

    alias_root.unlink()
    alias_root.symlink_to(root_b, target_is_directory=True)
    with pytest.raises(KnowledgeWriteConflict, match="app-local route changed"):
        append_steering_log(
            alias_root,
            "mute",
            "retarget-must-block",
            source="item",
            operation_id=f"route-copy-{missing_copy}-retarget",
            write_guard=guard,
        )
    assert not (root_b / "_heimdal").exists()


def test_steering_log_distinct_case_sensitive_roots_remain_independent(
    tmp_path: Path,
) -> None:
    upper_root = tmp_path / "CaseVault"
    lower_root = tmp_path / "casevault"
    upper_root.mkdir()
    try:
        lower_root.mkdir()
    except FileExistsError:
        pytest.skip("filesystem is case-insensitive")
    if upper_root.samefile(lower_root):
        pytest.skip("filesystem is case-insensitive")

    with write_ops_module._open_atomic_append_authority(
        upper_root,
        note_rel_path(STEERING_LOG),
    ) as upper_authority:
        upper_keys = set(upper_authority.host_state_keys)
    with write_ops_module._open_atomic_append_authority(
        lower_root,
        note_rel_path(STEERING_LOG),
    ) as lower_authority:
        lower_keys = set(lower_authority.host_state_keys)
    assert upper_keys.isdisjoint(lower_keys)

    guard = _allowing_guard()
    append_steering_log(
        upper_root,
        "wrong",
        "upper",
        source="chat",
        operation_id="case-sensitive-upper",
        write_guard=guard,
    )
    append_steering_log(
        lower_root,
        "mute",
        "lower",
        source="item",
        operation_id="case-sensitive-lower",
        write_guard=guard,
    )
    assert '"operation_id":"case-sensitive-upper"' in read_steering_log_body(
        upper_root
    )
    assert '"operation_id":"case-sensitive-lower"' in read_steering_log_body(
        lower_root
    )


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
        if not swapped and (fresh_vault / "_heimdal").exists():
            swapped = True
            (fresh_vault / "_heimdal").replace(parked_parent)
            (fresh_vault / "_heimdal").symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(write_ops_module, "_write_all", swap_parent)
    with pytest.raises(KnowledgeWriteConflict, match="authority mapping changed"):
        append_steering_log(
            fresh_vault,
            "wrong",
            "must-not-escape",
            source="chat",
            operation_id="racing-parent",
            write_guard=guard,
        )
    assert list(outside.iterdir()) == []
    assert not list(parked_parent.glob(".atomic-append-*"))


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
