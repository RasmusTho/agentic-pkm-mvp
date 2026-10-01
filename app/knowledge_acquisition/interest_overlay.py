"""Governed interest overlay for YouTube Source Note v2 (YSNV2-10, #4117).

The overlay is a read-only consumer.  Profile state is admitted only through
``read_governed_profile_for_overlay``, which rebuilds the ProfileAgent-written,
owner-approved, receipt-bound projection for one explicitly bound scope.  This
module never reads ProfileUpdateCandidate handoffs or proposal state, never
constructs a profile from YouTube behavior or prior notes, and has no profile
write, inference, or broader-scope fallback path.

When no admissible profile exists the overlay renders exactly one explicit
no-profile line and stops before inspecting any proposed connection.  When a
profile is admitted, each proposed connection must keep four separate fields:

- ``source_says`` plus resolvable transcript ``anchors`` (verbatim original
  source wording; a translation is never accepted as the quotation);
- ``system_inference`` (generated prose, D6 language);
- ``owner_link`` (a verbatim excerpt of the admitted approved profile content);
- ``suggested_use`` (generated prose, D6 language).

Incomplete, collapsed, or foreign-field connections are dropped and reported.

#5747 adds ``propose_local_connections``, the deterministic local producer used
at acquisition time.  It reads profile state only through
``read_governed_profile_for_overlay`` and proposes a connection when an
approved profile entry shares enough distinct content terms with one
transcript segment.  It performs no model, network, or LLM-routing call; its
generated prose is fixed D6 template text.  ``produce_interest_overlay`` feeds
those proposals through ``render_interest_overlay`` admission unchanged.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from app.knowledge.profile_consumer_projection import (
    ProfileConsumerProjection,
    rebuild_profile_projection,
)
from app.knowledge_acquisition.evidence_synthesis import (
    system_language_for,
    validate_generated_language,
    validate_resolvable_anchor,
)
from app.knowledge_acquisition.note_renderer import ProposalSection

INTEREST_OVERLAY_MODULE_ID = "interest_overlay"
OverlayStatus = Literal["connections", "no-connections", "no-profile"]

_CONNECTION_FIELDS = frozenset(
    {"source_says", "anchors", "system_inference", "owner_link", "suggested_use"}
)
_MIN_OWNER_LINK_WORDS = 3
_EMBED_OPENER = "![["
_HEADING = re.compile(r"#{1,6}(?:\s|$)")
_LINE_MARKER = re.compile(r"^(?:[-*+>]\s+|\d+[.)]\s+)+")
# KD-EF0ADFABFD23: ``%`` (Obsidian comment ``%%``), ``=`` (highlight ``==``) and
# ``#`` (inline ``#tag``) are escaped too, so transcript or profile text can neither
# hide the rest of the note nor restyle or tag it.
_MARKDOWN_ACTIVE = re.compile(r"([\\`*_\[\]!|~%=#])")
_TERM = re.compile(r"\w+", re.UNICODE)
_MIN_TERM_LENGTH = 4
_MIN_SHARED_TERMS = 2
_MAX_LOCAL_CONNECTIONS = 3
# Function words long enough to pass the term-length floor; matching on them would
# be noise rather than a content signal.  Bounded to the D6 languages.
_STOP_TERMS = frozenset(
    {
        "about", "also", "been", "being", "from", "have", "into", "just", "like", "more",
        "most", "much", "only", "other", "over", "some", "such", "than", "that", "their",
        "them", "then", "there", "these", "they", "this", "those", "very", "were", "what",
        "when", "where", "which", "while", "will", "with", "would", "your", "prefer",
        "interested", "follow",
        "alla", "andra", "denna", "detta", "eller", "efter", "från", "inte", "mellan",
        "också", "eftersom", "under", "utan", "vara", "vill", "över",
    }
)
_LOCAL_INFERENCE: Mapping[str, str] = {
    "en": (
        "This passage shares {count} distinct key terms with one approved profile entry, "
        "so it may relate to that stated interest."
    ),
    "sv": (
        "Det här avsnittet delar {count} olika nyckelord med en godkänd post i profilen, "
        "så det kan höra ihop med det uttalade intresset."
    ),
}
_LOCAL_SUGGESTED_USE: Mapping[str, str] = {
    "en": (
        "Review this passage when revisiting that interest and decide whether it belongs "
        "with related notes."
    ),
    "sv": (
        "Granska avsnittet när du återvänder till intresset och avgör om det hör hemma "
        "bland relaterade anteckningar."
    ),
}

NO_PROFILE_LINES: Mapping[str, str] = {
    "en": "No approved profile is available for this scope, so no interest connections were produced.",
    "sv": "Det finns ingen godkänd profil för det här omfånget, så inga intressekopplingar togs fram.",
}
_NO_CONNECTION_LINES: Mapping[str, str] = {
    "en": "The approved profile is available, but no connection was supported by source evidence.",
    "sv": "Den godkända profilen finns, men ingen koppling stöddes av belägg från källan.",
}
_TITLES: Mapping[str, str] = {"en": "Interest overlay", "sv": "Intresseöverlägg"}
_LABELS: Mapping[str, Mapping[str, str]] = {
    "en": {
        "source_says": "Source says",
        "system_inference": "System inference",
        "owner_link": "Owner link",
        "suggested_use": "Suggested use",
        "profile_version": "approved profile version",
    },
    "sv": {
        "source_says": "Källan säger",
        "system_inference": "Systemets slutledning",
        "owner_link": "Koppling till ägaren",
        "suggested_use": "Föreslagen användning",
        "profile_version": "godkänd profilversion",
    },
}


@dataclass(frozen=True)
class InterestOverlay:
    """One rebuildable, review-required overlay proposal."""

    status: OverlayStatus
    reason: str
    system_language: str
    connections: tuple[Mapping[str, Any], ...] = ()
    dropped: tuple[str, ...] = ()
    profile_scope_id: str | None = None
    profile_version_id: str | None = None
    profile_receipt_id: str | None = None

    def section(self) -> ProposalSection:
        """Project the overlay into the review-required proposal band."""

        language = self.system_language
        if self.status == "no-profile":
            content = NO_PROFILE_LINES[language]
        elif self.status == "no-connections":
            content = _NO_CONNECTION_LINES[language]
        else:
            content = "\n".join(_render_connection(c, language) for c in self.connections)
        return ProposalSection(
            module_id=INTEREST_OVERLAY_MODULE_ID,
            title=_TITLES[language],
            content=content,
        )


def admit_profile_for_interest_overlay(
    vault_root: Path | str,
    *,
    active_scope_id: str | None,
) -> ProfileConsumerProjection:
    """Admit only the governed same-scope profile projection for #4117."""

    return rebuild_profile_projection(vault_root, active_scope_id=active_scope_id)


