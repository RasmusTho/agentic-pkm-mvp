"""``youtube-sources list`` through the production CLI entrypoint (#6611, YSS-10)."""

from __future__ import annotations

import csv
import json
import socket
import uuid
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.cli.youtube_sources import KNOWN_LAST_ERROR_REASON_CODES
from app.knowledge_acquisition import source_registry as registry_module
from app.knowledge_acquisition.playlist_discovery import SAFE_REASON_CODES
from app.knowledge_acquisition.source_registry import SourceRegistry, reset_memory_source_registry
from app.knowledge_acquisition.youtube_onboarding import import_takeout_registry

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
    # The registry stores any non-empty reason code; only known codes are
    # projected, so a token-shaped planted value is withheld, not echoed.
    snake_secret = "secret_token_123"
    registry.record_poll_failure(ids["inbox"], reason_code=snake_secret, detail=_SECRET)
    assert registry.get(ids["inbox"]).last_error["reason_code"] == snake_secret
    assert SAFE_REASON_CODES <= KNOWN_LAST_ERROR_REASON_CODES
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
        assert _SECRET not in text and snake_secret not in text
        assert "Bearer" not in text and "page_token" not in text and "provenance" not in text
        for value in hidden_values:
            assert value not in text


class _RecordingCursor:
    def __init__(self, statements: list[str], table_present: bool) -> None:
        self._statements = statements
        self._table_present = table_present
        self._last = ""

    def execute(self, sql: str, params: object = None) -> None:
        del params
        self._last = sql
        self._statements.append(sql)

    def fetchone(self):
        if "to_regclass" in self._last:
            return ("oid",) if self._table_present else (None,)
        return None

    def fetchall(self):
        return []


class _RecordingConnection:
    def __init__(self, statements: list[str], table_present: bool) -> None:
        self._statements = statements
        self._table_present = table_present

    def cursor(self, *args, **kwargs):
        del args, kwargs
        return _RecordingCursor(self._statements, self._table_present)

    def close(self) -> None:
        pass


