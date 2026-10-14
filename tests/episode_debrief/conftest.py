"""Finite fixtures on an explicitly selected disposable PostgreSQL target."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.episode_debrief.trigger import run_debrief_tick
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.write_guard import WriteGuard
from scripts.yaml_roundtrip import dump_frontmatter


@pytest.fixture
def debrief_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import psycopg
    from psycopg.conninfo import make_conninfo

    # The global PG guard validates the explicit admin target before collection.
    # Each test owns a fresh database, never truncating the configured database.
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
    if not dsn:
        pytest.skip("Episode Debrief production-path proof requires an explicit disposable PG target")
    database = "test_episode_debrief_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{database}"')
    selected = make_conninfo(dsn, dbname=database)
    monkeypatch.setenv("DATABASE_URL", selected)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "0")
    monkeypatch.delenv("INSTANCE_VAULT_REGISTRY_PATH", raising=False)
    monkeypatch.delenv("INSTANCE_OWNERSHIP_ROOT", raising=False)
    with psycopg.connect(selected) as conn:
        conn.execute("""
            CREATE TABLE episode_engine_state (
                vault_binding_id text NOT NULL, key text NOT NULL, value jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (vault_binding_id, key));
            CREATE TABLE episodes (
                vault_binding_id text NOT NULL, episode_id text NOT NULL, scope text NOT NULL,
                note_path text NOT NULL, closed boolean NOT NULL, PRIMARY KEY (vault_binding_id, episode_id));
            CREATE TABLE episode_artifact_binding (
                vault_binding_id text NOT NULL, artifact_ref text NOT NULL, episode_id text NOT NULL,
                binding_state text NOT NULL, PRIMARY KEY (vault_binding_id, artifact_ref, episode_id));
            CREATE TABLE outbox (
                id uuid PRIMARY KEY, topic text NOT NULL, payload jsonb NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now(), delivered_at timestamptz,
                attempts integer NOT NULL DEFAULT 0, vault_binding_id text NOT NULL, legacy_key text);
        """)
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
        debrief_ref: list[str] | None = None,
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
        path.write_text(dump_frontmatter(fields, "Human content stays unchanged.\n"), encoding="utf-8")
        self.execute("INSERT INTO episodes VALUES (%s, %s, %s, %s, %s)",
                     (binding, episode_id, scope, relative, closed))
        for index in range(count):
            self.execute("INSERT INTO episode_artifact_binding VALUES (%s, %s, %s, 'active')",
                         (binding, f"artifact-{index}", episode_id))
        return episode_id

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
