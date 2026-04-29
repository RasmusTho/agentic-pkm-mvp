"""Tests for the migration reversibility marker system.

AC1: Marker taxonomy is defined and validated (two values: reversible / forward-only).
AC2: Pre-promotion checks fail when the required marker is missing or invalid.
AC3: Receipts include classification decisions for auditability.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.release_channels.reversibility import (
    FORWARD_ONLY,
    REVERSIBLE,
    VALID_MARKERS,
    MigrationClassificationResult,
    MigrationMarkerError,
    check_all_migrations,
    classify_migration,
    read_migration_marker,
)


# ---------------------------------------------------------------------------
# AC1 — Marker taxonomy: exactly two values, both readable from migration files
# ---------------------------------------------------------------------------


class TestMarkerTaxonomy:
    def test_exactly_two_valid_marker_values(self) -> None:
        assert VALID_MARKERS == frozenset({"reversible", "forward-only"})

    def test_reversible_constant_value(self) -> None:
        assert REVERSIBLE == "reversible"

    def test_forward_only_constant_value(self) -> None:
        assert FORWARD_ONLY == "forward-only"

    def test_read_reversible_marker(self, tmp_path: Path) -> None:
        f = tmp_path / "001_migration.py"
        f.write_text('reversibility = "reversible"\n', encoding="utf-8")
        assert read_migration_marker(f) == REVERSIBLE

    def test_read_forward_only_marker(self, tmp_path: Path) -> None:
        f = tmp_path / "002_migration.py"
        f.write_text('reversibility = "forward-only"\n', encoding="utf-8")
        assert read_migration_marker(f) == FORWARD_ONLY

    def test_type_annotated_marker_accepted(self, tmp_path: Path) -> None:
        f = tmp_path / "003_migration.py"
        f.write_text('reversibility: str = "reversible"\n', encoding="utf-8")
        assert read_migration_marker(f) == REVERSIBLE

    def test_classify_migration_returns_result(self, tmp_path: Path) -> None:
        f = tmp_path / "004_migration.py"
        f.write_text('reversibility = "forward-only"\n', encoding="utf-8")
        result = classify_migration(f)
        assert isinstance(result, MigrationClassificationResult)
        assert result.classification == FORWARD_ONLY
        assert result.is_forward_only is True

    def test_classify_reversible_is_not_forward_only(self, tmp_path: Path) -> None:
        f = tmp_path / "005_migration.py"
        f.write_text('reversibility = "reversible"\n', encoding="utf-8")
        result = classify_migration(f)
        assert result.is_forward_only is False


# ---------------------------------------------------------------------------
# AC2 — Pre-promotion checks fail when marker is missing or invalid
# ---------------------------------------------------------------------------


class TestPrePromotionFailurePath:
    def test_missing_marker_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "no_marker.py"
        f.write_text('revision = "abc"\n\ndef upgrade(): pass\n', encoding="utf-8")
        with pytest.raises(MigrationMarkerError, match="missing"):
            read_migration_marker(f)

    def test_invalid_marker_value_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "bad_value.py"
        f.write_text('reversibility = "maybe"\n', encoding="utf-8")
        with pytest.raises(MigrationMarkerError, match="invalid"):
            read_migration_marker(f)

    def test_empty_file_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.py"
        f.write_text("", encoding="utf-8")
        with pytest.raises(MigrationMarkerError, match="missing"):
            read_migration_marker(f)

    def test_check_all_fails_on_one_missing_marker(self, tmp_path: Path) -> None:
        good = tmp_path / "001_good.py"
        good.write_text('reversibility = "reversible"\n', encoding="utf-8")
        bad = tmp_path / "002_no_marker.py"
        bad.write_text('revision = "xyz"\n', encoding="utf-8")
        with pytest.raises(MigrationMarkerError):
            check_all_migrations([good, bad])

    def test_check_all_fails_on_invalid_marker(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.py"
        f.write_text('reversibility = "unknown"\n', encoding="utf-8")
        with pytest.raises(MigrationMarkerError):
            check_all_migrations([f])


# ---------------------------------------------------------------------------
# AC3 — Receipt includes classification decisions for auditability
# ---------------------------------------------------------------------------


class TestClassificationReceipt:
    def test_single_reversible_migration_receipt(self, tmp_path: Path) -> None:
        f = tmp_path / "001.py"
        f.write_text('reversibility = "reversible"\n', encoding="utf-8")
        receipt = check_all_migrations([f])
        assert receipt["migrations_checked"] == 1
        assert "001.py" in receipt["reversible"]
        assert receipt["forward_only"] == []
        decisions = receipt["classification_decisions"]
        assert len(decisions) == 1
        assert decisions[0]["migration"] == "001.py"
        assert decisions[0]["classification"] == "reversible"
        assert decisions[0]["is_forward_only"] is False

    def test_single_forward_only_migration_receipt(self, tmp_path: Path) -> None:
        f = tmp_path / "002.py"
        f.write_text('reversibility = "forward-only"\n', encoding="utf-8")
        receipt = check_all_migrations([f])
        assert receipt["migrations_checked"] == 1
        assert "002.py" in receipt["forward_only"]
        assert receipt["reversible"] == []
        decisions = receipt["classification_decisions"]
        assert decisions[0]["classification"] == "forward-only"
        assert decisions[0]["is_forward_only"] is True

    def test_mixed_migrations_receipt(self, tmp_path: Path) -> None:
        r = tmp_path / "001_rev.py"
        r.write_text('reversibility = "reversible"\n', encoding="utf-8")
        fo = tmp_path / "002_fwd.py"
        fo.write_text('reversibility = "forward-only"\n', encoding="utf-8")
        receipt = check_all_migrations([r, fo])
        assert receipt["migrations_checked"] == 2
        assert "001_rev.py" in receipt["reversible"]
        assert "002_fwd.py" in receipt["forward_only"]
        assert len(receipt["classification_decisions"]) == 2

    def test_receipt_classification_decisions_include_all_required_keys(self, tmp_path: Path) -> None:
        f = tmp_path / "check.py"
        f.write_text('reversibility = "reversible"\n', encoding="utf-8")
        receipt = check_all_migrations([f])
        decision = receipt["classification_decisions"][0]
        assert set(decision.keys()) == {"migration", "classification", "is_forward_only"}

    def test_empty_migration_list_returns_empty_receipt(self) -> None:
        receipt = check_all_migrations([])
        assert receipt["migrations_checked"] == 0
        assert receipt["reversible"] == []
        assert receipt["forward_only"] == []
        assert receipt["classification_decisions"] == []
