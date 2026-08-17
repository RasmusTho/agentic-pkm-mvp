from __future__ import annotations

from pathlib import Path

from app.instance.instance_state import InstanceStateLayout
from app.instance.runtime import InstanceRegistryRuntime

REPO_ROOT = Path(__file__).resolve().parents[2]


def _python_sources(*roots: str) -> dict[str, str]:
    return {
        str(path.relative_to(REPO_ROOT)): path.read_text(encoding="utf-8")
        for root in roots
        for path in sorted((REPO_ROOT / root).rglob("*.py"))
    }


def test_all_producers_match_production_rebind_schema_and_activation_seal(tmp_path) -> None:
    """Inventory every current producer, including the deliberately empty activation set."""
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "state", "test"), tmp_path / "host"
    )
    record = runtime.open_settings_rebind_store().install_dormant()
    snapshot = runtime.registry.load()
    sources = _python_sources("app", "scripts")

    assert snapshot.settings_rebind == record.as_payload()
    assert snapshot.extensions["runtimeFloors"]["minimum_settings_rebind_runtime"] == "1"
    direct_writers = {
        path
        for path, source in sources.items()
        if ".set_settings_rebind_state(" in source
    }
    assert direct_writers == set()
    assert "settings rebind runtime floor must precede the record" in sources[
        "app/instance/vault_registry.py"
    ]
    assert "install_settings_rebind_dormant" in sources["app/instance/settings_rebind.py"]
    assert ".install_settings_rebind_dormant(" in sources["app/instance/settings_rebind.py"]
    assert "Atomically install SETTINGS-05's floor" in sources["app/instance/vault_registry.py"]
    deployment = (REPO_ROOT / "scripts/lib/instance_state_deployment.sh").read_text(
        encoding="utf-8"
    )
    deploy = (REPO_ROOT / "scripts/deploy_channel.sh").read_text(encoding="utf-8")
    assert "settings-rebind-install-dormant" in deployment
    assert deployment.index("settings-rebind-install-dormant") < deployment.rindex(
        "deployment-finish"
    )
    assert "${target_sha}:app/instance/settings_rebind.py" in deploy
    assert not any(
        "settingsRebind" in source
        for path, source in sources.items()
        if path.startswith("app/api/")
    )
    assert not any(
        "settingsRebind" in source
        for path, source in sources.items()
        if path.startswith("app/watcher/")
    )
