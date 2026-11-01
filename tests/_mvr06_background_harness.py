"""Shared MVR-06A harness: run the real background-authority cutover on an MVR-05 instance.

Like the MVR-02/MVR-03 harnesses it drives *production* producers rather than seeding
state: the MVR-03 principal cutover, the MVR-05 floor from the real compose fence plan, the
SETTINGS-05 dormant bridge, and then the shipped `background-authority-cutover` CLI inside
a proved stopped deployment window. A fixture that wrote the role or intent directly would
prove the ordering rule against a fiction.
"""

from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from app.instance.mvr05_cutover import (
    discover_db_producer_fence,
    record_mvr05_runtime_floor,
)
from app.instance.runtime import _finish_instance_state_deployment
from app.instance.runtime import main as instance_runtime_main
from app.instance.settings_rebind import _install_dormant_settings_rebind
from tests._mvr03_principal_harness import provisioned_instance
from tests._mvr_default_vault_harness import REPO_ROOT, deployment_authority
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


def cli(*args: str) -> dict:
    buffer = StringIO()
    with redirect_stdout(buffer):
        code = instance_runtime_main(list(args))
    payload = json.loads(buffer.getvalue().strip().splitlines()[-1])
    payload["_exit_code"] = code
    return payload


def record_mvr05_floor(runtime) -> None:
    """The MVR-05 channel fence the MVR-06 floor must advance from."""

    record_mvr05_runtime_floor(
        runtime.registry,
        fence=discover_db_producer_fence(REPO_ROOT / "docker-compose.yaml"),
        channel_id=runtime.layout.channel_id,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )


def mvr05_instance(tmp_path: Path, *, extra_roots: tuple[str, ...] = ()):
    """An MVR-03 principal + MVR-05 floor + installed legacy picker bridge (#3163)."""

    runtime, first, extra, principal = provisioned_instance(tmp_path, extra_roots=extra_roots)
    record_mvr05_floor(runtime)
    _install_dormant_settings_rebind(
        runtime.registry,
        binding_id=first.vault_binding_id,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    return runtime, first, extra, principal


def run_background_cutover_through_cli(
    runtime, *, bootstrap_kind: str = "existing-install"
) -> dict:
    """The shipped cutover command inside a proved stopped window, then finish it."""

    legacy_path = runtime.layout.root / "missing-legacy.md"
    proof, inventory_path = deployment_authority(runtime, legacy_path)
    try:
        receipt = cli(
            "background-authority-cutover",
            "--channel",
            runtime.layout.channel_id,
            "--registry-path",
            str(runtime.layout.registry_path),
            "--host-global-root",
            str(runtime.ledger.root),
            "--quiescence-proof-path",
            str(runtime.ledger.root / "deployment-quiescence-proof.json"),
            "--bootstrap-kind",
            bootstrap_kind,
            "--consumer",
            "bootstrap-init",
        )
    finally:
        _finish_instance_state_deployment(
            channel=runtime.layout.channel_id,
            instance_state_root=runtime.layout.root.parent,
            host_global_root=runtime.ledger.root,
            legacy_path=legacy_path,
            inventory_path=inventory_path,
            backup_root=runtime.layout.root / "background-cutover-backup",
            restore_root=None,
            quiescence_proof=proof,
        )
    return receipt


def mvr06_instance(
    tmp_path: Path,
    *,
    extra_roots: tuple[str, ...] = (),
    bootstrap_kind: str = "existing-install",
):
    """An instance carried through the complete MVR-06A cutover by production producers."""

    runtime, first, extra, principal = mvr05_instance(tmp_path, extra_roots=extra_roots)
    receipt = run_background_cutover_through_cli(runtime, bootstrap_kind=bootstrap_kind)
    assert receipt["_exit_code"] == 0, receipt
    return runtime, first, extra, principal, receipt


__all__ = [
    "cli",
    "mvr05_instance",
    "mvr06_instance",
    "record_mvr05_floor",
    "run_background_cutover_through_cli",
]
