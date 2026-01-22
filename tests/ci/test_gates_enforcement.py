from __future__ import annotations

import pytest

from app.fitness.report import parse_summary_lines


def _assert_gates(lines: list[str]) -> None:
    parsed = parse_summary_lines(lines)
    gates = parsed.get("GATES") or {}
    ok_status = str(gates.get("ok", "false")).lower()
    reasons = gates.get("reasons")
    print(f"CI gates status: {ok_status} reasons={reasons}")
    if ok_status != "true":
        raise SystemExit(f"CI gates failed: {gates}")


def test_gates_logs_when_ok_true(capsys: pytest.CaptureFixture[str]) -> None:
    lines = ["CI SUMMARY GATES ok=true reasons=all-clear"]
    _assert_gates(lines)
    captured = capsys.readouterr()
    assert "CI gates status: true" in captured.out
    assert "all-clear" in captured.out


def test_gates_fails_when_ok_false(capsys: pytest.CaptureFixture[str]) -> None:
    lines = ["CI SUMMARY GATES ok=false reasons=bad-stuff"]
    with pytest.raises(SystemExit) as exc:
        _assert_gates(lines)
    assert "CI gates failed" in str(exc.value)
    captured = capsys.readouterr()
    assert "CI gates status: false" in captured.out
    assert "bad-stuff" in captured.out
