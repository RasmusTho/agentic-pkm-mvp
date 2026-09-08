"""Production-shaped fresh no-vault fixture for MVR-05B bootstrap tests."""

from __future__ import annotations

from pathlib import Path

from app.instance.local_operator_principal import AuthPosture
from app.instance.runtime import InstanceRegistryRuntime
from tests._mvr03_principal_harness import run_principal_cutover
from tests._mvr_default_vault_harness import new_runtime


def fresh_no_vault_instance(tmp_path: Path) -> tuple[InstanceRegistryRuntime, object]:
    """Provision only instance/principal authority; leave the registry empty."""

    host_global = tmp_path / "host-global"
    host_global.mkdir(mode=0o700)
    runtime = new_runtime(tmp_path)
    principal = run_principal_cutover(
        runtime,
        posture=AuthPosture(
            configured_credentials=0,
            credential=None,
            loopback_listener_proven=True,
            companion_proxy_configured=False,
        ),
        existing_install=False,
    )
    return runtime, principal


__all__ = ["fresh_no_vault_instance"]
