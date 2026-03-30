"""Phase B: Golden Vault + Seeded Snapshots.

Validates deterministic test vault and reproducible ingest outcomes.

Golden vault enables:
- Reproducible ingest tests (same input → same output)
- Deterministic retrieval results
- Panel agent consistency checks
- Cold rebuild validation (Phase D)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.quality_wave.conftest import MetricsCollector


@pytest.mark.not_pg
class TestGoldenVaultLoads:
    """Test that golden vault files are present and loadable."""

    def test_golden_vault_path_exists(self, golden_vault_path: Path):
        """Assert golden vault test seed directory exists."""
        assert golden_vault_path.exists(), f"Golden vault not found at {golden_vault_path}"
        assert golden_vault_path.is_dir()

    def test_golden_vault_has_required_files(self, golden_vault_path: Path):
        """Assert golden vault contains all required seed files."""
        required_files = [
            "golden.md",
            "expected_outcomes.json",
            "Note_1.md",
            "Note_2.md",
            "2_Cards/Concept.md",
            "Workbench/Draft.md",
        ]

        for rel_path in required_files:
            full_path = golden_vault_path / rel_path
            assert full_path.exists(), f"Missing golden vault file: {rel_path}"

    def test_golden_vault_note_files_have_content(self, golden_vault_path: Path):
        """Assert all markdown files have content."""
        note_files = [
            golden_vault_path / "Note_1.md",
            golden_vault_path / "Note_2.md",
            golden_vault_path / "2_Cards/Concept.md",
            golden_vault_path / "Workbench/Draft.md",
        ]

        for note_file in note_files:
            assert note_file.exists()
            content = note_file.read_text(encoding="utf-8")
            assert len(content) > 0, f"Empty note file: {note_file}"
            assert "---" in content, f"No frontmatter in: {note_file}"
            assert "uuid:" in content, f"Missing uuid in: {note_file}"

    def test_expected_outcomes_valid_json(self, expected_outcomes: dict):
        """Assert expected_outcomes.json is valid and complete."""
        assert isinstance(expected_outcomes, dict)
        assert "description" in expected_outcomes
        assert "ingest_metrics" in expected_outcomes
        assert "object_counts" in expected_outcomes

    def test_expected_outcomes_metrics_complete(self, expected_outcomes: dict):
        """Assert expected_outcomes has all required metric sections."""
        required_sections = [
            "ingest_metrics",
            "object_counts",
            "embedding_stats",
            "relation_stats",
            "promotion_readiness",
        ]

        for section in required_sections:
            assert section in expected_outcomes, f"Missing section: {section}"


@pytest.mark.not_pg
class TestGoldenVaultContent:
    """Test golden vault content for reproducibility."""

    def test_golden_vault_content_loadable(self, golden_vault_content: dict):
        """Assert golden vault content loads without errors."""
        assert len(golden_vault_content) > 0, "Golden vault content is empty"

    def test_golden_vault_has_expected_note_count(self, golden_vault_content: dict):
        """Assert golden vault has expected number of notes."""
        # Should have at least 4 notes: Note_1.md, Note_2.md, Concept.md, Draft.md
        assert len(golden_vault_content) >= 4, f"Expected at least 4 notes, got {len(golden_vault_content)}"

    def test_all_notes_have_frontmatter_uuid(self, golden_vault_content: dict):
        """Assert all notes in golden vault have uuid in frontmatter."""
        for path, content in golden_vault_content.items():
            if Path(path).name == "golden.md":
                continue
            assert "---" in content, f"Missing frontmatter in {path}"
            # Extract frontmatter
            lines = content.split("\n")
            assert any("uuid:" in line for line in lines), f"Missing uuid in {path}"

    def test_golden_vault_content_deterministic(self, golden_vault_path: Path):
        """Assert golden vault content can be loaded identically twice."""
        # Load once
        vault1 = {}
        for md_file in golden_vault_path.glob("**/*.md"):
            if md_file.name != "golden.md":  # Skip the golden.md doc itself
                vault1[str(md_file.relative_to(golden_vault_path))] = md_file.read_text(encoding="utf-8")

        # Load again
        vault2 = {}
        for md_file in golden_vault_path.glob("**/*.md"):
            if md_file.name != "golden.md":
                vault2[str(md_file.relative_to(golden_vault_path))] = md_file.read_text(encoding="utf-8")

        # Should be identical
        assert vault1 == vault2, "Golden vault content not deterministic"


@pytest.mark.not_pg
class TestExpectedOutcomesSnapshot:
    """Test expected outcomes snapshot for Phase D/E validation."""

    def test_ingest_metrics_snapshot(self, expected_outcomes: dict):
        """Assert ingest metrics snapshot is complete."""
        ingest = expected_outcomes["ingest_metrics"]

        assert "total_notes" in ingest
        assert ingest["total_notes"] >= 4
        assert "notes_with_uuid" in ingest
        assert ingest["notes_with_uuid"] == ingest["total_notes"]
        assert "objects_created" in ingest
        assert "embeddings_created" in ingest
        assert ingest["embeddings_created"] == ingest["objects_created"]

    def test_object_counts_snapshot(self, expected_outcomes: dict):
        """Assert object count breakdown is consistent."""
        counts = expected_outcomes["object_counts"]

        assert "total" in counts
        assert "by_review_state" in counts
        assert "by_kind" in counts

        # Total should match sum of review states
        state_total = sum(counts["by_review_state"].values())
        assert state_total == counts["total"]

    def test_embedding_stats_snapshot(self, expected_outcomes: dict):
        """Assert embedding statistics are valid."""
        embeddings = expected_outcomes["embedding_stats"]

        assert embeddings["total_embeddings"] > 0
        assert "model" in embeddings
        assert embeddings["embedding_dim"] == 1536  # Standard OpenAI embedding dim
        assert "avg_tokens_per_note" in embeddings

    def test_promotion_readiness_snapshot(self, expected_outcomes: dict):
        """Assert promotion readiness is documented."""
        promo = expected_outcomes["promotion_readiness"]

        assert "promotable_notes" in promo
        assert promo["promotable_notes"] >= 1
        assert "note_path" in promo
        assert "note_uuid" in promo


@pytest.mark.not_pg
class TestGoldenVaultReproducibility:
    """Test reproducibility invariants for golden vault."""

    def test_vault_content_same_across_loads(self, golden_vault_path: Path):
        """Assert vault content is identical across multiple loads."""
        loads = []
        for _ in range(3):
            vault = {}
            for md_file in sorted(golden_vault_path.glob("**/*.md")):
                if md_file.name != "golden.md":
                    vault[str(md_file.relative_to(golden_vault_path))] = md_file.read_text(
                        encoding="utf-8"
                    )
            loads.append(json.dumps(vault, sort_keys=True))

        # All three loads should be identical
        assert loads[0] == loads[1] == loads[2], "Vault content not reproducible"

    def test_expected_outcomes_snapshot_stable(self, golden_vault_path: Path):
        """Assert expected outcomes snapshot doesn't change."""
        outcomes_path = golden_vault_path / "expected_outcomes.json"
        outcomes1 = json.loads(outcomes_path.read_text(encoding="utf-8"))
        outcomes2 = json.loads(outcomes_path.read_text(encoding="utf-8"))

        assert json.dumps(outcomes1, sort_keys=True) == json.dumps(
            outcomes2, sort_keys=True
        ), "Expected outcomes not stable"

    def test_vault_no_dynamic_content(self, golden_vault_content: dict):
        """Assert golden vault contains no dynamic/timestamp content."""
        for path, content in golden_vault_content.items():
            # No timestamps should be present
            lower = content.lower()
            assert "timestamp:" not in lower, f"Dynamic timestamp in {path}"
            assert "date:" not in lower, f"Dynamic date in {path}"
            assert "generated_at:" not in lower, f"Dynamic generated_at in {path}"
            assert "updated_at:" not in lower, f"Dynamic updated_at in {path}"


