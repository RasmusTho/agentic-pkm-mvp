"""YSNV2-10 governed interest overlay tests (#4117).

Every test drives the production entry point ``render_interest_overlay``, which
admits profile state only through ``read_governed_profile_for_overlay``.  Allowed
fixtures are produced by the real ProfileAgent propose -> checked confirmation ->
governed write -> receipt path, so admission is never stubbed.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agents.profile_agent.runtime import (
    PROFILE_APPLY_ACTION_ID,
    ProfileAgent,
    ProfileUpdateCandidate,
    execute_profile_panel_actions,
    vault_profile_id,
)
from app.knowledge_acquisition import interest_overlay as overlay_module
from app.knowledge_acquisition.evidence_synthesis import validate_generated_language
from app.knowledge_acquisition.interest_overlay import (
    INTEREST_OVERLAY_MODULE_ID,
    NO_PROFILE_LINES,
    render_interest_overlay,
)
from app.knowledge_acquisition.note_renderer import render_review_required_note

pytestmark = pytest.mark.not_pg

_NOTE_PATH = "Profiles/Profile.md"
_SCOPE = "scope:work/project-alpha"
_OTHER_SCOPE = "scope:work/other-project"
_PROFILE_LINE = "Prefer local-first knowledge tools that keep data on the owner's machine."
_APPROVED_CONTENT = (
    f"<!--mimer:profile-scope scope_id={_SCOPE}-->\n\n## Interests\n\n- {_PROFILE_LINE}\n"
    "- Follow research on retrieval evaluation."
).rstrip()
_PENDING_LINE = "Interested in competitive cycling and marathon training plans."
_PENDING_CONTENT = f"<!--mimer:profile-scope scope_id={_SCOPE}-->\n\n## Interests\n\n- {_PENDING_LINE}"

_EN_SEGMENTS = [
    {"start": 0.0, "end": 10.0, "text": "Today we look at sync engines for notes.", "anchor": "seg-0"},
    {
        "start": 10.0,
        "end": 25.0,
        "text": "Our app keeps every file on your own disk and syncs peer to peer.",
        "anchor": "seg-1",
    },
    {"start": 25.0, "end": 40.0, "text": "Next we compare conflict resolution strategies.", "anchor": "seg-2"},
]
_EN_NORMALIZED = {"language": "en", "segments": _EN_SEGMENTS}
_ANCHOR_1 = {"segment_index": 1, "start": 10.0, "end": 25.0}
_INFERENCE_EN = "The product stores notes locally and synchronizes directly between devices."
_USE_EN = "Compare this design with the current vault sync setup before choosing a tool."


def _connection(**overrides: object) -> dict[str, object]:
    connection: dict[str, object] = {
        "source_says": "keeps every file on your own disk",
        "anchors": [dict(_ANCHOR_1)],
        "system_inference": _INFERENCE_EN,
        "owner_link": _PROFILE_LINE,
        "suggested_use": _USE_EN,
    }
    connection.update(overrides)
    return connection


def _new_profile_note(root: Path) -> tuple[Path, Path, str]:
    note_path = root / _NOTE_PATH
    note_path.parent.mkdir(parents=True)
    note_uuid = str(uuid4())
    note_path.write_text(
        f"---\nuuid: {note_uuid}\n---\n\n# Owner Profile\n\n## Interests\n\nThe profile starts empty.\n",
        encoding="utf-8",
    )
    return root, note_path, note_uuid


def _candidate(root: Path, note_uuid: str, content: str) -> ProfileUpdateCandidate:
    return ProfileUpdateCandidate(
        candidate_id=f"candidate-overlay-{uuid4().hex[:8]}",
        vault_id=vault_profile_id(root),
        profile_note_id=note_uuid,
        provenance_ref="conversation:2026-10-01:overlay-fixture",
        proposed_change="Record owner interests for the declared scope.",
        provenance="The owner stated these interests explicitly.",
        uncertainty="Scoped to the declared consumer scope.",
        proposed_content=content,
    )


def _propose(root: Path, note_uuid: str, content: str):
    return ProfileAgent(root, _NOTE_PATH).propose_candidate(_candidate(root, note_uuid, content))


def _check_proposal_box(note_path: Path) -> None:
    note_path.write_text(note_path.read_text(encoding="utf-8").replace("- [ ]", "- [x]"), encoding="utf-8")


def _approved_vault(root: Path, content: str = _APPROVED_CONTENT) -> tuple[Path, Path]:
    root, note_path, note_uuid = _new_profile_note(root)
    proposal = _propose(root, note_uuid, content)
    _check_proposal_box(note_path)
    action = SimpleNamespace(
        id=PROFILE_APPLY_ACTION_ID,
        option_id=proposal.option_id,
        label=f"Review ProfileAgent proposal {proposal.proposal_id}",
        checked=True,
        proposal_pending=True,
    )
    result = execute_profile_panel_actions([action], note_path=_NOTE_PATH, vault_root=root)
    assert [item.status for item in result] == ["triggered"]
    return root, note_path


def _vault_snapshot(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


class _ExplodingConnections:
    """Proves the no-profile path stops before inspecting any connection input."""

    def __iter__(self):
        raise AssertionError("connections must not be inspected without an admitted profile")

    def __len__(self) -> int:
        raise AssertionError("connections must not be inspected without an admitted profile")


def test_overlay_consumes_only_authorized_vault_wide_profile_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, note_path = _approved_vault(tmp_path / "vault")
    # Unrelated agent memory and secret material live in the same vault but are
    # never part of the governed projection.
    secret_line = "Private medical appointment on Friday with the cardiologist."
    (root / "Memory").mkdir()
    (root / "Memory" / "agent-memory.md").write_text(f"- {secret_line}\n", encoding="utf-8")

    reads: list[tuple[Path, str | None]] = []
    real_reader = overlay_module.read_governed_profile_for_overlay

    def _spy(vault_root, *, active_scope_id):
        reads.append((Path(vault_root), active_scope_id))
        return real_reader(vault_root, active_scope_id=active_scope_id)

    monkeypatch.setattr(overlay_module, "read_governed_profile_for_overlay", _spy)
    before = _vault_snapshot(root)

    allowed = render_interest_overlay(
        vault_root=root,
        active_scope_id=_SCOPE,
        normalized=_EN_NORMALIZED,
        connections=[
            _connection(),
            _connection(owner_link=secret_line),
            _connection(owner_link=_PENDING_LINE),
            _connection(profile_candidate={"proposed_content": _PENDING_CONTENT}),
        ],
    )

    assert reads == [(root, _SCOPE)]
    assert allowed.status == "connections"
    assert allowed.profile_scope_id == _SCOPE
    assert allowed.profile_version_id and allowed.profile_receipt_id
    assert [c["owner_link"] for c in allowed.connections] == [_PROFILE_LINE]
    assert allowed.dropped == (
        "owner_link_not_in_approved_profile",
        "owner_link_not_in_approved_profile",
        "connection_foreign_field",
    )
    assert secret_line not in allowed.section().content
    assert _PENDING_LINE not in allowed.section().content
    # Read-only: the overlay never writes the vault or the authority stream.
    assert _vault_snapshot(root) == before

    # Ungranted cross-scope read: the same approved profile is not admitted.
    cross = render_interest_overlay(
        vault_root=root, active_scope_id=_OTHER_SCOPE, normalized=_EN_NORMALIZED, connections=_ExplodingConnections()
    )
    assert cross.status == "no-profile"
    assert cross.reason == "profile_scope_mismatch"

    # A ProfileUpdateCandidate handoff / pending ProfileAgent proposal is not
    # profile state, even when its content is scope-bound.
    pending_root, _pending_note, pending_uuid = _new_profile_note(tmp_path / "pending-vault")
    _propose(pending_root, pending_uuid, _PENDING_CONTENT)
    pending = render_interest_overlay(
        vault_root=pending_root,
        active_scope_id=_SCOPE,
        normalized=_EN_NORMALIZED,
        connections=_ExplodingConnections(),
    )
    assert pending.status == "no-profile"
    assert pending.reason == "profile_not_receipt_bound"

    # A later pending proposal never displaces the admitted receipt-bound version.
    _propose(root, _note_uuid(note_path), _PENDING_CONTENT)
    still = render_interest_overlay(
        vault_root=root,
        active_scope_id=_SCOPE,
        normalized=_EN_NORMALIZED,
        connections=[_connection(owner_link=_PENDING_LINE), _connection()],
    )
    assert still.status == "connections"
    assert still.profile_version_id == allowed.profile_version_id
    assert [c["owner_link"] for c in still.connections] == [_PROFILE_LINE]


def _note_uuid(note_path: Path) -> str:
    text = note_path.read_text(encoding="utf-8")
    return text.split("uuid: ", 1)[1].split("\n", 1)[0].strip()


def test_overlay_connection_requires_anchor_and_owner_link_with_separated_fields(tmp_path: Path) -> None:
    root, _note_path = _approved_vault(tmp_path / "vault")

    overlay = render_interest_overlay(
        vault_root=root,
        active_scope_id=_SCOPE,
        normalized=_EN_NORMALIZED,
        connections=[
            _connection(),
            _connection(anchors=[]),
            _connection(anchors=[{"segment_index": 9, "start": 0.0, "end": 1.0}]),
            _connection(source_says="this sentence is not in the transcript"),
            _connection(system_inference=""),
            _connection(owner_link=None),
            _connection(suggested_use="   "),
            {key: value for key, value in _connection().items() if key != "suggested_use"},
            _connection(system_inference="keeps every file on your own disk"),
            _connection(suggested_use=_INFERENCE_EN),
            "not a mapping",
        ],
    )

    assert overlay.status == "connections"
    assert len(overlay.connections) == 1
    connection = overlay.connections[0]
    assert set(connection) == {
        "source_says",
        "anchors",
        "system_inference",
        "owner_link",
        "suggested_use",
        "profile_version_id",
        "profile_receipt_id",
    }
    assert connection["source_says"] == "keeps every file on your own disk"
    assert connection["anchors"] == [{"segment_index": 1, "start": 10.0, "end": 25.0, "anchor": "seg-1"}]
    assert connection["system_inference"] == _INFERENCE_EN
    assert connection["owner_link"] == _PROFILE_LINE
    assert connection["suggested_use"] == _USE_EN
    assert connection["profile_receipt_id"] == overlay.profile_receipt_id
    assert overlay.dropped == (
        "source_anchor_unresolvable",
        "source_anchor_unresolvable",
        "source_says_not_in_anchored_source",
        "system_inference_missing",
        "owner_link_missing",
        "suggested_use_missing",
        "suggested_use_missing",
        "fields_not_separated",
        "fields_not_separated",
        "connection_malformed",
    )

    # Four visibly separate fields render inside the non-authoritative proposal band.
    section = overlay.section()
    assert section.module_id == INTEREST_OVERLAY_MODULE_ID
    for label in ("Source says", "System inference", "Owner link", "Suggested use"):
        assert section.content.count(f"**{label}") == 1
    note = render_review_required_note(
        frontmatter={"type": "source-note"}, proposal_sections=[section], evidence=[("Source", "fixture")]
    )
    assert "keeps every file on your own disk" in note

    # An admitted profile with no supported connection renders one explicit line.
    empty = render_interest_overlay(
        vault_root=root, active_scope_id=_SCOPE, normalized=_EN_NORMALIZED, connections=[_connection(anchors=[])]
    )
    assert empty.status == "no-connections"
    assert empty.connections == ()
    assert len(empty.section().content.splitlines()) == 1


def test_overlay_cold_start_does_not_construct_local_behavior_profile(tmp_path: Path) -> None:
    # Prior YouTube source notes and watch behavior exist, but no governed profile.
    cold_root = tmp_path / "cold-vault"
    (cold_root / "Sources" / "YouTube").mkdir(parents=True)
    (cold_root / "Sources" / "YouTube" / "Prior note.md").write_text(
        f"# Prior note\n\n- {_PROFILE_LINE}\n", encoding="utf-8"
    )

    missing_root, missing_note, missing_uuid = _new_profile_note(tmp_path / "missing")
    pending_root, pending_note, pending_uuid = _new_profile_note(tmp_path / "pending")
    _propose(pending_root, pending_uuid, _APPROVED_CONTENT)
    checked_root, checked_note, checked_uuid = _new_profile_note(tmp_path / "checked")
    _propose(checked_root, checked_uuid, _APPROVED_CONTENT)
    _check_proposal_box(checked_note)
    stale_root, stale_note = _approved_vault(tmp_path / "stale")
    stale_note.write_text(
        stale_note.read_text(encoding="utf-8").replace(_PROFILE_LINE, "Tampered interest."), encoding="utf-8"
    )
    scoped_root, _scoped_note = _approved_vault(tmp_path / "scoped")

    cases = {
        "cold_start": (cold_root, _SCOPE, "authority_unavailable"),
        "missing": (missing_root, _SCOPE, "authority_unavailable"),
        "pending": (pending_root, _SCOPE, "profile_not_receipt_bound"),
        "checked_unreceipted": (checked_root, _SCOPE, "profile_not_receipt_bound"),
        "stale": (stale_root, _SCOPE, "profile_content_stale"),
        "out_of_scope": (scoped_root, _OTHER_SCOPE, "profile_scope_mismatch"),
        "no_active_scope": (scoped_root, None, "missing_or_invalid_active_scope"),
        "unavailable": (tmp_path / "does-not-exist", _SCOPE, "profile_authority_unavailable"),
    }
    for name, (root, scope, reason) in cases.items():
        before = _vault_snapshot(root)
        overlay = render_interest_overlay(
            vault_root=root, active_scope_id=scope, normalized=_EN_NORMALIZED, connections=_ExplodingConnections()
        )
        assert overlay.status == "no-profile", name
        assert overlay.reason == reason, name
        assert overlay.connections == () and overlay.dropped == (), name
        assert overlay.profile_version_id is None and overlay.profile_receipt_id is None, name
        content = overlay.section().content
        assert content.splitlines() == [NO_PROFILE_LINES["en"]], name
        assert _PROFILE_LINE not in content, name
        # No profile, authority stream, or cache is constructed from prior notes/behavior.
        assert _vault_snapshot(root) == before, name
    assert not (cold_root / ".mimer").exists()


def test_overlay_system_inference_and_suggested_use_follow_source_language_policy(tmp_path: Path) -> None:
    root, _note_path = _approved_vault(tmp_path / "vault")

    # Non-Swedish (French) source: generated fields are English; the quote stays French.
    fr_quote = "garde chaque fichier sur votre propre disque"
    fr_normalized = {
        "language": "fr",
        "segments": [
            {"start": 0.0, "end": 12.0, "text": f"Notre application {fr_quote} et synchronise en pair à pair."}
        ],
    }
    fr_anchor = [{"segment_index": 0, "start": 0.0, "end": 12.0}]
    french = render_interest_overlay(
        vault_root=root,
        active_scope_id=_SCOPE,
        normalized=fr_normalized,
        connections=[
            _connection(source_says=fr_quote, anchors=fr_anchor),
            # A translation presented as the quotation is not source wording.
            _connection(source_says="keeps every file on your own disk", anchors=fr_anchor),
            _connection(
                source_says=fr_quote,
                anchors=fr_anchor,
                system_inference="Le produit stocke les notes localement sur chaque appareil.",
            ),
        ],
    )
    assert french.system_language == "en"
    assert [c["source_says"] for c in french.connections] == [fr_quote]
    assert validate_generated_language(french.connections[0]["system_inference"], "en")
    assert validate_generated_language(french.connections[0]["suggested_use"], "en")
    assert french.dropped == ("source_says_not_in_anchored_source", "system_inference_language_mismatch")

    # Swedish-original source: generated fields are Swedish; English prose is refused.
    sv_quote = "sparar varje fil på din egen disk"
    sv_normalized = {
        "language": "sv-SE",
        "segments": [{"start": 0.0, "end": 12.0, "text": f"Vår app {sv_quote} och synkar direkt mellan enheter."}],
    }
    sv_inference = "Produkten lagrar anteckningarna lokalt och synkroniserar direkt mellan enheterna."
    sv_use = "Jämför den här lösningen med nuvarande synkronisering av valvet innan ett verktyg väljs."
    swedish = render_interest_overlay(
        vault_root=root,
        active_scope_id=_SCOPE,
        normalized=sv_normalized,
        connections=[
            _connection(source_says=sv_quote, anchors=fr_anchor, system_inference=sv_inference, suggested_use=sv_use),
            _connection(source_says=sv_quote, anchors=fr_anchor, system_inference=sv_inference),
        ],
    )
    assert swedish.system_language == "sv"
    assert [c["source_says"] for c in swedish.connections] == [sv_quote]
    assert swedish.connections[0]["system_inference"] == sv_inference
    assert swedish.dropped == ("suggested_use_language_mismatch",)
    assert "**Källan säger" in swedish.section().content

    # The explicit no-profile line itself follows D6.
    sv_cold = render_interest_overlay(
        vault_root=tmp_path / "empty", active_scope_id=_SCOPE, normalized=sv_normalized, connections=()
    )
    assert sv_cold.section().content.splitlines() == [NO_PROFILE_LINES["sv"]]
    assert validate_generated_language(NO_PROFILE_LINES["sv"], "sv")
    assert validate_generated_language(NO_PROFILE_LINES["en"], "en")
