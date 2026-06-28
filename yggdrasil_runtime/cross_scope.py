"""CrossScopeFlow evaluation — cross-scope use is governed, never a similarity outcome.

``evaluate(source_scope, target_scope, operation, flow)`` returns a decision. A cross-scope operation
is **denied** unless an explicit typed CrossScopeFlow grants that exact operation; absence of a flow
is a denial. When allowed, the material crosses as the most conservative evidence role the flow
permits (never over-granting standing). Similarity is never permission.
"""

from __future__ import annotations

from dataclasses import dataclass

# Conservative -> permissive ordering of evidence roles (semantic-dimensions.md).
_EVIDENCE_ORDER = ["non_evidence", "inspiration", "analogy", "reference", "background", "evidence"]


@dataclass(frozen=True)
class CrossScopeDecision:
    allowed: bool
    source_scope: str
    target_scope: str
    operation: str
    evidence_role_in_target: str | None = None
    reason: str = ""


def evaluate(source_scope: str, target_scope: str, operation: str, flow=None) -> CrossScopeDecision:
    """Decide whether ``operation`` may move material from ``source_scope`` into ``target_scope``."""
    # Same-scope use is not a cross-scope operation; there is no boundary to gate.
    if source_scope == target_scope:
        return CrossScopeDecision(
            allowed=True, source_scope=source_scope, target_scope=target_scope,
            operation=operation, reason="same-scope (no cross-scope boundary)",
        )
    # No flow -> denied. Similarity/relevance is not permission.
    if not flow:
        return CrossScopeDecision(
            allowed=False, source_scope=source_scope, target_scope=target_scope,
            operation=operation, reason="no CrossScopeFlow; similarity is not permission",
        )
    allowed_ops = flow.get("allowed_operations", [])
    denied_ops = flow.get("denied_operations", [])
    if operation in denied_ops or operation not in allowed_ops:
        return CrossScopeDecision(
            allowed=False, source_scope=source_scope, target_scope=target_scope,
            operation=operation, reason=f"operation {operation!r} not granted by this flow",
        )
    roles = [r for r in flow.get("evidence_roles_allowed", []) if r in _EVIDENCE_ORDER]
    # Cross as the most conservative role the flow permits (never over-grant standing).
    role_in_target = min(roles, key=_EVIDENCE_ORDER.index) if roles else None
    return CrossScopeDecision(
        allowed=True, source_scope=source_scope, target_scope=target_scope,
        operation=operation, evidence_role_in_target=role_in_target,
        reason="admitted by an explicit CrossScopeFlow",
    )
