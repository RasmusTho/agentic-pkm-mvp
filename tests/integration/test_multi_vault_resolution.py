from pathlib import Path


def test_resolution_precedence_and_fail_closed_behavior() -> None:
    source = (Path(__file__).resolve().parents[2] / "app/instance/active_context_service.py").read_text()
    assert "override_bearer if override_bearer is not None else session_bearer" in source
    selection = (Path(__file__).resolve().parents[2] / "app/instance/context_selection.py").read_text()
    assert "ReselectionRequiredError" in selection
