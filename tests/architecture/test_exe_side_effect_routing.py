"""Architecture rail for CAO/agent side-effect routing through EXE.

This test promotes the SBS fitness rule "No direct tool side effects from CAO
without GOV/EXE" from manual review to a CI-visible check. It is intentionally a
bounded detection rail, not broad runtime enforcement: current transitional
agent-side effects are inventoried in the allowlist below, and new direct
side-effect call sites under ``app/agents/**`` must either route through the
EXE ``ExecutionRequest`` boundary or be added here with a narrow reason.
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_ROOT = REPO_ROOT / "app" / "agents"

SIDE_EFFECT_FUNCTION_NAMES = frozenset(
    {
        "_worker_run_once",
        "append_jsonl_outbox_event",
        "audit_event",
        "emit",
        "execute_panel_intent",
        "plan_panel_actions",
        "write_companion",
        "write_note_from_absolute",
        "write_outbox_event",
    }
)
SIDE_EFFECT_METHOD_NAMES = frozenset(
    {
        "mkdir",
        "remove",
        "rename",
        "replace",
        "rmdir",
        "save_object",
        "unlink",
        "write_bytes",
        "write_text",
    }
)
SIDE_EFFECT_EXACT_CALLS = frozenset({"store.save"})


@dataclass(frozen=True, order=True)
class SideEffectCall:
    path: str
    qualname: str
    call: str

    def format(self) -> str:
        return f"{self.path}::{self.qualname} -> {self.call}"


@dataclass(frozen=True)
class AllowedSideEffect:
    count: int
    reason: str


@dataclass(frozen=True)
class ObservedSideEffect:
    call: SideEffectCall
    line_number: int


# Transitional inventory for direct CAO/agent side-effect call sites.
#
# Keep this allowlist narrow: keys are file + owning function/class + call
# identity, and ``count`` must match the number of occurrences. If a legacy call
# moves behind ExecutionRequest/EXE, shrink the allowlist in the same PR. If a
# new direct side-effect call appears, this test fails until the call is either
# routed through EXE or deliberately documented here.
ALLOWED_DIRECT_SIDE_EFFECTS: dict[SideEffectCall, AllowedSideEffect] = {
    SideEffectCall("app/agents/base/audit.py", "_cache_and_maybe_persist", "path.parent.mkdir"): AllowedSideEffect(
        1,
        "Legacy optional AUDIT_LOG_PATH file sink for local audit visibility.",
    ),
    SideEffectCall("app/agents/base/audit.py", "_cache_and_maybe_persist", "path.open"): AllowedSideEffect(
        1,
        "Legacy optional AUDIT_LOG_PATH append sink for local audit visibility.",
    ),
    SideEffectCall("app/agents/base/audit.py", "audit_log", "audit_event"): AllowedSideEffect(
        1,
        "Legacy agent audit service call; not an autonomous external tool execution.",
    ),
    SideEffectCall("app/agents/chunker/agent.py", "chunk_object", "audit_event"): AllowedSideEffect(
        1,
        "Legacy pipeline audit hook for chunking.",
    ),
    SideEffectCall("app/agents/normalizer/agent.py", "normalize_file", "audit_event"): AllowedSideEffect(
        1,
        "Legacy pipeline audit hook for normalization.",
    ),
    SideEffectCall("app/agents/normalizer/agent.py", "run", "store.save_object"): AllowedSideEffect(
        1,
        "Legacy normalizer object-store write path; D6 CI rail contains growth only.",
    ),
    SideEffectCall("app/agents/note_hygiene/fs.py", "archive_path", "pathlib.Path().mkdir"): AllowedSideEffect(
        1,
        "Legacy note-hygiene archive directory creation helper.",
    ),
    SideEffectCall("app/agents/note_hygiene/agent.py", "classify_and_act", "emit"): AllowedSideEffect(
        3,
        "Legacy note-hygiene cleanup event emission.",
    ),
    SideEffectCall(
        "app/agents/note_hygiene/agent.py",
        "_write",
        "write_note_from_absolute",
    ): AllowedSideEffect(
        1,
        "Legacy note-hygiene vault-note write wrapper.",
    ),
    SideEffectCall("app/agents/panel/writeback.py", "upsert_executed_ids", "store.save_object"): AllowedSideEffect(
        1,
        "Legacy panel idempotency marker write shared by panel runtime paths.",
    ),
    SideEffectCall(
        "app/agents/panel_agent/agent.py",
        "run_panel_intent_for_note",
        "append_jsonl_outbox_event",
    ): AllowedSideEffect(
        1,
        "Legacy panel-agent JSONL outbox emission.",
    ),
    SideEffectCall(
        "app/agents/panel_agent/execution.py",
        "refresh_panel_note_object",
        "store.save_object",
    ): AllowedSideEffect(
        1,
        "Legacy panel execution object refresh write.",
    ),
    SideEffectCall(
        "app/agents/panel_agent/execution.py",
        "run_panel_note_execution",
        "write_outbox_event",
    ): AllowedSideEffect(
        1,
        "Legacy panel execution DB outbox enqueue.",
    ),
    SideEffectCall(
        "app/agents/panel_agent/execution.py",
        "run_panel_note_execution",
        "execute_panel_intent",
    ): AllowedSideEffect(
        1,
        "Legacy panel execution envelope; broad ExecutionRequest retrofit is out of scope.",
    ),
    SideEffectCall("app/agents/panel_agent/planning.py", "plan_panel_actions", "store.save"): AllowedSideEffect(
        1,
        "Legacy panel planner store write for generated action plans.",
    ),
    SideEffectCall(
        "app/agents/panel_agent/runtime.py",
        "_persist_log",
        "store.save_object",
    ): AllowedSideEffect(
        1,
        "Legacy panel runtime log persistence.",
    ),
    SideEffectCall(
        "app/agents/panel_agent/runtime.py",
        "_write_db_outbox_events",
        "write_outbox_event",
    ): AllowedSideEffect(
        1,
        "Legacy panel runtime DB outbox enqueue.",
    ),
    SideEffectCall(
        "app/agents/panel_agent/runtime.py",
        "execute_panel_intent",
        "append_jsonl_outbox_event",
    ): AllowedSideEffect(
        1,
        "Legacy panel runtime JSONL outbox emission.",
    ),
    SideEffectCall(
        "app/agents/panel_agent/runtime.py",
        "execute_panel_intent",
        "plan_panel_actions",
    ): AllowedSideEffect(
        1,
        "Legacy panel runtime planner handoff for action plans.",
    ),
    SideEffectCall(
        "app/agents/panel_agent/runtime.py",
        "_apply_note_writeback",
        "note_file.write_text",
    ): AllowedSideEffect(
        1,
        "Legacy panel note writeback for checkbox removal and receipts.",
    ),
    SideEffectCall(
        "app/agents/panel_agent/runtime.py",
        "_refresh_companion_hash",
        "write_companion",
    ): AllowedSideEffect(
        1,
        "Legacy companion metadata refresh after panel note writeback.",
    ),
    SideEffectCall(
        "app/agents/pilot_agent/runtime.py",
        "run_promotion_agent",
        "append_jsonl_outbox_event",
    ): AllowedSideEffect(
        2,
        "Legacy pilot-agent success/error JSONL outbox emissions.",
    ),
    SideEffectCall(
        "app/agents/pilot_agent/runtime.py",
        "_deterministic_promotion_fallback",
        "append_jsonl_outbox_event",
    ): AllowedSideEffect(
        1,
        "Legacy pilot-agent fallback JSONL outbox emission.",
    ),
    SideEffectCall("app/agents/planner/agent.py", "PlannerAgent.save_plan", "self.store.save_object"): AllowedSideEffect(
        1,
        "Legacy planner object-store write.",
    ),
    SideEffectCall(
        "app/agents/planner/graph.py",
        "PlannerGraph._run_primitive_action",
        "self.store.save_object",
    ): AllowedSideEffect(
        1,
        "Legacy planner primitive-action object-store write.",
    ),
    SideEffectCall("app/agents/projector/agent.py", "project_object", "audit_event"): AllowedSideEffect(
        1,
        "Legacy pipeline audit hook for projection.",
    ),
    SideEffectCall("app/agents/promotion/agent.py", "_append_jsonl", "path.parent.mkdir"): AllowedSideEffect(
        1,
        "Legacy promotion-agent JSONL log directory creation.",
    ),
    SideEffectCall("app/agents/promotion/agent.py", "_append_jsonl", "path.open"): AllowedSideEffect(
        1,
        "Legacy promotion-agent JSONL log append sink.",
    ),
    SideEffectCall("app/agents/promotion/agent.py", "PromotionAgent.act", "_worker_run_once"): AllowedSideEffect(
        1,
        "Legacy promotion-agent worker handoff.",
    ),
    SideEffectCall("app/agents/reviewer/agent.py", "review", "audit_event"): AllowedSideEffect(
        1,
        "Legacy pipeline audit hook for review.",
    ),
    SideEffectCall("app/agents/set_evaluator/agent.py", "evaluate_object", "audit_event"): AllowedSideEffect(
        1,
        "Legacy pipeline audit hook for set evaluation.",
    ),
}


def test_no_direct_tool_side_effects_from_cao() -> None:
    """CAO/agent direct side-effect call sites stay inventoried and contained.

    Source: ``docs/architecture/SBS_FITNESS_RULES.md`` P0 rule
    "No direct tool side effects from CAO without GOV/EXE" and transition debt
    D6. This read-only scan covers ``app/agents/**``. It allows only the
    documented transitional inventory above; new direct side-effect call sites
    must route through EXE/ExecutionRequest or be deliberately reviewed here.
    """
    observed = list(_scan_agent_side_effect_calls())
    actual = Counter(hit.call for hit in observed)
    expected = Counter(
        {call: allowed.count for call, allowed in ALLOWED_DIRECT_SIDE_EFFECTS.items()}
    )

    unexpected = actual - expected
    missing = expected - actual

    assert not unexpected and not missing, (
        "CAO/agent direct side-effect calls must stay behind EXE/ExecutionRequest "
        "or in the explicit transitional allowlist. "
        f"Unexpected: {_format_unexpected(unexpected, observed)}. "
        f"Missing/stale allowlist entries: {_format_missing(missing)}."
    )

    undocumented = [
        call.format()
        for call, allowed in ALLOWED_DIRECT_SIDE_EFFECTS.items()
        if not allowed.reason.strip()
    ]
    assert not undocumented, "Allowlisted side-effect calls need a reason: " + "; ".join(
        sorted(undocumented)
    )


def _scan_agent_side_effect_calls() -> Iterable[ObservedSideEffect]:
    for path in sorted(AGENTS_ROOT.rglob("*.py")):
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents = _parent_map(module)
        relative_path = str(path.relative_to(REPO_ROOT))
        for node in ast.walk(module):
            if not isinstance(node, ast.Call):
                continue
            if not _is_direct_side_effect_call(node):
                continue
            yield ObservedSideEffect(
                call=SideEffectCall(
                    path=relative_path,
                    qualname=_qualname(node, parents),
                    call=_dotted_name(node.func),
                ),
                line_number=node.lineno,
            )


def _parent_map(module: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(module):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _is_direct_side_effect_call(node: ast.Call) -> bool:
    call_name = _call_name(node.func)
    call = _dotted_name(node.func)
    if call in SIDE_EFFECT_EXACT_CALLS:
        return True
    if call_name in SIDE_EFFECT_FUNCTION_NAMES:
        return True
    if call_name in SIDE_EFFECT_METHOD_NAMES:
        return True
    return _is_write_mode_open_call(node)


def _is_write_mode_open_call(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "open":
        return False
    if not node.args:
        return False
    mode_arg = node.args[0]
    if not isinstance(mode_arg, ast.Constant) or not isinstance(mode_arg.value, str):
        return False
    return any(marker in mode_arg.value for marker in ("w", "a", "x", "+"))


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        base = _dotted_name(node.func)
        return f"{base}()" if base else ""
    return ""


def _qualname(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    parts: list[str] = []
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            parts.append(current.name)
    return ".".join(reversed(parts)) or "<module>"


def _format_unexpected(
    unexpected: Counter[SideEffectCall],
    observed: Iterable[ObservedSideEffect],
) -> str:
    if not unexpected:
        return "none"
    lines_by_call: dict[SideEffectCall, list[int]] = defaultdict(list)
    for hit in observed:
        if hit.call in unexpected:
            lines_by_call[hit.call].append(hit.line_number)
    return "; ".join(
        f"{call.format()} count={unexpected[call]} lines={lines_by_call[call]}"
        for call in sorted(unexpected)
    )


def _format_missing(missing: Counter[SideEffectCall]) -> str:
    if not missing:
        return "none"
    return "; ".join(
        f"{call.format()} count={count}"
        for call, count in sorted(missing.items(), key=lambda item: item[0])
    )
