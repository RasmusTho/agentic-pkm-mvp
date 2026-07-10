from __future__ import annotations

import ast
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.briefing.compose import BRIEFING_WRITE_ACTION, briefing_note_path
from app.briefing.trigger import (
    first_contact_briefing,
    regenerate_briefing,
    scheduled_briefing_tick,
)
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard, WritesBlockedError

BRIEFING_DATE = date(2026, 7, 10)
MORNING = datetime(2026, 7, 10, 5, 15, tzinfo=timezone.utc)  # 07:15 Stockholm


def _context(tmp_path: Path) -> VaultContext:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings").mkdir()
    (vault / "settings" / "paths.md").write_text(
        "---\nsystemDir: system\n---\n", encoding="utf-8"
    )
    return VaultContext(status="selected", active_vault_id="v1", active_vault_path=str(vault))


def _write_fake_note(context: VaultContext, for_date: date) -> None:
    target = briefing_note_path(vault_context=context, for_date=for_date)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("briefing", encoding="utf-8")


def test_scheduled_tick_generates_once_per_day(tmp_path: Path) -> None:
    context = _context(tmp_path)
    calls = 0

    def compose(**kwargs: object) -> object:
        nonlocal calls
        calls += 1
        _write_fake_note(context, BRIEFING_DATE)
        return object()

    with patch("app.briefing.trigger.compose_briefing", side_effect=compose):
        first = scheduled_briefing_tick(vault_context=context, now=MORNING)
        second = scheduled_briefing_tick(vault_context=context, now=MORNING)
    assert first.triggered is True
    assert second.reason == "already_generated_today"
    assert calls == 1


def test_first_contact_of_day_falls_back_when_schedule_missed(tmp_path: Path) -> None:
    context = _context(tmp_path)

    def compose(**kwargs: object) -> object:
        _write_fake_note(context, BRIEFING_DATE)
        return object()

    with patch("app.briefing.trigger.compose_briefing", side_effect=compose) as mocked:
        result = first_contact_briefing(vault_context=context, now=MORNING)
    assert result.triggered is True
    assert result.reason == "first_contact"
    mocked.assert_called_once()


def test_duplicate_trigger_same_day_is_idempotent_at_call_site(tmp_path: Path) -> None:
    context = _context(tmp_path)
    barrier = threading.Barrier(2)
    calls = 0
    results = []

    def compose(**kwargs: object) -> object:
        nonlocal calls
        calls += 1
        _write_fake_note(context, BRIEFING_DATE)
        return object()

    def scheduled() -> None:
        barrier.wait()
        results.append(scheduled_briefing_tick(vault_context=context, now=MORNING))

    def companion() -> None:
        barrier.wait()
        results.append(first_contact_briefing(vault_context=context, now=MORNING))

    with patch("app.briefing.trigger.compose_briefing", side_effect=compose):
        threads = [threading.Thread(target=scheduled), threading.Thread(target=companion)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert calls == 1
    assert sum(result.triggered for result in results) == 1
    production_calls = {
        ("app/watcher/registry.py", "_run_briefing_tick"): "scheduled_briefing_tick",
        (
            "app/api/routes/companion.py",
            "trigger_first_contact_briefing",
        ): "first_contact_briefing",
    }
    for (path, function_name), expected_call in production_calls.items():
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        function = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        )
        assert any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == expected_call
            for node in ast.walk(function)
        )
    ui_tree = ast.parse(
        Path(
            "companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py"
        ).read_text(encoding="utf-8")
    )
    do_get = next(
        node
        for node in ast.walk(ui_tree)
        if isinstance(node, ast.FunctionDef) and node.name == "do_GET"
    )
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "post"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "/api/companion/briefing/first-contact"
        for node in ast.walk(do_get)
    )


def test_tunables_declared_once() -> None:
    names = {
        "BRIEFING_GENERATION_HOUR",
        "BRIEFING_TIMEZONE",
        "BRIEFING_ENABLED",
    }
    declarations: dict[str, list[str]] = {name: [] for name in names}
    for path in Path("app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in names:
                        declarations[target.id].append(path.as_posix())
    assert declarations == {name: ["app/briefing/config.py"] for name in names}
    docstring = ast.get_docstring(ast.parse(Path("app/briefing/config.py").read_text())) or ""
    assert "SINGLE_DEFAULT_REGISTRY" in docstring
    assert "provisional" in docstring.lower()


def test_manual_regenerate_bypasses_auto_trigger_guard(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _write_fake_note(context, BRIEFING_DATE)
    with patch("app.briefing.trigger.compose_briefing", return_value=object()) as mocked:
        result = regenerate_briefing(vault_context=context, for_date=BRIEFING_DATE)
    assert result.triggered is True
    assert result.reason == "manual_regenerate"
    mocked.assert_called_once()


def test_automatic_trigger_preserves_write_guard(tmp_path: Path) -> None:
    context = _context(tmp_path)
    guard = WriteGuard(lambda: {"state": "safe_mode", "reason": "test"})
    with pytest.raises(WritesBlockedError) as exc_info:
        scheduled_briefing_tick(vault_context=context, now=MORNING, write_guard=guard)
    assert exc_info.value.action == BRIEFING_WRITE_ACTION
