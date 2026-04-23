from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agents.panel_agent.wiring import (
    DEFAULT_PANEL_ACTION_WIRING_PATH,
    WiringConfigError,
    _load_yaml as load_wiring_yaml,
    _parse_wiring as parse_wiring,
)
from app.components.settings.prompts_loader import load_prompts
from app.components.settings.standards_loader import load_standards_registry
from app.components.settings.tools_loader import load_tools
from app.components.settings.agents_loader import load_agents
from app.components.settings.graphs_loader import load_graphs
from app.components.settings.models_loader import load_models
from app.components.settings.events_loader import load_events
from app.components.settings.panel_actions_loader import DEFAULT_PANEL_ACTIONS_PATH
from app.index.ingest_md import parse_markdown
from app.settings.panel_actions import resolve_panel_actions_root
from app.settings.panel_actions_settings import load_panel_actions_settings, panel_action_ids
from app.settings.watcher_settings import _settings_file, _read_frontmatter, invalid_allowed_actions, load_watcher_settings


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    ref: Optional[str] = None


_ACTION_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_MEASUREMENT_ONLY_ACTIONS = {"ingest.summary.create"}


def _panel_action_catalog_paths() -> list[Path]:
    for key in ("PANEL_ACTIONS_PATH", "PANEL_ACTIONS_FILE"):
        value = os.getenv(key)
        if value:
            return [Path(value).expanduser()]
    resolved = resolve_panel_actions_root()
    if resolved is None:
        return [DEFAULT_PANEL_ACTIONS_PATH] if DEFAULT_PANEL_ACTIONS_PATH.exists() else []
    if resolved.is_file():
        return [resolved]
    if resolved.is_dir():
        return sorted(path for path in resolved.glob("*.md") if path.is_file())
    return []


def _validate_panel_action_entries() -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for path in _panel_action_catalog_paths():
        try:
            frontmatter, _ = parse_markdown(path)
        except Exception as exc:
            issues.append(
                ValidationIssue(
                    code="panel_actions.invalid",
                    message=f"{path}: failed to load panel action catalog: {exc}",
                    ref="panel_actions",
                )
            )
            continue
        mappings = frontmatter.get("mappings")
        if not isinstance(mappings, list):
            continue
        for idx, raw in enumerate(mappings, start=1):
            if not isinstance(raw, dict):
                issues.append(
                    ValidationIssue(
                        code="panel_actions.missing_required_fields",
                        message=f"{path}: mappings[{idx}] must be a mapping with required fields (id, intent_type, downstream_event)",
                        ref="panel_actions",
                    )
                )
                continue
            action_id = str(raw.get("id") or "").strip()
            intent_type = str(raw.get("intent_type") or raw.get("intent") or "").strip()
            downstream_event = str(raw.get("downstream_event") or raw.get("event_type") or "").strip()
            if not action_id or not intent_type or not downstream_event:
                issues.append(
                    ValidationIssue(
                        code="panel_actions.missing_required_fields",
                        message=f"{path}: mappings[{idx}] is missing required fields (id, intent_type, downstream_event)",
                        ref="panel_actions",
                    )
                )
                continue
            if not _ACTION_ID_PATTERN.match(action_id):
                issues.append(
                    ValidationIssue(
                        code="panel_actions.invalid_action_id",
                        message=f"{path}: action id '{action_id}' at mappings[{idx}] must match {_ACTION_ID_PATTERN.pattern}",
                        ref="panel_actions",
                    )
                )
    return issues


def _validate_watcher_auto_run_shape() -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    path = _settings_file()
    try:
        data = _read_frontmatter(path)
    except Exception as exc:
        return [ValidationIssue(code="watcher_settings.invalid", message=str(exc), ref="watcher_settings")]
    auto_run = data.get("auto_run")
    if auto_run is None:
        return issues
    if not isinstance(auto_run, dict):
        return [
            ValidationIssue(
                code="watcher_settings.malformed_auto_run",
                message=f"{path}: auto_run must be a mapping",
                ref="watcher_settings:auto_run",
            )
        ]
    if "auto_exec_default" in auto_run and not isinstance(auto_run.get("auto_exec_default"), bool):
        issues.append(
            ValidationIssue(
                code="watcher_settings.malformed_auto_run",
                message=f"{path}: auto_run.auto_exec_default must be a boolean",
                ref="watcher_settings:auto_run",
            )
        )
    if "auto_exec_env" in auto_run:
        env_key = auto_run.get("auto_exec_env")
        if not isinstance(env_key, str) or not env_key.strip():
            issues.append(
                ValidationIssue(
                    code="watcher_settings.malformed_auto_run",
                    message=f"{path}: auto_run.auto_exec_env must be a non-empty string",
                    ref="watcher_settings:auto_run",
                )
            )
    if "allowed_actions" in auto_run:
        allowed_actions = auto_run.get("allowed_actions")
        if not isinstance(allowed_actions, list):
            issues.append(
                ValidationIssue(
                    code="watcher_settings.malformed_auto_run",
                    message=f"{path}: auto_run.allowed_actions must be a list of action ids",
                    ref="watcher_settings:auto_run",
                )
            )
        else:
            for idx, action in enumerate(allowed_actions, start=1):
                if not isinstance(action, str) or not action.strip():
                    issues.append(
                        ValidationIssue(
                            code="watcher_settings.malformed_auto_run",
                            message=f"{path}: auto_run.allowed_actions[{idx}] must be a non-empty string",
                            ref="watcher_settings:auto_run",
                        )
                    )
                elif action.strip() in _MEASUREMENT_ONLY_ACTIONS:
                    issues.append(
                        ValidationIssue(
                            code="watcher_settings.measurement_mode_required",
                            message=(
                                f"{path}: auto_run.allowed_actions[{idx}]={action!r} is measurement-only; "
                                "enable WATCHER_MEASUREMENT_MODE=1 during sync-latency harness runs instead"
                            ),
                            ref="watcher_settings:auto_run",
                        )
                    )
    return issues


