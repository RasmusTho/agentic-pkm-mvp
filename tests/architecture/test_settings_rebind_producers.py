from __future__ import annotations

from pathlib import Path
import json

import app.instance.runtime as runtime_module
from app.instance.instance_state import InstanceStateLayout
from app.instance.runtime import InstanceRegistryRuntime


REPO_ROOT = Path(__file__).resolve().parents[2]


def _sources(root: str) -> dict[str, str]:
    return {
        str(path.relative_to(REPO_ROOT)): path.read_text(encoding="utf-8")
        for path in sorted((REPO_ROOT / root).rglob("*.py"))
    }


def test_all_producers_match_production_rebind_schema_and_activation_seal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ownership_root = tmp_path / "ownership"
    ownership_root.mkdir(mode=0o700)
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "state", "test"),
        ownership_root,
    )
    runtime.registry.load()
    proof_path = ownership_root / "deployment-quiescence-proof.json"
    proof_path.write_text(json.dumps({"nonce": "proved-test-window"}), encoding="utf-8")
    monkeypatch.setattr(
        runtime_module,
        "_require_proved_deployment_lease",
        lambda **_kwargs: None,
    )
    assert (
        runtime_module.main(
            [
                "settings-rebind-install-dormant",
                "--channel",
                "test",
                "--registry-path",
                str(runtime.layout.registry_path),
                "--host-global-root",
                str(ownership_root),
                "--quiescence-proof-path",
                str(proof_path),
            ]
        )
        == 0
    )
    record = runtime.open_settings_rebind_store().read()
    snapshot = runtime.registry.load()
    app_sources = _sources("app")
    script_sources = _sources("scripts")

    assert snapshot.settings_rebind == record.as_payload()
    assert record.schema_revision == 1
    assert snapshot.extensions["runtimeFloors"]["minimum_settings_rebind_runtime"] == "1"
    assert "install_settings_rebind_dormant" in app_sources[
        "app/instance/settings_rebind.py"
    ]
    assert "install_dormant" in app_sources["app/instance/runtime.py"]
    assert "settings rebind runtime floor must precede the record" in app_sources[
        "app/instance/vault_registry.py"
    ]
    capability = json.loads(
        (
            REPO_ROOT
            / "app/instance/settings_rebind_runtime_capability.json"
        ).read_text(encoding="utf-8")
    )
    assert capability == {
        "schema": "agentic-pkm.runtime-capability-attestation.v1",
        "capability": "settings-rebind-runtime-floor",
        "revision": 1,
        "preserves": [
            "settings_rebind.v1",
            "minimum_settings_rebind_runtime=1",
        ],
        "rollbackPosture": "reject-incompatible-writer",
    }
    assert not any(
        "set_settings_rebind_state" in source or "install_dormant" in source
        for path, source in app_sources.items()
        if path.startswith(("app/api/", "app/watcher/"))
    )
    assert not any(
        "settings-rebind-initiate" in source for source in app_sources.values()
    )
    assert not any(
        "settings-rebind-initiate" in source for source in script_sources.values()
    )

    deployment = (REPO_ROOT / "scripts/lib/instance_state_deployment.sh").read_text(
        encoding="utf-8"
    )
    pending = deployment.index(
        '_write_settings_rebind_floor_receipt "${channel}" pending'
    )
    producer = deployment.index(
        "python -m app.instance.runtime settings-rebind-install-dormant"
    )
    installed = deployment.index(
        '_write_settings_rebind_floor_receipt "${channel}" installed'
    )
    finish = deployment.index("python -m app.instance.runtime deployment-finish")
    assert pending < producer < installed < finish


def test_provisional_migration_is_replaced_only_by_the_fenced_producer(
    tmp_path: Path,
) -> None:
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "state", "test"),
        tmp_path / "ownership",
    )
    snapshot = runtime.registry.load()
    frontmatter = runtime.registry._frontmatter_from_snapshot(snapshot)
    frontmatter["settingsRebind"] = {
        "schema": "settings_rebind.v1",
        "prior": {"vaultBindingId": "provisional-a"},
    }

    provisional = runtime.registry._snapshot_from_frontmatter(frontmatter)
    assert provisional.settings_rebind == frontmatter["settingsRebind"]
    assert "minimum_settings_rebind_runtime" not in provisional.extensions.get(
        "runtimeFloors", {}
    )
