from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("marker_position", "collection_status", "expected_status"),
    [("first", 5, 0), ("last", 5, 0), (None, 5, 86), ("first", 1, 86), (None, 0, 0)],
)
def test_collection_preflight_classifies_captured_output_without_pipe_race(
    tmp_path: Path, marker_position: str | None, collection_status: int, expected_status: int
) -> None:
    marker = "SKIPPED [1] live smoke: Set COMPANION_UI_SMOKE_URL\n"
    # Exceed pipe capacity so an early-exiting grep cannot race nondeterministically.
    output = "collection diagnostic\n" * 65536
    if marker_position == "first":
        output = marker + output
    elif marker_position == "last":
        output += marker
    output_path = tmp_path / "collection.txt"
    output_path.write_text(output, encoding="utf-8")
    calls_path = tmp_path / "calls.jsonl"
    fake_python = tmp_path / "python"
    fake_python.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "with Path(os.environ['SMOKE_TEST_CALLS']).open('a') as calls:\n"
        "    calls.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1:2] == ['-c']:\n"
        "    raise SystemExit(0)\n"
        "sys.stdout.write(Path(os.environ['SMOKE_TEST_OUTPUT']).read_text())\n"
        "raise SystemExit(int(os.environ['SMOKE_TEST_STATUS']))\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/companion_ui_postdeploy_smoke.sh"), "preflight"],
        env={
            **os.environ,
            "PYTHON": str(fake_python),
            "SMOKE_TEST_CALLS": str(calls_path),
            "SMOKE_TEST_OUTPUT": str(output_path),
            "SMOKE_TEST_STATUS": str(collection_status),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
    assert len(calls) == 2
    assert calls[0][0] == "-c" and "sync_playwright" in calls[0][1]
    assert calls[1] == [
        "-m", "pytest", str(REPO_ROOT / "tests/companion_ui/test_companion_ui_live_smoke.py"),
        "--collect-only", "-q", "-ra",
    ]
    assert result.returncode == expected_status, result.stderr[-500:]
    if expected_status:
        assert "companion UI pytest smoke preflight:" in result.stderr


def test_live_smoke_asserts_runtime_channel_without_vault_marker() -> None:
    smoke_script = (REPO_ROOT / "scripts/companion_ui_postdeploy_smoke.sh").read_text(
        encoding="utf-8"
    )
    deploy_script = (REPO_ROOT / "scripts/deploy_channel.sh").read_text(
        encoding="utf-8"
    )
    live_test = (
        REPO_ROOT / "tests/companion_ui/test_companion_ui_live_smoke.py"
    ).read_text(encoding="utf-8")

    for channel, port in {"dev": "8111", "test": "8112", "prod": "8113"}.items():
        assert f"run_channel {channel}" in smoke_script
        assert f"127.0.0.1:{port}" in smoke_script

    assert "COMPANION_UI_SMOKE_URL" in smoke_script
    assert "COMPANION_UI_EXPECTED_CHANNEL" in smoke_script
    assert "assert_operator_channel(" in live_test
    assert "assert_operator_channel(\n                    payload," in live_test
    assert 'meta[name="pkm-runtime-channel"]' in live_test
    assert 'meta[name="pkm-runtime-git-sha"]' in live_test
    assert "COMPANION_UI_EXPECTED_SHA" in smoke_script
    assert 'COMPANION_UI_EXPECTED_SHA="${target_sha}"' in deploy_script
    assert "workspace-vault-channel" not in live_test
    assert "connection refused" in live_test.lower() or "response is not None" in live_test
