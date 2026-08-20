from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import scripts.replay_pr_test_selection as replay


def _fake_history(*args: str) -> str:
    responses = {
        ("rev-parse", "--verify", "main^{commit}"): "head-sha\n",
        ("rev-list", "--first-parent", "--max-count=3", "head-sha"): "c3\nc2\nc1\n",
        ("rev-parse", "--verify", "c3^"): "p3\n",
        ("rev-parse", "--verify", "c2^"): "p2\n",
        ("rev-parse", "--verify", "c1^"): "p1\n",
        ("diff", "--name-only", "p3", "c3"): "pyproject.toml\n",
        ("diff", "--name-only", "p2", "c2"): "app/new_surface/example.py\n",
        (
            "diff",
            "--name-only",
            "p1",
            "c1",
        ): "companion-ui/companion-app/companion_ui/workspace/view.py\napp/instance/vault_registry.py\n",
    }
    return responses[args]


def test_replay_reports_current_policy_metrics(tmp_path: Path) -> None:
    selector_path = tmp_path / "select_pr_tests.py"
    selector_path.write_text("current selector policy\n", encoding="utf-8")

    report = replay.build_report(
        ref="main",
        limit=3,
        selector_path=selector_path,
        run_git=_fake_history,
    )

    assert report["metrics"] == {
        "deliveries": 3,
        "full_suite": {"count": 1, "rate": 1 / 3},
        "unowned": {"count": 1, "rate": 1 / 3},
        "multi_subsystem": {"count": 1, "rate": 1 / 3},
    }
    assert [delivery["commit"] for delivery in report["deliveries"]] == ["c3", "c2", "c1"]
    assert report["deliveries"][0]["selection"]["full_suite"] is True
    assert report["deliveries"][1]["selection"]["unowned_paths"] == [
        "app/new_surface/example.py"
    ]
    assert len(report["deliveries"][2]["selection"]["subsystems"]) > 1


def test_replay_binds_output_to_selector_and_ref(tmp_path: Path) -> None:
    selector_path = tmp_path / "select_pr_tests.py"
    selector_bytes = b"selector-version\n"
    selector_path.write_bytes(selector_bytes)

    report = replay.build_report(
        ref="main",
        limit=3,
        selector_path=selector_path,
        run_git=_fake_history,
    )

    assert report["schema_version"] == "affected-test-selector-replay.v1"
    assert report["selector"] == {
        "path": str(selector_path),
        "sha256": hashlib.sha256(selector_bytes).hexdigest(),
    }
    assert report["ref"] == {"requested": "main", "resolved_sha": "head-sha"}
    assert report["sample"] == {
        "requested_limit": 3,
        "returned": 3,
        "newest_commit": "c3",
        "oldest_commit": "c1",
    }
    assert "current selector" in report["interpretation"].lower()
    assert "failing-test recall" in report["interpretation"].lower()
    assert replay._selector_id(replay.DEFAULT_SELECTOR_PATH) == "scripts/select_pr_tests.py"


def test_replay_fails_loud_on_empty_sample(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def empty_history(*args: str) -> str:
        if args[0] == "rev-parse":
            return "head-sha\n"
        if args[0] == "rev-list":
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(replay, "_run_git", empty_history)

    exit_code = replay.main(["--ref", "main", "--limit", "3", "--json"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "no first-parent commits" in captured.err


def test_git_failure_is_reported_without_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failed_git(*args: str) -> str:
        raise subprocess.CalledProcessError(128, ["git", *args], stderr="unknown revision")

    monkeypatch.setattr(replay, "_run_git", failed_git)

    exit_code = replay.main(["--ref", "missing", "--limit", "3", "--json"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "unknown revision" in captured.err
    with pytest.raises(json.JSONDecodeError):
        json.loads(captured.out)
