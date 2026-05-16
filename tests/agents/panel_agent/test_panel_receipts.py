"""Issue #980: visible no-op and proposal receipts in the PanelAgent runtime.

These tests exercise the real PanelAgent LangGraph (no graph mocking) to confirm
that no-match runs, proposal-generation paths, and fallback diagnostics produce
visible bounded feedback in the AI status callout, that receipts remain bounded,
and that existing execution receipts for checked actions are preserved.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.agents.panel.writeback import AI_STATUS_HEADER, MAX_RECEIPTS
from app.agents.panel_agent.agent import run_panel_intent_for_note
from app.agents.panel_agent.runtime import PanelRuntimeResult, execute_panel_intent
from app.store import object_store as object_store_module
from app.store.object_store import DomainObject, ObjectStore


class _StubReasoningFacade:
    def __init__(self, response: dict) -> None:
        self._response = response

    def structured(self, messages, schema, *, task_kind: str, trace_id: str | None = None) -> dict:
        return self._response


def _seed_note(note_uuid: str, markdown: str, *, source_ref: str) -> None:
    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload={"raw_text": markdown, "origin": "vault"},
        source_ref=source_ref,
        created_at=datetime.now(timezone.utc),
    )
    ObjectStore().save_object(obj, emit_outbox=False)


def _settings_file(
    tmp_path: Path,
    *,
    action_id: str,
    label: str,
    intent_type: str,
    downstream_event: str,
    trust_verb: str | None = None,
) -> Path:
    path = tmp_path / "panel-actions.md"
    trust_line = f'    trust_verb: "{trust_verb}"\n' if trust_verb else ""
    path.write_text(
        f"""---
mappings:
  - id: \"{action_id}\"
    label: \"{label}\"
    intent_type: \"{intent_type}\"
{trust_line}    downstream_event: \"{downstream_event}\"
    params:
      maturity: \"evergreen\"
---
""",
        encoding="utf-8",
    )
    return path


def _vault_note(tmp_path: Path, note_uuid: str, markdown: str) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    note_file = vault / "n.md"
    note_file.write_text(markdown, encoding="utf-8")
    _seed_note(note_uuid, markdown, source_ref=str(note_file))
    return note_file


@pytest.fixture(autouse=True)
def _clear_memory_store() -> None:
    object_store_module._MEMORY_STORE.clear()


def _read_outbox(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_freeform_no_match_writes_visible_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #980-1: a freeform LLM pass that returns no matching action surfaces a
    visible bounded receipt line in the AI status callout and emits a
    `panel.action.logged` event with `reason: no_actions_matched`.
    """
    note_uuid = str(uuid4())
    settings_path = _settings_file(
        tmp_path,
        action_id="promote.evergreen",
        label="Make this note evergreen",
        intent_type="promotion",
        trust_verb="APPLY",
        downstream_event="review.promote.evergreen",
    )
    # Freeform panel with an instruction the LLM cannot map to anything.
    markdown = (
        "---\n"
        f"uuid: {note_uuid}\n"
        "---\n"
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        "Please do something that has no canonical action.\n"
        "%% AI:End %%\n"
    )
    note_file = _vault_note(tmp_path, note_uuid, markdown)
    outbox_path = tmp_path / "outbox.jsonl"

    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("VAULT_ROOT", str(note_file.parent))
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "llm")
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)
    # LLM returns empty selection: nothing fits.
    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": []}),
    )

    events = run_panel_intent_for_note(note_uuid, trace_id="trace-980-1", trigger="watcher")
    assert len(events) == 1
    result = execute_panel_intent(events[0], outbox_path=outbox_path)
    assert isinstance(result, PanelRuntimeResult)

    # Visible receipt in the AI status callout.
    updated = note_file.read_text(encoding="utf-8")
    assert AI_STATUS_HEADER in updated
    assert "Inga åtgärder matchade" in updated

    # Bounded event signal for downstream observability.
    records = _read_outbox(outbox_path)
    logged = [
        r for r in records
        if r.get("event") == "panel.action.logged"
        and (r.get("payload") or {}).get("reason") == "no_actions_matched"
    ]
    assert logged, "expected a panel.action.logged event with reason=no_actions_matched"


