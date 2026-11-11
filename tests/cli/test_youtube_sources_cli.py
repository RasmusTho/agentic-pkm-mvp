"""``youtube-sources list`` through the production CLI entrypoint (#6611, YSS-10)."""

from __future__ import annotations

import json
import socket
import uuid

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.knowledge_acquisition import source_registry as registry_module
from app.knowledge_acquisition.source_registry import SourceRegistry, reset_memory_source_registry

pytestmark = pytest.mark.not_pg

_SECRET = "sk-planted-SENTINEL-7f3a9c"
_EXPECTED_KEYS = {
    "binding_id",
    "kind",
    "title",
    "enabled",
    "interval_seconds",
    "policy",
    "last_success_at",
    "last_error",
}


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_memory_source_registry()
    yield SourceRegistry.for_runtime()
    reset_memory_source_registry()


def _invoke(*args: str):
    return CliRunner().invoke(cli, ["youtube-sources", "list", *args])


def _seed(registry: SourceRegistry) -> dict[str, str]:
    account = str(uuid.uuid4())
    inbox = registry.register(
        collection_kind="inbox_playlist",
        collection_ref="PLfixtureInbox",
        title="Fixture Inbox",
        account_binding_id=account,
        provenance={"origin": "user_pick", "detail": {"token": _SECRET}},
    )
    registry.set_inbox(account, inbox.binding_id)
    registry.record_poll_success(inbox.binding_id, cursor={"page_token": _SECRET})
    feed = registry.register(
        collection_kind="subscription_feed",
        collection_ref="UCfixtureChannel0000000000",
        title="Fixture Feed",
        poll_interval_seconds=7200,
        acquisition_policy={"mode": "candidate_metadata_only"},
    )
    registry.record_poll_failure(
        feed.binding_id, reason_code="network_error", detail={"raw": f"Bearer {_SECRET}"}
    )
    return {"account": account, "inbox": inbox.binding_id, "feed": feed.binding_id}


def test_list_projects_registry_and_empty_state(registry: SourceRegistry) -> None:
    empty = _invoke("--json")
    assert empty.exit_code == 0, empty.output
    assert json.loads(empty.output) == []
    assert _invoke().exit_code == 0

    ids = _seed(registry)
    result = _invoke("--json")
    assert result.exit_code == 0, result.output
    rows = {row["binding_id"]: row for row in json.loads(result.output)}
    assert set(rows) == {ids["inbox"], ids["feed"]}
    for row in rows.values():
        assert set(row) == _EXPECTED_KEYS

    stored_inbox = registry.get(ids["inbox"])
    assert stored_inbox is not None
    assert rows[ids["inbox"]] == {
        "binding_id": ids["inbox"],
        "kind": "inbox_playlist",
        "title": "Fixture Inbox",
        "enabled": True,
        "interval_seconds": 180,
        "policy": "acquire_transcript",
        "last_success_at": stored_inbox.last_success_at,
        "last_error": None,
    }
    assert stored_inbox.last_success_at is not None

    feed = rows[ids["feed"]]
    stored_feed = registry.get(ids["feed"])
    assert stored_feed is not None and stored_feed.last_error is not None
    assert feed["kind"] == "subscription_feed"
    assert feed["enabled"] is True
    assert feed["interval_seconds"] == 7200
    assert feed["policy"] == "candidate_metadata_only"
    assert feed["last_success_at"] is None
    assert feed["last_error"] == {"reason_code": "network_error", "at": stored_feed.last_error["at"]}

    human = _invoke()
    assert human.exit_code == 0, human.output
    assert ids["inbox"] in human.output and ids["feed"] in human.output
    assert "Fixture Inbox" in human.output and "last_error=network_error" in human.output


def test_list_is_read_only_and_fails_safely(
    registry: SourceRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(registry)
    before = registry.list_all()

    def _no_write(*_args, **_kwargs):
        raise AssertionError("youtube-sources list must not mutate the registry")

    def _no_network(*_args, **_kwargs):
        raise AssertionError("youtube-sources list must not call a provider")

    for name in (
        "register",
        "set_inbox",
        "select_inbox_if_absent_or_same",
        "rename",
        "update_acquisition_policy",
        "record_poll_success",
        "record_poll_failure",
        "record_source_degradation",
        "disable_source_for_auth",
    ):
        monkeypatch.setattr(SourceRegistry, name, _no_write)
    with monkeypatch.context() as net:
        net.setattr(socket.socket, "connect", _no_network)
        net.setattr(socket, "create_connection", _no_network)
        for args in (("--json",), ()):
            result = _invoke(*args)
            assert result.exit_code == 0, result.output
    assert registry.list_all() == before

    # A listing backend failure exits nonzero with a fixed reason code only.
    def _list_fails(self):
        raise RuntimeError(f"connection to postgresql://u:{_SECRET}@db failed")

    monkeypatch.setattr(SourceRegistry, "list_all", _list_fails)
    for args, expected in (
        (("--json",), '{"error": {"reason_code": "source_registry_unavailable"}}'),
        ((), "youtube-sources list failed: reason_code=source_registry_unavailable"),
    ):
        failed = CliRunner(mix_stderr=False).invoke(cli, ["youtube-sources", "list", *args])
        assert failed.exit_code == 1
        assert failed.stdout == ""
        assert failed.stderr.strip() == expected

    # The real backend resolution path: configured but unreachable Postgres.
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("DATABASE_URL", f"postgresql://operator:{_SECRET}@127.0.0.1:1/app")
    unreachable = CliRunner(mix_stderr=False).invoke(cli, ["youtube-sources", "list", "--json"])
    assert unreachable.exit_code == 1
    assert json.loads(unreachable.stderr) == {"error": {"reason_code": "source_registry_unavailable"}}

    def _schema_missing(self):
        raise registry_module.SourceRegistrySchemaMissingError(f"missing table ({_SECRET})")

    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setattr(SourceRegistry, "list_all", _schema_missing)
    missing = CliRunner(mix_stderr=False).invoke(cli, ["youtube-sources", "list", "--json"])
    assert missing.exit_code == 1
    assert json.loads(missing.stderr) == {"error": {"reason_code": "source_registry_schema_missing"}}


def test_list_output_does_not_expose_secrets(
    registry: SourceRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _seed(registry)
    # A stored reason code that is not a plain token is withheld, not echoed.
    registry.record_poll_failure(ids["inbox"], reason_code=f"auth {_SECRET}", detail=_SECRET)
    stored = registry.list_all()
    hidden_values = {ids["account"]}
    for binding in stored:
        hidden_values.add(binding.collection_ref)

    outputs = []
    for args in (("--json",), ()):
        result = CliRunner(mix_stderr=False).invoke(cli, ["youtube-sources", "list", *args])
        assert result.exit_code == 0, result.output
        outputs.append(result.stdout + result.stderr)
    rows = {row["binding_id"]: row for row in json.loads(outputs[0])}
    assert rows[ids["inbox"]]["last_error"]["reason_code"] is None
    assert rows[ids["feed"]]["last_error"]["reason_code"] == "network_error"

    def _fails(self):
        raise RuntimeError(f"password={_SECRET}")

    monkeypatch.setattr(SourceRegistry, "list_all", _fails)
    for args in (("--json",), ()):
        failed = CliRunner(mix_stderr=False).invoke(cli, ["youtube-sources", "list", *args])
        assert failed.exit_code == 1
        outputs.append(failed.stdout + failed.stderr)

    for text in outputs:
        assert _SECRET not in text
        assert "Bearer" not in text and "page_token" not in text and "provenance" not in text
        for value in hidden_values:
            assert value not in text
