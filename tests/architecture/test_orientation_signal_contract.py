"""Architecture fitness checks for Issue #5233's docs-only orientation seam."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = REPO_ROOT / "docs/CONCEPTS/ORIENTATION_SIGNAL_PROJECTION_CONTRACT.md"


def _contract() -> str:
    return " ".join(CONTRACT.read_text(encoding="utf-8").split())


def test_orientation_signal_contract_defines_derived_non_durable_model() -> None:
    text = _contract()

    for state in ("`active`", "`waiting`", "`supporting`", "`background`", "`unknown`"):
        assert state in text
    assert "request-time projection" in text
    assert "`orientation_state`" in text
    assert "equivalent field may be stored" in text
    assert "discarded or recomputed" in text


def test_orientation_signal_contract_defines_producer_matrix() -> None:
    text = _contract()

    for producer in (
        "Active context/session",
        "Commitment artifacts",
        "Frontmatter and path source context",
        "Vault topology",
        "Bounded recent activity",
        "Generic vault note ingestion",
    ):
        assert producer in text
    assert "Recent activity can corroborate" in text
    assert "cannot promote an ordinary note" in text


def test_orientation_signal_contract_defines_non_durable_projection_and_attribution() -> None:
    text = _contract()

    assert "Apply normal scope/policy and context-admissibility rules before ranking" in text
    assert "`unknown` may not be silently filtered as background" in text
    assert "Every source id emitted by ASK synthesis or recall" in text
    assert "admitted, citable source" in text
    assert "rebuildable, provenance-bearing projection" in text


def test_orientation_contract_separates_admissibility_and_intent() -> None:
    text = _contract()

    assert "ordinary retrieval question is not orientation" in text
    assert "Do not apply orientation filtering to an ordinary retrieval question" in text
    assert "`background` does not make an otherwise admitted source inadmissible" in text
    assert "Do not infer active work from generic prose" in text