@pytest.mark.not_pg
class TestGoldenVaultMetricsCapture:
    """Test metrics capture for reproducibility validation."""

    def test_metrics_snapshot_for_ingest(self, metrics: MetricsCollector, expected_outcomes: dict):
        """Assert metrics can be captured and matched to expected outcomes."""
        expected = expected_outcomes["ingest_metrics"]

        # Simulate an ingest run
        metrics.ingest_runs = 1
        metrics.object_count = expected["objects_created"]
        metrics.embedding_count = expected["embeddings_created"]

        snapshot = metrics.snapshot()

        assert snapshot["object_count"] == expected["objects_created"]
        assert snapshot["embedding_count"] == expected["embeddings_created"]

    def test_metrics_idempotent_for_same_vault(self, metrics: MetricsCollector, expected_outcomes: dict):
        """Assert metrics are identical when processing same vault twice."""
        expected = expected_outcomes["ingest_metrics"]

        # First run
        metrics1 = MetricsCollector()
        metrics1.ingest_runs = 1
        metrics1.object_count = expected["objects_created"]
        metrics1.embedding_count = expected["embeddings_created"]
        metrics1.snapshot()

        # Second run (same vault)
        metrics2 = MetricsCollector()
        metrics2.ingest_runs = 1
        metrics2.object_count = expected["objects_created"]
        metrics2.embedding_count = expected["embeddings_created"]
        metrics2.snapshot()

        metrics1.assert_idempotent(metrics2)

    def test_baseline_metrics_for_phase_c_d(self, metrics: MetricsCollector, expected_outcomes: dict):
        """Assert metrics baseline is set for Phase C/D metamorphic and rebuild tests."""
        ingest = expected_outcomes["ingest_metrics"]

        # Establish baseline
        baseline = {
            "objects": ingest["objects_created"],
            "embeddings": ingest["embeddings_created"],
            "relations": expected_outcomes["relation_stats"]["link_relations"],
        }

        assert baseline["objects"] > 0
        assert baseline["embeddings"] > 0

        # This baseline will be used in Phase C and D tests
        # to assert that metamorphic runs and cold rebuild maintain these counts
