from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_standalone_root


def test_generate_projections_rejects_incomplete_automation_store(tmp_path: Path) -> None:
    output_dir = tmp_path / "docs" / "generated" / "builderops"
    output_dir.mkdir(parents=True)
    existing_projection = output_dir / "docs-freshness.md"
    existing_markdown = "\n".join(
        [
            "State: Generated projection",
            "Authority: non-authoritative BuilderOps Vault projection",
            "Source of truth: BuilderOps Vault",
            "Generated at: 2026-06-18T20:29:32Z",
            "Projection type: docs-freshness",
            "Do not edit: regenerate from BuilderOps Vault records.",
            "",
            "# BuilderOps Docs Freshness Projection",
            "",
            "Record count: 5",
            "",
            "## Records",
            "",
            "### docsfresh_existing - Existing checked-in projection",
            "",
        ]
    )
    existing_projection.write_text(existing_markdown, encoding="utf-8")

    empty_db = tmp_path / "runtime" / "builderops" / "builderops.sqlite3"
    result = CliRunner().invoke(
        builderops_standalone_root,
        [
            "builderops",
            "--db-path",
            str(empty_db),
            "generate-projections",
            "--output-dir",
            str(output_dir),
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "refusing to overwrite existing BuilderOps projections" in result.output
    assert "docs-freshness" in result.output
    assert "existing record count 5" in result.output
    assert "selected store record count 0" in result.output
    assert "BUILDEROPS_DB_PATH" in result.output
    assert existing_projection.read_text(encoding="utf-8") == existing_markdown
