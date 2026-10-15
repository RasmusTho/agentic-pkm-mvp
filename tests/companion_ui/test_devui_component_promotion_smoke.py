"""The actual operator browser helper against the admitted production listener."""
import pytest

from scripts.devui_component_browser_smoke import smoke
from tests.builderops.test_devui_runtime import managed_sources  # noqa: F401
from tests.builderops.test_devui_builder_system_control_navigation import prepare_control_sources
from tests.companion_ui.test_devui_managed_journeys import _server

pytestmark = pytest.mark.browser_runtime


def test_component_smoke_exercises_runtime_and_refuses_wrong_identity(managed_sources, monkeypatch):  # noqa: F811
    source = managed_sources
    prepare_control_sources(source)
    with _server(source, monkeypatch):
        sha = source.environment["DEVUI_SOURCE_SHA"]
        assert smoke(sha, preflight=True) == {"browser_launch": True}
        assert smoke(sha, baseline=True)["baseline_overview"] is True
        result = smoke(sha)
        assert result["overview_system_focus_return"] is True
        assert result["forbidden_request_count"] == 0
        assert result["owner_acceptance"] is False
        with pytest.raises(RuntimeError, match="candidate mismatch"):
            smoke("0" * 40)

        # A visible static Focus shell must never count as a successful journey.
        from app.builderops import devui_runtime
        def unavailable(*args, **kwargs):
            raise devui_runtime.FocusInputError("fixture read failure")
        monkeypatch.setattr(devui_runtime, "read_managed_focus", unavailable)
        with pytest.raises(RuntimeError, match="Focus read or subject mismatch"):
            smoke(sha)
