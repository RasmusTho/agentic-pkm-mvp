"""Static contract for the full-host vault deployment overlay."""

from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
OVERLAY = REPO_ROOT / "docker-compose.full-host-vault.yml"
VAULT_ROOT_EXPR = "${DEPLOY_VAULT_CONTAINER_ROOT:?DEPLOY_VAULT_CONTAINER_ROOT must be set for a full-host vault binding}"


def _load_overlay() -> dict:
    return yaml.safe_load(OVERLAY.read_text(encoding="utf-8")) or {}


def test_full_host_overlay_binds_capture_watch_to_selected_vault() -> None:
    """Capture-watch must share the governed full-host vault binding.

    Verify: direct repair contract — the prod capture-watch service must not
    fall back to the container-local /app/vault root during a full-host deploy.
    """
    capture_watch = (_load_overlay().get("services") or {}).get("heimdal-capture-watch") or {}

    assert capture_watch["volumes"] == [
        {
            "type": "bind",
            "source": VAULT_ROOT_EXPR,
            "target": VAULT_ROOT_EXPR,
            "read_only": False,
        }
    ]
    assert capture_watch["environment"] == {
        "VAULT_ROOT": VAULT_ROOT_EXPR,
        "VAULT_ROOT_DEV": VAULT_ROOT_EXPR,
        "VAULT_ROOT_TEST": VAULT_ROOT_EXPR,
        "WATCHER_VAULT_PATH": VAULT_ROOT_EXPR,
    }
