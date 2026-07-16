"""Guard-at-seam enforcement for the settings compile writeback path (#2809).

``settings compile``/``settings watch`` write ``vault/@Settings/*.md`` via
``app/settings/writeback.py`` with no WriteGuard and no outbox event
(formal-model.md Divergence F-B). This test asserts the guard now lives at
the seam (``write_markdown_via_knowledge_port``, the single physical write
function behind both ``writeback_settings_block`` and the compiler's
auto-heal reference update) by exercising the real ``settings compile`` CLI
entrypoint with writes blocked, and confirming zero file mutation plus a
clean non-zero CLI exit.
"""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from click.testing import CliRunner

import app.cli as cli_module
from app.cli import cli
from app.settings import compiler
from app.write_guard import DEFAULT_WRITE_GUARD

pytestmark = pytest.mark.not_pg


def _write_md(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(body).strip() + "\n", encoding="utf-8")


def _seed_vault_needing_auto_heal(vault: Path) -> None:
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
            model_id: openai.chat.gpt_5_4_mini
        ```
        """,
    )


def test_blocked_compile_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "vault" / "@Settings"
    runtime_dir = tmp_path / "runtime" / "settings"
    _seed_vault_needing_auto_heal(vault)

    # Snapshot every settings file's content before compiling, so we can
    # assert byte-for-byte no mutation happened anywhere in @Settings.
    before = {p: p.read_text(encoding="utf-8") for p in sorted(vault.glob("*.md"))}
    assert before, "fixture must seed at least one settings file"
    assert not runtime_dir.exists()

    monkeypatch.setattr(compiler, "VAULT", vault)
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)
    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "safe_mode", "reason": "test-blocked"}
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["settings", "compile", "--auto-heal"])

    # Clean CLI non-zero error, not an uncaught traceback with partial
    # compilation.
    assert result.exit_code != 0
    assert "blocked" in result.output.lower()

    # Zero file mutations: every settings markdown file is byte-for-byte
    # unchanged from before the blocked compile attempt.
    after = {p: p.read_text(encoding="utf-8") for p in sorted(vault.glob("*.md"))}
    assert after == before


def test_settings_watch_compiles_the_watched_settings_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    watch_path = tmp_path / "custom-vault" / "settings"
    watch_path.mkdir(parents=True)
    legacy_watch_path = watch_path.parent / "@Settings"
    legacy_watch_path.mkdir()
    compile_calls: list[dict[str, object]] = []
    watch_calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        cli_module,
        "compile_all",
        lambda **kwargs: compile_calls.append(kwargs),
    )

    def _watch_once(*args: str, **_kwargs: object):
        watch_calls.append(args)
        yield [("modified", str(watch_path / "global.md"))]
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_module, "watch", _watch_once)

    result = CliRunner().invoke(
        cli,
        ["settings", "watch", "--path", str(watch_path)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert compile_calls == [
        {"auto_heal": False, "vault_root": watch_path.parent.resolve()},
        {"auto_heal": False, "vault_root": watch_path.parent.resolve()},
    ]
    assert watch_calls == [(str(watch_path.resolve()), str(legacy_watch_path))]
