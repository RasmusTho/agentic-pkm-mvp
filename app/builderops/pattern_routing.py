"""Observe-only routing for repeated learning and reevaluation patterns."""

from __future__ import annotations

from typing import Any, Mapping

from app.builderops.models import BuilderOpsValidationError, validate_source_refs

PATTERN_ROUTES = frozenset(
    {
        "transition_debt",
        "fitness_rule_candidate",
        "issue_candidate",
        "discard_supersession",
    }
)
TERMINAL_OUTCOMES_BY_ROUTE = {
    "transition_debt": "debt_or_fitness_recorded",
    "fitness_rule_candidate": "debt_or_fitness_recorded",
    "issue_candidate": "issue_created",
    "discard_supersession": "discarded_or_superseded",
}


class PatternRoutingError(BuilderOpsValidationError):
    """Raised when repeated-pattern routing input is malformed."""


def build_pattern_routing_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Classify repeated Builder System patterns without mutating repo state."""

    if not isinstance(payload, Mapping):
        raise PatternRoutingError("pattern routing payload must be an object")
    patterns = _normalize_patterns(payload.get("patterns", []))
    return {
        "observe_only": True,
        "mutations_performed": False,
        "mutation_channels": {
            "git_push": False,
            "github_issue": False,
            "github_label": False,
            "github_project": False,
            "product_runtime": False,
            "runtime_memory": False,
        },
        "routing_criteria": {
            "transition_debt": "Repeated, durable boundary/process gap with unclear or multi-step remediation.",
            "fitness_rule_candidate": "Repeated, mechanically detectable failure with clear owner and honest enforcement posture.",
            "issue_candidate": "Bounded implementation or workflow change with resolvable Verify targets.",
            "discard_supersession": "One-off, low-signal, obsolete, already-covered, or superseded pattern.",
        },
        "pattern": patterns,
        "routing_outcomes": sorted(PATTERN_ROUTES),
        "receipt_body": _receipt_body(patterns),
    }


def _normalize_patterns(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise PatternRoutingError("patterns must be a list")
    patterns: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise PatternRoutingError(f"patterns[{index}] must be an object")
        pattern_id = _required_string(item.get("id"), f"patterns[{index}].id")
        if pattern_id in seen_ids:
            raise PatternRoutingError(f"duplicate pattern id: {pattern_id}")
        seen_ids.add(pattern_id)
        route = _required_string(item.get("route"), f"patterns[{index}].route")
        if route not in PATTERN_ROUTES:
            raise PatternRoutingError(
                f"patterns[{index}].route must be one of {sorted(PATTERN_ROUTES)}"
            )
        source_refs = _validated_source_refs(
            item.get("source_refs"),
            f"patterns[{index}].source_refs",
        )
        repeat_count = item.get("repeat_count")
        if not isinstance(repeat_count, int) or isinstance(repeat_count, bool) or repeat_count < 1:
            raise PatternRoutingError(f"patterns[{index}].repeat_count must be a positive integer")
        if route != "discard_supersession" and repeat_count < 2:
            raise PatternRoutingError(
                f"patterns[{index}] requires repeat_count >= 2 unless discarded/superseded"
            )
        terminal_outcome = _required_string(
            item.get("terminal_outcome"),
            f"patterns[{index}].terminal_outcome",
        )
        expected_outcome = TERMINAL_OUTCOMES_BY_ROUTE[route]
        if terminal_outcome != expected_outcome:
            raise PatternRoutingError(
                f"patterns[{index}].terminal_outcome must be {expected_outcome!r}"
            )
        target_ref = _required_string(item.get("target_ref"), f"patterns[{index}].target_ref")
        patterns.append({
            "id": pattern_id,
            "route": route,
            "summary": _required_string(item.get("summary"), f"patterns[{index}].summary"),
            "repeat_count": repeat_count,
            "source_refs": source_refs,
            "target_ref": target_ref,
            "terminal_outcome": terminal_outcome,
            "recommendation": _required_string(
                item.get("recommendation"),
                f"patterns[{index}].recommendation",
            ),
        })
    return patterns


def _validated_source_refs(value: Any, field: str) -> list[dict[str, Any]]:
    try:
        validate_source_refs(value, field)
    except BuilderOpsValidationError as exc:
        raise PatternRoutingError(str(exc)) from exc
    if not isinstance(value, list):  # validate_source_refs guards this.
        raise PatternRoutingError(f"{field} must be a non-empty list")
    return list(value)


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PatternRoutingError(f"{field} must be a non-empty string")
    return value.strip()


def _receipt_body(patterns: list[dict[str, Any]]) -> str:
    routes = ", ".join(
        f"{item['id']}={item['route']}"
        for item in patterns
    )
    terminal_outcomes = ", ".join(
        f"{item['id']}={item['terminal_outcome']}"
        for item in patterns
    )
    return (
        "Repeated-pattern routing observe-only report: "
        f"patterns={len(patterns)}"
        + (f"; routes: {routes}; terminal_outcomes: {terminal_outcomes}." if routes else ".")
    )


__all__ = [
    "PATTERN_ROUTES",
    "PatternRoutingError",
    "build_pattern_routing_report",
]
