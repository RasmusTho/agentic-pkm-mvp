"""Parent epic delivery ledger rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


LEDGER_START = "<!-- builderops:epic-delivery-ledger v1"
LEDGER_END = "<!-- /builderops:epic-delivery-ledger -->"


class EpicDeliveryLedgerError(ValueError):
    """Raised when epic delivery ledger input is invalid."""


@dataclass(frozen=True)
class LedgerChild:
    issue_number: int
    title: str
    issue_status: str
    pr_number: int | None
    pr_status: str
    head_sha: str | None
    merge_sha: str | None
    ci_state: str
    blocker: str
    next_action: str


def build_parent_epic_delivery_ledger(
    *,
    epic_issue_number: int,
    children: Sequence[Mapping[str, Any]],
    live_truth: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Render a compact parent epic ledger from coordination inputs.

    The returned ledger is coordination evidence only. Optional live truth is
    read-only comparison input; conflicts are emitted as warnings and never
    silently overwrite the supplied coordination entries.
    """

    epic = _positive_int(epic_issue_number, "epic_issue_number")
    normalized_children = [_normalize_child(child) for child in children]
    warnings = _conflict_warnings(normalized_children, live_truth or {})
    markdown = _render_markdown(epic, normalized_children, warnings)
    return {
        "epic_issue_number": epic,
        "authority": "coordination_evidence_only_live_github_issues_prs_ci_win",
        "child_count": len(normalized_children),
        "warnings": warnings,
        "markdown": markdown,
        "children": [_child_payload(child) for child in normalized_children],
    }


def _normalize_child(child: Mapping[str, Any]) -> LedgerChild:
    issue_number = _positive_int(
        child.get("issue_number", child.get("child_issue", child.get("number"))),
        "child.issue_number",
    )
    pr_number = child.get("pr_number")
    if pr_number in ("", None):
        normalized_pr = None
    else:
        normalized_pr = _positive_int(pr_number, "child.pr_number")
    return LedgerChild(
        issue_number=issue_number,
        title=_text(child.get("title"), default=f"#{issue_number}"),
        issue_status=_text(child.get("issue_status", child.get("status")), default="unknown"),
        pr_number=normalized_pr,
        pr_status=_text(child.get("pr_status"), default="none"),
        head_sha=_optional_text(child.get("head_sha")),
        merge_sha=_optional_text(child.get("merge_sha")),
        ci_state=_text(child.get("ci_state"), default="unknown"),
        blocker=_text(child.get("blocker"), default="none"),
        next_action=_text(child.get("next_action"), default="read live GitHub truth"),
    )


def _conflict_warnings(
    children: Sequence[LedgerChild],
    live_truth: Mapping[str, Any],
) -> list[dict[str, Any]]:
    live_children = live_truth.get("children", live_truth)
    if not isinstance(live_children, Mapping):
        raise EpicDeliveryLedgerError("live_truth children must be an object keyed by issue number")
    warnings: list[dict[str, Any]] = []
    for child in children:
        live = live_children.get(str(child.issue_number), live_children.get(child.issue_number))
        if live is None:
            continue
        if not isinstance(live, Mapping):
            raise EpicDeliveryLedgerError("live_truth child entries must be objects")
        _compare_field(warnings, child, live, "issue_status")
        _compare_field(warnings, child, live, "pr_status")
        _compare_field(warnings, child, live, "head_sha")
        _compare_field(warnings, child, live, "merge_sha")
        _compare_field(warnings, child, live, "ci_state")
    return warnings


def _compare_field(
    warnings: list[dict[str, Any]],
    child: LedgerChild,
    live: Mapping[str, Any],
    field: str,
) -> None:
    live_value = live.get(field)
    if live_value in (None, ""):
        return
    ledger_value = getattr(child, field)
    if str(live_value) != str(ledger_value):
        warnings.append({
            "issue_number": child.issue_number,
            "field": field,
            "ledger_value": ledger_value,
            "live_value": live_value,
            "warning": "live_truth_conflict",
        })


def _render_markdown(
    epic_issue_number: int,
    children: Sequence[LedgerChild],
    warnings: Sequence[Mapping[str, Any]],
) -> str:
    lines = [
        f"{LEDGER_START} epic=#{epic_issue_number} -->",
        "Ledger authority: coordination evidence only; live GitHub Issues/PRs/CI win.",
        "",
        "| Child | Issue | PR | SHA | CI | Blocker | Next |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for child in children:
        child_ref = f"#{child.issue_number} {child.title}".strip()
        pr = f"#{child.pr_number} {child.pr_status}" if child.pr_number else child.pr_status
        sha = _sha_cell(child)
        lines.append(
            "| "
            + " | ".join([
                _escape_table(child_ref),
                _escape_table(child.issue_status),
                _escape_table(pr),
                _escape_table(sha),
                _escape_table(child.ci_state),
                _escape_table(child.blocker),
                _escape_table(child.next_action),
            ])
            + " |"
        )
    if warnings:
        lines.extend(["", "Warnings:"])
        for warning in warnings:
            lines.append(
                "- live_truth_conflict: "
                f"#{warning['issue_number']} {warning['field']} "
                f"ledger={warning['ledger_value']} live={warning['live_value']}"
            )
    lines.append(LEDGER_END)
    return "\n".join(lines) + "\n"


def _child_payload(child: LedgerChild) -> dict[str, Any]:
    return {
        "issue_number": child.issue_number,
        "title": child.title,
        "issue_status": child.issue_status,
        "pr_number": child.pr_number,
        "pr_status": child.pr_status,
        "head_sha": child.head_sha,
        "merge_sha": child.merge_sha,
        "ci_state": child.ci_state,
        "blocker": child.blocker,
        "next_action": child.next_action,
    }


def _sha_cell(child: LedgerChild) -> str:
    parts = []
    if child.head_sha:
        parts.append(f"head `{child.head_sha}`")
    if child.merge_sha:
        parts.append(f"merge `{child.merge_sha}`")
    return "<br>".join(parts) if parts else "none"


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EpicDeliveryLedgerError(f"{field} must be a positive integer")
    return value


def _text(value: Any, *, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


__all__ = ["EpicDeliveryLedgerError", "build_parent_epic_delivery_ledger"]
