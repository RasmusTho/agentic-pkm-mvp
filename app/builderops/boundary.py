"""Controlled BuilderOps Vault boundary for API and tool callers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from app.builderops.config import load_paths
from app.builderops.models import BuilderOpsValidationError
from app.builderops.schema import SCHEMA_VERSION
from app.builderops.store import SqliteBuilderOpsStore

BUILDEROPS_MCP_TOOL_PREFIX = "mcp.builderops."

AUTONOMOUS_AGENT_SAFE_OPERATIONS = frozenset({
    "health",
    "list_records",
    "read_record",
    "create_agent_worklog",
    "create_learning_signal",
    "create_promotion_intent",
    "append_receipt",
})

REQUIRES_HUMAN_GOVERNANCE_REVIEW = frozenset({
    "execute_promotion",
    "mutate_repo_authority",
    "mutate_github_authority",
    "mutate_product_runtime_truth",
    "publish_projection_as_truth",
})

BUILDEROPS_MCP_TOOL_NAMES = frozenset({
    f"{BUILDEROPS_MCP_TOOL_PREFIX}list_records",
    f"{BUILDEROPS_MCP_TOOL_PREFIX}read_record",
    f"{BUILDEROPS_MCP_TOOL_PREFIX}create_worklog",
    f"{BUILDEROPS_MCP_TOOL_PREFIX}create_learning_signal",
    f"{BUILDEROPS_MCP_TOOL_PREFIX}create_promotion_intent",
    f"{BUILDEROPS_MCP_TOOL_PREFIX}append_receipt",
})


class BuilderOpsBoundary:
    """Narrow API/tool facade over the BuilderOps store.

    This boundary intentionally delegates persistence and validation to
    SqliteBuilderOpsStore. It does not execute promotions or mutate any
    repo/GitHub/product authority surface.
    """

    def __init__(self, store: SqliteBuilderOpsStore) -> None:
        self._store = store
        self._store.initialize()

    @classmethod
    def from_path(cls, db_path: Path | str | None = None) -> "BuilderOpsBoundary":
        if db_path is None:
            paths = load_paths()
            paths.ensure()
            resolved = paths.db_path
        else:
            resolved = Path(db_path)
        return cls(SqliteBuilderOpsStore(resolved))

    @classmethod
    def from_settings(
        cls,
        settings: Mapping[str, Any] | None = None,
    ) -> "BuilderOpsBoundary":
        configured = None
        if settings is not None:
            configured = settings.get("builderops_db_path")
        return cls.from_path(str(configured) if configured else None)

    @property
    def db_path(self) -> Path:
        return self._store.db_path

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "schema_version": SCHEMA_VERSION,
            "db_path": str(self._store.db_path),
            "autonomous_agent_safe_operations": sorted(AUTONOMOUS_AGENT_SAFE_OPERATIONS),
            "requires_human_governance_review": sorted(REQUIRES_HUMAN_GOVERNANCE_REVIEW),
        }

    def list_records(self, object_type: str | None = None) -> list[dict[str, Any]]:
        return self._store.list_records(object_type)

    def read_record(self, record_id: str) -> dict[str, Any]:
        record = self._store.get_record(record_id)
        if record is None:
            raise BuilderOpsValidationError(f"BuilderOps record not found: {record_id}")
        return record

    def create_agent_worklog(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._store.create_agent_worklog(**dict(payload))

    def create_learning_signal(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._store.create_learning_signal(**dict(payload))

    def create_promotion_intent(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._store.create_promotion_intent(**dict(payload))

    def append_receipt(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._store.append_receipt(**dict(payload))


def is_builderops_mcp_tool(tool_name: str) -> bool:
    return tool_name in BUILDEROPS_MCP_TOOL_NAMES


def execute_builderops_mcp_tool(
    *,
    tool_name: str,
    tool_args: Mapping[str, Any] | None,
    settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    boundary = BuilderOpsBoundary.from_settings(settings)
    args = dict(tool_args or {})

    if tool_name == f"{BUILDEROPS_MCP_TOOL_PREFIX}list_records":
        return {
            "status": "ok",
            "records": boundary.list_records(args.get("object_type")),
        }
    if tool_name == f"{BUILDEROPS_MCP_TOOL_PREFIX}read_record":
        return {"status": "ok", "record": boundary.read_record(str(args["record_id"]))}
    if tool_name == f"{BUILDEROPS_MCP_TOOL_PREFIX}create_worklog":
        return {"status": "ok", "record": boundary.create_agent_worklog(args)}
    if tool_name == f"{BUILDEROPS_MCP_TOOL_PREFIX}create_learning_signal":
        return {"status": "ok", "record": boundary.create_learning_signal(args)}
    if tool_name == f"{BUILDEROPS_MCP_TOOL_PREFIX}create_promotion_intent":
        return {"status": "ok", "record": boundary.create_promotion_intent(args)}
    if tool_name == f"{BUILDEROPS_MCP_TOOL_PREFIX}append_receipt":
        return {"status": "ok", "record": boundary.append_receipt(args)}

    raise BuilderOpsValidationError(f"unsupported BuilderOps MCP tool: {tool_name}")


__all__ = [
    "AUTONOMOUS_AGENT_SAFE_OPERATIONS",
    "BUILDEROPS_MCP_TOOL_NAMES",
    "BUILDEROPS_MCP_TOOL_PREFIX",
    "BuilderOpsBoundary",
    "REQUIRES_HUMAN_GOVERNANCE_REVIEW",
    "execute_builderops_mcp_tool",
    "is_builderops_mcp_tool",
]
