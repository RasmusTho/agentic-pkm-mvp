from __future__ import annotations

from pathlib import Path

import pytest

from app.events.types import ASK_QUERY_RECEIVED, INGEST_OBJECT_CREATED, PROMOTE_INTENT_CREATED
from app.settings.flows import get_flows_for_event, load_flow_settings


def test_loads_default_flow_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sample = tmp_path / "flows.yaml"
    sample.write_text(
        """
flows:
  ingest:
    enabled: true
    triggers:
      - ingest.object.created
  qa:
    enabled: false
    triggers:
      - ask.query.received
        """.strip()
    + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FLOW_SETTINGS_PATH", str(sample))
    settings = load_flow_settings(force=True)
    assert "ingest" in settings.flows
    assert INGEST_OBJECT_CREATED in settings.flows["ingest"].triggers
    assert not settings.flows["qa"].enabled


def test_get_flows_for_event_filters_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sample = tmp_path / "flows.yaml"
    sample.write_text(
        """
flows:
  ingest:
    enabled: true
    triggers:
      - ingest.object.created
  qa:
    enabled: false
    triggers:
      - ask.query.received
  promotion:
    enabled: true
    triggers:
      - promote.intent.created
        """.strip()
    + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FLOW_SETTINGS_PATH", str(sample))
    settings = load_flow_settings(force=True)
    assert get_flows_for_event(INGEST_OBJECT_CREATED, settings) == ["ingest"]
    assert get_flows_for_event(ASK_QUERY_RECEIVED, settings) == []
    assert get_flows_for_event(PROMOTE_INTENT_CREATED, settings) == ["promotion"]


def test_default_sample_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FLOW_SETTINGS_PATH", raising=False)
    settings = load_flow_settings(force=True, path=Path("docs/settings/flows.settings.yaml"))
    assert get_flows_for_event(INGEST_OBJECT_CREATED, settings) == ["ingest"]
