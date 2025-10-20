from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.agent.interestingness import InterestingnessResult
from app.config.agent import AgentConfig


class MemoryAgentRepository:
    def __init__(self) -> None:
        self.runs: dict[UUID, dict[str, Any]] = {}
        self.tasks: dict[UUID, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.memories: dict[UUID, dict[str, Any]] = {}
        self.interesting_items: dict[UUID, dict[str, Any]] = {}
        self.feature_flags: dict[str, dict[str, Any]] = {}
        self._last_heartbeat: dict[str, Any] | None = None

    def record_run_start(self, run_id: UUID, config: AgentConfig) -> None:
        self.runs[run_id] = {
            "status": "running",
            "config": config.model_dump(mode="json"),
            "plan_summary": "",
            "result_summary": "",
            "started_at": datetime.now(tz=timezone.utc),
        }

    def record_run_complete(
        self,
        run_id: UUID,
        status: str,
        plan_summary: str,
        result_summary: str,
    ) -> None:
        run = self.runs.setdefault(run_id, {})
        run.update(
            {
                "status": status,
                "plan_summary": plan_summary,
                "result_summary": result_summary,
                "completed_at": datetime.now(tz=timezone.utc),
            }
        )

    def register_task(self, run_id: UUID, kind: str, payload: dict[str, Any]) -> UUID:
        task_id = uuid4()
        self.tasks[task_id] = {
            "run_id": run_id,
            "kind": kind,
            "payload": payload,
            "status": "pending",
        }
        return task_id

    def complete_task(self, task_id: UUID, status: str, result: dict[str, Any] | None) -> None:
        task = self.tasks.setdefault(task_id, {})
        task.update(
            {
                "status": status,
                "result": result or {},
                "completed_at": datetime.now(tz=timezone.utc),
            }
        )

    def log_event(
        self,
        run_id: UUID,
        kind: str,
        payload: dict[str, Any],
        task_id: UUID | None,
    ) -> None:
        self.events.append(
            {
                "run_id": run_id,
                "kind": kind,
                "payload": payload,
                "task_id": task_id,
                "ts": datetime.now(tz=timezone.utc),
            }
        )

    def add_memory(
        self,
        run_id: UUID | None,
        layer: str,
        payload: dict[str, Any],
        provenance: dict[str, Any],
    ) -> UUID:
        memory_id = uuid4()
        self.memories[memory_id] = {
            "run_id": run_id,
            "layer": layer,
            "payload": payload,
            "provenance": provenance,
        }
        return memory_id

    def record_heartbeat(self, agent_name: str, run_id: UUID | None, status: str) -> None:
        self._last_heartbeat = {
            "agent_name": agent_name,
            "run_id": run_id,
            "status": status,
            "last_seen": datetime.now(tz=timezone.utc),
        }

    def upsert_interesting_item(self, run_id: UUID, item: InterestingnessResult) -> None:
        self.interesting_items[item.object_id] = {
            "object_id": item.object_id,
            "run_id": run_id,
            "novelty": item.novelty,
            "anomaly": item.anomaly,
            "uncertainty": item.uncertainty,
            "value": item.value,
            "score": item.score,
            "reason": item.reason,
            "payload": item.payload,
            "created_at": datetime.now(tz=timezone.utc),
        }

    def fetch_top_interesting(
        self,
        limit: int,
        *,
        system_intent: str | None = None,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        items = sorted(
            self.interesting_items.values(),
            key=lambda row: (row["score"], row["created_at"]),
            reverse=True,
        )
        if system_intent:
            items = [item for item in items if item.get("payload", {}).get("system_intent") == system_intent]
        if tag:
            items = [
                item
                for item in items
                if tag in {t for t in item.get("payload", {}).get("emergent_tags", [])}
            ]
        return items[:limit]

    def get_last_heartbeat(self) -> dict[str, Any] | None:
        return self._last_heartbeat

    def set_feature_flag(self, key: str, value: dict[str, Any], scope: str | None = None) -> None:
        record = dict(value)
        if scope:
            record["_scope"] = scope
        self.feature_flags[key] = record

    def get_feature_flag(self, key: str) -> dict[str, Any] | None:
        return self.feature_flags.get(key)

    def close(self) -> None:
        return

    def interesting_summary(self) -> dict[str, Any]:
        intent_counts: dict[str, int] = {}
        tag_counts: dict[str, int] = {}
        for item in self.interesting_items.values():
            payload = item.get("payload", {})
            intent = payload.get("system_intent", "unknown")
            intent_counts[intent] = intent_counts.get(intent, 0) + 1
            for tag in payload.get("emergent_tags", []):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        return {
            "total": len(self.interesting_items),
            "system_intent": intent_counts,
            "emergent_tags": tag_counts,
        }
