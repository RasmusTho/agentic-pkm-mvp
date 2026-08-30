from __future__ import annotations

from pathlib import Path

from app.agents.panel_agent.policy import watcher_panel_writeback_allowed
from app.heimdal.candidate_projection import project_pending_candidates
from app.heimdal.cursor_store import reset_memory_cursor_store
from app.heimdal.observation_log import reset_memory_observation_log
from app.heimdal.meeting_finalization import meetings_dir_rel
from app.heimdal.publish import publish_observation
from app.knowledge_acquisition.candidate_writeback import (
    write_candidate_note,
)
from app.knowledge_acquisition.source_bundle import materialize_youtube_source_bundle
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard
from tests.knowledge_acquisition.test_candidate_writeback import _assembled_candidate
from tests.knowledge_acquisition.test_youtube_source_bundle import _source_material


def _vault(root: Path) -> VaultContext:
    root.mkdir(parents=True, exist_ok=True)
    return VaultContext("selected", "vault-test", "Vault Test", str(root))


def _guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def test_current_sources_producers_use_resolved_selected_vault_root(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("VAULT_SOURCES_DIR_REL", "ConfiguredSources")
    vault = _vault(tmp_path / "vault")

    candidate = _assembled_candidate()
    note = write_candidate_note(candidate, vault_context=vault, write_guard=_guard())
    assert note.artifact_path is not None
    assert note.artifact_path.startswith("ConfiguredSources/")

    _raw, transcript, bundle_candidate = _source_material(tmp_path)
    bundle = materialize_youtube_source_bundle(
        bundle_candidate,
        transcript,
        vault_context=vault,
        write_guard=_guard(),
    )
    assert bundle.source_folder.startswith("ConfiguredSources/YouTube/_attachments/")
    assert meetings_dir_rel(Path(vault.active_vault_path)) == "ConfiguredSources/Meetings"

    reset_memory_observation_log()
    reset_memory_cursor_store()
    try:
        publish_observation(
            topic="heimdal.observation.published",
            observation_id="obs-sources-zone",
            payload={
                "observation_id": "obs-sources-zone",
                "episode_id": "episode-sources-zone",
                "content": "Heimdal candidate",
                "raw_ref": "raw:sources-zone",
                "provenance": {
                    "content_identity": "sha256:" + "a" * 64,
                    "raw_ref": "raw:sources-zone",
                    "capture_chain": ["test"],
                },
            },
            source="test.sources-zone",
            stage_versions={"test": "1"},
        )
        karakeep_id = "karakeep:sources-zone"
        publish_observation(
            topic="heimdal.observation.published",
            observation_id=karakeep_id,
            payload={
                "observation_id": karakeep_id,
                "episode_id": karakeep_id,
                "content": "Karakeep candidate",
                "raw_ref": "raw:karakeep:sources-zone",
                "content_structure": {
                    "karakeep": {
                        "item_kind": "link",
                        "source_item_identity": karakeep_id,
                        "source_url": "https://example.com/sources-zone",
                        "tombstone": False,
                    }
                },
                "provenance": {
                    "sensor": "karakeep_rest",
                    "content_identity": "sha256:" + "b" * 64,
                    "raw_ref": "raw:karakeep:sources-zone",
                    "capture_chain": ["karakeep"],
                },
            },
            source="test.sources-zone",
            stage_versions={"test": "1"},
        )
        projected = project_pending_candidates(vault_context=vault, write_guard=_guard())
        paths = {result.artifact_path for result in projected}
        assert any(path and path.startswith("ConfiguredSources/Heimdal/") for path in paths)
        assert any(path and path.startswith("ConfiguredSources/Reading/Karakeep/") for path in paths)
        assert not (Path(vault.active_vault_path) / "Sources").exists()
        assert watcher_panel_writeback_allowed(
            "ConfiguredSources/panel.md", vault_root=Path(vault.active_vault_path)
        ) is False
    finally:
        reset_memory_observation_log()
        reset_memory_cursor_store()


def test_malformed_sources_setting_denies_panel_agent_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("VAULT_SOURCES_DIR_REL", raising=False)
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    (settings_dir / "system-settings.md").write_text(
        "---\npaths:\n  sources_dir_rel: []\n---\n",
        encoding="utf-8",
    )

    assert watcher_panel_writeback_allowed(
        "Sources/panel.md", vault_root=tmp_path
    ) is False
