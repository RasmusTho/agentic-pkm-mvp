"""Finite fixtures on an explicitly selected disposable PostgreSQL target."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

from app.episode_debrief.trigger import run_debrief_tick
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.write_guard import WriteGuard
from scripts.yaml_roundtrip import dump_frontmatter

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def debrief_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import psycopg

    # The global PG guard validates the explicit admin target before collection.
    # Each test owns a fresh database, never truncating the configured database.
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
    if not dsn:
        pytest.skip("Episode Debrief production-path proof requires an explicit disposable PG target")
    database = "test_episode_debrief_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{database}"')
    # Alembic needs URL form; keep the explicit target's host, port and options.
    selected = urlunsplit(urlsplit(dsn)._replace(path="/" + database))
    monkeypatch.setenv("DATABASE_URL", selected)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "0")
    monkeypatch.delenv("INSTANCE_VAULT_REGISTRY_PATH", raising=False)
    monkeypatch.delenv("INSTANCE_OWNERSHIP_ROOT", raising=False)
    # The production schema is migration-owned: run `alembic upgrade head`
    # rather than hand-written tables, so the proof exercises the real columns.
    from alembic import command
    from alembic.config import Config

    with psycopg.connect(selected, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.upgrade(config, "head")
    fixture = DebriefDB(selected, tmp_path)
    try:
        yield fixture
    finally:
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')


class DebriefDB:
    def __init__(self, dsn: str, root: Path) -> None:
        self.dsn = dsn
        self.root = root

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        import psycopg
        with psycopg.connect(self.dsn) as conn:
            cursor = conn.execute(sql, params)
            return cursor.fetchall() if cursor.description else []

    def episode(
        self, *, count: int = 3, scope: str = "work", closed: bool = True,
        binding: str = COMPATIBILITY_BINDING_ID, episode_id: str | None = None,
        debrief_ref: list[str] | None = None, extra_fields: dict[str, Any] | None = None,
    ) -> str:
        episode_id = episode_id or "ep-" + str(uuid4())
        relative = f"episodes/{episode_id}.md"
        if binding != COMPATIBILITY_BINDING_ID:
            relative = f"foreign-bindings/{binding}/{relative}"
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        fields: dict[str, Any] = {
            "episode_id": episode_id, "scope": scope, "title": "Finite fixture",
            "time": {"start": "2026-10-13T08:00:00Z", "closed": closed},
            "segmentation": "proposed",
        }
        if debrief_ref is not None:
            fields["debrief_ref"] = debrief_ref
        fields.update(extra_fields or {})
        path.write_text(dump_frontmatter(fields, "Human content stays unchanged.\n"), encoding="utf-8")
        self.execute("INSERT INTO episodes (vault_binding_id, episode_id, scope, title, time_start, "
                     "closed, segmentation, note_path) VALUES (%s, %s, %s, 'Finite fixture', "
                     "'2026-10-13T08:00:00Z', %s, 'proposed', %s)",
                     (binding, episode_id, scope, closed, relative))
        self.bind(episode_id, count=count, scope=scope, binding=binding)
        return episode_id

    def bind(
        self, episode_id: str, *, count: int, scope: str = "work",
        binding: str = COMPATIBILITY_BINDING_ID, prefix: str = "artifact",
    ) -> None:
        for index in range(count):
            self.execute("INSERT INTO episode_artifact_binding (vault_binding_id, artifact_ref, episode_id, "
                         "scope, basis, confidence, binding_state, rule) "
                         "VALUES (%s, %s, %s, %s, 'time_overlap', 1.0, 'active', 'fixture')",
                         (binding, f"{prefix}-{index}", episode_id, scope))

    def closure(
        self, episode_id: str, *, scope: str = "work", malformed: bool = False,
        ordinal: int = 1, binding: str = COMPATIBILITY_BINDING_ID,
    ) -> str:
        from psycopg.types.json import Jsonb
        row_id = str(uuid4())
        payload = {"payload": {"episode_id": episode_id, "scope": scope, "closed_at": "2026-10-13T09:00:00Z",
                               "bound_artifact_count": "NaN" if malformed else 3}}
        self.execute("INSERT INTO outbox (id, topic, payload, created_at, vault_binding_id) "
                     "VALUES (%s, 'episode.closed', %s, '2026-10-13T09:00:00Z'::timestamptz "
                     "+ %s * interval '1 second', %s)",
                     (row_id, Jsonb(payload), ordinal, binding))
        return row_id

    def triggers(self) -> list[dict[str, Any]]:
        return [row[0] for row in self.execute(
            "SELECT payload->'payload' FROM outbox WHERE topic='debrief.trigger.created' ORDER BY id")]

    def tick(self, **kwargs: Any) -> dict[str, Any]:
        return run_debrief_tick(vault_root=self.root,
                               write_guard=WriteGuard(lambda: {"state": "healthy"}), **kwargs)
