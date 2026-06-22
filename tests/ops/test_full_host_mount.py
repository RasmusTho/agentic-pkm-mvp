"""Full-host mount for in-process vault selection (#2310) + legacy mount removal (#2386).

``api`` / ``worker`` / ``watcher`` must bind-mount the host ``/Users`` and
``/Volumes`` at IDENTICAL container paths so a selected host-absolute vault path
(internal SSD / iCloud Obsidian, or a ``/Volumes/T7`` external vault) resolves
transparently in-container. Mount the parents (never a specific volume) so boot
survives an absent T7.

The legacy ``./vault:/app/vault`` *fallback* is removed (#2386 / Slice 05D of
#2311). The base compose no longer synthesizes ``./vault`` for a no-vault
startup; the ``/app/vault`` compatibility mount lives in a separate
``docker-compose.legacy-vault.yml`` overlay that requires an explicitly bound
vault (``VAULT_HOST_ROOT``) and is only included for explicit-vault startups.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _REPO_ROOT / "docker-compose.yaml"
_LEGACY_COMPOSE = _REPO_ROOT / "docker-compose.legacy-vault.yml"
_ENVIRONMENTS_DOC = _REPO_ROOT / "docs" / "ENVIRONMENTS.md"
_START_SCRIPT = _REPO_ROOT / "scripts" / "start_full_system.sh"
_SERVICES = ("api", "worker", "watcher")


def _service_volumes(compose: Path, service: str) -> list[str]:
    data = yaml.safe_load(compose.read_text(encoding="utf-8"))
    return [str(v) for v in data["services"][service].get("volumes", [])]


def _all_mount_sources(compose: Path) -> list[str]:
    """Bind-mount source strings (left of the first ``:``) across all services.

    Operates on parsed volume entries so explanatory comments mentioning
    ``./vault`` do not count as a real fallback source.
    """
    data = yaml.safe_load(compose.read_text(encoding="utf-8"))
    sources: list[str] = []
    for service in data.get("services", {}).values():
        for vol in service.get("volumes", []) or []:
            sources.append(str(vol).split(":", 1)[0])
    return sources


def test_compose_mounts_users_and_volumes_same_path() -> None:
    # #2310 same-path full-host mount contract — must remain unchanged.
    for service in _SERVICES:
        vols = _service_volumes(_COMPOSE, service)
        assert "/Users:/Users" in vols, service
        assert "/Volumes:/Volumes" in vols, service


def test_mount_targets_are_parents_not_specific_volume() -> None:
    for service in _SERVICES:
        vols = _service_volumes(_COMPOSE, service)
        # Mount the /Volumes parent, never a specific volume (e.g. /Volumes/T7),
        # so boot does not depend on the external disk being present.
        assert not any(v.startswith("/Volumes/") for v in vols), (
            f"{service} mounts a specific volume; mount the /Volumes parent instead"
        )


def test_no_vault_startup_does_not_preserve_legacy_app_vault_mount() -> None:
    """No-vault compose startup must not bind repo-local ``./vault`` to ``/app/vault``.

    The base compose must carry no ``/app/vault`` mount and no ``./vault``
    fallback source, so a startup with ``VAULT_HOST_ROOT`` / ``VAULT_ROOT``
    unset (the no-vault idle posture, #2005) cannot synthesize ``./vault``.
    """
    # No base mount targets /app/vault, and no ./vault fallback source remains
    # (checked on parsed mount entries, so comments may still mention ./vault).
    for service in _SERVICES:
        vols = _service_volumes(_COMPOSE, service)
        assert not any(v.endswith(":/app/vault") for v in vols), service
    sources = _all_mount_sources(_COMPOSE)
    assert not any("./vault" in s for s in sources), (
        f"base compose must not bind the ./vault fallback source; got {sources}"
    )


def test_legacy_compose_overlay_requires_explicit_vault() -> None:
    """The retained ``/app/vault`` compatibility mount lives in an explicit overlay.

    The overlay must source the bind from an explicitly bound vault
    (``VAULT_HOST_ROOT``) with no ``./vault`` no-vault fallback, so it cannot be
    selected by an unset vault.
    """
    assert _LEGACY_COMPOSE.exists(), "docker-compose.legacy-vault.yml overlay must exist"
    # Checked on parsed mount entries so explanatory comments may mention ./vault.
    sources = _all_mount_sources(_LEGACY_COMPOSE)
    assert not any("./vault" in s for s in sources), (
        f"legacy overlay must not carry a ./vault fallback source; got {sources}"
    )
    for service in _SERVICES:
        vols = _service_volumes(_LEGACY_COMPOSE, service)
        legacy = [v for v in vols if v.endswith(":/app/vault")]
        assert legacy, f"{service} legacy overlay must define the /app/vault mount"
        for line in legacy:
            # Required-variable form: errors if VAULT_HOST_ROOT is unset, never
            # falls back to ./vault.
            assert "${VAULT_HOST_ROOT:?" in line, line


def test_start_script_includes_legacy_overlay_only_for_explicit_vault() -> None:
    """start_full_system.sh adds the legacy overlay only when a vault is bound.

    The overlay must be appended to COMPOSE_FILE on the explicit-vault branch
    (NO_VAULT_MODE != 1) and must not be appended on the no-vault idle branch.
    """
    text = _START_SCRIPT.read_text(encoding="utf-8")
    assert "docker-compose.legacy-vault.yml" in text, (
        "start_full_system.sh must reference the legacy overlay for explicit vaults"
    )


def test_environment_docs_match_legacy_mount_contract() -> None:
    """ENVIRONMENTS.md no longer says the legacy mount remains until #2311.

    It must document the removed fallback / explicit compatibility contract
    instead of the old "remains until ... migrated (#2311)" wording.
    """
    text = _ENVIRONMENTS_DOC.read_text(encoding="utf-8")
    assert "remains until the eager `resolve_vault_root()` consumers are migrated (#2311)" not in text, (
        "ENVIRONMENTS.md still claims the legacy mount remains until #2311"
    )
    # The doc must describe the new contract: an explicit-only compatibility
    # mount, no no-vault ./vault fallback.
    assert "/app/vault" in text
    assert "explicit" in text.lower()
