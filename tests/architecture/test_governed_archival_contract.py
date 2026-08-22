"""Architecture-level acceptance tests for the governed archival contract."""

from __future__ import annotations

from pathlib import Path
import inspect

from app.archival.transition import ArchivalTransitionKernel


ROOT = Path(__file__).resolve().parents[2]


def test_contract_preserves_sbs_ownership_and_forbids_central_registry() -> None:
    contract = (ROOT / "docs/contracts/GOVERNED_ARCHIVAL_FLOW.md").read_text()
    implementation = (ROOT / "app/archival/contracts.py").read_text()

    for owner in ("HKA", "SIP", "GOV", "PDM", "DRI"):
        assert owner in contract
    assert "MUST NOT create a central archive authority, registry, or store" in contract
    assert "class ArchiveStore" not in implementation
    assert "class ArchiveRegistry" not in implementation


def test_normative_contract_and_invariant_registry_match() -> None:
    contract = (ROOT / "docs/contracts/GOVERNED_ARCHIVAL_FLOW.md").read_text()
    registry = (ROOT / "docs/testing/invariant-tests.md").read_text()

    for identifier in (
        *(f"ARCHIVE-MUST-{number:02d}" for number in range(1, 8)),
        *(f"ARCHIVE-GATE-{number:02d}" for number in range(1, 5)),
        *(f"ARCHIVE-DOCTOR-{number:02d}" for number in range(1, 4)),
    ):
        assert identifier in contract
        assert identifier in registry


def test_transition_kernel_has_no_private_persistence_or_content_store() -> None:
    source = inspect.getsource(ArchivalTransitionKernel)
    assert "dict[" not in source
    assert "bytes" not in source
    assert "registry" not in source.lower()
