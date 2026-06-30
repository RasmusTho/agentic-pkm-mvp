from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_live_smoke_asserts_render_and_channel_marker() -> None:
    smoke_script = (REPO_ROOT / "scripts/companion_ui_postdeploy_smoke.sh").read_text(
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
    assert "workspace-vault-channel" in live_test
    assert "connection refused" in live_test.lower() or "response is not None" in live_test
    assert "runtime channel marker" in live_test
