"""#2986 (G2-1) -- ``finding_id`` is content-derived and stable across reruns.

Spec: ``docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md`` §1:
``finding_id = hash(note_uuid, class, span, proposed_change)``.
"""
from __future__ import annotations

import pytest

from app.curation.findings import (
    CurationFinding,
    FindingClass,
    FindingTrack,
    InvalidFindingClassError,
    MECHANICAL_ALLOWLIST,
    compute_finding_id,
    track_for_class,
)


def test_finding_id_stable_across_repeated_calls() -> None:
    """Identical inputs always produce the identical id (no randomness/sequence)."""
    id_1 = compute_finding_id(
        note_uuid="uuid-1",
        finding_class=FindingClass.STRUCTURE_ORPHAN,
        span="L1:body",
        proposed_change="link this note",
    )
    id_2 = compute_finding_id(
        note_uuid="uuid-1",
        finding_class=FindingClass.STRUCTURE_ORPHAN,
        span="L1:body",
        proposed_change="link this note",
    )
    assert id_1 == id_2


@pytest.mark.parametrize(
    "field_name,override",
    [
        ("note_uuid", "uuid-2"),
        ("span", "L2:body"),
        ("proposed_change", "different proposed change"),
    ],
)
def test_finding_id_changes_when_any_tracked_field_changes(field_name: str, override: str) -> None:
    """The id changes if and only if one of the four tracked fields changes."""
    base_kwargs = dict(
        note_uuid="uuid-1",
        finding_class=FindingClass.STRUCTURE_ORPHAN,
        span="L1:body",
        proposed_change="link this note",
    )
    base_id = compute_finding_id(**base_kwargs)

    changed_kwargs = dict(base_kwargs)
    changed_kwargs[field_name] = override
    changed_id = compute_finding_id(**changed_kwargs)

    assert changed_id != base_id


def test_finding_id_changes_when_class_changes() -> None:
    base_kwargs = dict(
        note_uuid="uuid-1",
        span="L1:body",
        proposed_change="link this note",
    )
    id_orphan = compute_finding_id(finding_class=FindingClass.STRUCTURE_ORPHAN, **base_kwargs)
    id_gap = compute_finding_id(finding_class=FindingClass.STRUCTURE_GAP, **base_kwargs)
    assert id_orphan != id_gap


def test_curation_finding_create_derives_matching_id() -> None:
    """``CurationFinding.create`` derives an id identical to calling the hash directly."""
    finding = CurationFinding.create(
        note_uuid="uuid-1",
        finding_class=FindingClass.STRUCTURE_ORPHAN,
        span="L1:body",
        observed="no inbound links",
        proposed="link this note",
    )
    expected = compute_finding_id(
        note_uuid="uuid-1",
        finding_class=FindingClass.STRUCTURE_ORPHAN,
        span="L1:body",
        proposed_change="link this note",
    )
    assert finding.finding_id == expected


# ---------------------------------------------------------------------------
# Closed-enum / track-derivation contract
# ---------------------------------------------------------------------------


def test_track_derives_from_class_membership_never_confidence() -> None:
    """Track is decided purely by class membership in MECHANICAL_ALLOWLIST."""
    for finding_class in FindingClass:
        expected_track = (
            FindingTrack.AUTO_FIX if finding_class in MECHANICAL_ALLOWLIST else FindingTrack.PROPOSE
        )
        assert track_for_class(finding_class) is expected_track


def test_unknown_class_fails_loud_with_no_default_track() -> None:
    """An unrecognized class raises rather than silently defaulting a track."""
    with pytest.raises(InvalidFindingClassError):
        track_for_class("class.not_in_the_closed_enum")


def test_curation_finding_create_rejects_unknown_class() -> None:
    with pytest.raises(InvalidFindingClassError):
        CurationFinding.create(
            note_uuid="uuid-1",
            finding_class="class.not_in_the_closed_enum",
            span="L1:body",
            observed="x",
            proposed="y",
        )
