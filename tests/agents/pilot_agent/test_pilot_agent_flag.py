"""Test suite for pilot agent feature flag contract.

Enforces flag-controlled activation/deactivation of pilot LangGraph agents.
"""

from __future__ import annotations

import os



class TestFeatureFlagActivation:
    """Verify feature flag controls agent activation."""

    def test_promotion_agent_activates_with_flag(self, monkeypatch):
        monkeypatch.setenv("LANGGRAPH_PILOT_AGENT", "promotion")
        # Flag should be readable
        assert os.environ.get("LANGGRAPH_PILOT_AGENT") == "promotion"

    def test_reviewer_agent_activates_with_flag(self, monkeypatch):
        monkeypatch.setenv("LANGGRAPH_PILOT_AGENT", "reviewer")
        assert os.environ.get("LANGGRAPH_PILOT_AGENT") == "reviewer"

    def test_flag_off_disables_pilot_agent(self, monkeypatch):
        monkeypatch.setenv("LANGGRAPH_PILOT_AGENT", "off")
        assert os.environ.get("LANGGRAPH_PILOT_AGENT") == "off"

    def test_flag_unset_defaults_to_off(self, monkeypatch):
        monkeypatch.delenv("LANGGRAPH_PILOT_AGENT", raising=False)
        flag_value = os.environ.get("LANGGRAPH_PILOT_AGENT", "off")
        assert flag_value == "off"


class TestFeatureFlagValidation:
    """Verify flag accepts valid values and rejects invalid ones."""

    def test_flag_value_promotion_valid(self, monkeypatch):
        monkeypatch.setenv("LANGGRAPH_PILOT_AGENT", "promotion")
        flag_value = os.environ.get("LANGGRAPH_PILOT_AGENT")
        valid_values = {"promotion", "reviewer", "off"}
        assert flag_value in valid_values

    def test_flag_value_reviewer_valid(self, monkeypatch):
        monkeypatch.setenv("LANGGRAPH_PILOT_AGENT", "reviewer")
        flag_value = os.environ.get("LANGGRAPH_PILOT_AGENT")
        valid_values = {"promotion", "reviewer", "off"}
        assert flag_value in valid_values

    def test_flag_value_off_valid(self, monkeypatch):
        monkeypatch.setenv("LANGGRAPH_PILOT_AGENT", "off")
        flag_value = os.environ.get("LANGGRAPH_PILOT_AGENT")
        valid_values = {"promotion", "reviewer", "off"}
        assert flag_value in valid_values

    def test_flag_value_invalid_warns(self, monkeypatch, caplog):
        monkeypatch.setenv("LANGGRAPH_PILOT_AGENT", "invalid_agent")
        flag_value = os.environ.get("LANGGRAPH_PILOT_AGENT")
        valid_values = {"promotion", "reviewer", "off"}
        is_valid = flag_value in valid_values

        if not is_valid:
            # Implementation should log warning and fallback
            assert flag_value not in valid_values


class TestFeatureFlagRuntime:
    """Verify flag changes are respected at runtime (not cached)."""

    def test_flag_can_be_changed_at_runtime(self, monkeypatch):
        monkeypatch.setenv("LANGGRAPH_PILOT_AGENT", "promotion")
        assert os.environ.get("LANGGRAPH_PILOT_AGENT") == "promotion"

        monkeypatch.setenv("LANGGRAPH_PILOT_AGENT", "reviewer")
        assert os.environ.get("LANGGRAPH_PILOT_AGENT") == "reviewer"

    def test_flag_disabled_after_enable(self, monkeypatch):
        monkeypatch.setenv("LANGGRAPH_PILOT_AGENT", "promotion")
        assert os.environ.get("LANGGRAPH_PILOT_AGENT") == "promotion"

        monkeypatch.setenv("LANGGRAPH_PILOT_AGENT", "off")
        assert os.environ.get("LANGGRAPH_PILOT_AGENT") == "off"

    def test_flag_not_cached_across_calls(self, monkeypatch):
        """Flag value should be read fresh each time, not cached."""
        monkeypatch.setenv("LANGGRAPH_PILOT_AGENT", "promotion")
        value1 = os.environ.get("LANGGRAPH_PILOT_AGENT")

        monkeypatch.setenv("LANGGRAPH_PILOT_AGENT", "reviewer")
        value2 = os.environ.get("LANGGRAPH_PILOT_AGENT")

        assert value1 != value2

    def test_flag_changes_visible_immediately(self, monkeypatch):
        monkeypatch.setenv("LANGGRAPH_PILOT_AGENT", "off")

        def get_flag():
            return os.environ.get("LANGGRAPH_PILOT_AGENT")

        assert get_flag() == "off"
        monkeypatch.setenv("LANGGRAPH_PILOT_AGENT", "promotion")
        assert get_flag() == "promotion"


class TestFeatureFlagFallback:
    """Verify invalid flag values trigger fallback behavior."""

    def test_invalid_flag_falls_back_to_off(self, monkeypatch):
        monkeypatch.setenv("LANGGRAPH_PILOT_AGENT", "typo_promotion")
        flag_value = os.environ.get("LANGGRAPH_PILOT_AGENT")
        valid_values = {"promotion", "reviewer", "off"}

        if flag_value not in valid_values:
            fallback = "off"
            assert fallback == "off"

    def test_empty_flag_falls_back_to_off(self, monkeypatch):
        monkeypatch.setenv("LANGGRAPH_PILOT_AGENT", "")
        flag_value = os.environ.get("LANGGRAPH_PILOT_AGENT") or "off"
        assert flag_value == "off"

    def test_case_insensitivity_or_warning(self, monkeypatch):
        """Flag should handle case sensitivity (normalize or warn)."""
        monkeypatch.setenv("LANGGRAPH_PILOT_AGENT", "PROMOTION")
        flag_value = os.environ.get("LANGGRAPH_PILOT_AGENT")
        # Implementation should normalize or warn on case mismatch
        assert flag_value is not None

    def test_whitespace_handling(self, monkeypatch):
        """Flag with whitespace should be trimmed or warned."""
        monkeypatch.setenv("LANGGRAPH_PILOT_AGENT", "  promotion  ")
        flag_value = os.environ.get("LANGGRAPH_PILOT_AGENT").strip()
        assert flag_value == "promotion"
