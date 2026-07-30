from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
import re
import threading

import pytest

FdToken = tuple[int, int, str, str]
DuplicationEvent = tuple[str, int, int]
_STAGE_NAME_RE = re.compile(r"^\.candidate-stage-[0-9a-f]{32}$")


class FdOracle:
    """Track logical FD generations across success, faults, and real races."""

    def __init__(self) -> None:
        self.opened: list[FdToken] = []
        self.close_attempts: list[FdToken | None] = []
        self.duplicates: list[DuplicationEvent] = []
        self.active: dict[int, FdToken] = {}
        self.events: list[tuple[object, ...]] = []
        self._generation = 0
        self._ignored_active: set[int] = set()
        self._retired_tracked: set[int] = set()
        self._scope_depth = 0
        self._lock = threading.Lock()

    @contextmanager
    def observe(self) -> Iterator[None]:
        """Limit ownership accounting to the production call under test."""

        with self._lock:
            self._scope_depth += 1
        try:
            yield
        finally:
            with self._lock:
                self._scope_depth -= 1
                assert self._scope_depth >= 0

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_open = os.open
        real_close = os.close
        real_dup = os.dup
        real_dup2 = os.dup2
        real_dup3 = getattr(os, "dup3", None)

        def register_duplicate(
            operation: str,
            source_fd: int,
            duplicate_fd: int,
        ) -> int:
            with self._lock:
                source = self.active.get(source_fd)
                if source is None:
                    return duplicate_fd
                self._generation += 1
                token = (
                    duplicate_fd,
                    self._generation,
                    f"duplicated_{source[2]}",
                    f"{operation}:{source[3]}",
                )
                assert duplicate_fd not in self.active
                assert duplicate_fd not in self._ignored_active
                self._retired_tracked.discard(duplicate_fd)
                self.active[duplicate_fd] = token
                self.opened.append(token)
                self.duplicates.append((operation, source_fd, duplicate_fd))
                self.events.append((operation, source_fd, duplicate_fd, token))
            return duplicate_fd

        def traced_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            fd = real_open(path, flags, mode, dir_fd=dir_fd)
            raw_path = os.fsdecode(path)
            kind = (
                "stage"
                if raw_path.startswith(".candidate-stage-")
                else "directory"
                if flags & getattr(os, "O_DIRECTORY", 0)
                else "file"
            )
            with self._lock:
                assert fd not in self.active, f"raw fd {fd} reused while still owned"
                assert fd not in self._ignored_active
                self._retired_tracked.discard(fd)
                if self._scope_depth == 0 or kind == "file":
                    self._ignored_active.add(fd)
                    return fd
                self._generation += 1
                token = (fd, self._generation, kind, raw_path)
                self.active[fd] = token
                self.opened.append(token)
                self.events.append(("open", raw_path, flags, dir_fd, token))
            return fd

        def traced_close(fd: int) -> None:
            with self._lock:
                token = self.active.pop(fd, None)
                if token is not None:
                    self.close_attempts.append(token)
                    self.events.append(("close", fd, token))
                    self._retired_tracked.add(fd)
                elif fd in self._ignored_active:
                    self._ignored_active.remove(fd)
                elif self._scope_depth > 0 and fd in self._retired_tracked:
                    self.close_attempts.append(None)
                    self.events.append(("close", fd, None))
            real_close(fd)

        def traced_dup(fd: int) -> int:
            return register_duplicate("dup", fd, real_dup(fd))

        def traced_dup2(fd: int, fd2: int, inheritable: bool = True) -> int:
            duplicate = real_dup2(fd, fd2, inheritable=inheritable)
            return register_duplicate("dup2", fd, duplicate)

        monkeypatch.setattr(os, "open", traced_open)
        monkeypatch.setattr(os, "close", traced_close)
        monkeypatch.setattr(os, "dup", traced_dup)
        monkeypatch.setattr(os, "dup2", traced_dup2)
        if real_dup3 is not None:

            def traced_dup3(fd: int, fd2: int, flags: int = 0) -> int:
                duplicate = real_dup3(fd, fd2, flags)
                return register_duplicate("dup3", fd, duplicate)

            monkeypatch.setattr(os, "dup3", traced_dup3)


def assert_exact_fd_ownership(
    opened: list[FdToken],
    close_attempts: list[FdToken | None],
    duplicates: list[DuplicationEvent],
) -> None:
    assert duplicates == []
    assert None not in close_attempts
    assert len(close_attempts) == len(opened)
    assert sorted(close_attempts) == sorted(opened)


def assert_exact_stage_names(names: list[str]) -> None:
    assert names
    assert len(names) == len(set(names))
    for name in names:
        assert _STAGE_NAME_RE.fullmatch(name)
        assert len(name.encode("utf-8")) == 49
        assert not name.endswith(".md")


def assert_cleanup_fence(events: list[tuple[object, ...]]) -> None:
    unlink_indexes = [index for index, event in enumerate(events) if event[0] == "unlink"]
    assert unlink_indexes
    for unlink_index in unlink_indexes:
        assert unlink_index + 1 < len(events)
        assert events[unlink_index + 1][0] == "fsync"


def assert_hidden_stage_state(
    names: list[str],
    *,
    sentinel_name: str,
    expected_owned_count: int,
) -> None:
    assert names.count(sentinel_name) == 1
    owned_names = [name for name in names if name != sentinel_name]
    assert len(owned_names) == expected_owned_count
    if owned_names:
        assert_exact_stage_names(owned_names)


def assert_stage_publication_order(events: list[tuple[object, ...]]) -> None:
    stage_opens = [
        (index, event)
        for index, event in enumerate(events)
        if event[0] == "open" and isinstance(event[4], tuple) and event[4][2] == "stage"
    ]
    assert len(stage_opens) == 1
    open_index, open_event = stage_opens[0]
    stage_token = open_event[4]
    assert isinstance(stage_token, tuple)
    stage_fd = stage_token[0]
    close_indexes = [
        index
        for index, event in enumerate(events)
        if event[0] == "close" and event[2] == stage_token
    ]
    publish_indexes = [index for index, event in enumerate(events) if event[0] == "publish"]
    assert len(close_indexes) == len(publish_indexes) == 1
    fsync_indexes = [
        index
        for index, event in enumerate(events)
        if event[0] == "fsync" and event[1] == stage_fd and open_index < index < close_indexes[0]
    ]
    assert len(fsync_indexes) == 1
    assert open_index < fsync_indexes[0] < close_indexes[0] < publish_indexes[0]