def test_list_never_bootstraps_pg_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt-in schema autocreate must not turn a read-only listing into DDL."""

    statements: list[str] = []
    table = {"present": False}
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    monkeypatch.setattr(registry_module, "_resolve_backend", lambda: "pg")
    monkeypatch.setattr(
        registry_module, "_pg_connect", lambda: _RecordingConnection(statements, table["present"])
    )

    # Schema absent: the listing refuses safely instead of creating it.
    missing = CliRunner(mix_stderr=False).invoke(cli, ["youtube-sources", "list", "--json"])
    assert missing.exit_code == 1
    assert json.loads(missing.stderr) == {"error": {"reason_code": "source_registry_schema_missing"}}

    # Schema present: the listing reads it.
    table["present"] = True
    for args in (("--json",), ()):
        result = _invoke(*args)
        assert result.exit_code == 0, result.output
    assert any("FROM acquisition_source_registry" in sql for sql in statements)
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements), statements

    # Control: the read-write constructor does run DDL here (the fake keeps
    # reporting the table absent, so its post-create assertion then refuses).
    statements.clear()
    table["present"] = False
    with pytest.raises(registry_module.SourceRegistrySchemaMissingError):
        SourceRegistry.for_runtime()
    assert any(sql.lstrip().upper().startswith("CREATE") for sql in statements)


def test_list_suppresses_takeout_id_fallback_titles(
    registry: SourceRegistry, tmp_path: Path
) -> None:
    channel_id = "UCuntitledFixture0000001"
    playlist_id = "PLuntitledFixtureList"
    root = tmp_path / "Takeout"
    root.mkdir()
    with (root / "subscriptions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Channel ID", "Channel Title", "Channel URL"])
        writer.writerow([channel_id, "", f"https://www.youtube.com/channel/{channel_id}"])
    with (root / "playlists.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Playlist ID", "Playlist Title"])
        writer.writerow([playlist_id, ""])
    import_takeout_registry(root, registry=registry, account_binding_id=str(uuid.uuid4()))
    stored = registry.list_all()
    assert {binding.title for binding in stored} == {channel_id, playlist_id}

    result = CliRunner(mix_stderr=False).invoke(cli, ["youtube-sources", "list", "--json"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)
    assert len(rows) == 2 and all(row["title"] is None for row in rows)

    human = CliRunner(mix_stderr=False).invoke(cli, ["youtube-sources", "list"])
    assert human.exit_code == 0, human.output
    assert human.stdout.count("(untitled)") == 2
    for text in (result.stdout + result.stderr, human.stdout + human.stderr):
        assert channel_id not in text and playlist_id not in text


def test_list_withholds_titles_containing_listed_identifiers(registry: SourceRegistry) -> None:
    """Only listed literal refs/account ids withhold a title; ordinary titles stay."""

    account = str(uuid.uuid4())
    own_ref = "PLembeddedRefFixture01"
    withheld_titles = {
        "own ref in prose": f"Playlist {own_ref}",
        "own ref in URL": f"https://www.youtube.com/playlist?list={own_ref}",
        "account id": f"Inbox for {account}",
        "account id uppercase": f"Inbox {account.upper()}",
    }
    # Not a listed identifier, so shown as stored: the filter is bounded to
    # known literal values and is not a URL/id-shape or secret detector.
    kept_titles = {
        "plain": "Mimer Inbox",
        "unicode": "Föreläsningar 2026 – AI & lärande",
        "caps": "PLAYLIST OF THE YEAR",
        "short code": "Lecture series PL-101",
        "unlisted URL": "https://example.com/playlist",
        "unlisted channel-shaped id": "Mirror of UCforeignChannelFixture001",
        "unlisted token-like text": "notes ghp_9fK2xQ7LmZ3vB8nR4tY6wP1sD0cE5a",
        "unlisted uuid": f"Batch {uuid.uuid4()}",
        "control chars": "Inbox\x1b[2Jcleared",
    }
    ids: dict[str, str] = {}
    for index, (label, title) in enumerate((*withheld_titles.items(), *kept_titles.items())):
        binding = registry.register(
            collection_kind="owned_playlist",
            collection_ref=own_ref if index == 0 else f"PLtitleFixtureRef{index:04d}",
            title=title,
            account_binding_id=account,
        )
        ids[label] = binding.binding_id
    assert registry.get(ids["own ref in prose"]).collection_ref == own_ref
    # A short ref (Liked videos is ``LL``) matches case-sensitively.
    liked = registry.register(
        collection_kind="liked_videos", collection_ref="LL", title="LL backup", account_binding_id=account
    )
    withheld_titles["short ref"] = liked.title
    ids["short ref"] = liked.binding_id

    result = CliRunner(mix_stderr=False).invoke(cli, ["youtube-sources", "list", "--json"])
    assert result.exit_code == 0, result.output
    titles = {row["binding_id"]: row["title"] for row in json.loads(result.stdout)}
    for label in withheld_titles:
        assert titles[ids[label]] is None, label
    for label, title in kept_titles.items():
        assert titles[ids[label]] == title, label

    human = CliRunner(mix_stderr=False).invoke(cli, ["youtube-sources", "list"])
    assert human.exit_code == 0, human.output
    assert human.stdout.count("(untitled)") == len(withheld_titles)
    assert "https://example.com/playlist" in human.stdout
    # Both modes escape control characters instead of emitting them raw.
    assert "\\u001b[2Jcleared" in human.stdout
    for text in (result.stdout + result.stderr, human.stdout + human.stderr):
        assert "\x1b" not in text
        for value in (own_ref, account, account.upper()):
            assert value not in text
        for binding in registry.list_all():
            assert binding.collection_ref not in text


def test_list_withholds_titles_with_boundaryless_identifiers(registry: SourceRegistry) -> None:
    """Review finding on 71d3c146d: token-boundary matching leaked glued refs."""

    account = str(uuid.uuid4())
    channel_ref = "UCabcdefghijklmnopqrstuv"
    # Too short for the id-shape regexes: only the actual-identifier check catches it.
    short_ref = "PLshortQ7"
    other_short_ref = "PLtinyZ3"
    cases = [
        ("subscription_feed", channel_ref, None, f"mirror x{channel_ref}y"),
        ("public_playlist", short_ref, None, f"mixx{short_ref}yy"),
        ("public_playlist", "PLcaseFold5", None, "copy of xplcasefold5x"),
        ("owned_playlist", other_short_ref, account, f"see_{short_ref.upper()}_too"),
        ("owned_playlist", "PLacctGlue1", account, f"acct{account}tail"),
        ("owned_playlist", "PLacctHex22", account, f"hex{account.replace('-', '')}tail"),
    ]
    ids = []
    for kind, ref, account_id, title in cases:
        binding = registry.register(
            collection_kind=kind, collection_ref=ref, title=title, account_binding_id=account_id
        )
        ids.append(binding.binding_id)
    kept = registry.register(
        collection_kind="public_playlist",
        collection_ref="PLkeptTitle8",
        title="All music, liked and allowed",
    )

    result = CliRunner(mix_stderr=False).invoke(cli, ["youtube-sources", "list", "--json"])
    assert result.exit_code == 0, result.output
    titles = {row["binding_id"]: row["title"] for row in json.loads(result.stdout)}
    assert all(titles[binding_id] is None for binding_id in ids), titles
    assert titles[kept.binding_id] == "All music, liked and allowed"

    human = CliRunner(mix_stderr=False).invoke(cli, ["youtube-sources", "list"])
    assert human.exit_code == 0, human.output
    assert human.stdout.count("(untitled)") == len(cases)
    assert "All music, liked and allowed" in human.stdout
    hidden = {account, account.replace("-", "")}
    hidden.update(binding.collection_ref for binding in registry.list_all())
    for text in (result.stdout + result.stderr, human.stdout + human.stderr):
        folded = text.casefold()
        for value in hidden:
            assert value.casefold() not in folded, value
