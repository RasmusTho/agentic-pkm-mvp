"""Fail-loud channel-env preflight (issue #1997 F2).

These tests pin the contract that the test-channel entrypoints refuse to run on
an inconsistent or ambient configuration instead of silently targeting the
wrong thing. They are pure (no Docker, no network): the preflight reads an env
mapping and reports.
"""

from __future__ import annotations

import pytest

from app.ops.channel_preflight import (
    ChannelPreflightError,
    channel_env_preflight,
    raise_if_blocking,
)


def _consistent_test_env() -> dict[str, str]:
    """A fully channel-correct host-side test env (no violations)."""
    return {
        "PKM_ENVIRONMENT": "test",
        "PKM_CHANNEL": "test",
        "VAULT_ROOT": "/srv/agentic-pkm/vault-test",
        "VAULT_ROOT_TEST": "/srv/agentic-pkm/vault-test",
        "INDEX_OUTBOX_PATH": "/srv/agentic-pkm/tmp-test/index-outbox.jsonl",
        "DATABASE_URL": "postgresql+psycopg://app:app@127.0.0.1:15434/app_test",
        "DB_DSN": "postgresql+psycopg://app:app@127.0.0.1:15434/app_test",
        "WORKER_HEARTBEAT_PATH": "/srv/agentic-pkm/tmp-test/worker_heartbeat.json",
        "WATCHER_HEARTBEAT_PATH": "/srv/agentic-pkm/tmp-test/watcher_heartbeat.json",
    }


def test_accepts_consistent_channel_config() -> None:
    result = channel_env_preflight(_consistent_test_env(), channel="test")
    assert result.ok, result.format_report()
    assert result.blocking is False
    assert result.offending_vars == ()


def test_rejects_inconsistent_channel_config() -> None:
    """The named Verify target for #1997 F2.

    An env that mixes the six prior symptoms must be refused, and every
    offending variable must be named (no silent fallback).
    """
    bad_env = {
        # PKM_ENVIRONMENT says test, but the rest of the env is wrong:
        "PKM_ENVIRONMENT": "test",
        # relative vault root → CWD-relative divergence
        "VAULT_ROOT": "vault-test",
        # VAULT_ROOT_TEST disagrees with VAULT_ROOT
        "VAULT_ROOT_TEST": "/srv/other/vault-test",
        # outbox left ambient (unset) → CWD-relative default
        # (INDEX_OUTBOX_PATH intentionally absent)
        # in-container DSN reached from the host + prod DB name
        "DATABASE_URL": "postgresql+psycopg://app:app@db:5432/app",
        # heartbeat in tmp/ not tmp-test/
        "WORKER_HEARTBEAT_PATH": "/srv/agentic-pkm/tmp/worker_heartbeat.json",
    }

    result = channel_env_preflight(bad_env, channel="test", context="host")

    assert result.blocking is True
    assert not result.ok
    offending = set(result.offending_vars)
    # Each symptom's variable is named explicitly.
    assert "VAULT_ROOT" in offending
    assert "VAULT_ROOT_TEST" in offending
    assert "INDEX_OUTBOX_PATH" in offending
    assert "DATABASE_URL" in offending
    assert "WORKER_HEARTBEAT_PATH" in offending
    # The report is actionable and names the canonical bring-up.
    report = result.format_report()
    assert "Refusing to run" in report
    assert "bootstrap_test_channel.sh" in report


def test_unset_channel_is_blocking_not_ambient() -> None:
    """An unset channel must fail loud, never assume a default."""
    result = channel_env_preflight({}, channel=None)
    assert result.blocking is True
    assert "PKM_ENVIRONMENT" in result.offending_vars


def test_prod_channel_is_refused_by_this_harness() -> None:
    """This harness only bootstraps the test channel — never the operator vault."""
    result = channel_env_preflight({"PKM_ENVIRONMENT": "prod"}, channel=None)
    assert result.blocking is True
    assert "PKM_ENVIRONMENT" in result.offending_vars


def test_relative_index_outbox_is_rejected() -> None:
    env = _consistent_test_env()
    env["INDEX_OUTBOX_PATH"] = "tmp-test/index-outbox.jsonl"  # relative
    result = channel_env_preflight(env, channel="test")
    assert "INDEX_OUTBOX_PATH" in result.offending_vars


def test_index_outbox_in_plain_tmp_is_rejected() -> None:
    env = _consistent_test_env()
    env["INDEX_OUTBOX_PATH"] = "/srv/agentic-pkm/tmp/index-outbox.jsonl"  # tmp/ not tmp-test/
    result = channel_env_preflight(env, channel="test")
    assert "INDEX_OUTBOX_PATH" in result.offending_vars


def test_in_container_dsn_is_host_unreachable() -> None:
    env = _consistent_test_env()
    env["DATABASE_URL"] = "postgresql+psycopg://app:app@db:5432/app_test"
    env["DB_DSN"] = env["DATABASE_URL"]
    result = channel_env_preflight(env, channel="test", context="host")
    assert "DATABASE_URL" in result.offending_vars


def test_in_container_dsn_is_fine_in_container_context() -> None:
    env = _consistent_test_env()
    env["DATABASE_URL"] = "postgresql+psycopg://app:app@db:5432/app_test"
    env["DB_DSN"] = env["DATABASE_URL"]
    result = channel_env_preflight(env, channel="test", context="container")
    assert result.ok, result.format_report()


def test_prod_db_name_rejected_for_test_channel() -> None:
    env = _consistent_test_env()
    env["DATABASE_URL"] = "postgresql+psycopg://app:app@127.0.0.1:15434/app"
    env["DB_DSN"] = env["DATABASE_URL"]
    result = channel_env_preflight(env, channel="test")
    assert "DATABASE_URL" in result.offending_vars


def test_channel_derived_from_env_when_not_explicit() -> None:
    env = _consistent_test_env()
    result = channel_env_preflight(env)  # no explicit channel
    assert result.channel == "test"
    assert result.ok, result.format_report()


def test_raise_if_blocking_names_vars() -> None:
    result = channel_env_preflight({"PKM_ENVIRONMENT": "test"}, channel="test")
    assert result.blocking
    with pytest.raises(ChannelPreflightError) as exc:
        raise_if_blocking(result)
    # The raised message carries the actionable report.
    assert "VAULT_ROOT" in str(exc.value)


def test_raise_if_blocking_passthrough_when_ok() -> None:
    result = channel_env_preflight(_consistent_test_env(), channel="test")
    assert raise_if_blocking(result) is result
