from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[2] / "app/api/request_active_context.py").read_text()


def test_migrated_scoped_read_rejects_stripped_carrier_without_default_downgrade() -> None:
    assert "detail=\"reselection_required\"" in SOURCE
    assert "status.HTTP_401_UNAUTHORIZED" in SOURCE


def test_invalid_selection_never_falls_back() -> None:
    assert "except (" in SOURCE
    assert "raise _selection_failure(exc)" in SOURCE
