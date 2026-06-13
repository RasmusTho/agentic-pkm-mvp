"""CRE runtime wiring (#1958): a moment is computed on a tick and surfaced.

Proves the dormancy gap is closed end-to-end: the governed relevance tick (the
watcher/scheduler hook) computes a moment from vault-native data and materializes
it through the WriteGuard with a receipt, and the glance-surface API route
(`GET /api/companion/now`) surfaces it pull-only. No proactivity, no external
source, no notification.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.vault.manager as vault_manager
from app.api.app import app
from app.relevance import collect_now_moments
from app.vault.manager import VaultContext
from app.vault.paths import get_vault_system_dir_rel
from app.watcher.relevance_tick import run_relevance_tick

TODAY = date(2026, 6, 13)


@pytest.fixture(autouse=True)
def _reset_vault_manager():
    """Isolate the vault-manager singleton so the route resolves our temp vault."""

    vault_manager._GLOBAL_MANAGER = None
    yield
    vault_manager._GLOBAL_MANAGER = None


def _build_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    daily = vault / "Daily" / f"{TODAY.isoformat()}.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text("---\nuuid: daily-uuid\n---\n\n# Today\n", encoding="utf-8")
    note = vault / "Projects" / "Contextual Relevance Engine.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\nuuid: cre-uuid\ndue: 2026-06-15\n---\n\n# CRE\n\n- [ ] finish the scarcity gate\n",
        encoding="utf-8",
    )
    return vault


def _ctx(vault: Path) -> VaultContext:
    return VaultContext(status="selected", active_vault_id="v1", active_vault_path=str(vault))


def test_moment_materialized_and_surfaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _build_vault(tmp_path)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    receipts = tmp_path / "moment_receipts.jsonl"
    reachout_receipts = tmp_path / "reachout_receipts.jsonl"

    # The runtime tick (watcher/scheduler hook) computes + materializes moments.
    summary = run_relevance_tick(
        vault,
        vault_context=_ctx(vault),
        outbox_path=receipts,
        reachout_outbox_path=reachout_receipts,
    )
    assert summary["materialized"] >= 1

    # A durable Markdown artifact landed in the vault system plane, with a receipt.
    moments_dir = vault / get_vault_system_dir_rel(vault) / "moments"
    assert moments_dir.is_dir()
    assert list(moments_dir.glob("*.md")), "the tick must write a moment artifact"
    assert receipts.exists() and receipts.read_text(encoding="utf-8").strip()

    # The glance-surface route surfaces the materialized moment, pull-only.
    client = TestClient(app)
    resp = client.get("/api/companion/now")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list) and data, "the now route must surface the materialized moment"
    first = data[0]
    assert first["moment_id"] and first["title"]
    assert first["urgency_band"] in ("routine", "timely", "pressing", "critical")

    # collect_now_moments reads the same artifact back (the route's projection source).
    views = collect_now_moments(_ctx(vault))
    assert views and views[0]["moment_id"] == first["moment_id"]
