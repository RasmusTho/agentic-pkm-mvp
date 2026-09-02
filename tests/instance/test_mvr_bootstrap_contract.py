from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MVR_README = REPO_ROOT / "docs" / "MULTI_VAULT_RUNTIME" / "README.md"
BOOTSTRAP_HEADING = "### Fresh bootstrap after operational-lineage loss"


def _bootstrap_section() -> str:
    text = MVR_README.read_text(encoding="utf-8")
    start = text.index(BOOTSTRAP_HEADING)
    remainder = text[start + len(BOOTSTRAP_HEADING) :]
    end = remainder.find("\n### ")
    return remainder if end == -1 else remainder[:end]


def _transition_rows(section: str) -> list[dict[str, str]]:
    table_lines = [line for line in section.splitlines() if line.lstrip().startswith("|")]
    assert len(table_lines) >= 3, "the MVR bootstrap contract must contain a transition table"
    headers = [cell.strip() for cell in table_lines[0].strip().strip("|").split("|")]
    assert all(
        set(cell) <= {"-", ":", " "}
        for cell in table_lines[1].strip().strip("|").split("|")
    )
    return [
        dict(zip(headers, (cell.strip() for cell in line.strip().strip("|").split("|"))))
        for line in table_lines[2:]
    ]


def test_missing_operational_lineage_requires_fresh_fenced_epoch() -> None:
    section = _bootstrap_section()
    lowered = section.lower()
    rows = _transition_rows(section)

    for lineage in ("journal", "lease", "ownership", "recovery lineage"):
        assert lineage in lowered
    assert "fresh bootstrap epoch" in lowered
    assert "inactive_fenced" in lowered

    missing_lineage = next(
        row for row in rows if "missing operational lineage" in row["Event"].lower()
    )
    assert missing_lineage["To"] == "inactive_fenced"
    assert "new epoch" in missing_lineage["Required evidence / refusal"].lower()

    direct_activation_targets = {"active", "owned", "effect_capable"}
    for row in rows:
        if row["From"] in {"unknown_or_missing", "inactive_fenced"}:
            assert row["To"] not in direct_activation_targets

    activation = next(row for row in rows if "explicit activation" in row["Event"].lower())
    assert activation["From"] == "activation_ready"
    assert activation["To"] == "active"
    effect_enablement = next(row for row in rows if "effect capability" in row["Event"].lower())
    assert effect_enablement["From"] == "owned"
    assert effect_enablement["To"] == "effect_capable"


def test_bootstrap_contract_requires_authoritative_readback_and_receipt() -> None:
    section = _bootstrap_section()
    lowered = section.lower()
    rows = _transition_rows(section)

    for source in (
        "owner-native mvr registry/config",
        "host-global ownership ledger",
        "live channel/process readback",
        "external effect readback",
    ):
        assert source in lowered
    for refusal in ("ownership_conflict_refused", "readback_unavailable"):
        assert refusal in lowered
    for receipt_field in ("epoch id", "source digest", "readback digest", "decision digest"):
        assert receipt_field in lowered

    conflict = next(row for row in rows if "ownership conflict" in row["Event"].lower())
    assert conflict["To"] == "ownership_conflict_refused"
    unavailable = next(row for row in rows if "readback unavailable" in row["Event"].lower())
    assert unavailable["To"] == "inactive_fenced"

    activation = next(row for row in rows if "explicit activation" in row["Event"].lower())
    activation_rule = activation["Required evidence / refusal"].lower()
    assert "convergence receipt" in activation_rule
    assert "no inferred ownership" in activation_rule
    assert "no inferred prior effect" in activation_rule

    reconciliation_start = lowered.index("reconciliation — do not duplicate")
    reconciliation = lowered[reconciliation_start:]
    for issue in ("#2143", "#3863", "#3864", "#3865", "#3866", "#3867", "#3868", "#3869"):
        assert issue in reconciliation
    for forbidden in (
        "parallel registry",
        "parallel journal",
        "parallel supervisor",
        "parallel recovery",
    ):
        assert forbidden in reconciliation
