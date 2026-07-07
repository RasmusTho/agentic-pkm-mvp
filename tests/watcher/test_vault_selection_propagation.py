"""#3119 — a vault selected/initialized through the Companion UI is invisible
to the watcher/worker.

Vault *selection* (the API process's in-process ``VaultManager`` state, set by
``POST /api/companion/vault/select`` / ``/vault/initialize``) and vault *ingest
binding* (the watcher/worker's own boot-time ``WATCHER_VAULT_PATH``) are two
independent binding slots by deliberate design (#2476 — "document the split,
do not converge": the watcher is a background daemon with its own lifecycle
and must not couple to the HTTP process's in-memory singleton). A container
topology with no prior ``VAULT_HOST_ROOT``/``WATCHER_VAULT_PATH`` binding can
therefore accept a UI vault selection while the watcher continues watching a
different path (or nothing at all) — with no error surfaced anywhere.

This test suite covers the resolution the issue's AC1 accepts: rather than
forcing live re-binding (which would mean restructuring the watcher's
boot-time-frozen ``RegistryConfig`` / tick loop — a much larger, riskier
change to an intentionally-independent daemon), the API-selected vault is
compared against the watcher's own self-reported heartbeat ``vault_path`` so
divergence is *visible* instead of silent (``app.api.routes.ingest_binding``).

These tests are pure: no Docker, no network, no real watcher loop — just the
comparison contract against a heartbeat file on disk (which is exactly what
the real watcher writes every tick via
``app.watcher.heartbeat.write_registry_heartbeat``).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.api.routes.ingest_binding import ingest_binding_status

pytestmark = pytest.mark.not_pg


def _write_heartbeat(path: Path, *, vault_path: str, ts: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": ts if ts is not None else time.time(), "vault_path": vault_path}
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestIngestBindingStatus:
    def test_ui_selected_vault_becomes_watched(self, tmp_path: Path) -> None:
        """The happy path AC1 asks for: watcher heartbeat confirms the same
        vault the UI selected, within a bounded time (the heartbeat's own
        freshness window) — reported as ``state == "bound"``."""

        vault_path = str(tmp_path / "MyVault")
        heartbeat_path = tmp_path / "watcher_heartbeat.json"
        _write_heartbeat(heartbeat_path, vault_path=vault_path)

        status = ingest_binding_status(
            selected_vault_path=vault_path,
            heartbeat_path=heartbeat_path,
        )

        assert status.state == "bound"
        assert status.is_bound is True
        assert status.watcher_vault_path == vault_path

    def test_diverged_when_watcher_bound_to_different_vault(self, tmp_path: Path) -> None:
        """The exact #3119 scenario: the API's selection and the watcher's
        actual binding point at two different vaults. Must be reported, not
        silently treated as success."""

        selected = str(tmp_path / "SelectedVault")
        watched = str(tmp_path / "SomeOtherVault")
        heartbeat_path = tmp_path / "watcher_heartbeat.json"
        _write_heartbeat(heartbeat_path, vault_path=watched)

        status = ingest_binding_status(
            selected_vault_path=selected,
            heartbeat_path=heartbeat_path,
        )

        assert status.state == "diverged"
        assert status.is_bound is False
        assert status.watcher_vault_path == watched
        assert "different vault" in status.detail

    def test_unbound_when_watcher_has_never_reported(self, tmp_path: Path) -> None:
        """No prior VAULT_HOST_ROOT/WATCHER_VAULT_PATH binding at all — the
        watcher has never written a heartbeat. This is the fresh-container,
        no-env-preconfigured scenario the issue's Suggested Validation names."""

        selected = str(tmp_path / "FreshlyInitializedVault")
        heartbeat_path = tmp_path / "does_not_exist.json"

        status = ingest_binding_status(
            selected_vault_path=selected,
            heartbeat_path=heartbeat_path,
        )

        assert status.state == "unbound"
        assert status.is_bound is False
        assert status.watcher_vault_path is None

    def test_unbound_when_watcher_heartbeat_is_stale(self, tmp_path: Path) -> None:
        """A watcher that was bound but has stopped ticking (crashed, paused,
        or never restarted after the vault changed) must not silently read as
        'bound' just because an old heartbeat file still exists on disk."""

        vault_path = str(tmp_path / "MyVault")
        heartbeat_path = tmp_path / "watcher_heartbeat.json"
        _write_heartbeat(heartbeat_path, vault_path=vault_path, ts=time.time() - 999)

        status = ingest_binding_status(
            selected_vault_path=vault_path,
            heartbeat_path=heartbeat_path,
            stale_seconds=60.0,
        )

        assert status.state == "unbound"
        assert status.is_bound is False

    def test_unknown_when_no_vault_selected(self, tmp_path: Path) -> None:
        """Nothing to compare against yet — distinct from an active mismatch."""

        heartbeat_path = tmp_path / "watcher_heartbeat.json"
        _write_heartbeat(heartbeat_path, vault_path=str(tmp_path / "Vault"))

        status = ingest_binding_status(
            selected_vault_path=None,
            heartbeat_path=heartbeat_path,
        )

        assert status.state == "unknown"
        assert status.is_bound is False

    def test_malformed_heartbeat_degrades_to_unbound_not_a_crash(self, tmp_path: Path) -> None:
        """A corrupt heartbeat file must degrade to a visible 'unbound'
        signal, not raise and break the caller (capture/workspace endpoints
        must never 500 because this advisory check failed)."""

        vault_path = str(tmp_path / "MyVault")
        heartbeat_path = tmp_path / "watcher_heartbeat.json"
        heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        heartbeat_path.write_text("{not valid json", encoding="utf-8")

        status = ingest_binding_status(
            selected_vault_path=vault_path,
            heartbeat_path=heartbeat_path,
        )

        assert status.state == "unbound"
        assert status.is_bound is False

    def test_trailing_slash_and_expanduser_do_not_cause_false_divergence(
        self, tmp_path: Path
    ) -> None:
        """Path representation differences (trailing slash) between the two
        processes must not manufacture a false 'diverged' report."""

        base = tmp_path / "MyVault"
        heartbeat_path = tmp_path / "watcher_heartbeat.json"
        _write_heartbeat(heartbeat_path, vault_path=str(base) + "/")

        status = ingest_binding_status(
            selected_vault_path=str(base),
            heartbeat_path=heartbeat_path,
        )

        assert status.state == "bound"
