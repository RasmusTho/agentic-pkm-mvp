"""Real transfer engine, replacing only the host process-control boundary."""

from app.instance.ownership_ledger import OwnershipLedger
from app.instance.runtime import InstanceRegistryRuntime, _load_deployment_quiescence_proof
from app.instance.local_operator_principal import AuthPosture
from tests._mvr03_principal_harness import run_principal_cutover
from tests._mvr05b_bootstrap_harness import fresh_no_vault_instance
from tests._mvr_default_vault_harness import activate, deployment_authority, new_runtime
from tests.helpers.vault_settings import initialize_test_vault


def transfer_pair(tmp_path, monkeypatch):
    destination_root = tmp_path / "destination"
    destination_root.mkdir()
    destination, _ = fresh_no_vault_instance(destination_root)
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = new_runtime(source_root)
    source.ledger = OwnershipLedger(destination.ledger.root)
    root = source_root / "vault"
    root.mkdir()
    initialize_test_vault(root)
    registration = source.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    activate(source, registration, source_root)
    run_principal_cutover(
        source,
        posture=AuthPosture(
            configured_credentials=0,
            credential=None,
            loopback_listener_proven=True,
            companion_proxy_configured=False,
        ),
    )
    # Independent destination channel with the same physical ownership ledger.
    destination.layout = type(destination.layout)(
        destination.layout.root, "test", destination.layout.registry_path
    )
    destination_vault = destination_root / "vault"
    destination_vault.mkdir()
    initialize_test_vault(destination_vault)
    destination_first = destination.bootstrap_env_binding(
        vault_root=destination_vault, watcher_vault_path=destination_vault
    )
    activate(destination, destination_first, destination_root, other_runtimes=(source,))
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(source.registry.path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(source.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", source.layout.channel_id)
    monkeypatch.delenv("WATCHER_ENABLE", raising=False)
    proof_path = source.ledger.root / "deployment-quiescence-proof.json"

    def stop_and_prove():
        if proof_path.exists():
            return _load_deployment_quiescence_proof(proof_path)
        proof, _ = deployment_authority(
            source, source_root / "missing-legacy.md", other_runtimes=(destination,)
        )
        return proof

    return source, destination, registration, stop_and_prove


def reopen(runtime):
    return InstanceRegistryRuntime.for_paths(
        runtime.layout, runtime.ledger.root, initialize_layout=False
    )