def _validate_panel_action_wiring() -> list[ValidationIssue]:
    candidate = Path(os.getenv("PANEL_ACTION_WIRING_PATH") or DEFAULT_PANEL_ACTION_WIRING_PATH)
    try:
        data = load_wiring_yaml(candidate)
        parse_wiring(data, candidate)
        return []
    except WiringConfigError as exc:
        return [ValidationIssue(code="panel_wiring.invalid", message=str(exc), ref="panel_wiring")]


def validate_settings() -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    try:
        prompts = load_prompts()
    except Exception as exc:  # pragma: no cover - fatal load
        return [ValidationIssue(code="prompts.load_failed", message=str(exc))]

    try:
        _ = load_standards_registry()
    except Exception as exc:
        issues.append(ValidationIssue(code="standards.load_failed", message=str(exc)))

    try:
        tools = load_tools()
    except Exception as exc:
        issues.append(ValidationIssue(code="tools.load_failed", message=str(exc)))
        tools = {}

    try:
        agents = load_agents()
    except Exception as exc:
        issues.append(ValidationIssue(code="agents.load_failed", message=str(exc)))
        agents = {}

    try:
        graphs = load_graphs()
    except Exception as exc:
        issues.append(ValidationIssue(code="graphs.load_failed", message=str(exc)))
        graphs = {}

    try:
        models = load_models()
    except Exception as exc:
        issues.append(ValidationIssue(code="models.load_failed", message=str(exc)))
        models = {}

    try:
        events = load_events()
    except Exception as exc:
        issues.append(ValidationIssue(code="events.load_failed", message=str(exc)))
        events = {}

    model_ids = set(models.keys())
    for pid, p in prompts.items():
        for mid in p.allowed_models:
            if mid not in model_ids:
                issues.append(
                    ValidationIssue(
                        code="prompts.unknown_model",
                        message=f"Prompt {pid} references unknown model id: {mid}",
                        ref=f"prompt:{pid}",
                    )
                )
        if p.inputs_schema and not Path(p.inputs_schema).exists():
            issues.append(
                ValidationIssue(
                    code="prompts.missing_inputs_schema",
                    message=f"Prompt {pid} inputs_schema missing: {p.inputs_schema}",
                    ref=f"prompt:{pid}",
                )
            )
        if p.outputs_schema and not Path(p.outputs_schema).exists():
            issues.append(
                ValidationIssue(
                    code="prompts.missing_outputs_schema",
                    message=f"Prompt {pid} outputs_schema missing: {p.outputs_schema}",
                    ref=f"prompt:{pid}",
                )
            )

    tool_ids = set(tools.keys())
    for aid, a in agents.items():
        for tid in a.allowed_tools:
            if tid not in tool_ids:
                issues.append(
                    ValidationIssue(
                        code="agents.unknown_tool",
                        message=f"Agent {aid} references unknown tool id: {tid}",
                        ref=f"agent:{aid}",
                    )
                )
        for ref in a.settings_refs:
            if not Path(ref).exists():
                issues.append(
                    ValidationIssue(
                        code="agents.missing_settings_ref",
                        message=f"Agent {aid} references missing settings ref: {ref}",
                        ref=f"agent:{aid}",
                    )
                )

    agent_ids = set(agents.keys())
    event_ids = set(events.keys())
    for gid, g in graphs.items():
        if g.agent_id not in agent_ids:
            issues.append(
                ValidationIssue(
                    code="graphs.unknown_agent",
                    message=f"Graph {gid} references unknown agent_id: {g.agent_id}",
                    ref=f"graph:{gid}",
                )
            )
        for ev in g.input_events + g.output_events:
            if ev not in event_ids:
                issues.append(
                    ValidationIssue(
                        code="graphs.unknown_event",
                        message=f"Graph {gid} references unknown event id: {ev}",
                        ref=f"graph:{gid}",
                    )
                )

    panel_actions_settings = None
    try:
        panel_actions_settings = load_panel_actions_settings()
    except Exception as exc:
        issues.append(ValidationIssue(code="panel_actions.invalid", message=str(exc), ref="panel_actions"))
    issues.extend(_validate_panel_action_entries())

    issues.extend(_validate_panel_action_wiring())

    watcher_settings = None
    try:
        watcher_settings = load_watcher_settings()
    except Exception as exc:
        issues.append(ValidationIssue(code="watcher_settings.invalid", message=str(exc), ref="watcher_settings"))
    issues.extend(_validate_watcher_auto_run_shape())
    if panel_actions_settings and watcher_settings:
        invalid_actions = invalid_allowed_actions(watcher_settings, panel_action_ids(panel_actions_settings))
        if invalid_actions:
            issues.append(
                ValidationIssue(
                    code="watcher_settings.unknown_action",
                    message=f"watcher settings reference unknown actions: {invalid_actions}",
                    ref="watcher_settings:auto_run",
                )
            )
    return issues


def issues_to_json(issues: List[ValidationIssue]) -> Dict[str, Any]:
    return {
        "ok": len(issues) == 0,
        "issues": [{"code": i.code, "message": i.message, "ref": i.ref} for i in issues],
    }
