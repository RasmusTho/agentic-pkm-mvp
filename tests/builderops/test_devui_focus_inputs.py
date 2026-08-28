from __future__ import annotations

import json
import subprocess

import pytest

from app.builderops.devui_focus_inputs import FocusInputError, read_focus_inputs


def test_focus_inputs_require_exact_configured_repository_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "title": "Source-authorized Issue",
                    "html_url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/4835",
                    "updated_at": "2026-08-13T12:00:00Z",
                }
            ),
            stderr="",
        )

    monkeypatch.setenv("COCKPIT_GITHUB_REPO", "RasmusTho/agentic-pkm-mvp")
    monkeypatch.setattr("app.builderops.devui_focus_inputs.subprocess.run", fake_run)

    result = read_focus_inputs("github:RasmusTho/agentic-pkm-mvp#4835")
    assert result["subject"]["stable_id"] == "github:RasmusTho/agentic-pkm-mvp#4835"
    assert calls == [["gh", "api", "repos/RasmusTho/agentic-pkm-mvp/issues/4835"]]

    calls.clear()
    with pytest.raises(FocusInputError, match="repository is not configured"):
        read_focus_inputs("github:someone-else/agentic-pkm-mvp#4835")
    assert calls == [], "a repository mismatch must refuse before any GitHub read"
