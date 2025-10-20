from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from app.config.agent import AgentConfig

from .interestingness import InterestingnessResult


class AgentRepository(Protocol):
    def record_run_start(self, run_id: UUID, config: AgentConfig) -> None: ...

    def record_run_complete(
        self,
        run_id: UUID,
        status: str,
        plan_summary: str,
        result_summary: str,
    ) -> None: ...

    def register_task(self, run_id: UUID, kind: str, payload: dict[str, Any]) -> UUID: ...

    def complete_task(self, task_id: UUID, status: str, result: dict[str, Any] | None) -> None: ...

    def log_event(
        self,
        run_id: UUID,
        kind: str,
        payload: dict[str, Any],
        task_id: UUID | None,
    ) -> None: ...

    def add_memory(
        self,
        run_id: UUID | None,
        layer: str,
        payload: dict[str, Any],
        provenance: dict[str, Any],
    ) -> UUID: ...

    def record_heartbeat(self, agent_name: str, run_id: UUID | None, status: str) -> None: ...

    def upsert_interesting_item(self, run_id: UUID, item: InterestingnessResult) -> None: ...

    def fetch_top_interesting(
        self,
        limit: int,
        *,
        system_intent: str | None = None,
        tag: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_last_heartbeat(self) -> dict[str, Any] | None: ...

    def set_feature_flag(self, key: str, value: dict[str, Any], scope: str | None = None) -> None: ...

    def get_feature_flag(self, key: str) -> dict[str, Any] | None: ...

    def interesting_summary(self) -> dict[str, Any]: ...

    def close(self) -> None: ...


class PostgresAgentRepository:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def record_run_start(self, run_id: UUID, config: AgentConfig) -> None:
        payload = json.dumps(config.model_dump(mode="json"))
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_runs (id, status, config)
                    VALUES (%s, %s, %s::jsonb)
                    """,
                    (str(run_id), "running", payload),
                )

    def record_run_complete(
        self,
        run_id: UUID,
        status: str,
        plan_summary: str,
        result_summary: str,
    ) -> None:
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agent_runs
                    SET status = %s,
                        plan_summary = %s,
                        result_summary = %s,
                        completed_at = now()
                    WHERE id = %s
                    """,
                    (status, plan_summary, result_summary, str(run_id)),
                )

    def register_task(self, run_id: UUID, kind: str, payload: dict[str, Any]) -> UUID:
        task_id = uuid4()
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_tasks (id, run_id, kind, payload)
                    VALUES (%s, %s, %s, %s::jsonb)
                    """,
                    (str(task_id), str(run_id), kind, json.dumps(payload)),
                )
        return task_id

    def complete_task(self, task_id: UUID, status: str, result: dict[str, Any] | None) -> None:
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agent_tasks
                    SET status = %s,
                        result = %s::jsonb,
                        completed_at = now()
                    WHERE id = %s
                    """,
                    (status, json.dumps(result or {}), str(task_id)),
                )

    def log_event(
        self,
        run_id: UUID,
        kind: str,
        payload: dict[str, Any],
        task_id: UUID | None,
    ) -> None:
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_events (run_id, task_id, kind, payload)
                    VALUES (%s, %s, %s, %s::jsonb)
                    """,
                    (str(run_id), str(task_id) if task_id else None, kind, json.dumps(payload)),
                )

    def add_memory(
        self,
        run_id: UUID | None,
        layer: str,
        payload: dict[str, Any],
        provenance: dict[str, Any],
    ) -> UUID:
        memory_id = uuid4()
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_memories (id, run_id, layer, payload, provenance)
                    VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
                    """,
                    (
                        str(memory_id),
                        str(run_id) if run_id else None,
                        layer,
                        json.dumps(payload),
                        json.dumps(provenance),
                    ),
                )
        return memory_id

    def record_heartbeat(self, agent_name: str, run_id: UUID | None, status: str) -> None:
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_heartbeats (agent_name, run_id, status, last_seen)
                    VALUES (%s, %s, %s, now())
                    ON CONFLICT (agent_name)
                    DO UPDATE SET
                      run_id = EXCLUDED.run_id,
                      status = EXCLUDED.status,
                      last_seen = EXCLUDED.last_seen
                    """,
                    (agent_name, str(run_id) if run_id else None, status),
                )

    def upsert_interesting_item(self, run_id: UUID, item: InterestingnessResult) -> None:
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO interesting_items (
                      object_id,
                      run_id,
                      novelty,
                      anomaly,
                      uncertainty,
                      value,
                      score,
                      reason,
                      payload,
                      created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
                    ON CONFLICT (object_id) DO UPDATE SET
                      run_id = EXCLUDED.run_id,
                      novelty = EXCLUDED.novelty,
                      anomaly = EXCLUDED.anomaly,
                      uncertainty = EXCLUDED.uncertainty,
                      value = EXCLUDED.value,
                      score = EXCLUDED.score,
                      reason = EXCLUDED.reason,
                      payload = EXCLUDED.payload,
                      created_at = EXCLUDED.created_at
                    """,
                    (
                        str(item.object_id),
                        str(run_id),
                        item.novelty,
                        item.anomaly,
                        item.uncertainty,
                        item.value,
                        item.score,
                        item.reason,
                        json.dumps(item.payload),
                    ),
                )

    def fetch_top_interesting(
        self,
        limit: int,
        *,
        system_intent: str | None = None,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        params: list[Any] = []
        if system_intent:
            filters.append("payload ->> 'system_intent' = %s")
            params.append(system_intent)
        if tag:
            filters.append(
                "EXISTS (SELECT 1 FROM jsonb_array_elements_text(payload -> 'emergent_tags') AS t WHERE t = %s)"
            )
            params.append(tag)

        where_clause = ""
        if filters:
            where_clause = "WHERE " + " AND ".join(filters)

        query = f"""
            SELECT
              object_id,
              run_id,
              novelty,
              anomaly,
              uncertainty,
              value,
              score,
              reason,
              payload,
              created_at
            FROM interesting_items
            {where_clause}
            ORDER BY score DESC, created_at DESC
            LIMIT %s
        """
        params.append(limit)
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            cur = conn.execute(query, params)
            rows = cur.fetchall()
        for row in rows:
            if isinstance(row.get("created_at"), datetime):
                row["created_at"] = row["created_at"].astimezone(timezone.utc)
        return rows

    def get_last_heartbeat(self) -> dict[str, Any] | None:
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            cur = conn.execute(
                """
                SELECT agent_name, run_id, status, last_seen
                FROM agent_heartbeats
                ORDER BY last_seen DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
        if row and isinstance(row.get("last_seen"), datetime):
            row["last_seen"] = row["last_seen"].astimezone(timezone.utc)
        return row

    def set_feature_flag(self, key: str, value: dict[str, Any], scope: str | None = None) -> None:
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO feature_flags (key, value, scope)
                VALUES (%s, %s::jsonb, %s)
                ON CONFLICT (key) DO UPDATE SET
                  value = EXCLUDED.value,
                  scope = EXCLUDED.scope
                """,
                (key, json.dumps(value), scope),
            )

    def get_feature_flag(self, key: str) -> dict[str, Any] | None:
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            cur = conn.execute(
                "SELECT value FROM feature_flags WHERE key = %s",
                (key,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return row["value"]

    def interesting_summary(self) -> dict[str, Any]:
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            intent_rows = conn.execute(
                """
                SELECT payload ->> 'system_intent' AS intent, COUNT(*)::bigint
                FROM interesting_items
                GROUP BY intent
                """
            ).fetchall()
            tag_rows = conn.execute(
                """
                SELECT tag, COUNT(*)::bigint
                FROM (
                  SELECT jsonb_array_elements_text(payload -> 'emergent_tags') AS tag
                  FROM interesting_items
                ) AS tags
                GROUP BY tag
                """
            ).fetchall()
            total = conn.execute("SELECT COUNT(*)::bigint FROM interesting_items").scalar_one()

        return {
            "total": int(total or 0),
            "system_intent": {row["intent"] or "unknown": int(row["count"]) for row in intent_rows},
            "emergent_tags": {row["tag"] or "": int(row["count"]) for row in tag_rows if row["tag"]},
        }