def test_proposal_generation_writes_receipt_without_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #980-2: a freeform proposal-generation pass for a governance-bearing
    capability writes a visible proposal receipt line in the AI status callout
    while NOT executing the governed effect in the same pass (preserves #979).
    """
    note_uuid = str(uuid4())
    settings_path = _settings_file(
        tmp_path,
        action_id="promote.evergreen",
        label="Make this note evergreen",
        intent_type="promotion",
        trust_verb="APPLY",
        downstream_event="review.promote.evergreen",
    )
    markdown = (
        "---\n"
        f"uuid: {note_uuid}\n"
        "---\n"
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        "Make this note evergreen\n"
        "%% AI:End %%\n"
    )
    note_file = _vault_note(tmp_path, note_uuid, markdown)
    outbox_path = tmp_path / "outbox.jsonl"

    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("VAULT_ROOT", str(note_file.parent))
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "llm")
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)
    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": [{"id": "promote.evergreen"}]}),
    )

    events = run_panel_intent_for_note(note_uuid, trace_id="trace-980-2", trigger="watcher")
    execute_panel_intent(events[0], outbox_path=outbox_path)

    updated = note_file.read_text(encoding="utf-8")
    # Visible proposal receipt line.
    assert AI_STATUS_HEADER in updated
    assert "Förslag: Make this note evergreen" in updated
    assert "väntar bekräftelse" in updated

    # No governance-bearing execution event fires from a proposal-only pass.
    records = _read_outbox(outbox_path)
    topics = {r.get("event") for r in records}
    assert "promote.intent.created" not in topics
    # Proposal_offered event IS emitted.
    proposal_offered = [
        r for r in records
        if r.get("event") == "panel.action.logged"
        and (r.get("payload") or {}).get("reason") == "proposal_offered"
    ]
    assert proposal_offered


def test_fallback_and_no_match_are_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #980-3: a checked action that has no canonical mapping surfaces a
    bounded fallback receipt in the AI status callout (visible diagnostic for
    'AI status or AI-log fallback/no-match outcomes').
    """
    note_uuid = str(uuid4())
    settings_path = _settings_file(
        tmp_path,
        action_id="promote.evergreen",
        label="Make this note evergreen",
        intent_type="promotion",
        trust_verb="APPLY",
        downstream_event="review.promote.evergreen",
    )
    # Checkbox labelled with a string that does NOT match the catalog label, so
    # the action falls into the unmapped_action bucket and produces a logged
    # outcome the human should see.
    markdown = (
        "---\n"
        f"uuid: {note_uuid}\n"
        "---\n"
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        "Do something\n"
        "## AI-åtgärder\n"
        "- [x] Some unmapped freeform request\n"
        "%% AI:End %%\n"
    )
    note_file = _vault_note(tmp_path, note_uuid, markdown)
    outbox_path = tmp_path / "outbox.jsonl"

    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("VAULT_ROOT", str(note_file.parent))
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    events = run_panel_intent_for_note(note_uuid, trace_id="trace-980-3", trigger="watcher")
    execute_panel_intent(events[0], outbox_path=outbox_path)

    updated = note_file.read_text(encoding="utf-8")
    assert AI_STATUS_HEADER in updated
    # The unmapped action surfaces as a visible warning receipt with a reason.
    assert "Some unmapped freeform request" in updated
    assert "unmapped_action" in updated


def test_receipts_remain_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #980-4: receipt block stays bounded — total receipts in AI status
    callout never exceed MAX_RECEIPTS, even after many runs.
    """
    note_uuid = str(uuid4())
    settings_path = _settings_file(
        tmp_path,
        action_id="promote.evergreen",
        label="Make this note evergreen",
        intent_type="promotion",
        trust_verb="APPLY",
        downstream_event="review.promote.evergreen",
    )
    # Seed an AI status callout that already has MAX_RECEIPTS + 5 lines.
    receipts_block = "\n".join(
        f"> - ✅ historic-{i} (2026-01-01 00:00)" for i in range(MAX_RECEIPTS + 5)
    )
    markdown = (
        "---\n"
        f"uuid: {note_uuid}\n"
        "---\n"
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        "Please do something that has no canonical action.\n"
        "%% AI:End %%\n"
        f"{AI_STATUS_HEADER}\n"
        f"{receipts_block}\n"
    )
    note_file = _vault_note(tmp_path, note_uuid, markdown)
    outbox_path = tmp_path / "outbox.jsonl"

    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("VAULT_ROOT", str(note_file.parent))
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "llm")
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)
    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": []}),
    )

    events = run_panel_intent_for_note(note_uuid, trace_id="trace-980-4", trigger="watcher")
    execute_panel_intent(events[0], outbox_path=outbox_path)

    updated = note_file.read_text(encoding="utf-8")
    # Count receipt lines (lines starting with `> - ` inside the AI status block).
    receipt_lines = [ln for ln in updated.splitlines() if ln.startswith("> - ")]
    assert len(receipt_lines) <= MAX_RECEIPTS, (
        f"AI status callout exceeded MAX_RECEIPTS={MAX_RECEIPTS}: {len(receipt_lines)} lines"
    )


# ---------------------------------------------------------------------------
# Issue #1012: suppress repeated no-match receipts on rerun
# ---------------------------------------------------------------------------

def _no_match_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, note_uuid: str) -> tuple[Path, Path]:
    """Shared setup for no-match rerun tests. Returns (note_file, outbox_path)."""
    settings_path = _settings_file(
        tmp_path,
        action_id="promote.evergreen",
        label="Make this note evergreen",
        intent_type="promotion",
        trust_verb="APPLY",
        downstream_event="review.promote.evergreen",
    )
    markdown = (
        "---\n"
        f"uuid: {note_uuid}\n"
        "---\n"
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        "Please do something that has no canonical action.\n"
        "%% AI:End %%\n"
    )
    note_file = _vault_note(tmp_path, note_uuid, markdown)
    outbox_path = tmp_path / "outbox.jsonl"

    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("VAULT_ROOT", str(note_file.parent))
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "llm")
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)
    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": []}),
    )
    return note_file, outbox_path


def test_no_match_rerun_unchanged_input_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #1012-1 + #1012-2: rerun with unchanged instruction must not append
    another 'Inga åtgärder matchade' line or emit another panel.action.logged event.
    """
    note_uuid = str(uuid4())
    note_file, outbox_path = _no_match_setup(tmp_path, monkeypatch, note_uuid)

    # First run.
    events = run_panel_intent_for_note(note_uuid, trace_id="trace-1012-a", trigger="watcher")
    execute_panel_intent(events[0], outbox_path=outbox_path)

    after_first = note_file.read_text(encoding="utf-8")
    assert "Inga åtgärder matchade" in after_first
    no_match_count_1 = after_first.count("Inga åtgärder matchade")

    logged_events_1 = [
        r for r in _read_outbox(outbox_path)
        if r.get("event") == "panel.action.logged"
        and (r.get("payload") or {}).get("reason") == "no_actions_matched"
    ]
    assert logged_events_1, "expected a no_actions_matched event on first run"

    # Simulate watcher re-index: update ObjectStore with the post-writeback content.
    _seed_note(note_uuid, after_first, source_ref=str(note_file))

    # Second run — same instruction.
    events2 = run_panel_intent_for_note(note_uuid, trace_id="trace-1012-b", trigger="watcher")
    execute_panel_intent(events2[0], outbox_path=outbox_path)

    after_second = note_file.read_text(encoding="utf-8")
    assert after_second.count("Inga åtgärder matchade") == no_match_count_1, (
        "rerun appended a duplicate no-match receipt line"
    )

    logged_events_2 = [
        r for r in _read_outbox(outbox_path)
        if r.get("event") == "panel.action.logged"
        and (r.get("payload") or {}).get("reason") == "no_actions_matched"
    ]
    assert len(logged_events_2) == len(logged_events_1), (
        "rerun emitted an extra panel.action.logged(no_actions_matched) event"
    )


def test_no_match_changed_input_writes_fresh_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #1012-3: if the panel instruction changes between runs and still resolves
    to no-match, a new receipt IS written.
    """
    note_uuid = str(uuid4())
    note_file, outbox_path = _no_match_setup(tmp_path, monkeypatch, note_uuid)

    # First run.
    events = run_panel_intent_for_note(note_uuid, trace_id="trace-1012-c", trigger="watcher")
    execute_panel_intent(events[0], outbox_path=outbox_path)

    after_first = note_file.read_text(encoding="utf-8")
    assert "Inga åtgärder matchade" in after_first

    # Simulate instruction change: replace the panel instruction.
    changed_markdown = after_first.replace(
        "Please do something that has no canonical action.",
        "Please do something different that also has no canonical action.",
    )
    note_file.write_text(changed_markdown, encoding="utf-8")
    _seed_note(note_uuid, changed_markdown, source_ref=str(note_file))

    # Second run — different instruction.
    events2 = run_panel_intent_for_note(note_uuid, trace_id="trace-1012-d", trigger="watcher")
    execute_panel_intent(events2[0], outbox_path=outbox_path)

    after_second = note_file.read_text(encoding="utf-8")
    assert after_second.count("Inga åtgärder matchade") > after_first.count("Inga åtgärder matchade"), (
        "expected a fresh no-match receipt for changed instruction"
    )


def test_fallback_rerun_unchanged_input_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #1012-4: a rerun of an unmapped checked action must not append a duplicate
    fallback receipt or emit an extra event when the action and reason are unchanged.
    """
    note_uuid = str(uuid4())
    settings_path = _settings_file(
        tmp_path,
        action_id="promote.evergreen",
        label="Make this note evergreen",
        intent_type="promotion",
        trust_verb="APPLY",
        downstream_event="review.promote.evergreen",
    )
    markdown = (
        "---\n"
        f"uuid: {note_uuid}\n"
        "---\n"
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        "Do something\n"
        "## AI-åtgärder\n"
        "- [x] Some unmapped freeform request\n"
        "%% AI:End %%\n"
    )
    note_file = _vault_note(tmp_path, note_uuid, markdown)
    outbox_path = tmp_path / "outbox.jsonl"

    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("VAULT_ROOT", str(note_file.parent))
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    # First run.
    events = run_panel_intent_for_note(note_uuid, trace_id="trace-1012-e", trigger="watcher")
    execute_panel_intent(events[0], outbox_path=outbox_path)

    after_first = note_file.read_text(encoding="utf-8")
    assert "unmapped_action" in after_first
    fallback_count_1 = after_first.count("unmapped_action")

    # Simulate re-index with same content (fallback action was removed from panel).
    _seed_note(note_uuid, after_first, source_ref=str(note_file))

    # Second run — same note, no new checked action.
    events2 = run_panel_intent_for_note(note_uuid, trace_id="trace-1012-f", trigger="watcher")
    execute_panel_intent(events2[0], outbox_path=outbox_path)

    after_second = note_file.read_text(encoding="utf-8")
    assert after_second.count("unmapped_action") == fallback_count_1, (
        "rerun appended a duplicate fallback receipt"
    )
