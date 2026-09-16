"""Read one governed Focus subject into inputs for the pure Focus composer.

This adapter deliberately reads only the selected subject.  It does not reuse
or join the root devUI composition payload, and it owns no cache, store, or
workflow transition.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import subprocess
from typing import Any

from app.builderops.control_plane.models import EnvelopeValidationError, canonical_repository


_ISSUE_SUBJECT = re.compile(r"github:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#([1-9][0-9]*)\Z")
_HEADING = re.compile(r"^(?P<marks>#{1,6})[ \t]+(?P<title>.*?)[ \t]*#*[ \t]*$")
_FENCE = re.compile(
    r"^[ \t]{0,3}(?P<marker>`{3,}|~{3,})(?P<suffix>[^\r\n]*)"
)
_LIST_ITEM = re.compile(r"^(?P<indent>[ \t]*)(?:[-*+]|[0-9]+[.)])[ \t]+(?P<text>.*)$")
_DECLARED_SECTIONS = {
    "context": "Context",
    "scope": "Scope",
    "acceptance criteria": "Acceptance Criteria",
    "source anchors": "Source Anchors",
    "source docs": "Source Docs",
}
_MAX_SECTION_CHARS = 16_000
_MAX_ITEM_CHARS = 4_000
_MAX_DECLARATION_CLAIMS = 40
_MAX_INTENT_CHARS = 16_000


@dataclass
class _SectionBlock:
    """One bounded, unfenced Markdown section from the selected Issue."""

    key: str
    label: str
    level: int
    lines: list[str] = field(default_factory=list)
    retained_chars: int = 0
    fenced_content: bool = False
    oversized: bool = False

    @property
    def text(self) -> str:
        return "\n".join(line.rstrip("\r\n") for line in self.lines).strip()


def _section_key(title: str) -> str | None:
    normalized = re.sub(r"\s+", " ", title.strip().rstrip(":"))
    key = normalized.casefold()
    return key if key in _DECLARED_SECTIONS else None


def _read_issue_sections(body: str) -> dict[str, list[_SectionBlock]]:
    """Read only the finite named sections outside fenced Markdown examples.

    Headings are discovered across the complete returned Issue body, while each
    section's retained text is capped. This preserves small unaffected sections
    when an unrelated section is oversized without allowing source text to grow
    the Focus response without bound.
    """

    sections: dict[str, list[_SectionBlock]] = {key: [] for key in _DECLARED_SECTIONS}
    current: _SectionBlock | None = None
    fence_marker: str | None = None
    for raw_line in body.splitlines(keepends=True):
        fence_match = _FENCE.match(raw_line)
        if fence_marker is not None:
            if (
                fence_match is not None
                and not fence_match.group("suffix").strip()
                and fence_match.group("marker")[0] == fence_marker[0]
            ):
                marker = fence_match.group("marker")
                if len(marker) >= len(fence_marker):
                    fence_marker = None
            if current is not None:
                current.fenced_content = True
            continue
        if fence_match is not None:
            fence_marker = fence_match.group("marker")
            if current is not None:
                current.fenced_content = True
            continue

        heading_match = _HEADING.match(raw_line.rstrip("\r\n"))
        if heading_match is not None:
            level = len(heading_match.group("marks"))
            if current is not None:
                if level <= current.level or _section_key(heading_match.group("title")) is not None:
                    current = None
                else:
                    if current.retained_chars + len(raw_line) > _MAX_SECTION_CHARS:
                        current.oversized = True
                    else:
                        current.lines.append(raw_line)
                        current.retained_chars += len(raw_line)
                    continue
            if current is None:
                key = _section_key(heading_match.group("title"))
                if key is not None:
                    current = _SectionBlock(
                        key=key,
                        label=_DECLARED_SECTIONS[key],
                        level=level,
                    )
                    sections[key].append(current)
            continue

        if current is None:
            continue
        if current.retained_chars + len(raw_line) > _MAX_SECTION_CHARS:
            current.oversized = True
            continue
        current.lines.append(raw_line)
        current.retained_chars += len(raw_line)
    return sections


def _section_status(blocks: list[_SectionBlock]) -> str:
    if not blocks:
        return "missing"
    if len(blocks) != 1:
        return "ambiguous"
    block = blocks[0]
    if block.oversized:
        return "partial"
    if not block.text:
        return "unread"
    return "complete"


def _section_items(block: _SectionBlock) -> tuple[list[str], bool]:
    """Return bounded list entries and whether the list is malformed/partial."""

    items: list[list[str]] = []
    base_indent: int | None = None
    malformed = False
    dropped_item = False
    for raw_line in block.lines:
        line = raw_line.rstrip("\r\n")
        match = _LIST_ITEM.match(line)
        indent = match.group("indent") if match is not None else ""
        indent_width = len(indent.expandtabs(4))
        starts_item = match is not None and (base_indent is None or indent_width <= base_indent)
        if starts_item:
            if base_indent is None:
                base_indent = indent_width
            if len(items) >= _MAX_DECLARATION_CLAIMS:
                malformed = True
                dropped_item = True
                continue
            dropped_item = False
            items.append([line.strip()[:_MAX_ITEM_CHARS]])
            if len(line.strip()) > _MAX_ITEM_CHARS:
                malformed = True
            continue
        if dropped_item:
            continue
        if not line.strip():
            if items:
                items[-1].append("")
            continue
        if items:
            items[-1].append(line[:_MAX_ITEM_CHARS])
            if len(line) > _MAX_ITEM_CHARS:
                malformed = True
        else:
            malformed = True
            items.append([line.strip()[:_MAX_ITEM_CHARS]])
            if len(line.strip()) > _MAX_ITEM_CHARS:
                malformed = True
    rendered = ["\n".join(lines).strip() for lines in items]
    return [item for item in rendered if item], malformed


def _section_ref(source_ref: Mapping[str, str], label: str) -> dict[str, str]:
    return {
        **source_ref,
        "locator": f"{source_ref['locator']}#{re.sub(r'[^a-z0-9]+', '-', label.casefold()).strip('-')}",
    }


def _revision_claim_id(
    *, content_hash: str, section: str, position: int, text: str
) -> str:
    digest = hashlib.sha256(
        f"{content_hash}:{section}:{position}:{text}".encode("utf-8")
    ).hexdigest()[:16]
    return f"issue-declaration:{section.casefold().replace(' ', '-')}:r{position}-{digest}"


class FocusInputError(ValueError):
    """The requested Focus subject cannot be read as a governed subject."""


def _source_ref(*, source_type: str, source_id: str, locator: str, version: str) -> dict[str, str]:
    return {
        "source_type": source_type,
        "source_id": source_id,
        "locator": locator,
        "version": version,
    }


def _claim(
    *,
    claim_id: str,
    claim: str,
    source_ref: Mapping[str, str],
    captured_at: str,
    coverage: str = "complete",
    cardinality: str = "nonempty",
    limitation: str | None = None,
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "claim": claim,
        "source_ref": dict(source_ref),
        "availability": "available",
        "freshness": "fresh",
        "coverage": coverage,
        "cardinality": cardinality,
        "linkage": "linked",
        "captured_at": captured_at,
        "limitation": limitation,
    }


def _common_inputs(
    *, subject: Mapping[str, Any], source_ref: Mapping[str, str], summary: str, captured_at: str
) -> dict[str, Any]:
    return {
        "subject": dict(subject),
        "owner_intent": {"summary": summary, "source_ref": dict(source_ref)},
        "governing_sources": [
            _claim(
                claim_id="governing-subject",
                claim="Selected subject is readable from its governing source.",
                source_ref=source_ref,
                captured_at=captured_at,
            )
        ],
        "evidence": [
            _claim(
                claim_id="subject-read",
                claim="Selected subject read completed for this projection.",
                source_ref=source_ref,
                captured_at=captured_at,
            )
        ],
        "receipts": [],
        "risks": [],
        "next_legal_step": {
            "workflow_ref": None,
            "actor_class": "system",
            "legality": "unavailable",
            "reason": "This read route does not infer a workflow transition.",
        },
        "execution_observations": [],
        "conversation_port": {
            "availability": "unsupported",
            "reason": "Conversation Port runtime is not delivered by this read route.",
        },
        "limitations": [],
    }


def _limitation(
    *, kind: str, reason: str, source_ref: Mapping[str, str], evidence_state: str
) -> dict[str, Any]:
    return {
        "kind": kind,
        "reason": reason,
        "source_ref": dict(source_ref),
        "evidence_state": evidence_state,
        "linkage": "linked",
    }


def _repositories_match(left: str, right: str) -> bool:
    try:
        return canonical_repository(left) == canonical_repository(right)
    except EnvelopeValidationError:
        return False


def _declaration_claim(
    *,
    content_hash: str,
    section: str,
    position: int,
    text: str,
    source_ref: Mapping[str, str],
    captured_at: str,
) -> dict[str, Any]:
    label = _DECLARED_SECTIONS[section]
    return _claim(
        claim_id=_revision_claim_id(
            content_hash=content_hash,
            section=section,
            position=position,
            text=text,
        ),
        claim=f"Declared {label} source text (no result inferred):\n{text}",
        source_ref=_section_ref(source_ref, label),
        captured_at=captured_at,
        coverage="partial",
        cardinality="not_countable",
        limitation=(
            "This is source-declared Issue text only; referenced documents, "
            "applicability, enforcement, and criterion results were not assessed."
        ),
    )


def _append_section_limitation(
    limitations: list[dict[str, Any]],
    *,
    section: str,
    status: str,
    source_ref: Mapping[str, str],
    block: _SectionBlock | None = None,
) -> None:
    if block is not None and block.fenced_content:
        limitations.append(
            _limitation(
                kind="fenced_example_ignored",
                reason=(
                    f"Fenced example content in the declared {_DECLARED_SECTIONS[section]} "
                    "section was ignored as non-authoritative source text."
                ),
                source_ref=_section_ref(source_ref, _DECLARED_SECTIONS[section]),
                evidence_state="partial",
            )
        )
    if status == "complete":
        return
    reason = {
        "missing": f"The selected Issue has no {_DECLARED_SECTIONS[section]} section; no content was measured or inferred.",
        "unread": f"The selected Issue's {_DECLARED_SECTIONS[section]} section is unreadable or empty; no content was measured or inferred.",
        "ambiguous": f"The selected Issue has multiple {_DECLARED_SECTIONS[section]} sections; declarations were not silently merged.",
        "partial": f"The selected Issue's {_DECLARED_SECTIONS[section]} section is partial or oversized; only bounded readable text is projected.",
    }.get(status, f"The selected Issue's {_DECLARED_SECTIONS[section]} section could not be assessed.")
    limitations.append(
        _limitation(
            kind=f"issue_section_{status}",
            reason=reason,
            source_ref=_section_ref(source_ref, _DECLARED_SECTIONS[section]),
            evidence_state=status if status in {"missing", "unread", "partial"} else "partial",
        )
    )


def _read_issue_inputs(
    subject_id: str,
    match: re.Match[str],
    *,
    repository: str | None = None,
    issue_reader: Callable[[str, str], Any] | None = None,
) -> dict[str, Any]:
    requested_repository, number_text = match.groups()
    configured_repo = (
        repository if issue_reader is not None else os.environ.get("COCKPIT_GITHUB_REPO")
    )
    repository = requested_repository
    matches_repository = configured_repo == repository
    if issue_reader is not None and configured_repo is not None:
        matches_repository = _repositories_match(configured_repo, repository)
    if not matches_repository:
        raise FocusInputError("requested Issue repository is not configured for the local read")
    if issue_reader is not None:
        try:
            issue = issue_reader(repository, number_text)
        except Exception as exc:
            raise FocusInputError("selected Issue source is unavailable") from exc
    else:
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{repository}/issues/{number_text}"],
                capture_output=True,
                check=False,
                text=True,
                timeout=20,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise FocusInputError("selected Issue source is unavailable") from exc
        if result.returncode != 0:
            raise FocusInputError("selected Issue is unavailable or unsupported")
        try:
            issue = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise FocusInputError("selected Issue source is unavailable") from exc
    if not isinstance(issue, Mapping) or issue.get("pull_request"):
        raise FocusInputError("selected Issue is unavailable or unsupported")
    title = issue.get("title")
    html_url = issue.get("html_url")
    updated_at = issue.get("updated_at")
    if not isinstance(title, str) or not title:
        raise FocusInputError("selected Issue source is unavailable")
    if not isinstance(html_url, str) or not html_url:
        raise FocusInputError("selected Issue source is unavailable")
    if not isinstance(updated_at, str) or not updated_at:
        raise FocusInputError("selected Issue source is unavailable")
    issue_number = issue.get("number")
    if issue_number is not None and (
        type(issue_number) is not int or issue_number != int(number_text)
    ):
        raise FocusInputError("selected Issue response identity is invalid")
    addressed_issue = re.fullmatch(
        r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)",
        html_url,
    )
    if (
        addressed_issue is None
        or not _repositories_match(addressed_issue.group(1), repository)
        or addressed_issue.group(2) != number_text
    ):
        raise FocusInputError("selected Issue response identity is invalid")
    body = issue.get("body")
    content_hash: str | None = None
    sections: dict[str, list[_SectionBlock]] = {
        key: [] for key in _DECLARED_SECTIONS
    }
    if isinstance(body, str):
        content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        sections = _read_issue_sections(body)
    source_ref = _source_ref(
        source_type="github_issue",
        source_id=f"{repository}#{number_text}",
        locator=html_url,
        version=updated_at,
    )
    if content_hash is not None:
        source_ref["content_hash"] = content_hash
    captured_at = datetime.now(timezone.utc).isoformat()
    inputs = _common_inputs(
        subject={
            "kind": "issue",
            "stable_id": subject_id,
            "authority_ref": source_ref,
            "title": title,
        },
        source_ref=source_ref,
        summary=f"Read the governed Issue: {title}",
        captured_at=captured_at,
    )
    limitations = inputs["limitations"]
    if content_hash is None:
        limitations.append(
            _limitation(
                kind="issue_body_unavailable",
                reason="The selected Issue body was unavailable; only identity and title are projected.",
                source_ref=source_ref,
                evidence_state="unread",
            )
        )
        inputs["governing_sources"][0].update(
            coverage="partial",
            cardinality="not_countable",
            limitation="Issue identity is readable but body text is unavailable.",
        )
        inputs["evidence"][0].update(
            coverage="partial",
            cardinality="not_countable",
            limitation="Issue identity is readable but body text is unavailable.",
        )
        return inputs

    context = sections["context"]
    scope = sections["scope"]
    for section in ("context", "scope"):
        blocks = sections[section]
        _append_section_limitation(
            limitations,
            section=section,
            status=_section_status(blocks),
            source_ref=source_ref,
            block=blocks[0] if len(blocks) == 1 else None,
        )
    intent_parts = [
        f"Declared Context:\n{context[0].text}" for _ in [0] if _section_status(context) == "complete"
    ]
    intent_parts.extend(
        f"Declared Scope:\n{scope[0].text}" for _ in [0] if _section_status(scope) == "complete"
    )
    if intent_parts:
        intent_summary = "\n\n".join(intent_parts)
        if len(intent_summary) > _MAX_INTENT_CHARS:
            intent_summary = intent_summary[:_MAX_INTENT_CHARS].rstrip()
            limitations.append(
                _limitation(
                    kind="issue_intent_oversized",
                    reason="Context and Scope declarations exceed the bounded owner-intent projection.",
                    source_ref=source_ref,
                    evidence_state="partial",
                )
            )
        inputs["owner_intent"]["summary"] = intent_summary

    declaration_claim_count = 0
    for section in ("source anchors", "source docs"):
        blocks = sections[section]
        status = _section_status(blocks)
        _append_section_limitation(
            limitations,
            section=section,
            status=status,
            source_ref=source_ref,
            block=blocks[0] if len(blocks) == 1 else None,
        )
        if status != "complete":
            continue
        items, malformed = _section_items(blocks[0])
        if malformed:
            limitations.append(
                _limitation(
                    kind="issue_section_partial",
                    reason=(
                        f"Only bounded readable {_DECLARED_SECTIONS[section]} list text is projected; "
                        "malformed or oversized entries remain unassessed."
                    ),
                    source_ref=_section_ref(source_ref, _DECLARED_SECTIONS[section]),
                    evidence_state="partial",
                )
            )
        for position, text in enumerate(items, start=1):
            if declaration_claim_count >= _MAX_DECLARATION_CLAIMS:
                limitations.append(
                    _limitation(
                        kind="issue_declarations_truncated",
                        reason="The selected Issue contains more declaration items than the bounded Focus projection permits.",
                        source_ref=source_ref,
                        evidence_state="partial",
                    )
                )
                break
            inputs["governing_sources"].append(
                _declaration_claim(
                    content_hash=content_hash,
                    section=section,
                    position=position,
                    text=text,
                    source_ref=source_ref,
                    captured_at=captured_at,
                )
            )
            declaration_claim_count += 1

    acceptance_blocks = sections["acceptance criteria"]
    acceptance_status = _section_status(acceptance_blocks)
    _append_section_limitation(
        limitations,
        section="acceptance criteria",
        status=acceptance_status,
        source_ref=source_ref,
        block=acceptance_blocks[0] if len(acceptance_blocks) == 1 else None,
    )
    if acceptance_status == "complete":
        items, malformed = _section_items(acceptance_blocks[0])
        if malformed:
            limitations.append(
                _limitation(
                    kind="issue_section_partial",
                    reason=(
                        "Only bounded readable Acceptance Criteria list text is projected; "
                        "malformed or oversized entries remain unassessed."
                    ),
                    source_ref=_section_ref(source_ref, "Acceptance Criteria"),
                    evidence_state="partial",
                )
            )
        for position, text in enumerate(items, start=1):
            if declaration_claim_count >= _MAX_DECLARATION_CLAIMS:
                limitations.append(
                    _limitation(
                        kind="issue_declarations_truncated",
                        reason="The selected Issue contains more declaration items than the bounded Focus projection permits.",
                        source_ref=source_ref,
                        evidence_state="partial",
                    )
                )
                break
            inputs["evidence"].append(
                _declaration_claim(
                    content_hash=content_hash,
                    section="acceptance criteria",
                    position=position,
                    text=text,
                    source_ref=source_ref,
                    captured_at=captured_at,
                )
            )
            declaration_claim_count += 1
    if acceptance_status in {"missing", "unread", "ambiguous"}:
        # Keep the absence explicit in an existing evidence axis without
        # turning an absent section into measured empty or inferred success.
        inputs["evidence"].append(
            _claim(
                claim_id=_revision_claim_id(
                    content_hash=content_hash,
                    section="acceptance criteria status",
                    position=1,
                    text=acceptance_status,
                ),
                claim=(
                    f"Acceptance Criteria declaration is {acceptance_status}; "
                    "per-criterion result evidence is not assessed."
                ),
                source_ref=_section_ref(source_ref, "Acceptance Criteria"),
                captured_at=captured_at,
                coverage="unread" if acceptance_status in {"missing", "unread"} else "partial",
                cardinality="not_countable",
                limitation="No requirement coverage or result is inferred from this source state.",
            )
        )
    if not any("Verify:" in item for item in inputs["evidence"] if isinstance(item.get("claim"), str)):
        limitations.append(
            _limitation(
                kind="criterion_results_unassessed",
                reason="Declared Verify pointers, when present, are source text only; no result, coverage, or acceptance is inferred.",
                source_ref=_section_ref(source_ref, "Acceptance Criteria"),
                evidence_state="unread" if acceptance_status != "complete" else "partial",
            )
        )
    else:
        limitations.append(
            _limitation(
                kind="criterion_results_unassessed",
                reason="Declared Verify pointers remain source text only; their tests and results were not read or evaluated.",
                source_ref=_section_ref(source_ref, "Acceptance Criteria"),
                evidence_state="partial",
            )
        )
    return inputs


def read_focus_inputs(
    subject_id: str,
    *,
    repository: str | None = None,
    issue_reader: Callable[[str, str], Any] | None = None,
    owner_fact_reader: Callable[[], dict[str, Any]] | None = None,
    issue_delivery_reader: Callable[[str], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Return detached composer inputs for exactly one stable governed subject."""

    if not isinstance(subject_id, str) or not subject_id:
        raise FocusInputError("subject must be a stable governed identity")
    match = _ISSUE_SUBJECT.fullmatch(subject_id)
    if match is not None:
        from app.builderops.devui_owner_facts import append_focus_owner_facts, read_owner_fact_transport

        inputs = _read_issue_inputs(
            subject_id, match, repository=repository, issue_reader=issue_reader
        )
        inputs = append_focus_owner_facts(inputs, owner_fact_reader() if owner_fact_reader else read_owner_fact_transport(repository=repository))
        delivery = issue_delivery_reader(subject_id) if issue_delivery_reader else None
        if delivery is not None:
            if (
                not isinstance(delivery, dict)
                or delivery.get("contract") != "fca-issue-delivery-readback.v1"
                or delivery.get("state") != "delivered"
                or delivery.get("subject_ref") != subject_id
                or not isinstance(delivery.get("evidence"), list)
                or not delivery["evidence"]
                or any(
                    not isinstance(item, dict)
                    or not isinstance(item.get("source_ref"), dict)
                    for item in delivery["evidence"]
                )
            ):
                raise FocusInputError("Issue-delivery readback is incompatible with selected subject")
            focus_evidence = [
                {
                    "claim_id": item["evidence_id"],
                    "claim": item["claim"],
                    "source_ref": deepcopy(item["source_ref"]),
                    "availability": item["availability"],
                    "freshness": item["freshness"],
                    "coverage": item["completeness"],
                    "cardinality": item["cardinality"],
                    "linkage": item["linkage"],
                    "captured_at": item["captured_at"],
                    "read_watermark": item.get("read_watermark"),
                    "limitation": item.get("limitation"),
                }
                for item in delivery["evidence"]
            ]
            inputs["evidence"].extend(focus_evidence)
            source_ref = delivery["evidence"][0].get("source_ref") if delivery["evidence"] else None
            inputs["limitations"].append(
                {
                    "kind": "issue_delivery_scope",
                    "reason": "Repository delivery and readiness do not establish owner trial or acceptance.",
                    "source_ref": deepcopy(source_ref),
                    "evidence_state": "partial",
                    "linkage": "linked",
                }
            )
        return inputs
    raise FocusInputError("selected subject is unsupported")


__all__ = ["FocusInputError", "read_focus_inputs"]
