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
        vault / "llm_routing.md",
        """
        ---
        uuid: r
        ---
        ## Routing
        ```yaml settings
        default_chat:
          primary:
            provider: openai
            model: gpt-4.1-mini
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
    _write_md(
        vault / "llm_routing.md",
        """
        ---
        uuid: r
        ---
        ## Routing
        ```yaml settings
        default_chat:
          primary:
            provider: openai
            model: gpt-4.1-mini
        ```
        """,
    )

    writes: list[str] = []

    def _fake_write_note(path: Path, content: str, *, vault_root: Path | None = None):  # type: ignore[no-untyped-def]
        resolved_root = (vault_root or vault.parent).resolve()
        resolved_path = Path(path).resolve()
        rel = resolved_path.relative_to(resolved_root).as_posix()
        writes.append(rel)
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(content, encoding="utf-8")
        return None

    monkeypatch.setattr(compiler, "VAULT", vault)
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)
    monkeypatch.setattr("app.settings.writeback.write_note_from_absolute", _fake_write_note)

    compiler.compile_all(auto_heal=True)

    assert "@Settings/global.md" in writes


def test_compile_all_writes_llm_routing_runtime_file(tmp_path, monkeypatch) -> None:
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
        log_level: INFO
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
        vault / "llm_routing.md",
        """
        ---
        uuid: r
        ---
        ## Routing
        ```yaml settings
        tasks:
          plan:
            primary:
              provider: deepseek
              model: deepseek-chat
        ```
        """,
    )

    monkeypatch.setattr(compiler, "VAULT", vault)
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)

    bundle = compiler.compile_all(auto_heal=False)

    assert bundle.llm_routing.tasks["plan"].primary.provider == "deepseek"
    compiled = (runtime_dir / "llm_routing.yaml").read_text(encoding="utf-8")
    assert "deepseek" in compiled
