from __future__ import annotations

from pathlib import Path

import pytest

from app.stores import reset_store_backends
from app.watcher.vault_watcher import run_watcher_daemon, run_watcher_tick

pytestmark = pytest.mark.not_pg


def _write_note(base: Path, rel: str, body: str) -> Path:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_watcher_tick_uses_external_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reset_store_backends()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    vault = tmp_path / "PKM - Alpha"
    snapshot = tmp_path / "state" / "vault_watcher_state.json"
    _write_note(
        vault,
        "Notes/A.md",
        """---
uuid: NOTE-1
ai_panel_auto_run: watcher
---
content
""",
    )

    summary, _ = run_watcher_tick(
        vault_root=vault,
        snapshot_path=snapshot,
        skip_panel=True,
        emit_only=False,
        dry_run=False,
        max_notes=10,
        force=False,
        outbox_path=tmp_path / "outbox.jsonl",
    )

    assert summary["changed"] == 1
    assert snapshot.exists()
    assert snapshot.parent != vault
    assert "snapshot_path" in summary
    assert summary["snapshot_path"].endswith("vault_watcher_state.json")


def test_watcher_daemon_respects_cooldown_and_poll(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reset_store_backends()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    vault = tmp_path / "Vault"
    _write_note(
        vault,
        "Notes/A.md",
        """---
uuid: 12345678-1234-1234-1234-123456789abc
ai_panel_auto_run: watcher
---
content
""",
    )
    snapshot = tmp_path / "state" / "daemon.json"
    sleeps: list[float] = []

    summaries = run_watcher_daemon(
        vault_root=vault,
        snapshot_path=snapshot,
        skip_panel=True,
        emit_only=False,
        dry_run=False,
        max_notes=10,
        force=False,
        poll_seconds=3,
        cooldown_seconds=7,
        max_loops=2,
        sleep_fn=sleeps.append,
        outbox_path=tmp_path / "outbox.jsonl",
    )

    assert len(summaries) == 2
    assert summaries[0]["changed"] == 1
    assert summaries[1]["changed"] == 0
    assert sleeps == [7]


def test_watcher_counts_panel_candidate_for_ai_fence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reset_store_backends()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("WATCHER_AUTO_EXEC", "1")
    vault = tmp_path / "Vault"
    _write_note(
        vault,
        "Notes/Panel.md",
        """---
uuid: 00000000-0000-0000-0000-000000000000
---
%% AI:Start %%
## AI-instruction
- [ ] Run this action
%% AI:End %%
""",
    )
    snapshot = tmp_path / "state" / "panel-candidate.json"

    summary, _ = run_watcher_tick(
        vault_root=vault,
        snapshot_path=snapshot,
        skip_panel=True,
        emit_only=False,
        dry_run=False,
        max_notes=10,
        force=False,
        outbox_path=tmp_path / "outbox.jsonl",
    )

    assert summary["panel_candidates"] == 1
    assert summary["panel_skipped_policy"] == 0
