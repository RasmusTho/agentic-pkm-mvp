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
from app.knowledge.profile_consumer_projection import rebuild_profile_projection
from app.knowledge_acquisition.interest_overlay import (
    admit_profile_for_interest_overlay,
    read_governed_profile_for_overlay,
)


_NOTE_PATH = "Profiles/Profile.md"
_SCOPE = "scope:work/project-alpha"
_SCOPE_MARKER = f"<!--mimer:profile-scope scope_id={_SCOPE}-->"
_INITIAL_CONTENT = "## Preferences\n\nThe owner profile starts empty."
_PENDING_CONTENT = "## Preferences\n\nThis pending proposal has no scope binding."
_APPROVED_CONTENT = f"{_SCOPE_MARKER}\n\n## Preferences\n\nPrefer direct answers."


@pytest.fixture
def profile_note(tmp_path: Path) -> tuple[Path, Path, str]:
    return _new_profile_note(tmp_path / "vault")


def _new_profile_note(root: Path) -> tuple[Path, Path, str]:
    note_path = root / _NOTE_PATH
    note_path.parent.mkdir(parents=True)
    note_uuid = str(uuid4())
    note_path.write_text(
        f"---\nuuid: {note_uuid}\n---\n\n# Owner Profile\n\n{_INITIAL_CONTENT}\n",
        encoding="utf-8",
    )
    return root, note_path, note_uuid


def _candidate(
    root: Path,
    note_uuid: str,
    *,
    content: str = _APPROVED_CONTENT,
) -> ProfileUpdateCandidate:
    return ProfileUpdateCandidate(
        candidate_id="candidate-consumer-projection-01",
        vault_id=vault_profile_id(root),
        profile_note_id=note_uuid,
        provenance_ref="conversation:2026-09-29:profile-scope",
        proposed_change="Record the owner preference for direct answers.",
        provenance="The owner explicitly requested this preference.",
        uncertainty="The preference is scoped to the declared consumer scope.",
        proposed_content=content,
    )


def _complete_profile_write(
    root: Path,
    note_path: Path,
    note_uuid: str,
    *,
    content: str = _APPROVED_CONTENT,
) -> None:
    agent = ProfileAgent(root, _NOTE_PATH)
    proposal = agent.propose_candidate(_candidate(root, note_uuid, content=content))
    # The browser checkbox projection is covered by its own production tests;
    # this helper feeds the same source-backed checked action to ProfileAgent's
    # real write/readback path.
    note_path.write_text(
        note_path.read_text(encoding="utf-8").replace("- [ ]", "- [x]"),
        encoding="utf-8",
    )
    action = SimpleNamespace(
        id=PROFILE_APPLY_ACTION_ID,
        option_id=proposal.option_id,
        label=f"Review ProfileAgent proposal {proposal.proposal_id}",
        checked=True,
        proposal_pending=True,
    )
    result = execute_profile_panel_actions(
        [action],
        note_path=_NOTE_PATH,
        vault_root=root,
    )
    assert [item.status for item in result] == ["triggered"]
    assert note_path.read_text(encoding="utf-8").endswith(content + "\n")


def test_projection_rebuilds_only_from_approved_versions_and_receipts(
    profile_note: tuple[Path, Path, str],
) -> None:
    root, note_path, note_uuid = profile_note
    before = note_path.read_bytes()

    # A durable proposal is not a consumer projection until the terminal
    # receipt exists.
    agent = ProfileAgent(root, _NOTE_PATH)
    agent.propose_candidate(_candidate(root, note_uuid))
    pending = rebuild_profile_projection(root, active_scope_id=_SCOPE)
    assert pending.status == "no-profile"
    assert pending.reason == "profile_not_receipt_bound"

    _complete_profile_write(root, note_path, note_uuid)
    after_write = note_path.read_bytes()
    first = rebuild_profile_projection(root, active_scope_id=_SCOPE)
    restarted = rebuild_profile_projection(root, active_scope_id=_SCOPE)

    assert first.available
    assert restarted == first
    assert first.profile_content == "## Preferences\n\nPrefer direct answers."
    assert first.receipt_id and first.version_id
    assert after_write != before
    assert note_path.read_bytes() == after_write


