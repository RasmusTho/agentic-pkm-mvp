from __future__ import annotations

import subprocess

import pytest

from tests.deploy import compose_bind_support as support


@pytest.mark.parametrize("version,bind,expected", [
    ("2.38.2", {"create_host_path": True}, True),
    ("2.38.2", {"create_host_path": False}, False),
    ("2.38.2", {}, False),
    ("v2.40.3", {}, False),
    ("5.0.0", {}, True),
    ("5.1.3", {}, True),
    ("5.1.3", {"create_host_path": False}, False),
])
def test_omitted_create_host_path_follows_compose_renderer_default(
    monkeypatch: pytest.MonkeyPatch, version: str, bind: dict[str, object], expected: bool,
) -> None:
    support.compose_major_version.cache_clear()
    monkeypatch.setattr(support.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(
        a, 0, version + "\n", ""))
    try:
        assert support.effective_create_host_path(bind) is expected
    finally:
        support.compose_major_version.cache_clear()


def test_unparsable_compose_version_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    support.compose_major_version.cache_clear()
    monkeypatch.setattr(support.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(
        a, 0, "dev-build\n", ""))
    try:
        with pytest.raises(RuntimeError, match="unparsable docker compose version"):
            support.effective_create_host_path({})
    finally:
        support.compose_major_version.cache_clear()
