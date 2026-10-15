from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.cli.health import _check_youtube_sync
from app.knowledge_acquisition.sync_observability import collect_youtube_sync_status

pytestmark = pytest.mark.not_pg


class _State:
    def __init__(self, value):
        self.value = value

    def get(self, key):
        return self.value if key == "last_tick" else None


class _TokenStore:
    def has_record(self, binding_id):
        return binding_id == "binding-1"


class _AccountStore:
    def list_all(self):
        return (SimpleNamespace(account_binding_id="binding-1", state="degraded", reason_code="auth_revoked"),)


class _Quota:
    def status(self, budget):
        return {"spent_today": budget, "budget": budget, "exhausted": True}


def _source(reason_code=None):
    return SimpleNamespace(
        binding_id="source-1",
        account_binding_id="binding-1",
        collection_kind="inbox_playlist",
        collection_ref="PLfixture",
        enabled=True,
        poll_interval_seconds=180,
        last_attempt_at=None,
        last_success_at=None,
        last_error={"reason_code": reason_code, "at": "2026-10-15T00:00:00+00:00"} if reason_code else None,
        cursor={},
    )


class _Registry:
    def __init__(self, rows):
        self.rows = tuple(rows)

    def list_all(self):
        return self.rows


class _Requests:
    def list_all(self):
        return (
            SimpleNamespace(status="pending", requested_at="2026-10-15T00:00:00+00:00"),
            SimpleNamespace(status="dead_lettered", requested_at="2026-10-15T00:00:01+00:00"),
        )


def test_doctor_check_reason_codes_and_redaction(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.knowledge_acquisition.sync_observability as observed

    monkeypatch.setattr(observed, "_DEFAULT_GATES", {"youtubeSync.enabled": True, "youtubeSync.runnerEnabled": True})
    monkeypatch.setenv("YOUTUBE_TOKEN_STORE_KEY", "00" * 32)
    payload = collect_youtube_sync_status(
        now=datetime(2026, 10, 15, 1, tzinfo=timezone.utc),
        source_registry=_Registry((_source("auth_revoked"),)),
        request_store=_Requests(),
        account_store=_AccountStore(),
        token_store=_TokenStore(),
        quota_store=_Quota(),
        sync_state=_State({"at": "2026-10-15T00:00:00+00:00"}),
        gates={"youtubeSync.enabled": True, "youtubeSync.runnerEnabled": True},
    )
    monkeypatch.setattr(observed, "collect_youtube_sync_status", lambda **_: payload)
    result = _check_youtube_sync()
    reasons = set(result["data"]["reason_codes"])
    assert {"auth_revoked", "quota_exhausted", "runner_offline", "dead_letters_present"} <= reasons
    assert "00" * 32 not in str(result)


def test_stale_runner_never_reads_up_to_date() -> None:
    now = datetime(2026, 10, 15, 1, tzinfo=timezone.utc)
    result = collect_youtube_sync_status(
        now=now,
        source_registry=_Registry((_source(),)),
        request_store=_Requests(),
        account_store=_AccountStore(),
        token_store=_TokenStore(),
        quota_store=_Quota(),
        sync_state=_State({"at": (now - timedelta(seconds=601)).isoformat()}),
        runner_stale_seconds=600,
        gates={"youtubeSync.enabled": True, "youtubeSync.runnerEnabled": True},
    )
    assert result["runner_offline"] is True
    assert result["status"] == "offline"
    assert result["reason_code"] == "auth_revoked"


def test_signals_ride_existing_health_contract() -> None:
    result = collect_youtube_sync_status(
        source_registry=_Registry((_source(),)),
        request_store=_Requests(),
        account_store=_AccountStore(),
        token_store=_TokenStore(),
        quota_store=_Quota(),
        sync_state=_State(None),
        gates={"youtubeSync.enabled": False, "youtubeSync.runnerEnabled": False},
    )
    assert result["queue"]["depth"] == 1
    assert result["queue"]["dead_letters"] == 1
    assert result["dead_letters"] == 1
