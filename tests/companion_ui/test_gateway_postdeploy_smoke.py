from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


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
