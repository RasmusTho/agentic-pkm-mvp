from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from app.settings import compiler

pytestmark = pytest.mark.not_pg


def _write_md(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(body).strip() + "\n", encoding="utf-8")


def test_auto_heal_rewrites_invalid_values(tmp_path, monkeypatch):
    vault = tmp_path / "vault" / "@Settings"
    runtime_dir = tmp_path / "runtime" / "settings"

    _write_md(
        vault / "global.md",
        """
        ---
        uuid: g
        ---
        ## Runtime
        ```yaml settings
        timeout_ms: "fast"
        log_level: "LOUD"
        ```
        """,
    )
    _write_md(
        vault / "providers.md",
        """
        ---
        uuid: p
        ---
        ## Provider defaults
        ```yaml settings
        llm: {}
        ```
        """,
    )
    _write_md(
        vault / "agents" / "classifier.md",
        """
        ---
        uuid: c
        ---
        ## Toggles
        - [x] enable

        ## Runtime
        ```yaml settings
        timeout_ms: fast
        min_confidence: 0.4
        ```
        """,
    )

    monkeypatch.setattr(compiler, "VAULT", vault)
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)

    bundle = compiler.compile_all(auto_heal=True)

    assert bundle.global_.timeout_ms == 8000
    assert bundle.agents["classifier"].timeout_ms == 8000

    agent_md = (vault / "agents" / "classifier.md").read_text(encoding="utf-8")
    assert "timeout_ms: 8000" in agent_md
    assert "<!-- BEGIN:settings:reference -->" in agent_md


def test_auto_heal_writes_settings_via_knowledge_port(tmp_path, monkeypatch) -> None:
    vault = tmp_path / "vault" / "@Settings"
    runtime_dir = tmp_path / "runtime" / "settings"

    _write_md(
        vault / "global.md",
        """
        ---
        uuid: g
        ---
        ## Runtime
        ```yaml settings
        timeout_ms: "fast"
        ```
        """,
    )
    _write_md(
        vault / "providers.md",
        """
        ---
        uuid: p
        ---
        ## Provider defaults
        ```yaml settings
        llm: {}
        ```
        """,
    )

    writes: list[str] = []

    class FakePort:
        def write_note(self, locator, content):  # type: ignore[no-untyped-def]
            writes.append(locator.path)
            target = (vault.parent / locator.path).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return None

    monkeypatch.setattr(compiler, "VAULT", vault)
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)
    monkeypatch.setattr("app.settings.writeback.resolve_knowledge_port", lambda **kwargs: FakePort())

    compiler.compile_all(auto_heal=True)

    assert "@Settings/global.md" in writes
