from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.builderops.control_plane.auth import CredentialRegistry
from app.builderops.control_plane.health import (
    HealthService,
    LiveOperationalStatusProvider,
    OperationalStatus,
)
from app.builderops.control_plane.health_probe import probe_worker
from app.builderops.control_plane.migrations import SCHEMA_VERSION
from app.builderops.control_plane.service import create_app


class _Store:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    def readiness(self) -> dict[str, int]:
        if not self.available:
            raise RuntimeError("postgresql://user:raw-database-secret@db/builderops")
        return {"schema_version": SCHEMA_VERSION, "authority_epoch": 1}


class _Operational:
    def snapshot(self) -> OperationalStatus:
        return OperationalStatus(
            outbox_pending=3,
            outbox_oldest_age_seconds=12.5,
            dead_letters=1,
            active_leases=2,
            lease_conflicts_total=4,
            rate_limit_enabled=True,
            rate_limit_rejections_total=5,
            executor_heartbeat_state="healthy",
            durability_posture="rebuildable",
        )


def _registry(tmp_path: Path) -> CredentialRegistry:
    secret = tmp_path / "status.secret"
    secret.write_text("raw-client-secret", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "credentials": [
                    {
                        "id": "operator",
                        "principal": "operator:health",
                        "secret_ref": "host-secret:operator",
                        "secret_file": str(secret),
                        "scopes": ["health:read", "status:read"],
                        "rotation_generation": 7,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return CredentialRegistry(manifest)


def test_readiness_and_status_cover_required_dependencies_without_secrets(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    store = _Store()
    health = HealthService(store, registry, _Operational())  # type: ignore[arg-type]
    client = TestClient(create_app(store=store, credentials=registry, health=health))  # type: ignore[arg-type]
    headers = {"Authorization": "Bearer raw-client-secret"}

    assert client.get("/healthz", headers=headers).json() == {"ok": True}
    ready = client.get("/readyz", headers=headers)
    assert ready.status_code == 200
    payload = client.get("/status", headers=headers).json()
    assert payload["database"] == {
        "available": True,
        "schema_version": SCHEMA_VERSION,
        "authority_epoch": 1,
    }
    assert payload["outbox"] == {
        "pending": 3,
        "oldest_age_seconds": 12.5,
        "dead_letters": 1,
        "authority_threatening": False,
    }
    assert payload["leases"] == {"active": 2, "conflicts_total": 4}
    assert payload["rate_limit"] == {"enabled": True, "rejections_total": 5}
    assert payload["executor_heartbeat"] == {"state": "healthy"}
    assert payload["durability"] == {
        "posture": "rebuildable",
        "database_rebuild_required": False,
        "backup_restore_deferred": True,
    }
    serialized = json.dumps(payload)
    assert "raw-client-secret" not in serialized
    assert "raw-database-secret" not in serialized

    unavailable_store = _Store(available=False)
    unavailable_health = HealthService(unavailable_store, registry, _Operational())  # type: ignore[arg-type]
    unavailable = TestClient(
        create_app(store=unavailable_store, credentials=registry, health=unavailable_health)  # type: ignore[arg-type]
    )
    assert unavailable.get("/healthz", headers=headers).status_code == 200
    assert unavailable.get("/readyz", headers=headers).status_code == 503
    assert "raw-database-secret" not in unavailable.get("/status", headers=headers).text


def test_restored_positive_authority_epoch_is_ready(tmp_path: Path) -> None:
    class RestoredStore(_Store):
        def readiness(self) -> dict[str, int]:
            return {"schema_version": SCHEMA_VERSION, "authority_epoch": 42}

    registry = _registry(tmp_path)
    health = HealthService(RestoredStore(), registry, _Operational())  # type: ignore[arg-type]
    client = TestClient(
        create_app(store=RestoredStore(), credentials=registry, health=health)  # type: ignore[arg-type]
    )
    response = client.get("/readyz", headers={"Authorization": "Bearer raw-client-secret"})
    assert response.status_code == 200
    assert response.json()["database"]["authority_epoch"] == 42


def test_database_outage_cannot_escape_live_status_boundary(tmp_path: Path) -> None:
    class OfflineStore(_Store):
        def readiness(self) -> dict[str, int]:
            raise RuntimeError("database offline: raw-password")

        def service_heartbeat(self, service_name: str) -> dict[str, object] | None:
            raise RuntimeError(f"database offline for {service_name}: raw-password")

    registry = _registry(tmp_path)
    store = OfflineStore()
    operational = LiveOperationalStatusProvider(
        store,  # type: ignore[arg-type]
        worker_heartbeat_file=tmp_path / "missing-worker.json",
    )
    client = TestClient(
        create_app(
            store=store,  # type: ignore[arg-type]
            credentials=registry,
            health=HealthService(store, registry, operational),  # type: ignore[arg-type]
        )
    )
    headers = {"Authorization": "Bearer raw-client-secret"}

    assert client.get("/readyz", headers=headers).status_code == 503
    response = client.get("/status", headers=headers)

    assert response.status_code == 200
    assert response.json()["database"] == {
        "available": False,
        "schema_version": None,
        "authority_epoch": None,
    }
    assert response.json()["executor_heartbeat"] == {"state": "unknown"}
    assert "raw-password" not in response.text


def test_live_provider_reports_rebuildable_posture_and_shared_worker_heartbeat(
    tmp_path: Path,
) -> None:
    heartbeat = tmp_path / "worker.json"
    heartbeat.write_text(
        json.dumps(
            {
                "state": "running",
                "observed_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    provider = LiveOperationalStatusProvider(
        _Store(),  # type: ignore[arg-type]
        worker_heartbeat_file=heartbeat,
    )
    snapshot = provider.snapshot()
    assert snapshot.executor_heartbeat_state == "healthy"
    assert snapshot.durability_posture == "rebuildable"


def test_worker_probe_requires_fresh_database_heartbeat(monkeypatch) -> None:
    class HeartbeatStore:
        heartbeat: dict[str, object] | None = {
            "service_name": "outbox-worker",
            "state": "running",
            "observed_at": datetime.now(timezone.utc),
            "credential": "must-not-be-used",
        }

        def service_heartbeat(self, service_name: str) -> dict[str, object] | None:
            assert service_name == "outbox-worker"
            return self.heartbeat

    store = HeartbeatStore()
    monkeypatch.setattr(
        "app.builderops.control_plane.health_probe.production_store",
        lambda _env: store,
    )
    assert probe_worker() is True
    store.heartbeat = None
    assert probe_worker() is False
