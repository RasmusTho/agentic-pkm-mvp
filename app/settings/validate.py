from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.components.settings.prompts_loader import load_prompts
from app.components.settings.standards_loader import load_standards_registry
from app.components.settings.tools_loader import load_tools
from app.components.settings.agents_loader import load_agents
from app.components.settings.graphs_loader import load_graphs
from app.components.settings.models_loader import load_models


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    ref: Optional[str] = None


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
    for gid, g in graphs.items():
        if g.agent_id not in agent_ids:
            issues.append(
                ValidationIssue(
                    code="graphs.unknown_agent",
                    message=f"Graph {gid} references unknown agent_id: {g.agent_id}",
                    ref=f"graph:{gid}",
                )
            )

    return issues


def issues_to_json(issues: List[ValidationIssue]) -> Dict[str, Any]:
    return {
        "ok": len(issues) == 0,
        "issues": [{"code": i.code, "message": i.message, "ref": i.ref} for i in issues],
    }
