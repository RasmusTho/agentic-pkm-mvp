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
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

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
_MIN_OWNER_LINK_CHARS = 8

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
    connections: Sequence[object],
) -> InterestOverlay:
    """Render four-part connections against the admitted governed profile only."""

    language = system_language_for(normalized.get("language"))
    projection = read_governed_profile_for_overlay(vault_root, active_scope_id=active_scope_id)
    if not projection.available or not projection.profile_content:
        # Stop: no connection is inspected and nothing is inferred locally.
        return InterestOverlay(status="no-profile", reason=projection.reason, system_language=language)

    segments = normalized.get("segments")
    if not isinstance(segments, list):
        segments = []
    profile_text = _normalize_space(projection.profile_content)
    kept: list[Mapping[str, Any]] = []
    dropped: list[str] = []
    for candidate in connections:
        outcome = _admit_connection(candidate, segments, profile_text, language)
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


def _admit_connection(
    candidate: object,
    segments: Sequence[object],
    profile_text: str,
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
    if len(owner_link) < _MIN_OWNER_LINK_CHARS or owner_link not in profile_text:
        return "owner_link_not_in_approved_profile"
    normalized_fields = {_normalize_space(value).casefold() for value in fields.values()}
    if len(normalized_fields) != len(fields):
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
    return f"{whole // 60:02d}:{whole % 60:02d}"


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
    return _normalize_space(value).replace("*", r"\*").replace("_", r"\_")


__all__ = [
    "INTEREST_OVERLAY_MODULE_ID",
    "NO_PROFILE_LINES",
    "InterestOverlay",
    "admit_profile_for_interest_overlay",
    "read_governed_profile_for_overlay",
    "render_interest_overlay",
]
