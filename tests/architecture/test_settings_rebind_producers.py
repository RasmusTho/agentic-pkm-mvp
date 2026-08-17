from __future__ import annotations

from pathlib import Path
import os
import subprocess

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


def test_floor_receipt_is_published_only_after_proof_and_dormant_install() -> None:
    deployment = (REPO_ROOT / "scripts/lib/instance_state_deployment.sh").read_text(
        encoding="utf-8"
    )
    proof = deployment.index("python -m app.instance.runtime deployment-prove")
    pending = deployment.index('_write_settings_rebind_floor_receipt "${channel}" pending')
    mvr_floor = deployment.index("mvr05-record-floor")
    install = deployment.index("python -m app.instance.runtime settings-rebind-install-dormant")
    installed = deployment.index('_write_settings_rebind_floor_receipt "${channel}" installed')
    finish = deployment.rindex("deployment-finish")

    assert proof < pending < mvr_floor < install < installed < finish


def test_floor_receipt_path_uses_resolved_default_and_explicit_host_root(tmp_path) -> None:
    library = REPO_ROOT / "scripts/lib/instance_ownership_host_state.sh"
    default_state = tmp_path / "xdg-state"
    explicit_state = tmp_path / "explicit-state"
    base_env = os.environ | {"HOME": str(tmp_path / "home")}

    default = subprocess.run(
        ["bash", "-c", f'source "{library}"; resolve_instance_ownership_host_state_dir; printf %s "$INSTANCE_OWNERSHIP_HOST_STATE_DIR"'],
        env=base_env | {"XDG_STATE_HOME": str(default_state)},
        check=True,
        capture_output=True,
        text=True,
    )
    explicit = subprocess.run(
        ["bash", "-c", f'source "{library}"; resolve_instance_ownership_host_state_dir; printf %s "$INSTANCE_OWNERSHIP_HOST_STATE_DIR"'],
        env=base_env | {"INSTANCE_OWNERSHIP_HOST_STATE_DIR": str(explicit_state)},
        check=True,
        capture_output=True,
        text=True,
    )

    assert default.stdout == str(default_state / "agentic-pkm" / "instance-ownership")
    assert explicit.stdout == str(explicit_state)


def test_rollback_reads_floor_receipt_only_after_host_root_preparation() -> None:
    deploy = (REPO_ROOT / "scripts/deploy_channel.sh").read_text(encoding="utf-8")
    prepared = deploy.index("prepare_instance_ownership_host_state_dir")
    marker = deploy.index('settings_rebind_floor_marker="${INSTANCE_OWNERSHIP_HOST_STATE_DIR}')
    admission = deploy.index('if [ "${action}" = "rollback" ] && [ -f "${settings_rebind_floor_marker}" ]')

    assert prepared < marker < admission


def test_pristine_pre_floor_rollback_remains_unfenced() -> None:
    deploy = (REPO_ROOT / "scripts/deploy_channel.sh").read_text(encoding="utf-8")
    admission = 'if [ "${action}" = "rollback" ] && [ -f "${settings_rebind_floor_marker}" ]'
    assert admission in deploy
    # A missing receipt is the durable proof that no SETTINGS floor transition
    # began; generic scalar rollback must therefore retain its pre-floor path.
    assert deploy.index(admission) < deploy.index(
        'if [ "${scalar_rollback}" = "1" ]', deploy.index(admission)
    )
