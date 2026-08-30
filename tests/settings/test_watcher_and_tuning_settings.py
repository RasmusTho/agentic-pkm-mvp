from __future__ import annotations

from pathlib import Path

from app.curation.contradiction import _contradiction_floor_from_settings, run_contradiction_pass
from app.expansion.connect import _relatedness_floor_from_settings
from app.retrieval.capability import RetrievalHit, RetrievalResponse
from app.settings.models import SettingsBundle, WatcherAndTuningSettings
from app.watcher.config import WatcherConfig
from app.write_guard import WriteGuard


def test_empty_settings_legacy_env_and_operator_tier_preserve_watcher_and_tuning_behavior(
    monkeypatch
) -> None:
    bundle = SettingsBundle(
        watcher_and_tuning=WatcherAndTuningSettings(
            debounce_ms=125,
            rate_limit_per_min=7,
            backoff_seconds=3,
            tick_sleep_seconds=0.25,
            connect_relatedness_floor=0.45,
            contradiction_floor=0.3,
        )
    )
    monkeypatch.setattr("app.watcher.config.get_settings_bundle", lambda: bundle)
    monkeypatch.setattr("app.expansion.connect.get_settings_bundle", lambda: bundle)
    monkeypatch.setattr("app.curation.contradiction.get_settings_bundle", lambda: bundle)
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "operator")
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "1")
    monkeypatch.setenv("WATCHER_RATE_LIMIT_PER_MIN", "2")
    monkeypatch.setenv("WATCHER_BACKOFF_SECONDS", "3")
    monkeypatch.setenv("WATCHER_TICK_SLEEP_SECONDS", "0.5")

    cfg = WatcherConfig(enable=False, vault_path=Path("."), scope_glob="*.md")
    cfg.reload_tunables_from_settings()

    assert (cfg.debounce_ms, cfg.rate_limit_per_min, cfg.backoff_seconds, cfg.tick_sleep_seconds) == (
        1500,
        30,
        10,
        1.0,
    )
    assert _relatedness_floor_from_settings() == 0.55
    assert _contradiction_floor_from_settings() == 0.4


def test_configured_contradiction_floor_is_honored_through_production_pass(
    tmp_path: Path, monkeypatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    for name, uuid, body in (
        ("a.md", "uuid-a", "The deadline is Tuesday."),
        ("b.md", "uuid-b", "The deadline is Wednesday."),
    ):
        (vault / name).write_text(
            f"---\nuuid: {uuid}\nkind: note\n---\n\n# {name}\n\n{body}\n",
            encoding="utf-8",
        )
    bundle = SettingsBundle(
        watcher_and_tuning=WatcherAndTuningSettings(contradiction_floor=0.3)
    )
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setattr("app.curation.contradiction.get_settings_bundle", lambda: bundle)

    def retrieve(_request):
        return RetrievalResponse(
            query="deadline",
            hits=[
                RetrievalHit(
                    object_id="a",
                    doc_id="a",
                    text="Tuesday",
                    score=0.35,
                    snippet="Tuesday",
                    source_ref="a.md",
                    payload={"uuid": "uuid-a"},
                ),
                RetrievalHit(
                    object_id="b",
                    doc_id="b",
                    text="Wednesday",
                    score=0.35,
                    snippet="Wednesday",
                    source_ref="b.md",
                    payload={"uuid": "uuid-b"},
                ),
            ],
        )

    report = run_contradiction_pass(
        vault_root=vault,
        queries=["deadline"],
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy", "reason": None}),
        outbox_path=tmp_path / "outbox.jsonl",
        materialize=False,
        retrieve_fn=retrieve,
    )

    assert len(report.findings) == 2
