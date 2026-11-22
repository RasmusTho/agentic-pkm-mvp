from __future__ import annotations

import multiprocessing
import os
import random
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from app.instance import context_bound_write
from app.knowledge import atomic_append_reconcile as mod
from app.knowledge.atomic_append_reconcile import (
    CUT_OFF_NOTICE,
    AtomicAppendCollision,
    AtomicAppendResult,
    atomic_append_reconcile_relative,
)
from app.knowledge.errors import KnowledgeCapabilityError, KnowledgeWriteConflict
from app.write_guard import WriteGuard, WritesBlockedError
from tests.knowledge import linux_acl

GUARD = WriteGuard(lambda: {"state": "healthy"})
OP_A = "a" * 32
OP_B = "b" * 32
OP_C = "c" * 32
FORK = multiprocessing.get_context("fork")


def append(vault: Path, rel: str, op: str, text: str, **kwargs):
    kwargs.setdefault("write_guard", GUARD)
    return atomic_append_reconcile_relative(rel, op, text, vault_root=vault, **kwargs)


def entry(op: str, text: str) -> bytes:
    return mod._entry_bytes(op, text.encode())


def closed_entries(path: Path) -> dict:
    return mod._parse(path.read_bytes()).entries


@pytest.fixture
def vault(tmp_path: Path):
    root = tmp_path / "vault"
    root.mkdir()
    fd = os.open(root, os.O_RDONLY)
    try:
        label = mod._filesystem_type(fd)
    finally:
        os.close(fd)
    if label in mod._UNSUPPORTED_LINUX_FS.values() or label in mod._UNSUPPORTED_DARWIN_FS:
        # tmp_path lives on tmpfs here; use real disk for the real code path.
        alt = Path(tempfile.mkdtemp(dir="/var/tmp"))
        try:
            yield alt
        finally:
            shutil.rmtree(alt, ignore_errors=True)
        return
    yield root


@pytest.fixture(autouse=True)
def _reset_seams(monkeypatch):
    monkeypatch.setattr(mod, "_CHECKPOINT", None)


