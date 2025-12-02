from __future__ import annotations

import json
import textwrap
from pathlib import Path

from click.testing import CliRunner

from app.cli import cli


def _write_test_note(vault: Path) -> Path:
    note = vault / "Test" / "Alpha-HumanFlows.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        textwrap.dedent(
            """
            ---
            uuid: test-alpha-uuid
            ---
            Body text for indexing.

            %% AI:Start %%
            ## AI-instruktion
            Fact check: The Earth has two moons.
            ## AI-åtgärder
            - [ ] Mark this fact as incorrect
            ## AI-logg
            - inserted
            %% AI:End %%
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return note


def test_alpha_human_flows_outbox_strips_panels(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_test_note(vault)
    outbox = tmp_path / "outbox.jsonl"

    runner = CliRunner()
    env = {
        "INDEX_OUTBOX_PATH": str(outbox),
        "STORE_BACKEND": "memory",
        "LLM_PROVIDER": "mock",
        "LLM_MOCK_RESPONSE": "Mock outbox test",
    }
    result = runner.invoke(
        cli,
        ["alpha-human-flows", "--vault-root", str(vault), "--sample-size", "0", "--reset-outbox"],
        env=env,
    )

    assert result.exit_code == 0, result.output
    assert outbox.exists()
    content = outbox.read_text(encoding="utf-8")
    assert "The Earth has two moons" not in content
    assert "AI-instruktion" not in content
    assert "AI-åtgärder" not in content
    assert "AI-logg" not in content

    lines = [json.loads(line) for line in content.splitlines() if line.strip()]
    assert lines
    payloads = [entry.get("payload") or {} for entry in lines]
    text_seen = " ".join(json.dumps(p) for p in payloads)
    assert "Body text for indexing." in text_seen


def test_alpha_human_flows_outbox_reset_and_dry_run(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_test_note(vault)
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text("legacy The Earth has two moons.\n", encoding="utf-8")

    runner = CliRunner()
    env = {
        "INDEX_OUTBOX_PATH": str(outbox),
        "STORE_BACKEND": "memory",
        "LLM_PROVIDER": "mock",
        "LLM_MOCK_RESPONSE": "Mock outbox test",
    }
    result = runner.invoke(
        cli,
        ["alpha-human-flows", "--vault-root", str(vault), "--sample-size", "0", "--reset-outbox", "--dry-run"],
        env=env,
    )

    assert result.exit_code == 0, result.output
    content = outbox.read_text(encoding="utf-8")
    assert "legacy The Earth has two moons." in content


def test_alpha_human_flows_outbox_reset_truncates(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_test_note(vault)
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text("legacy The Earth has two moons.\nAI-logg legacy\n", encoding="utf-8")

    runner = CliRunner()
    env = {
        "INDEX_OUTBOX_PATH": str(outbox),
        "STORE_BACKEND": "memory",
        "LLM_PROVIDER": "mock",
        "LLM_MOCK_RESPONSE": "Mock outbox test",
    }
    result = runner.invoke(
        cli,
        ["alpha-human-flows", "--vault-root", str(vault), "--sample-size", "0", "--reset-outbox"],
        env=env,
    )

    assert result.exit_code == 0, result.output
    content = outbox.read_text(encoding="utf-8")
    assert "legacy The Earth has two moons." not in content
    assert "AI-logg" not in content
    lines = [json.loads(line) for line in content.splitlines() if line.strip()]
    assert lines
    text_seen = " ".join(json.dumps(entry.get("payload") or {}) for entry in lines)
    assert "Body text for indexing." in text_seen
    assert "The Earth has two moons" not in content
    assert "AI-instruktion" not in content
    assert "AI-åtgärder" not in content