def read_governed_profile_for_overlay(
    vault_root: Path | str,
    *,
    active_scope_id: str | None,
) -> ProfileConsumerProjection:
    """Named read-only production adapter used by the overlay renderer."""

    return admit_profile_for_interest_overlay(
        vault_root,
        active_scope_id=active_scope_id,
    )


def render_interest_overlay(
    *,
    vault_root: Path | str,
    active_scope_id: str | None,
    normalized: Mapping[str, Any],
    connections: Iterable[object],
) -> InterestOverlay:
    """Render four-part connections against the admitted governed profile only."""

    if not isinstance(normalized, Mapping):
        normalized = {}
    language = system_language_for(normalized.get("language"))
    projection = read_governed_profile_for_overlay(vault_root, active_scope_id=active_scope_id)
    if not projection.available or not projection.profile_content:
        # Stop: no connection is inspected and nothing is inferred locally.
        return InterestOverlay(status="no-profile", reason=projection.reason, system_language=language)

    segments = normalized.get("segments")
    if not isinstance(segments, list):
        segments = []
    profile_lines = _profile_lines(projection.profile_content)
    kept: list[Mapping[str, Any]] = []
    dropped: list[str] = []
    if isinstance(connections, (str, bytes, Mapping)) or not isinstance(connections, Iterable):
        dropped.append("connections_malformed")
        connections = ()
    for candidate in connections:
        outcome = _admit_connection(candidate, segments, profile_lines, language)
        if isinstance(outcome, str):
            dropped.append(outcome)
            continue
        kept.append(
            {
                **outcome,
                "profile_version_id": projection.version_id,
                "profile_receipt_id": projection.receipt_id,
            }
        )
    return InterestOverlay(
        status="connections" if kept else "no-connections",
        reason=projection.reason,
        system_language=language,
        connections=tuple(kept),
        dropped=tuple(dropped),
        profile_scope_id=projection.scope_id,
        profile_version_id=projection.version_id,
        profile_receipt_id=projection.receipt_id,
    )


