from __future__ import annotations

from pathlib import Path

from app.ops.tars_qualification import POLICY_VERSION, QUALIFICATION_SCHEMA_VERSION


def test_tars_owner_contract_matches_policy_version() -> None:
    owner_contract = Path("docs/BUILDEROPS_CONTROL_PLANE/README.md").read_text(encoding="utf-8")
    docs_index = Path("docs/DOCS_INDEX.md").read_text(encoding="utf-8")
    normalized_contract = " ".join(owner_contract.split())

    assert "## TARS qualification contract" in owner_contract
    assert f"`{QUALIFICATION_SCHEMA_VERSION}`" in owner_contract
    assert f"`{POLICY_VERSION}`" in owner_contract
    assert "VM 102" in owner_contract
    assert "24 hours" in owner_contract
    assert "governed live-operations receipt" in normalized_contract
    assert "GPU passthrough" in owner_contract
    assert "test Tailscale" in owner_contract
    assert "TARS qualification owner entry" in docs_index
    assert "docs/BUILDEROPS_CONTROL_PLANE/README.md :: TARS qualification contract" in docs_index
