from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

import app.watcher.registry as registry
from scripts.yaml_roundtrip import load_frontmatter

pytestmark = pytest.mark.not_pg


def _write_config(path: Path) -> None:
    path.write_text(
        dedent(
            """\
            version: 1
            watchers:
              - name: panel
                scope_glob: "${VAULT_INBOX_DIR_REL}/**"
                debounce_ms: 0
                rate_limit_per_min: 120
                emit_event: "panel.scan.requested"
            """
        ),
        encoding="utf-8",
    )


def _write_note(path: Path, frontmatter: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")


def test_registry_panel_policy_skips_never_and_counts_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    inbox = vault_root / "📥 Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    candidate = inbox / "candidate.md"
    _write_note(
        candidate,
        "title: Candidate",
        "%% AI:Start %%\n- [ ] Do thing\n%% AI:End %%",
    )

    never = inbox / "never.md"
    _write_note(
        never,
        "title: Never\nai_panel_auto_run: never",
        "%% AI:Start %%\n- [ ] Do thing\n%% AI:End %%",
    )

    config_path = tmp_path / "watchers.yaml"
    _write_config(config_path)

    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault_root))
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "📥 Inbox")
    monkeypatch.setenv("WATCHER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("WATCHER_AUTO_EXEC", "1")
    monkeypatch.setenv("WATCHER_SUMMARY_INTERVAL", "0")
    monkeypatch.setenv("WATCHER_TICK_SLEEP_SECONDS", "0.05")
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "0")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))

    processed: list[str] = []
    original_process = registry._process_panel_note

    def spy_process(*, vault_root, rel_path, outbox_path, state, action_mappings):
        processed.append(str(rel_path))
        return original_process(
            vault_root=vault_root,
            rel_path=rel_path,
            outbox_path=outbox_path,
            state=state,
            action_mappings=action_mappings,
        )

    monkeypatch.setattr(registry, "_process_panel_note", spy_process)

    summaries = registry.run_registry_once(config_path)
    summary = summaries["panel"]

    assert "📥 Inbox/candidate.md" in processed
    assert "📥 Inbox/never.md" not in processed
    assert summary.get("panel_candidates") == 1
    assert summary.get("panel_skipped_policy") == 1


def test_registry_panel_auto_exec_disabled_skips_mutations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    inbox = vault_root / "📥 Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    candidate = inbox / "candidate.md"
    _write_note(
        candidate,
        "title: Candidate",
        "%% AI:Start %%\n- [ ] Do thing\n%% AI:End %%",
    )

    config_path = tmp_path / "watchers.yaml"
    _write_config(config_path)

    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault_root))
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "📥 Inbox")
    monkeypatch.setenv("WATCHER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("WATCHER_AUTO_EXEC", "0")
    monkeypatch.setenv("WATCHER_SUMMARY_INTERVAL", "0")
    monkeypatch.setenv("WATCHER_TICK_SLEEP_SECONDS", "0.05")
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "0")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))

    processed: list[str] = []
    monkeypatch.setattr(registry, "_process_panel_note", lambda **_: processed.append("called"))

    summaries = registry.run_registry_once(config_path)
    summary = summaries["panel"]

    assert processed == []
    assert summary.get("panel_candidates") == 1
    assert summary.get("panel_skipped_auto_exec") == 1

    frontmatter, _ = load_frontmatter(candidate.read_text(encoding="utf-8"))
    assert not str(frontmatter.get("uuid") or "").strip()
