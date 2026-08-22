from pathlib import Path

from app.archival import ArchivalAdapter, PolicyProfile


ROOT = Path(__file__).parents[2]
CONTRACT = ROOT / "docs/contracts/GOVERNED_ARCHIVAL_FLOW.md"
INVARIANTS = ROOT / "docs/testing/invariant-tests.md"


def test_contract_preserves_sbs_ownership_and_forbids_central_registry():
    text = CONTRACT.read_text()
    for owner in ("HKA", "SIP", "GOV", "PDM", "DRI"):
        assert owner in text
    assert "central archive registry" in text
    assert "central archive store" in text


def test_normative_contract_and_invariant_registry_match():
    contract = CONTRACT.read_text()
    registry = INVARIANTS.read_text()
    for invariant in (
        "ARCHIVE-MUST-01",
        "ARCHIVE-MUST-02",
        "ARCHIVE-MUST-03",
        "ARCHIVE-MUST-04",
        "ARCHIVE-MUST-05",
        "ARCHIVE-GATE-01",
        "ARCHIVE-GATE-02",
        "ARCHIVE-GATE-03",
        "ARCHIVE-GATE-04",
        "ARCHIVE-DOCTOR-01",
        "ARCHIVE-DOCTOR-02",
        "ARCHIVE-DOCTOR-03",
    ):
        assert invariant in contract
        assert invariant in registry

    assert "ArchivalAdapter" in contract
    assert "Provider-free" in contract
    assert "ARCHIVE-MUST-01" in contract
    assert ArchivalAdapter is not None
    assert PolicyProfile.RAW_EVIDENCE.value == "raw_evidence"
