"""MVR-05B4a (#6160): MCP vault tools resolve their vault from an explicit carrier."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.instance.active_context_service import (
    ACTION_SELECTION_INSPECT,
    PERMISSION_SELECTION_READ,
    WRITE_CLASS_READ,
    ActiveContextSelectionService,
)
from app.instance.context_selection import ContextSelectionStore
from app.instance.vault_carrier import VaultCarrier, carrier_from_active_context
from app.mcp import vault_tools
from app.orchestrator import executor
from tests._mvr03_principal_harness import provisioned_instance


def _scoped_context(tmp_path: Path):
    runtime, first, _extra, record = provisioned_instance(tmp_path, extra_roots=("two",))
    service = ActiveContextSelectionService(
        registry_store=runtime.registry,
        principal_record=record,
        selection_store=ContextSelectionStore(),
    )
    derived = service.derive("trusted_loopback")
    bearer, _ = service.create(derived=derived, binding_ids=[first.vault_binding_id])
    context = service.resolve_request_context(
        derived=derived,
        session_bearer=bearer,
        override_bearer=None,
        action=ACTION_SELECTION_INSPECT,
        write_class=WRITE_CLASS_READ,
        required_permission=PERMISSION_SELECTION_READ,
    ).snapshot
    return runtime, first, context


def test_mcp_vault_tools_use_explicit_context_carrier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, first, context = _scoped_context(tmp_path)
    decoy = tmp_path / "decoy-env-vault"
    decoy.mkdir()
    for key in ("MCP_VAULT_ROOT", "VAULT_DIR", "VAULT_ROOT"):
        monkeypatch.setenv(key, str(decoy))

    env_reads: list[str] = []
    real_getenv = vault_tools.os.getenv

    def _spy_getenv(key, default=None):  # type: ignore[no-untyped-def]
        # Record the MCP carrier's own vault-env reads (the module under test).
        caller = sys._getframe(1).f_globals.get("__name__")
        if caller == vault_tools.__name__ and key in {"MCP_VAULT_ROOT", "VAULT_DIR", "VAULT_ROOT"}:
            env_reads.append(key)
        return real_getenv(key, default)

    def _no_global(*_args, **_kwargs):
        raise AssertionError("a carrier-bearing MCP call read the process-global vault")

    monkeypatch.setattr(vault_tools.os, "getenv", _spy_getenv)
    monkeypatch.setattr(vault_tools, "resolve_optional_vault_root", _no_global)

    carrier = carrier_from_active_context(context, registry_store=runtime.registry)
    bound_root = Path(first.path).resolve()
    assert carrier.root == bound_root
    assert carrier.vault_binding_id == first.vault_binding_id
    assert carrier.context_generation == context.generation

    # Reads: the carrier (argument or setting) is the whole answer.
    assert vault_tools.get_vault_root(carrier=carrier) == bound_root
    assert vault_tools.get_vault_root({"vault_carrier": carrier}) == bound_root
    # An explicit settings path cannot outrank the carrier.
    assert vault_tools.get_vault_root({"vault_carrier": carrier, "vault_root": str(decoy)}) == bound_root

    # Writes carrying a scoped context are sealed before any filesystem seam.
    with pytest.raises(vault_tools.VaultToolError, match="capability_not_ready"):
        vault_tools.append_note(title="t", body="b", carrier=carrier)
    with pytest.raises(vault_tools.VaultToolError, match="capability_not_ready"):
        executor._resolve_effect_vault_root({"vault_carrier": carrier})  # noqa: SLF001
    assert not any(bound_root.rglob("_mcp/*.md"))

    # An operator carrier (explicit selection) writes into its own root.
    operator_root = tmp_path / "operator-vault"
    operator_root.mkdir()
    operator = VaultCarrier(source="explicit_selection", root=operator_root.resolve())
    written = vault_tools.append_note(title="Carrier note", body="body", carrier=operator)
    assert written.resolve().is_relative_to(operator_root.resolve())
    assert executor._resolve_effect_vault_root({"vault_carrier": operator}) == operator_root.resolve()  # noqa: SLF001

    # A no-vault carrier refuses instead of falling back to the environment.
    with pytest.raises(vault_tools.VaultToolError, match="no vault is bound"):
        vault_tools.get_vault_root(carrier=VaultCarrier(source="no_vault", root=None))

    assert env_reads == [], env_reads
    assert not any(decoy.iterdir())

    # Only a carrier-free call reaches the named compatibility adapter.
    monkeypatch.setattr(vault_tools, "resolve_optional_vault_root", lambda **_k: None)
    assert vault_tools.get_vault_root() == decoy.resolve()
    assert env_reads == ["MCP_VAULT_ROOT"]
