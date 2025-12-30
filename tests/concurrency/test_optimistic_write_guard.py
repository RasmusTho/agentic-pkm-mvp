import pytest

from app.components.concurrency import OptimisticWriteGuard, VersionMismatch


def test_optimistic_locking_write_conflict(tmp_path) -> None:
    path = tmp_path / "note.md"
    guard = OptimisticWriteGuard()

    path.write_text("A", encoding="utf-8")
    expected = guard.compute_version(b"A")

    path.write_text("B", encoding="utf-8")

    with pytest.raises(VersionMismatch):
        guard.write_if_unchanged(path, expected, "C")

    assert path.read_text(encoding="utf-8") == "B"
