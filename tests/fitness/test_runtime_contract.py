from __future__ import annotations

import json
from pathlib import Path

from app.testing.runtime_contract import failing_check_names, write_contract_report


def test_failing_check_names_returns_false_entries_only() -> None:
    checks = {"a": True, "b": False, "c": False}
    assert failing_check_names(checks) == ["b", "c"]


def test_write_contract_report_writes_json(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    payload = {"checks": {"ok": True}, "errors": []}
    write_contract_report(path, payload)
    assert json.loads(path.read_text(encoding="utf-8")) == payload