class Counter:
    """Count (and optionally observe) the primitive's write and sync calls."""

    def __init__(self, monkeypatch):
        self.writes = 0
        self.syncs: list[str] = []
        real_write, real_sync = mod._write, mod._sync_file

        def write(fd, data):
            self.writes += 1
            return real_write(fd, data)

        def sync_file(fd):
            self.syncs.append("dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
            real_sync(fd)

        def sync_dir(fd):
            sync_file(fd)

        monkeypatch.setattr(mod, "_write", write)
        monkeypatch.setattr(mod, "_sync_file", sync_file)
        monkeypatch.setattr(mod, "_sync_directory", sync_dir)


# --- AC1 ---------------------------------------------------------------------------


def test_append_replay_and_collision_are_exactly_once(vault, monkeypatch):
    note = vault / "note.md"
    original = b"# Title\n\nhand written, no markers\n"
    note.write_bytes(original)
    counter = Counter(monkeypatch)

    assert append(vault, "note.md", OP_A, "first entry\n") == AtomicAppendResult("appended")
    assert note.read_bytes() == original + entry(OP_A, "first entry\n")
    assert counter.writes == 1 and counter.syncs == ["file"]

    after_first = note.read_bytes()
    assert append(vault, "note.md", OP_A, "first entry\n") == AtomicAppendResult(
        "reconciled_replay"
    )
    assert counter.writes == 1 and counter.syncs == ["file"]
    assert note.read_bytes() == after_first

    with pytest.raises(AtomicAppendCollision):
        append(vault, "note.md", OP_A, "different text\n")
    assert note.read_bytes() == after_first

    # Replay after the note was renamed or moved.
    (vault / "sub").mkdir()
    note.rename(vault / "sub" / "moved.md")
    assert append(vault, "sub/moved.md", OP_A, "first entry\n").outcome == "reconciled_replay"
    assert (vault / "sub" / "moved.md").read_bytes() == after_first
    assert counter.writes == 1

    # A note that does not end in a newline still gets the entry on its own line.
    plain = vault / "plain.md"
    plain.write_bytes(b"no trailing newline")
    append(vault, "plain.md", OP_B, "text without newline")
    assert plain.read_bytes() == b"no trailing newline\n" + entry(OP_B, "text without newline")
    assert closed_entries(plain)[OP_B].edited is False


def test_entry_text_and_ids_are_validated(vault):
    (vault / "n.md").write_bytes(b"x\n")
    for bad in ("nul\x00byte", "lone \ud800 surrogate", f"<!--ya:end {OP_A} b=00000000-->"):
        with pytest.raises(ValueError):
            append(vault, "n.md", OP_B, bad)
    with pytest.raises(ValueError):
        append(vault, "n.md", "not-an-id", "text")
    assert (vault / "n.md").read_bytes() == b"x\n"


# --- AC2 ---------------------------------------------------------------------------


def test_name_changes_never_publish_foreign_content(vault, monkeypatch):
    note = vault / "note.md"
    note.write_bytes(b"original\n")
    names_before = sorted(p.name for p in vault.iterdir())

    # Name swapped before the write: refused, the foreign file is untouched.
    def swap(point):
        if point == "before_final_checks":
            note.rename(vault / "saved.md")
            note.write_bytes(b"FOREIGN-AUTHORITY\n")

    monkeypatch.setattr(mod, "_CHECKPOINT", swap)
    with pytest.raises(KnowledgeWriteConflict):
        append(vault, "note.md", OP_A, "entry\n")
    assert note.read_bytes() == b"FOREIGN-AUTHORITY\n"
    assert (vault / "saved.md").read_bytes() == b"original\n"
    monkeypatch.setattr(mod, "_CHECKPOINT", None)
    note.unlink()
    (vault / "saved.md").rename(note)

    # Renamed during the write: the entry lands in that same note and the call succeeds.
    real_write = mod._write

    def rename_then_write(fd, data):
        note.rename(vault / "moved.md")
        return real_write(fd, data)

    monkeypatch.setattr(mod, "_write", rename_then_write)
    assert append(vault, "note.md", OP_A, "entry\n").outcome == "appended"
    assert (vault / "moved.md").read_bytes() == b"original\n" + entry(OP_A, "entry\n")
    assert not note.exists()
    (vault / "moved.md").rename(note)

    # Loses its last name during the write: the call fails.
    def unlink_then_write(fd, data):
        note.unlink()
        return real_write(fd, data)

    monkeypatch.setattr(mod, "_write", unlink_then_write)
    with pytest.raises(KnowledgeWriteConflict):
        append(vault, "note.md", OP_B, "entry two\n")

    monkeypatch.setattr(mod, "_write", real_write)
    # Nothing but the names this test itself made exists: no stage or temp file.
    assert sorted(p.name for p in vault.iterdir()) == sorted(
        n for n in names_before if n != "note.md"
    )


# --- AC3 ---------------------------------------------------------------------------


def test_anchored_vault_paths_fail_closed(vault, monkeypatch):
    outside = vault.parent / "outside"
    outside.mkdir()
    victim = outside / "victim.md"
    victim.write_bytes(b"victim\n")
    (vault / "real.md").write_bytes(b"real\n")

    (vault / "link.md").symlink_to(victim)
    (vault / "hl.md").write_bytes(b"hl\n")
    os.link(vault / "hl.md", vault / "hard.md")
    os.mkfifo(vault / "fifo.md")
    (vault / "dir.md").mkdir()
    (vault / "linkdir").symlink_to(outside)
    for rel in ("link.md", "hard.md", "fifo.md", "dir.md", "linkdir/victim.md", "missing.md"):
        with pytest.raises(KnowledgeCapabilityError):
            append(vault, rel, OP_A, "x\n")
    assert victim.read_bytes() == b"victim\n"
    assert (vault / "hl.md").read_bytes() == b"hl\n"
    assert not (vault / "missing.md").exists()

    for rel in ("../outside/victim.md", "/etc/passwd", "a/../../x.md", "a\\b.md", ""):
        with pytest.raises(ValueError):
            append(vault, rel, OP_A, "x\n")
    assert victim.read_bytes() == b"victim\n"

    # Replaced root: a different directory appears at the root path before the write.
    (vault / "sub").mkdir()
    (vault / "sub" / "n.md").write_bytes(b"sub original\n")
    moved_root = vault.parent / "moved-root"
    fresh_n = b"fresh\n"

    def replace_root(point):
        if point == "before_final_checks":
            vault.rename(moved_root)
            vault.mkdir()
            (vault / "sub").mkdir()
            (vault / "sub" / "n.md").write_bytes(fresh_n)

    monkeypatch.setattr(mod, "_CHECKPOINT", replace_root)
    with pytest.raises(KnowledgeWriteConflict):
        append(vault, "sub/n.md", OP_A, "x\n")
    assert (vault / "sub" / "n.md").read_bytes() == fresh_n
    assert (moved_root / "sub" / "n.md").read_bytes() == b"sub original\n"
    shutil.rmtree(vault)
    moved_root.rename(vault)

    # Replaced parent.
    def replace_parent(point):
        if point == "before_final_checks":
            (vault / "sub").rename(vault / "sub-old")
            (vault / "sub").mkdir()
            (vault / "sub" / "n.md").write_bytes(fresh_n)

    monkeypatch.setattr(mod, "_CHECKPOINT", replace_parent)
    with pytest.raises(KnowledgeWriteConflict):
        append(vault, "sub/n.md", OP_A, "x\n")
    assert (vault / "sub" / "n.md").read_bytes() == fresh_n
    assert (vault / "sub-old" / "n.md").read_bytes() == b"sub original\n"
    monkeypatch.setattr(mod, "_CHECKPOINT", None)

    # Expired deadline, blocked guard and expired authority: before any byte.
    target = vault / "real.md"
    with pytest.raises(KnowledgeWriteConflict):
        append(vault, "real.md", OP_A, "x\n", deadline=time.monotonic() - 1)
    with pytest.raises(WritesBlockedError):
        append(
            vault,
            "real.md",
            OP_A,
            "x\n",
            write_guard=WriteGuard(lambda: {"state": "safe_mode", "reason": "test"}),
        )
    expired = {"now": False}

    def locator(root, resource):
        if expired["now"]:
            raise context_bound_write.ContextBoundSourceRefused("authority expired")

    monkeypatch.setattr(context_bound_write, "require_effect_locator", locator)
    expired["now"] = True
    with pytest.raises(context_bound_write.ContextBoundSourceRefused):
        append(vault, "real.md", OP_A, "x\n")
    expired["now"] = False
    # Authority that expires between reading the note and the write.
    monkeypatch.setattr(
        mod,
        "_CHECKPOINT",
        lambda p: expired.update(now=True) if p == "before_final_checks" else None,
    )
    with pytest.raises(context_bound_write.ContextBoundSourceRefused):
        append(vault, "real.md", OP_A, "x\n")
    assert target.read_bytes() == b"real\n"


# --- AC4 ---------------------------------------------------------------------------


def _metadata(path: Path) -> dict:
    info = path.lstat()
    result = {
        "mode": info.st_mode,
        "uid": info.st_uid,
        "gid": info.st_gid,
        "ino": info.st_ino,
        "nlink": info.st_nlink,
        "xattrs": {k: os.getxattr(path, k) for k in os.listxattr(path)}
        if hasattr(os, "listxattr")
        else {},
    }
    if sys.platform == "linux":
        result["acl"] = linux_acl.read_linux_access_acl(path)
    elif sys.platform == "darwin":
        listing = subprocess.run(
            ["ls", "-le", os.fspath(path)], capture_output=True, text=True, check=True
        ).stdout.splitlines()
        result["acl"] = listing[1:]  # the ACL entries; line 0 carries size and time
        assert result["acl"], "the macOS ACL fixture did not take"
    else:
        raise AssertionError("unsupported platform for the ACL check")
    return result


def test_special_permission_bits_refuse_and_metadata_is_untouched(vault, monkeypatch):
    for bits in (stat.S_ISUID, stat.S_ISGID):
        note = vault / f"bits{bits}.md"
        note.write_bytes(b"original\n")
        note.chmod(0o644 | bits)
        if not note.stat().st_mode & bits:
            pytest.fail("the filesystem did not keep the special permission bit")
        with pytest.raises(KnowledgeCapabilityError):
            append(vault, note.name, OP_A, "x\n")
        assert note.read_bytes() == b"original\n"

    capability = vault / "cap.md"
    capability.write_bytes(b"original\n")
    monkeypatch.setattr(mod, "_has_file_capability", lambda fd: True)
    with pytest.raises(KnowledgeCapabilityError):
        append(vault, "cap.md", OP_A, "x\n")
    assert capability.read_bytes() == b"original\n"
    monkeypatch.undo()

    # Ordinary note carrying a real ACL: nothing but the data changes.
    note = vault / "acl.md"
    if sys.platform == "linux":
        linux_acl.create_linux_named_acl_file(note, content=b"original\n")
    elif sys.platform == "darwin":
        note.write_bytes(b"original\n")
        note.chmod(0o640)
        subprocess.run(
            ["chmod", "+a", "everyone deny delete", os.fspath(note)], check=True
        )
    else:
        raise AssertionError("unsupported platform for the ACL check")
    before = _metadata(note)
    assert append(vault, "acl.md", OP_A, "entry\n").outcome == "appended"
    assert note.read_bytes() == b"original\n" + entry(OP_A, "entry\n")
    assert _metadata(note) == before


# --- AC5 ---------------------------------------------------------------------------

_ORIGINALS = (b"# Note\n\nsome text\n", b"# Note\n\nno trailing newline")


def _fillers(missing: int, kind: str) -> bytes:
    if kind == "none":
        return b""
    if kind == "zeros":
        return b"\x00" * missing
    rng = random.Random(missing)
    return bytes(rng.choice(b"abcdef\x00\xff\x01") for _ in range(missing))


def test_cut_off_entry_is_never_counted_and_nothing_is_lost(vault):
    full = entry(OP_A, "first line\nsecond line\n")
    other = entry(OP_B, "other\n")
    note = vault / "note.md"
    for original in _ORIGINALS:
        for kind in ("none", "zeros", "garbage"):
            for k in range(len(full)):
                # What an interrupted write leaves: its separator newline, then a prefix.
                start = original + (b"" if original.endswith(b"\n") else b"\n")
                torn = start + full[:k] + _fillers(len(full) - k, kind)
                if kind != "none" and k == len(full) - 1 and torn.endswith(b"\n"):
                    continue
                # Written range cut off or damaged: never counted as written.
                assert OP_A not in mod._parse(torn).entries, (k, kind)

                # The same operation completes it (or yields exactly one closed entry).
                note.write_bytes(torn)
                assert append(vault, "note.md", OP_A, "first line\nsecond line\n").outcome == "appended"
                result = note.read_bytes()
                assert result.startswith(torn), (k, kind)
                assert list(mod._parse(result).entries) == [OP_A]
                if kind == "none" and k >= 6:
                    assert result == start + full  # the missing rest only

                # Any other append keeps the fragment as plain text, with the visible line.
                note.write_bytes(torn)
                assert append(vault, "note.md", OP_B, "other\n").outcome == "appended"
                result = note.read_bytes()
                assert result.startswith(torn)
                # A lone missing final newline is supplied by the separator; the entry
                # is then whole, so it is not cut off any more.
                separated = torn if torn.endswith(b"\n") else torn + b"\n"
                finished = OP_A in mod._parse(separated).entries
                assert list(mod._parse(result).entries) == ([OP_A, OP_B] if finished else [OP_B])
                if finished:
                    assert result.count(CUT_OFF_NOTICE.encode()) == 0
                    continue
                tail_start = mod._parse(torn).tail_start
                tail = b"" if tail_start is None else torn[tail_start:]
                # A short fragment that is only the start of any entry is completed
                # as this entry; every other fragment stays plain text with the notice.
                absorbed = tail_start is not None and other.startswith(tail)
                notice = tail_start is not None and not absorbed
                assert result.count(CUT_OFF_NOTICE.encode()) == (1 if notice else 0), (k, kind)
                if absorbed:
                    assert result == torn[:tail_start] + other
                assert result.endswith(other)

                # The cut-off operation can still be done afterwards.
                assert append(vault, "note.md", OP_A, "first line\nsecond line\n").outcome == "appended"
                assert set(mod._parse(note.read_bytes()).entries) == {OP_A, OP_B}

    # A cut-off entry in the middle of a note is plain text and never counted.
    middle = b"before\n" + full[:40] + b"\n" + other
    note.write_bytes(middle)
    assert list(mod._parse(middle).entries) == [OP_B]
    append(vault, "note.md", OP_A, "first line\nsecond line\n")
    assert note.read_bytes().startswith(middle)
    assert set(mod._parse(note.read_bytes()).entries) == {OP_A, OP_B}

    # A damaged (NUL / invalid UTF-8) body is plain text; a new entry follows the visible line.
    for bad in (b"bro\x00ken\n", b"bro\xffken\n"):
        damaged = (
            f"<!--ya:begin {OP_A} h={mod._sha8(b'x')}-->\n".encode()
            + bad
            + f"<!--ya:end {OP_A} b={mod._sha8(bad)}-->\n".encode()
        )
        note.write_bytes(damaged)
        assert mod._parse(damaged).entries == {}
        append(vault, "note.md", OP_A, "good\n")
        result = note.read_bytes()
        assert result.startswith(damaged)
        assert CUT_OFF_NOTICE.encode() in result[len(damaged) :]
        assert list(mod._parse(result).entries) == [OP_A]


# --- AC6 ---------------------------------------------------------------------------


def _child(vault, op, text, point, partial, create=False):
    def die(name):
        if name == point:
            os._exit(9)

    if point is not None:
        mod._CHECKPOINT = die
    if partial is not None:
        real = mod._write

        def short_write(fd, data):
            real(fd, data[:partial])
            os._exit(9)

        mod._write = short_write
    try:
        append(vault, "note.md", op, text, create=create)
    except BaseException:
        os._exit(1)
    os._exit(0)


def _run_child(*args, **kwargs):
    process = FORK.Process(target=_child, args=args, kwargs=kwargs)
    process.start()
    process.join(60)
    return process.exitcode


def test_process_death_at_every_point_recovers_or_leaves_visible_text(vault):
    text = "entry one\nentry two\n"
    full = entry(OP_A, text)
    note = vault / "note.md"
    original = b"# Note\nbody"
    for point in ("before_final_checks", "before_write", "after_write", "after_sync"):
        note.write_bytes(original)
        assert _run_child(vault, OP_A, text, point, None) == 9
        for retry_op in (OP_A, OP_B):
            snapshot = note.read_bytes()
            assert append(vault, "note.md", retry_op, text if retry_op == OP_A else "b\n").outcome in {
                "appended",
                "reconciled_replay",
            }
            assert note.read_bytes().startswith(snapshot)
        assert set(mod._parse(note.read_bytes()).entries) == {OP_A, OP_B}
        assert note.read_bytes().count(b"<!--ya:begin " + OP_A.encode()) == 1

    for partial in range(len(full) + 1):
        note.write_bytes(original)
        assert _run_child(vault, OP_A, text, None, partial) == 9
        torn = note.read_bytes()
        assert OP_A not in mod._parse(torn).entries or partial == len(full)
        assert append(vault, "note.md", OP_A, text).outcome in {"appended", "reconciled_replay"}
        result = note.read_bytes()
        assert result.startswith(torn)
        assert list(mod._parse(result).entries) == [OP_A]
        assert result.count(b"<!--ya:begin " + OP_A.encode()) == 1

    # Death right after the note was created, before anything was written.
    note.unlink()
    assert _run_child(vault, OP_A, text, "before_write", None, create=True) == 9
    assert note.read_bytes() == b""
    assert append(vault, "note.md", OP_A, text).outcome == "appended"
    assert note.read_bytes() == full


# --- AC7 ---------------------------------------------------------------------------


def _fresh_note(vault: Path) -> Path:
    note = vault / "note.md"
    note.write_bytes(b"")
    append(vault, "note.md", OP_A, "alpha\nline two\ttabbed\x07bell\n")
    append(vault, "note.md", OP_B, "beta\n")
    return note


ALPHA = "alpha\nline two\ttabbed\x07bell\n"


def _edit_body(data: bytes) -> bytes:
    return data.replace(b"line two", b"LINE 2")


def _reflow(data: bytes) -> bytes:
    return data.replace(b"alpha\nline two", b"alpha line two")


def _strip_control(data: bytes) -> bytes:
    return data.replace(b"\x07", b"").replace(b"\t", b" ")


def _crlf(data: bytes) -> bytes:
    return data.replace(b"\n", b"\r\n")


def _paste_twice(data: bytes) -> bytes:
    block = entry(OP_A, ALPHA)
    return data.replace(block, block + block)


def test_hand_edits_never_block_appends(vault):
    block = entry(OP_A, ALPHA)
    edits = {
        "edit-body": (_edit_body, "edited"),
        "reflow": (_reflow, "edited"),
        "strip-control": (_strip_control, "edited"),
        "crlf": (_crlf, "edited"),
        "paste-twice": (_paste_twice, "intact"),
        "delete-entry": (lambda d: d.replace(block, b""), "gone"),
        "delete-begin-marker": (
            lambda d: d.replace(block.split(b"\n", 1)[0] + b"\n", b""),
            "gone",
        ),
        "edit-begin-marker": (lambda d: d.replace(b"ya:begin " + OP_A.encode(), b"ya:begin x"), "gone"),
        "delete-end-marker": (lambda d: d.replace(block.splitlines(keepends=True)[-1], b""), "gone"),
    }
    note = vault / "note.md"
    for label, (edit, expectation) in edits.items():
        _fresh_note(vault)
        data = note.read_bytes()
        edited = edit(data)
        assert edited != data, label
        note.write_bytes(edited)

        # A later append never fails and never changes an existing byte.
        assert append(vault, "note.md", OP_C, "gamma\n").outcome == "appended", label
        assert note.read_bytes().startswith(edited), label
        assert mod._parse(note.read_bytes()).entries[OP_C].edited is False

        # Replay of the edited operation.
        note.write_bytes(edited)
        before = edited
        result = append(vault, "note.md", OP_A, ALPHA)
        if expectation == "edited":
            assert result == AtomicAppendResult("reconciled_replay", edited=True), label
            assert note.read_bytes() == before
        elif expectation == "intact":
            assert result == AtomicAppendResult("reconciled_replay", edited=False), label
            assert note.read_bytes() == before
        else:
            # Entry or marker deleted: the operation is appended again.
            assert result.outcome == "appended", label
            assert note.read_bytes().startswith(before)
            assert OP_A in mod._parse(note.read_bytes()).entries, label

    # Same id, different text after an edit is still a collision, with nothing written.
    _fresh_note(vault)
    note.write_bytes(_edit_body(note.read_bytes()))
    data = note.read_bytes()
    with pytest.raises(AtomicAppendCollision):
        append(vault, "note.md", OP_A, "something else\n")
    assert note.read_bytes() == data


# --- AC8 ---------------------------------------------------------------------------

_SHARED_OP = "5" * 32


def _worker(paths, index, count, queue):
    outcomes = []
    for i in range(count):
        vault = paths[(index + i) % len(paths)]
        op = f"{index:04x}{i:04x}".ljust(32, "0")
        outcomes.append(append(vault, "note.md", op, f"worker {index} entry {i}\n").outcome)
        outcomes.append(("shared", append(vault, "note.md", _SHARED_OP, "shared\n").outcome))
    queue.put(outcomes)


def test_concurrent_cooperating_writers_append_each_operation_once(vault):
    note = vault / "note.md"
    original = b"# Note\n"
    note.write_bytes(original)
    alias = vault.parent / f"{vault.name}-alias"
    alias.symlink_to(vault)
    paths = [vault, alias]
    workers, per_worker = 6, 4
    queue = FORK.Queue()
    processes = [FORK.Process(target=_worker, args=(paths, n, per_worker, queue)) for n in range(workers)]
    for process in processes:
        process.start()
    results = [queue.get(timeout=120) for _ in processes]
    for process in processes:
        process.join(60)
        assert process.exitcode == 0

    data = note.read_bytes()
    assert data.startswith(original)
    parsed = mod._parse(data)
    expected_ops = {f"{n:04x}{i:04x}".ljust(32, "0") for n in range(workers) for i in range(per_worker)}
    assert set(parsed.entries) == expected_ops | {_SHARED_OP}
    assert data.count(b"<!--ya:begin ") == len(expected_ops) + 1
    assert data.count(b"<!--ya:end ") == len(expected_ops) + 1
    assert parsed.tail_start is None
    shared = [o[1] for r in results for o in r if isinstance(o, tuple)]
    assert shared.count("appended") == 1
    assert shared.count("reconciled_replay") == len(shared) - 1
    assert all(o == "appended" for r in results for o in r if isinstance(o, str))


# --- AC9 ---------------------------------------------------------------------------


def _tree(root: Path) -> dict:
    snapshot = {}
    for path in sorted(root.rglob("*")) + [root]:
        info = path.lstat()
        snapshot[os.fspath(path.relative_to(root))] = (
            info.st_ino,
            info.st_mode,
            info.st_size if path.is_file() else None,
            info.st_mtime_ns if not path.is_dir() else None,
        )
    return snapshot


def test_no_state_outside_the_note_and_unsupported_storage_is_refused(vault, monkeypatch):
    (vault / "sub").mkdir()
    note = vault / "sub" / "note.md"
    note.write_bytes(b"no markers here\n")
    (vault / "other.md").write_bytes(b"other\n")
    before = _tree(vault)

    forbidden = []
    for name in (
        "rename", "replace", "unlink", "remove", "rmdir", "mkdir", "link", "symlink",
        "truncate", "ftruncate", "chmod", "fchmod", "chown", "fchown", "setxattr",
        "removexattr", "mkfifo", "utime",
    ):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, lambda *a, _n=name, **k: forbidden.append(_n))
    real_open = os.open

    def checked_open(path, flags, *args, **kwargs):
        if flags & (os.O_CREAT | os.O_TRUNC):
            forbidden.append("open-creating")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", checked_open)
    append(vault, "sub/note.md", OP_A, "entry\n")
    monkeypatch.undo()
    assert forbidden == []
    after = _tree(vault)
    changed = {k for k in after if before.get(k) != after[k]}
    assert changed == {"sub/note.md", "sub"} or changed == {"sub/note.md"}
    assert after["sub/note.md"][0] == before["sub/note.md"][0]  # same inode
    assert set(after) == set(before)

    # Creating a note syncs the file, then its directory, then the entry; no other state.
    counter = Counter(monkeypatch)
    append(vault, "sub/created.md", OP_A, "entry\n", create=True)
    assert counter.syncs == ["file", "dir", "file"]
    assert (vault / "sub" / "created.md").read_bytes() == entry(OP_A, "entry\n")
    assert sorted(p.name for p in (vault / "sub").iterdir()) == ["created.md", "note.md"]
    with pytest.raises(KnowledgeCapabilityError):
        append(vault, "nodir/created.md", OP_A, "entry\n", create=True)
    assert not (vault / "nodir").exists()
    monkeypatch.undo()

    # A failed sync fails the call; a retry of the same operation still ends well.
    (vault / "sync.md").write_bytes(b"x\n")
    real_sync = mod._sync_file
    monkeypatch.setattr(mod, "_sync_file", lambda fd: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(KnowledgeWriteConflict):
        append(vault, "sync.md", OP_A, "entry\n")
    monkeypatch.setattr(mod, "_sync_file", real_sync)
    assert append(vault, "sync.md", OP_A, "entry\n").outcome in {"reconciled_replay", "appended"}
    assert list(closed_entries(vault / "sync.md")) == [OP_A]
    for failing in ("_sync_file", "_sync_directory"):
        fresh = vault / f"fresh-{failing}.md"
        monkeypatch.setattr(mod, failing, lambda fd: (_ for _ in ()).throw(OSError("disk")))
        with pytest.raises(KnowledgeWriteConflict):
            append(vault, fresh.name, OP_A, "entry\n", create=True)
        monkeypatch.undo()
        assert append(vault, fresh.name, OP_A, "entry\n", create=True).outcome in {
            "appended",
            "reconciled_replay",
        }
        assert list(closed_entries(fresh)) == [OP_A]

    # Unsupported storage and oversize notes: refused before any write.
    fine = vault / "fine.md"
    fine.write_bytes(b"fine\n")
    for label in ("nfs", "fuse", "tmpfs", "smbfs", "macfuse"):
        monkeypatch.setattr(mod, "_filesystem_type", lambda fd, label=label: label)
        with pytest.raises(KnowledgeCapabilityError):
            append(vault, "fine.md", OP_A, "entry\n")
        assert fine.read_bytes() == b"fine\n"
    monkeypatch.undo()
    huge = vault / "huge.md"
    with huge.open("wb") as handle:
        handle.truncate(mod.MAX_NOTE_BYTES + 1)
    with pytest.raises(KnowledgeCapabilityError):
        append(vault, "huge.md", OP_A, "entry\n")
    assert huge.stat().st_size == mod.MAX_NOTE_BYTES + 1
    edge = vault / "edge.md"
    with edge.open("wb") as handle:
        handle.truncate(mod.MAX_NOTE_BYTES - 10)
    with pytest.raises(KnowledgeCapabilityError):
        append(vault, "edge.md", OP_A, "entry\n")
    assert edge.stat().st_size == mod.MAX_NOTE_BYTES - 10
