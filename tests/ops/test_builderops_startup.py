from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


def test_github_sync_partial_result_is_degraded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ops import builderops_startup

    responses = iter(
        [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="5000\n", stderr=""),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(
                    {
                        "ok": True,
                        "sync_result": "partial",
                        "sync_note": "kill switch skipped open-issue reconciliation",
                        "kill_switch_active": True,
                        "upserted": 3,
                        "reconciled": 0,
                        "repos": {
                            "RasmusTho/agentic-pkm-mvp": {
                                "sync_result": "partial",
                                "kill_switch_active": True,
                            }
                        },
                    }
                ),
                stderr="",
            ),
        ]
    )
    monkeypatch.setattr(builderops_startup, "_resolve_gh", lambda _gh_bin: "/usr/bin/gh")
    monkeypatch.setattr(builderops_startup, "_run", lambda *args, **kwargs: next(responses))
    result: dict[str, object] = {"reasons": []}

    receipt = builderops_startup._github_sync(
        python_bin="python3",
        root=tmp_path,
        repos=["RasmusTho/agentic-pkm-mvp"],
        env={},
        gh_bin="gh",
        rate_limit_min=25,
        skip=False,
        result=result,
    )

    assert receipt["status"] == "degraded"
    assert receipt["reason"] == "dispatcher_pull_partial"
    assert receipt["sync_result"] == "partial"
    assert receipt["kill_switch_active"] is True
    assert result["reasons"] == ["dispatcher_pull_partial"]
