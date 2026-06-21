"""Full-host mount for in-process vault selection (#2310).

``api`` / ``worker`` / ``watcher`` must bind-mount the host ``/Users`` and
``/Volumes`` at IDENTICAL container paths so a selected host-absolute vault path
(internal SSD / iCloud Obsidian, or a ``/Volumes/T7`` external vault) resolves
transparently in-container. Mount the parents (never a specific volume) so boot
survives an absent T7. The legacy ``/app/vault`` mount is preserved (its removal
is #2311's migration).
"""
from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _REPO_ROOT / "docker-compose.yaml"
_SERVICES = ("api", "worker", "watcher")


def _service_volumes(service: str) -> list[str]:
    data = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    return [str(v) for v in data["services"][service].get("volumes", [])]


def test_compose_mounts_users_and_volumes_same_path() -> None:
    for service in _SERVICES:
        vols = _service_volumes(service)
        assert "/Users:/Users" in vols, service
        assert "/Volumes:/Volumes" in vols, service
        # Additive: the legacy /app/vault mount is preserved (#2311 owns removal).
        assert any(v.endswith(":/app/vault") for v in vols), service


def test_mount_targets_are_parents_not_specific_volume() -> None:
    for service in _SERVICES:
        vols = _service_volumes(service)
        # Mount the /Volumes parent, never a specific volume (e.g. /Volumes/T7),
        # so boot does not depend on the external disk being present.
        assert not any(v.startswith("/Volumes/") for v in vols), (
            f"{service} mounts a specific volume; mount the /Volumes parent instead"
        )
