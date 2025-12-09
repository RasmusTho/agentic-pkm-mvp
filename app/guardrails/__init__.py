from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional


GuardrailStatus = Literal["allow", "modify", "block", "fail"]


@dataclass
class GuardrailDecision:
    status: GuardrailStatus
    modified_args: Optional[dict[str, Any]] = None
    modified_result: Optional[Any] = None
    reasons: list[str] = field(default_factory=list)


def run_pre_guardrails(tool_name: str, args: dict, state: Any) -> GuardrailDecision:
    # Phase 1 stub: always allow.
    return GuardrailDecision(status="allow", modified_args=None, modified_result=None, reasons=[])


def run_post_guardrails(tool_name: str, args: dict, result: Any, state: Any) -> GuardrailDecision:
    # Phase 1 stub: always allow.
    return GuardrailDecision(status="allow", modified_args=None, modified_result=None, reasons=[])


__all__ = [
    "GuardrailDecision",
    "GuardrailStatus",
    "run_pre_guardrails",
    "run_post_guardrails",
]
