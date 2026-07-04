"""Guard-at-seam enforcement for the panel writeback path (#2808).

``execute_panel_intent`` (app/agents/panel_agent/runtime.py) writes vault note
markdown with no WriteGuard at the seam itself; two API callers
(PanelConfirmationService, CheckboxProjectionService) compensate caller-side,
but the CLI (`panel run` / `panel run-many`) and the outbox worker's
`PANEL_SCAN_REQUESTED` handler reach the same seam with no guard at all
(formal-model.md Divergence F-A). These tests assert the guard now lives at
the seam by exercising the real production call sites — the CLI entrypoint
and the worker handler — with writes blocked, and confirming zero vault file
mutation occurs.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.objects import DomainObject, ObjectStore
from app.write_guard import DEFAULT_WRITE_GUARD
from app.workers import outbox_worker
from tests.helpers.pkm_alpha_helper import reset_memory_stores


_PANEL_MARKDOWN_TEMPLATE = """%% AI:Start %%
## AI-instruktion
Promote please.
## AI-åtgärder
- [x] Gör denna anteckning evergreen
%% AI:End %%
"""


def _seed_note(note_uuid: str, markdown: str, *, source_ref: str = "vault/Note.md") -> None:
    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload={"raw_text": markdown, "origin": "vault"},
        source_ref=source_ref,
        created_at=datetime.now(timezone.utc),
    )
    ObjectStore().save_object(obj, emit_outbox=False, trace_id="trace-writeback-guard")


def _write_panel_actions_settings(tmp_path: Path) -> Path:
    settings_path = tmp_path / "panel-actions.md"
    settings_path.write_text(
        """---
mappings:
  - id: promote.evergreen
    label: "Gör denna anteckning evergreen"
    intent_type: promotion
    trust_verb: APPLY
    downstream_event: review.promote.evergreen
    params:
      maturity: evergreen
---
""",
        encoding="utf-8",
    )
    return settings_path


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    reset_memory_stores()


def test_cli_path_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`panel run` (CLI) must refuse the vault write when WriteGuard blocks,
    with no partial file mutation, instead of writing checkbox removal +
    receipts via the unguarded seam.
    """
    note_uuid = str(uuid.uuid4())
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    note_path = vault_root / "panel-note.md"
    note_path.write_text(_PANEL_MARKDOWN_TEMPLATE, encoding="utf-8")
    original_content = note_path.read_text(encoding="utf-8")

    _seed_note(note_uuid, _PANEL_MARKDOWN_TEMPLATE, source_ref=str(note_path))

    settings_path = _write_panel_actions_settings(tmp_path)
    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))

    # Simulate a blocked write-guard state (health contract short-circuit),
    # exactly as tests/cli/test_health_authority_spine.py does.
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "safe_mode", "reason": "test-blocked"})

    runner = CliRunner()
    env = {
        "INDEX_OUTBOX_PATH": str(outbox_path),
        "PANEL_ACTIONS_PATH": str(settings_path),
        "VAULT_ROOT": str(vault_root),
    }
    result = runner.invoke(cli, ["panel", "run", "--uuid", note_uuid], env=env)

    # The CLI must not crash uncontrolled into a stack trace with partial
    # side effects; it must surface the block and exit non-zero.
    assert result.exit_code != 0, result.output

    # No partial file mutation: the note file on disk is byte-for-byte
    # unchanged (no checkbox removal, no receipt block written).
    assert note_path.read_text(encoding="utf-8") == original_content


def test_worker_path_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The outbox worker's PANEL_SCAN_REQUESTED handler must refuse the vault
    write when WriteGuard blocks, with no partial file mutation.
    """
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))

    vault_root = tmp_path / "vault"
    inbox = vault_root / "\U0001f4e5 Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    note_uuid = str(uuid.uuid4())
    note_path = inbox / "panel-note.md"
    note_path.write_text(
        "---\n"
        f"uuid: {note_uuid}\n"
        "ai_panel_auto_run: watcher\n"
        "---\n"
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        "Promote this test note when checked.\n\n"
        "## AI-åtgärder\n"
        "- [x] Make this note evergreen <!--ai:id=promote.evergreen-->\n\n"
        "## AI-logg\n"
        "%% AI:End %%\n",
        encoding="utf-8",
    )
    original_content = note_path.read_text(encoding="utf-8")

    payload = {
        "vault_path": str(note_path),
        "relative_path": "\U0001f4e5 Inbox/panel-note.md",
        "hash": "test-hash",
        "mtime": 123.0,
    }

    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "safe_mode", "reason": "test-blocked"})

    from app.write_guard import WritesBlockedError

    with pytest.raises(WritesBlockedError):
        outbox_worker.handle_panel_scan_requested(payload, vault_root=vault_root)

    # No partial file mutation: checkbox removal / receipt writeback never
    # reached the vault file.
    assert note_path.read_text(encoding="utf-8") == original_content