def test_consumer_admission_requires_same_scope_approved_receipt_bound_version(
    profile_note: tuple[Path, Path, str],
) -> None:
    root, note_path, note_uuid = profile_note
    _complete_profile_write(root, note_path, note_uuid)

    admitted = admit_profile_for_interest_overlay(root, active_scope_id=_SCOPE)
    denied = admit_profile_for_interest_overlay(
        root,
        active_scope_id="scope:work/other-project",
    )

    assert admitted.available
    assert admitted.scope_id == _SCOPE
    assert admitted.vault_id != admitted.scope_id
    assert denied.status == "no-profile"
    assert denied.reason == "profile_scope_mismatch"


def test_nonconsumable_profile_states_return_explicit_no_profile(
    profile_note: tuple[Path, Path, str],
    tmp_path: Path,
) -> None:
    root, note_path, note_uuid = profile_note

    assert rebuild_profile_projection(root, active_scope_id=_SCOPE).status == "no-profile"

    agent = ProfileAgent(root, _NOTE_PATH)
    agent.propose_candidate(_candidate(root, note_uuid, content=_PENDING_CONTENT))
    assert rebuild_profile_projection(root, active_scope_id=_SCOPE).status == "no-profile"

    # Frontmatter is outside the approved-content digest and cannot supply a
    # missing scope binding.
    note_text = note_path.read_text(encoding="utf-8")
    note_path.write_text(note_text.replace("uuid: ", "scope_id: scope:work/project-alpha\nuuid: "), encoding="utf-8")
    assert rebuild_profile_projection(root, active_scope_id=_SCOPE).status == "no-profile"

    no_scope_root, no_scope_note, no_scope_uuid = _new_profile_note(tmp_path / "no-scope-vault")
    _complete_profile_write(
        no_scope_root,
        no_scope_note,
        no_scope_uuid,
        content="## Preferences\n\nApproved but scope omitted.",
    )
    assert rebuild_profile_projection(no_scope_root, active_scope_id=_SCOPE).reason == (
        "profile_scope_missing_or_malformed"
    )

    # A real approved receipt becomes stale as soon as the receipt-bound body
    # changes, even when the authority stream itself remains available. Use a
    # fresh vault so the pending proposal above remains a separate refusal case.
    stale_root, stale_note_path, stale_note_uuid = _new_profile_note(tmp_path / "stale-vault")
    _complete_profile_write(stale_root, stale_note_path, stale_note_uuid)
    stale_note_path.write_text(
        stale_note_path.read_text(encoding="utf-8").replace(
            "Prefer direct answers.", "Tampered content."
        ),
        encoding="utf-8",
    )
    stale = rebuild_profile_projection(stale_root, active_scope_id=_SCOPE)
    assert stale.status == "no-profile"
    assert stale.reason == "profile_content_stale"


def test_youtube_overlay_is_read_only_consumer_of_governed_profile_projection(
    profile_note: tuple[Path, Path, str],
) -> None:
    root, note_path, note_uuid = profile_note
    _complete_profile_write(root, note_path, note_uuid)
    note_before = note_path.read_bytes()
    authority_before = next((root / ".mimer" / "profile-authority").glob("*.jsonl")).read_bytes()

    admitted = read_governed_profile_for_overlay(root, active_scope_id=_SCOPE)
    cold_start = read_governed_profile_for_overlay(root, active_scope_id=None)

    assert admitted.available
    assert cold_start.status == "no-profile"
    assert note_path.read_bytes() == note_before
    assert next((root / ".mimer" / "profile-authority").glob("*.jsonl")).read_bytes() == authority_before
