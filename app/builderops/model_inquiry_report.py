"""Human-readable, derived Markdown projection for model inquiry traces."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.builderops.model_inquiry_contract import (
    ModelInquiryIssueProposal,
    ModelTurnResponse,
    parse_issue_proposal,
    parse_model_turn_response,
)
from app.builderops.models import BuilderOpsValidationError


def render_markdown_report(trace: Mapping[str, Any]) -> str:
    """Render a deterministic read-only view of one validated inquiry trace."""
    inquiry = _mapping(trace.get("inquiry"), "inquiry")
    question = _mapping(trace.get("question"), "question")
    inquiry_id = _text(inquiry, "inquiry_id")
    workflow = _text(inquiry, "workflow")
    lines = [
        f"# Model inquiry — {inquiry_id}",
        "",
        f"Workflow: `{workflow}`",
        "",
        "This is a readable projection of the canonical JSON inquiry records. "
        "The JSON records remain the authoritative BuilderOps trace.",
        "",
        "## Question",
        "",
        *_fenced(_text(question, "content")),
        "## Model turns",
        "",
    ]
    turns = trace.get("turns")
    if not isinstance(turns, list):
        raise BuilderOpsValidationError("inquiry report requires ordered turns")
    if not turns:
        lines.extend(["No model turns were committed.", ""])
    for turn in turns:
        lines.extend(_render_turn(_mapping(turn, "turn")))

    synthesis = trace.get("synthesis")
    if synthesis is not None:
        lines.extend(["## Shared synthesis", ""])
        lines.extend(_render_model_content(_text(_mapping(synthesis, "synthesis"), "content")))

    readiness = trace.get("readiness")
    if readiness is not None:
        readiness_map = _mapping(readiness, "readiness")
        lines.extend(
            [
                "## Readiness",
                "",
                f"Outcome: **{_text(readiness_map, 'outcome')}**",
                "",
                *_fenced(_text(readiness_map, "rationale")),
            ]
        )

    terminal = _terminal_receipt(trace)
    if terminal is not None:
        lines.extend(
            [
                "## Run result",
                "",
                f"Outcome: **{_text(terminal, 'outcome')}**",
                "",
                f"Terminal receipt: `{_text(terminal, 'id')}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _render_turn(turn: Mapping[str, Any]) -> list[str]:
    title = f"### {_text(turn, 'sequence')}. {_text(turn, 'role')}"
    phase = turn.get("phase")
    if isinstance(phase, str) and phase:
        title += f" — {phase}"
    lines = [title, ""]
    content = _text(turn, "content")
    try:
        response = parse_model_turn_response(content)
    except BuilderOpsValidationError:
        lines.extend(_fenced(content))
        return lines

    lines.extend([f"Stance: **{response.stance}**", ""])
    lines.extend(_render_response(response))
    return lines


def _render_model_content(content: str) -> list[str]:
    try:
        response = parse_model_turn_response(content)
    except BuilderOpsValidationError:
        return _fenced(content)
    return [f"Stance: **{response.stance}**", "", *_render_response(response)]


def _render_response(response: ModelTurnResponse) -> list[str]:
    lines = ["#### Response", ""]
    lines.extend(_render_response_content(response.content))
    _append_list(lines, "Claims", response.claims)
    _append_list(lines, "Risks", response.risks)
    _append_list(lines, "Blocking questions", response.blocking_questions)
    return lines


def _render_response_content(content: str) -> list[str]:
    try:
        proposal: ModelInquiryIssueProposal = parse_issue_proposal(content)
    except BuilderOpsValidationError:
        return _fenced(content)
    return ["Proposed issue", "", *_fenced(f"{proposal.title}\n\n{proposal.body}")]


def _append_list(lines: list[str], heading: str, values: list[str]) -> None:
    if not values:
        return
    lines.extend([f"#### {heading}", ""])
    lines.extend(_fenced("\n".join(f"- {value}" for value in values)))


def _fenced(content: str) -> list[str]:
    fence = "```"
    while fence in content:
        fence += "`"
    return [fence, content, fence, ""]


def _terminal_receipt(trace: Mapping[str, Any]) -> Mapping[str, Any] | None:
    receipts = trace.get("receipts")
    if not isinstance(receipts, list):
        raise BuilderOpsValidationError("inquiry report requires receipts")
    for receipt in receipts:
        if isinstance(receipt, Mapping) and receipt.get("event_type") == "inquiry_run_terminal":
            return receipt
    return None


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BuilderOpsValidationError(f"inquiry report requires {label} object")
    return value


def _text(value: Mapping[str, Any], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, (str, int)):
        raise BuilderOpsValidationError(f"inquiry report requires {field}")
    return str(result)


__all__ = ["render_markdown_report"]
