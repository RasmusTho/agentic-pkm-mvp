from pathlib import Path

import pytest

from app.outbox.events import INDEX_OUTBOX_PATH
from app.runtime.runtime_loop import OutboxPathError, resolve_outbox_path


def test_resolve_outbox_path_defaults_to_index_outbox(monkeypatch) -> None:
    monkeypatch.delenv("INDEX_OUTBOX_PATH", raising=False)
    resolved = resolve_outbox_path(None)
    assert resolved == Path(INDEX_OUTBOX_PATH)


def test_resolve_outbox_path_rejects_directory(tmp_path: Path) -> None:
    directory = tmp_path / "dir"
    directory.mkdir()
    with pytest.raises(OutboxPathError):
        resolve_outbox_path(directory)
