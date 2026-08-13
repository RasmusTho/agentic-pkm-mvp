"""Shared JRNL-03/JRNL-04 journal-candidate lifecycle semantics."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from app.agents.panel_agent.parser import find_panels, parse_panel


PRIMARY_ACCEPT_LABEL = "Accept this draft as today's journal entry"
ADDENDUM_ACCEPT_LABEL = "Accept and append this addendum to today's journal"
DISMISS_LABEL = "Dismiss this journal candidate"

JournalCandidateType = Literal["primary", "addendum"]
JournalCandidateAction = Literal["accept", "dismiss"]


class JournalCandidateContractError(ValueError):
    """The candidate's durable Panel or proposal identity is ambiguous."""


def checked_journal_action(
    body: str, *, candidate_type: JournalCandidateType
) -> JournalCandidateAction | None:
    """Return the sole checked action from the exact JRNL Panel contract."""

    expected_accept = (
        ADDENDUM_ACCEPT_LABEL
        if candidate_type == "addendum"
        else PRIMARY_ACCEPT_LABEL
    )
    matching_actions: list[tuple[str, bool]] = []
    for panel in find_panels(body):
        parsed = parse_panel(panel.raw_block, panel.panel_id)
        for action in parsed.actions:
            if action.label in {expected_accept, DISMISS_LABEL}:
                matching_actions.append((action.label, action.checked))

    labels = [label for label, _checked in matching_actions]
    if labels.count(expected_accept) != 1 or labels.count(DISMISS_LABEL) != 1:
        raise JournalCandidateContractError(
            "journal candidate must carry exactly one accept and one dismiss "
            "action in a valid AI-åtgärder Panel"
        )
    checked = {label for label, is_checked in matching_actions if is_checked}
    if len(checked) > 1:
        raise JournalCandidateContractError(
            "journal candidate has both accept and dismiss checked"
        )
    if expected_accept in checked:
        return "accept"
    if DISMISS_LABEL in checked:
        return "dismiss"
    return None


def strip_journal_review_panel(body: str) -> str:
    """Remove exactly one JRNL review Panel from the candidate body."""

    rendered = body
    removed = 0
    for panel in find_panels(body):
        parsed = parse_panel(panel.raw_block, panel.panel_id)
        labels = {action.label for action in parsed.actions}
        if DISMISS_LABEL in labels and labels.intersection(
            {PRIMARY_ACCEPT_LABEL, ADDENDUM_ACCEPT_LABEL}
        ):
            rendered = rendered.replace(panel.raw_block, "", 1)
            removed += 1
    if removed != 1:
        raise JournalCandidateContractError(
            "journal candidate review Panel is missing or ambiguous"
        )
    return rendered.strip() + "\n"


def journal_decline_finding_id(
    *,
    candidate_type: JournalCandidateType,
    for_date: str,
    frontmatter: dict[str, Any],
    body: str,
) -> str:
    """Bind decline suppression to proposal content and source basis.

    Volatile proposal ids, timestamps, and activation receipts are excluded so
    an unchanged JRNL-03 rerun remains suppressed. Any body or source-basis
    change mints a new id and is therefore independently reviewable.
    """

    sources = frontmatter.get("sources")
    occurrences = frontmatter.get("source_occurrences")
    basis = {
        "candidate_type": candidate_type,
        "for_date": for_date,
        "sources": sources if isinstance(sources, list) else [],
        "source_occurrences": occurrences if isinstance(occurrences, list) else [],
        "body": strip_journal_review_panel(body),
    }
    encoded = json.dumps(
        basis,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "journal-candidate-" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ADDENDUM_ACCEPT_LABEL",
    "DISMISS_LABEL",
    "JournalCandidateAction",
    "JournalCandidateContractError",
    "JournalCandidateType",
    "PRIMARY_ACCEPT_LABEL",
    "checked_journal_action",
    "journal_decline_finding_id",
    "strip_journal_review_panel",
]
