"""Focused regression proof for the seven #5100 / #3309 review residuals."""

from __future__ import annotations

from pathlib import Path

from app.release_channels.cutover_readiness import _pending_migration_delta


ROOT = Path(__file__).resolve().parents[2]


def _write_migration(
    versions: Path,
    filename: str,
    revision: str,
    down_revision: str | tuple[str, ...] | None,
) -> None:
    versions.mkdir(parents=True, exist_ok=True)
    (versions / filename).write_text(
        f"revision = {revision!r}\ndown_revision = {down_revision!r}\nreversibility = 'reversible'\n",
        encoding="utf-8",
    )


def test_release_ci_checkout_and_transcript_residuals(tmp_path: Path) -> None:
    workflow = (ROOT / ".github/workflows/app-image-build.yml").read_text(encoding="utf-8")
    assert workflow.index("Set up QEMU") < workflow.index("Set up Docker Buildx")
    assert "github.event_name != 'push' || github.ref != 'refs/heads/main'" in workflow

    fleet_guard = (ROOT / "app/release_channels/fleet_model_fitness.py").read_text(encoding="utf-8")
    assert 'APP_CODE_SERVICES = ("api", "worker", "watcher", "heimdal-capture-watch")' in fleet_guard

    versions = tmp_path / "versions"
    _write_migration(versions, "001.py", "001", None)
    _write_migration(versions, "left.py", "left", "001")
    _write_migration(versions, "right.py", "right", "001")
    _write_migration(versions, "merge.py", "merge", ("left", "right"))
    delta = _pending_migration_delta(versions, ("left", "right"))
    assert [migration.revision for migration in delta.pending] == ["merge"]
    release_channels = (ROOT / "docs/RELEASE_CHANNELS/README.md").read_text(encoding="utf-8")
    assert "union of their ancestor" in release_channels

    transcript_readme = ROOT / "docs/research/builder-system-skill-review-2026-07-09/transcripts/README.md"
    docs_index = (ROOT / "docs/DOCS_INDEX.md").read_text(encoding="utf-8")
    assert transcript_readme.exists()
    assert str(transcript_readme.relative_to(ROOT)) in docs_index


def test_ask_timeout_documentation_residual() -> None:
    llm_doc = (ROOT / "docs/LLM.md").read_text(encoding="utf-8")
    assert "defaults to 60s when unset" in llm_doc
    assert '"timeout_seconds": 60.0' in llm_doc
