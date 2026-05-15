"""
TDD tests for app/services/companion_eligibility.py

Companion eligibility policy:
- system_path: note is inside the system/generated folder → ineligible
- placeholder_title: filename stem is a known placeholder → ineligible
- empty_note: note has no meaningful non-frontmatter content → ineligible
- cooldown_active: note mtime is too recent → ineligible, retry after cooldown
- eligible: all checks pass → eligible

Cooldown settings:
  COMPANION_CREATE_COOLDOWN_SECONDS (env, vault settings, default 60)
  COMPANION_RENAME_COOLDOWN_SECONDS (env, vault settings, default 20)
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.services.companion_eligibility import (
    check_companion_eligibility,
    has_meaningful_content,
    is_placeholder_title,
    load_companion_settings,
)


# ---------------------------------------------------------------------------
# is_placeholder_title
# ---------------------------------------------------------------------------

class TestIsPlaceholderTitle:
    def test_namnlos_ascii_is_placeholder(self) -> None:
        assert is_placeholder_title("Namnlos") is True

    def test_namnlös_umlaut_is_placeholder(self) -> None:
        assert is_placeholder_title("Namnlös") is True

    def test_namnlos_lowercase_is_placeholder(self) -> None:
        assert is_placeholder_title("namnlös") is True

    def test_namnlos_with_number_is_placeholder(self) -> None:
        assert is_placeholder_title("Namnlös 1") is True
        assert is_placeholder_title("Namnlos 2") is True

    def test_untitled_is_placeholder(self) -> None:
        assert is_placeholder_title("Untitled") is True

    def test_untitled_with_number_is_placeholder(self) -> None:
        assert is_placeholder_title("Untitled 3") is True

    def test_new_note_is_placeholder(self) -> None:
        assert is_placeholder_title("New note") is True
        assert is_placeholder_title("New Note") is True

    def test_unnamed_is_placeholder(self) -> None:
        assert is_placeholder_title("Unnamed") is True

    def test_real_title_is_not_placeholder(self) -> None:
        assert is_placeholder_title("My Important Note") is False
        assert is_placeholder_title("Project Plan 2026") is False
        assert is_placeholder_title("Namnlöst beslut") is False  # Swedish, but not placeholder

    def test_empty_string_is_placeholder(self) -> None:
        assert is_placeholder_title("") is True


# ---------------------------------------------------------------------------
# has_meaningful_content
# ---------------------------------------------------------------------------

class TestHasMeaningfulContent:
    def test_empty_string_has_no_content(self) -> None:
        assert has_meaningful_content("") is False

    def test_whitespace_only_has_no_content(self) -> None:
        assert has_meaningful_content("   \n\n\t  ") is False

    def test_single_word_is_meaningful(self) -> None:
        assert has_meaningful_content("Hello") is True

    def test_full_sentence_is_meaningful(self) -> None:
        assert has_meaningful_content("This note contains meaningful information.") is True

    def test_only_headings_are_not_meaningful(self) -> None:
        # A heading without any body text is still not meaningful
        assert has_meaningful_content("# Heading only") is False

    def test_heading_with_body_is_meaningful(self) -> None:
        assert has_meaningful_content("# Heading\n\nSome body text here.") is True

    def test_horizontal_rule_only_is_not_meaningful(self) -> None:
        assert has_meaningful_content("---\n---\n\n---") is False

    def test_newlines_only_is_not_meaningful(self) -> None:
        assert has_meaningful_content("\n\n\n") is False


# ---------------------------------------------------------------------------
# check_companion_eligibility — system_path
# ---------------------------------------------------------------------------

class TestSystemPathCheck:
    def test_note_under_system_is_ineligible(self, tmp_path: Path) -> None:
        note = tmp_path / "_system" / "companions" / "some.md"
        note.parent.mkdir(parents=True)
        note.write_text("---\n---\nBody\n", encoding="utf-8")
        result = check_companion_eligibility(note, tmp_path)
        assert result.eligible is False
        assert result.reason == "system_path"

    def test_note_under_system_subfolder_is_ineligible(self, tmp_path: Path) -> None:
        note = tmp_path / "_system" / "settings" / "config.md"
        note.parent.mkdir(parents=True)
        note.write_text("---\n---\nConfig\n", encoding="utf-8")
        result = check_companion_eligibility(note, tmp_path)
        assert result.eligible is False
        assert result.reason == "system_path"

    def test_note_outside_system_not_rejected_for_system_path(self, tmp_path: Path) -> None:
        note = tmp_path / "Notes" / "real.md"
        note.parent.mkdir(parents=True)
        note.write_text("Content here.", encoding="utf-8")
        # Even if ineligible for another reason, should not be system_path
        result = check_companion_eligibility(
            note, tmp_path,
            raw_body="Content here.",
            file_mtime=time.time() - 200,
            cooldown_seconds=60.0,
        )
        assert result.reason != "system_path"


# ---------------------------------------------------------------------------
# check_companion_eligibility — placeholder_title
# ---------------------------------------------------------------------------

class TestPlaceholderTitleCheck:
    def test_namnlos_file_is_ineligible(self, tmp_path: Path) -> None:
        note = tmp_path / "Namnlös.md"
        note.write_text("", encoding="utf-8")
        result = check_companion_eligibility(
            note, tmp_path,
            raw_body="",
            file_mtime=time.time() - 200,
            cooldown_seconds=60.0,
        )
        assert result.eligible is False
        assert result.reason == "placeholder_title"

    def test_untitled_file_is_ineligible(self, tmp_path: Path) -> None:
        note = tmp_path / "Untitled.md"
        note.write_text("", encoding="utf-8")
        result = check_companion_eligibility(
            note, tmp_path,
            raw_body="",
            file_mtime=time.time() - 200,
            cooldown_seconds=60.0,
        )
        assert result.eligible is False
        assert result.reason == "placeholder_title"

    def test_real_title_file_is_not_rejected_for_placeholder(self, tmp_path: Path) -> None:
        note = tmp_path / "My Note.md"
        note.write_text("Some content.", encoding="utf-8")
        result = check_companion_eligibility(
            note, tmp_path,
            raw_body="Some content.",
            file_mtime=time.time() - 200,
            cooldown_seconds=60.0,
        )
        assert result.reason != "placeholder_title"


# ---------------------------------------------------------------------------
# check_companion_eligibility — empty_note
# ---------------------------------------------------------------------------

class TestEmptyNoteCheck:
    def test_empty_body_is_ineligible(self, tmp_path: Path) -> None:
        note = tmp_path / "My Note.md"
        note.write_text("", encoding="utf-8")
        result = check_companion_eligibility(
            note, tmp_path,
            raw_body="",
            file_mtime=time.time() - 200,
            cooldown_seconds=60.0,
        )
        assert result.eligible is False
        assert result.reason == "empty_note"

    def test_whitespace_only_body_is_ineligible(self, tmp_path: Path) -> None:
        note = tmp_path / "My Note.md"
        note.write_text("   \n\n", encoding="utf-8")
        result = check_companion_eligibility(
            note, tmp_path,
            raw_body="   \n\n",
            file_mtime=time.time() - 200,
            cooldown_seconds=60.0,
        )
        assert result.eligible is False
        assert result.reason == "empty_note"

    def test_heading_only_body_is_ineligible(self, tmp_path: Path) -> None:
        note = tmp_path / "My Note.md"
        note.write_text("# Just a heading", encoding="utf-8")
        result = check_companion_eligibility(
            note, tmp_path,
            raw_body="# Just a heading",
            file_mtime=time.time() - 200,
            cooldown_seconds=60.0,
        )
        assert result.eligible is False
        assert result.reason == "empty_note"

    def test_body_with_content_is_not_rejected_for_empty(self, tmp_path: Path) -> None:
        note = tmp_path / "My Note.md"
        note.write_text("Real content here.", encoding="utf-8")
        result = check_companion_eligibility(
            note, tmp_path,
            raw_body="Real content here.",
            file_mtime=time.time() - 200,
            cooldown_seconds=60.0,
        )
        assert result.reason != "empty_note"


# ---------------------------------------------------------------------------
# check_companion_eligibility — cooldown_active
# ---------------------------------------------------------------------------

class TestCooldownCheck:
    def test_recently_created_note_is_in_cooldown(self, tmp_path: Path) -> None:
        note = tmp_path / "My Note.md"
        note.write_text("Some content.", encoding="utf-8")
        now = time.time()
        result = check_companion_eligibility(
            note, tmp_path,
            raw_body="Some content.",
            file_mtime=now - 5,  # 5 seconds ago — within 60s cooldown
            cooldown_seconds=60.0,
            now_timestamp=now,
        )
        assert result.eligible is False
        assert result.reason == "cooldown_active"

    def test_next_check_after_set_when_cooldown_active(self, tmp_path: Path) -> None:
        note = tmp_path / "My Note.md"
        note.write_text("Some content.", encoding="utf-8")
        now = time.time()
        mtime = now - 10  # 10s ago, 60s cooldown → 50s remaining
        result = check_companion_eligibility(
            note, tmp_path,
            raw_body="Some content.",
            file_mtime=mtime,
            cooldown_seconds=60.0,
            now_timestamp=now,
        )
        assert result.eligible is False
        assert result.next_check_after is not None
        assert result.next_check_after > now  # future timestamp

    def test_stable_note_is_not_in_cooldown(self, tmp_path: Path) -> None:
        note = tmp_path / "My Note.md"
        note.write_text("Some content.", encoding="utf-8")
        now = time.time()
        result = check_companion_eligibility(
            note, tmp_path,
            raw_body="Some content.",
            file_mtime=now - 120,  # 2 minutes ago — beyond 60s cooldown
            cooldown_seconds=60.0,
            now_timestamp=now,
        )
        assert result.reason != "cooldown_active"

    def test_zero_cooldown_disables_cooldown_check(self, tmp_path: Path) -> None:
        note = tmp_path / "My Note.md"
        note.write_text("Some content.", encoding="utf-8")
        now = time.time()
        result = check_companion_eligibility(
            note, tmp_path,
            raw_body="Some content.",
            file_mtime=now - 1,  # 1 second ago
            cooldown_seconds=0.0,  # disabled
            now_timestamp=now,
        )
        # With cooldown disabled, should not hit cooldown_active
        assert result.reason != "cooldown_active"


# ---------------------------------------------------------------------------
# check_companion_eligibility — eligible (all checks pass)
# ---------------------------------------------------------------------------

class TestEligible:
    def test_real_note_with_content_and_stable_mtime_is_eligible(self, tmp_path: Path) -> None:
        note = tmp_path / "My Important Note.md"
        note.write_text("Some real content here.", encoding="utf-8")
        now = time.time()
        result = check_companion_eligibility(
            note, tmp_path,
            raw_body="Some real content here.",
            file_mtime=now - 120,
            cooldown_seconds=60.0,
            now_timestamp=now,
        )
        assert result.eligible is True
        assert result.reason == "eligible"
        assert result.next_check_after is None


# ---------------------------------------------------------------------------
# Priority: system_path checked before placeholder/empty/cooldown
# ---------------------------------------------------------------------------

class TestEligibilityPriority:
    def test_system_path_takes_priority_over_other_checks(self, tmp_path: Path) -> None:
        """system_path should be reported even if other checks would also fail."""
        note = tmp_path / "_system" / "companions" / "Namnlös.md"
        note.parent.mkdir(parents=True)
        note.write_text("", encoding="utf-8")
        result = check_companion_eligibility(
            note, tmp_path,
            raw_body="",
            file_mtime=time.time() - 1,
            cooldown_seconds=60.0,
        )
        assert result.reason == "system_path"

    def test_placeholder_title_checked_before_empty(self, tmp_path: Path) -> None:
        """Placeholder title is checked before empty_note."""
        note = tmp_path / "Namnlös.md"
        note.write_text("", encoding="utf-8")
        result = check_companion_eligibility(
            note, tmp_path,
            raw_body="",
            file_mtime=time.time() - 200,
            cooldown_seconds=60.0,
        )
        assert result.reason == "placeholder_title"


# ---------------------------------------------------------------------------
# load_companion_settings
# ---------------------------------------------------------------------------

class TestLoadCompanionSettings:
    def test_returns_default_cooldown_when_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COMPANION_CREATE_COOLDOWN_SECONDS", raising=False)
        monkeypatch.delenv("COMPANION_RENAME_COOLDOWN_SECONDS", raising=False)
        settings = load_companion_settings()
        assert settings.create_cooldown_seconds == 60.0
        assert settings.rename_cooldown_seconds == 20.0

    def test_env_override_for_create_cooldown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COMPANION_CREATE_COOLDOWN_SECONDS", "30")
        settings = load_companion_settings()
        assert settings.create_cooldown_seconds == 30.0

    def test_env_override_for_rename_cooldown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COMPANION_RENAME_COOLDOWN_SECONDS", "5")
        settings = load_companion_settings()
        assert settings.rename_cooldown_seconds == 5.0

    def test_zero_disables_cooldown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COMPANION_CREATE_COOLDOWN_SECONDS", "0")
        settings = load_companion_settings()
        assert settings.create_cooldown_seconds == 0.0

    def test_invalid_env_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COMPANION_CREATE_COOLDOWN_SECONDS", "not-a-number")
        settings = load_companion_settings()
        assert settings.create_cooldown_seconds == 60.0
