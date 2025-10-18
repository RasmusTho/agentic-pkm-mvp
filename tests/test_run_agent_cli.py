from unittest.mock import patch

from app.agent.models import AgentState
from run_agent import main


def _state(**overrides):
    defaults = {
        "run_id": "test-run",
        "task": overrides.get("task", "summarize"),
        "user_input": overrides.get("user_input"),
        "profile": overrides.get("profile", "work"),
        "result": overrides.get("result"),
        "cites": overrides.get("cites", []),
        "feedback": overrides.get("feedback"),
        "error": overrides.get("error"),
    }
    return AgentState(**defaults)


def test_dry_run_prints_preview(capsys):
    exit_code = main(["--task", "summarize", "--input", "demo text", "--dry-run"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Dry run" in out
    assert "summarize" in out
    assert "demo text" in out


def test_cli_invokes_agent_and_prints_result(capsys):
    fake_state = _state(result="All good", cites=["ctx:1"])
    with patch("run_agent.invoke", return_value=fake_state) as mock_invoke:
        exit_code = main(["--task", "summarize", "--input", "demo"])
    assert exit_code == 0
    mock_invoke.assert_called_once_with(task="summarize", profile="work", input_text="demo")

    out, err = capsys.readouterr()
    assert "All good" in out
    assert "Sources: ctx:1" in out
    assert err == ""


def test_cli_reports_agent_error(capsys):
    fake_state = _state(error="boom")
    with patch("run_agent.invoke", return_value=fake_state):
        exit_code = main(["--task", "summarize"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Agent reported error" in captured.err
