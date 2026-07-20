"""Architecture guard for future YouTube runtime-gating consumers (YSS-06/YSS-10)."""

from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = pytest.mark.not_pg


def test_yss06_yss10_consume_gating_only_via_accessor() -> None:
    root = Path(__file__).resolve().parents[2]
    consumer_paths = (
        root / "app/watcher/registry.py",  # YSS-06 tick host
        root / "app/knowledge_acquisition/sync_scheduler.py",  # YSS-06
        root / "app/cli/youtube_sync.py",  # YSS-10
    )
    for path in consumer_paths:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        if "youtubeSync.enabled" not in source and "youtubeSync.runnerEnabled" not in source:
            continue
        assert "resolve_accepted_runtime_gating" in source, path
        assert ".resolve(context)" not in source, path
