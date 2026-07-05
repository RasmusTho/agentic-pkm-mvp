"""``CurationFinding`` data shape + the closed, versioned class enum.

Spec: ``docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md`` §1.

Design constraints carried over verbatim from the spec (do not relax these
without an owner-ratified ADR):

- The class enum is **closed**. ``track_for_class`` is the only place track
  is derived, and it derives strictly from class membership in
  ``MECHANICAL_ALLOWLIST`` -- never from confidence, never from an LLM
  output. Any class outside the enum fails loud (:class:`InvalidFindingClassError`);
  there is no default track.
- ``finding_id`` is content-derived: ``hash(note_uuid, class, span, proposed_change)``.
  Two lint passes over an unchanged vault must produce byte-identical ids, so
  reruns are provably idempotent no-ops.
- This slice (G2-1) only ever emits ``propose``-track findings (the lint
  checks below are all propose-track classes). The ``auto_fix`` track exists
  in the enum/table because the class->track mapping is shared substrate for
  later slices (G2-2/G2-3); no auto-apply code path exists yet.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum


class InvalidFindingClassError(ValueError):
    """Raised when a finding class is not a member of the closed enum.

    The engine must fail loud here -- there is no default/fallback track for
    an unrecognized class (spec §1: "anything else -> invalid: engine fails
    loud; no default track").
    """


class FindingTrack(str, Enum):
    AUTO_FIX = "auto_fix"
    PROPOSE = "propose"


class LanguageVerdict(str, Enum):
    SV = "sv"
    EN = "en"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class FindingClass(str, Enum):
    """The closed, versioned curation-finding class enum (spec §1 table).

    Adding a class here is a versioned-artifact change, not a scattered code
    constant -- it is the single place that may mint a class, and the single
    place ``track_for_class`` consults for the class -> track wall.
    """

    LINK_BROKEN_WIKILINK = "link.broken_wikilink"
    LINK_DEAD_EXTERNAL = "link.dead_external"
    MARKDOWN_MALFORMED_SYNTAX = "markdown.malformed_syntax"
    FRONTMATTER_SCHEMA_VIOLATION = "frontmatter.schema_violation"
    TEXT_MISSPELLING = "text.misspelling"
    TEXT_GRAMMAR = "text.grammar"
    TEXT_TRANSCRIPTION_ARTIFACT = "text.transcription_artifact"
    CONTRADICTION_CLAIM_CONFLICT = "contradiction.claim_conflict"
    STRUCTURE_ORPHAN = "structure.orphan"
    STRUCTURE_GAP = "structure.gap"
    STRUCTURE_STALE_CLAIM = "structure.stale_claim"

    # Cognitive Expansion -- Connect (EXP-1, #2994). Non-amendably propose-track:
    # see ``CONNECT_FINDING_CLASSES`` below -- no configuration, flag, or future
    # slice may move a `connect.*` class onto ``MECHANICAL_ALLOWLIST``.
    # Spec: docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md §1.1.
    CONNECT_RELATED_UNLINKED = "connect.related_unlinked"
    CONNECT_THEMATIC_LINK = "connect.thematic_link"
    CONNECT_CLUSTER_EMERGENCE = "connect.cluster_emergence"


# Closed mechanical-allowlist: classes whose track is `auto_fix`. Membership
# here is what decides the track (spec §1: "class ∈ MECHANICAL_ALLOWLIST ->
# auto_fix else -> propose") -- never confidence, never LLM output. This
# slice (G2-1) never exercises the auto_fix branch operationally (no writer
# exists yet; that is G2-2/G2-3), but the mapping is defined once here so
# later slices share one wall instead of re-deriving it.
MECHANICAL_ALLOWLIST: frozenset[FindingClass] = frozenset(
    {
        FindingClass.LINK_BROKEN_WIKILINK,
        FindingClass.MARKDOWN_MALFORMED_SYNTAX,
        FindingClass.FRONTMATTER_SCHEMA_VIOLATION,
        FindingClass.TEXT_MISSPELLING,
        FindingClass.TEXT_TRANSCRIPTION_ARTIFACT,
    }
)

# Every lint check in this slice (G2-1) only ever emits classes from this set.
# All are propose-track by the table (§1): vault-health lint findings "imply
# meaning" per the spec, so none of the eight initial checks auto-applies.
LINT_FINDING_CLASSES: frozenset[FindingClass] = frozenset(
    {
        FindingClass.LINK_BROKEN_WIKILINK,
        FindingClass.LINK_DEAD_EXTERNAL,
        FindingClass.FRONTMATTER_SCHEMA_VIOLATION,
        FindingClass.STRUCTURE_ORPHAN,
        FindingClass.STRUCTURE_GAP,
        FindingClass.STRUCTURE_STALE_CLAIM,
    }
)

# Cognitive Expansion -- Connect (EXP-1, #2994) finding classes. Every member is,
# and must remain, disjoint from ``MECHANICAL_ALLOWLIST`` -- this is asserted at
# import time below so the propose-track mapping is a construction-level
# guarantee, not a runtime check alone (spec §1.1: "a `connect.*` class on
# auto-fix is a contract violation, not a config choice").
CONNECT_FINDING_CLASSES: frozenset[FindingClass] = frozenset(
    {
        FindingClass.CONNECT_RELATED_UNLINKED,
        FindingClass.CONNECT_THEMATIC_LINK,
        FindingClass.CONNECT_CLUSTER_EMERGENCE,
    }
)

assert CONNECT_FINDING_CLASSES.isdisjoint(MECHANICAL_ALLOWLIST), (
    "connect.* classes must never appear in MECHANICAL_ALLOWLIST -- this would "
    "silently move a Connect finding onto the auto_fix track, violating the "
    "non-amendable propose-track mapping (EXPANSION_CONNECT_AND_CREATE.md §1.1)"
)


def track_for_class(finding_class: FindingClass | str) -> FindingTrack:
    """Derive the track for a class -- the only place this derivation happens.

    Raises :class:`InvalidFindingClassError` for any value outside the closed
    enum. Never guesses a default track.
    """
    try:
        resolved = FindingClass(finding_class)
    except ValueError as exc:
        raise InvalidFindingClassError(
            f"{finding_class!r} is not a member of the closed FindingClass enum; "
            "the engine fails loud rather than default a track"
        ) from exc
    if resolved in MECHANICAL_ALLOWLIST:
        return FindingTrack.AUTO_FIX
    return FindingTrack.PROPOSE


def compute_finding_id(
    *,
    note_uuid: str,
    finding_class: FindingClass | str,
    span: str,
    proposed_change: str,
) -> str:
    """Content-derived, stable finding id.

    ``hash(note_uuid, class, span, proposed_change)`` per spec §1. Never
    random/sequential: identical inputs always produce the identical id, so a
    rerun over an unchanged vault is a provable no-op, and the id changes if
    and only if one of these four fields changes.
    """
    resolved_class = FindingClass(finding_class).value
    digest_input = "\x1f".join([note_uuid, resolved_class, span, proposed_change])
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CurationFinding:
    """One curation finding (spec §1 schema).

    ``finding_id`` and ``track`` are always derived (never passed in as
    independent truth) so a finding can never be constructed in an
    inconsistent state -- see :meth:`create`.
    """

    finding_id: str
    note_uuid: str
    finding_class: FindingClass
    track: FindingTrack
    span: str
    observed: str
    proposed: str
    evidence: tuple[str, ...] = field(default_factory=tuple)
    language_verdict: LanguageVerdict = LanguageVerdict.UNKNOWN
    reversal: tuple[str, str] | None = None  # (revert_marker_id, receipt_id); auto_fix only

    @staticmethod
    def create(
        *,
        note_uuid: str,
        finding_class: FindingClass | str,
        span: str,
        observed: str,
        proposed: str,
        evidence: tuple[str, ...] = (),
        language_verdict: LanguageVerdict = LanguageVerdict.UNKNOWN,
        reversal: tuple[str, str] | None = None,
    ) -> "CurationFinding":
        """Construct a finding with a derived id and a derived track.

        This is the only supported constructor for production call sites:
        both ``finding_id`` and ``track`` are computed here, never accepted
        as caller-supplied values, so it is impossible to build a finding
        whose id doesn't match its own content or whose track disagrees with
        the closed class->track wall.
        """
        try:
            resolved_class = FindingClass(finding_class)
        except ValueError as exc:
            raise InvalidFindingClassError(
                f"{finding_class!r} is not a member of the closed FindingClass enum; "
                "the engine fails loud rather than default a track"
            ) from exc
        resolved_track = track_for_class(resolved_class)
        finding_id = compute_finding_id(
            note_uuid=note_uuid,
            finding_class=resolved_class,
            span=span,
            proposed_change=proposed,
        )
        return CurationFinding(
            finding_id=finding_id,
            note_uuid=note_uuid,
            finding_class=resolved_class,
            track=resolved_track,
            span=span,
            observed=observed,
            proposed=proposed,
            evidence=tuple(evidence),
            language_verdict=language_verdict,
            reversal=reversal,
        )


__all__ = [
    "CurationFinding",
    "FindingClass",
    "FindingTrack",
    "InvalidFindingClassError",
    "LanguageVerdict",
    "CONNECT_FINDING_CLASSES",
    "LINT_FINDING_CLASSES",
    "MECHANICAL_ALLOWLIST",
    "compute_finding_id",
    "track_for_class",
]