def propose_local_connections(
    *,
    vault_root: Path | str,
    active_scope_id: str | None,
    normalized: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Deterministically propose four-part connections from local evidence only.

    Profile state is read only through ``read_governed_profile_for_overlay``; no
    model, network, or LLM-routing call is made.  For each approved profile entry
    (in profile order) the earliest transcript segment sharing the most distinct
    content terms (at least ``_MIN_SHARED_TERMS``) yields one proposal.  The
    proposals are not trusted: ``render_interest_overlay`` re-admits each one.
    """

    if not isinstance(normalized, Mapping):
        return ()
    projection = read_governed_profile_for_overlay(vault_root, active_scope_id=active_scope_id)
    if not projection.available or not projection.profile_content:
        return ()
    segments = normalized.get("segments")
    if not isinstance(segments, list):
        return ()
    language = system_language_for(normalized.get("language"))
    segment_terms = [
        _content_terms(segment.get("text")) if isinstance(segment, Mapping) else frozenset()
        for segment in segments
    ]
    proposals: list[dict[str, Any]] = []
    for line in _profile_lines(projection.profile_content):
        line_terms = _content_terms(line)
        if len(line_terms) < _MIN_SHARED_TERMS:
            continue
        best_index, best_count = -1, 0
        for index, terms in enumerate(segment_terms):
            count = len(line_terms & terms)
            if count > best_count:
                best_index, best_count = index, count
        if best_count < _MIN_SHARED_TERMS:
            continue
        segment = segments[best_index]
        proposals.append(
            {
                "source_says": _normalize_space(str(segment.get("text") or "")),
                "anchors": [
                    {
                        "segment_index": best_index,
                        "start": segment.get("start"),
                        "end": segment.get("end"),
                    }
                ],
                "system_inference": _LOCAL_INFERENCE[language].format(count=best_count),
                "owner_link": line,
                "suggested_use": _LOCAL_SUGGESTED_USE[language],
            }
        )
        if len(proposals) >= _MAX_LOCAL_CONNECTIONS:
            break
    return tuple(proposals)


def produce_interest_overlay(
    *,
    vault_root: Path | str,
    active_scope_id: str | None,
    normalized: Mapping[str, Any],
) -> InterestOverlay:
    """Acquisition-time overlay: local deterministic proposals through governed admission."""

    return render_interest_overlay(
        vault_root=vault_root,
        active_scope_id=active_scope_id,
        normalized=normalized,
        connections=propose_local_connections(
            vault_root=vault_root,
            active_scope_id=active_scope_id,
            normalized=normalized,
        ),
    )


def _content_terms(value: object) -> frozenset[str]:
    if not isinstance(value, str):
        return frozenset()
    return frozenset(
        term
        for term in (match.casefold() for match in _TERM.findall(value))
        if len(term) >= _MIN_TERM_LENGTH and not term.isdigit() and term not in _STOP_TERMS
    )


def _admit_connection(
    candidate: object,
    segments: Sequence[object],
    profile_lines: Sequence[str],
    language: str,
) -> dict[str, Any] | str:
    """Return the admitted connection or the reason it was dropped."""

    if not isinstance(candidate, Mapping) or not all(isinstance(key, str) for key in candidate):
        return "connection_malformed"
    if set(candidate) - _CONNECTION_FIELDS:
        # Extra payloads (candidate handoffs, memory refs, profile bodies) are
        # never admitted as a side channel into the overlay.
        return "connection_foreign_field"

    anchors = candidate.get("anchors")
    if (
        not isinstance(anchors, list)
        or not anchors
        or not all(isinstance(a, Mapping) and validate_resolvable_anchor(a, segments) for a in anchors)
    ):
        return "source_anchor_unresolvable"
    source_says = _text(candidate.get("source_says"))
    if source_says is None:
        return "source_says_missing"
    anchored_text = _normalize_space(" ".join(_segment_text(segments, a) for a in anchors))
    if _normalize_space(source_says) not in anchored_text:
        # D6: the quotation must be original source wording, never a translation.
        return "source_says_not_in_anchored_source"

    fields: dict[str, str] = {"source_says": source_says}
    for name in ("system_inference", "owner_link", "suggested_use"):
        value = _text(candidate.get(name))
        if value is None:
            return f"{name}_missing"
        fields[name] = value

    owner_link = _normalize_space(fields["owner_link"])
    if len(owner_link.split()) < _MIN_OWNER_LINK_WORDS or not any(
        owner_link in line for line in profile_lines
    ):
        # The match signal must quote one approved profile entry, not a heading,
        # a cross-line span, or a stray word.
        return "owner_link_not_in_approved_profile"
    if any(_EMBED_OPENER in value for value in fields.values()):
        return "connection_contains_embed"
    normalized_fields = [_normalize_space(value).casefold() for value in fields.values()]
    if any(
        i != j and a in b for i, a in enumerate(normalized_fields) for j, b in enumerate(normalized_fields)
    ):
        return "fields_not_separated"
    for name in ("system_inference", "suggested_use"):
        if not validate_generated_language(fields[name], language):
            return f"{name}_language_mismatch"

    return {
        "source_says": fields["source_says"],
        "anchors": [_anchor_projection(segments, a) for a in anchors],
        "system_inference": fields["system_inference"],
        "owner_link": fields["owner_link"],
        "suggested_use": fields["suggested_use"],
    }


def _text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _normalize_space(value: str) -> str:
    return " ".join(value.split())


def _profile_lines(profile_content: str) -> tuple[str, ...]:
    """Approved profile entries with list markers removed; headings are not entries."""

    lines: list[str] = []
    for raw in profile_content.splitlines():
        line = raw.strip()
        if not line or _HEADING.match(line):
            continue
        line = _normalize_space(_LINE_MARKER.sub("", line))
        if line:
            lines.append(line)
    return tuple(lines)


def _segment_text(segments: Sequence[object], anchor: Mapping[str, Any]) -> str:
    segment = segments[int(anchor["segment_index"])]
    text = segment.get("text") if isinstance(segment, Mapping) else None
    return text if isinstance(text, str) else ""


def _anchor_projection(segments: Sequence[object], anchor: Mapping[str, Any]) -> dict[str, Any]:
    segment = segments[int(anchor["segment_index"])]
    projected: dict[str, Any] = {
        "segment_index": int(anchor["segment_index"]),
        "start": float(anchor["start"]),
        "end": float(anchor["end"]),
    }
    if isinstance(segment, Mapping) and segment.get("anchor"):
        projected["anchor"] = str(segment["anchor"])
    return projected


def _timestamp(seconds: float) -> str:
    whole = int(math.floor(seconds))
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _render_connection(connection: Mapping[str, Any], language: str) -> str:
    labels = _LABELS[language]
    stamps = ", ".join(_timestamp(anchor["start"]) for anchor in connection["anchors"])
    return "\n".join(
        (
            f"- **{labels['source_says']}** ({stamps}): “{_inline(connection['source_says'])}”",
            f"  - **{labels['system_inference']}:** {_inline(connection['system_inference'])}",
            f"  - **{labels['owner_link']}:** “{_inline(connection['owner_link'])}” "
            f"({labels['profile_version']} {connection['profile_version_id']})",
            f"  - **{labels['suggested_use']}:** {_inline(connection['suggested_use'])}",
        )
    )


def _inline(value: str) -> str:
    """Render one field as inert inline text (no links, emphasis, or code)."""

    return _MARKDOWN_ACTIVE.sub(r"\\\1", _normalize_space(value))


__all__ = [
    "INTEREST_OVERLAY_MODULE_ID",
    "NO_PROFILE_LINES",
    "InterestOverlay",
    "admit_profile_for_interest_overlay",
    "produce_interest_overlay",
    "propose_local_connections",
    "read_governed_profile_for_overlay",
    "render_interest_overlay",
]
