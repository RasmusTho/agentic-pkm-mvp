"""Structural guard for MVR-05B request consumers."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_request_consumers_use_context_seam() -> None:
    """Scoped production reads must not regain a global vault-manager lookup."""

    for relative in ("app/api/routes/ask.py", "app/api/routes/search.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "require_scoped_read_context" in source, relative
        assert "context_bound_effect_window" in source, relative
        assert "get_vault_manager" not in source, relative

    companion = (ROOT / "app/api/routes/companion.py").read_text(encoding="utf-8")
    scoped_start = companion.index("def list_scoped_vault_notes")
    scoped_source = companion[scoped_start : scoped_start + 2400]
    assert "require_scoped_read_context" in scoped_source
    assert "context_bound_read_window" in scoped_source
    assert "get_vault_manager" not in scoped_source
