from pathlib import Path


def test_dormant_archival_handlers_are_not_installed_on_external_surfaces() -> None:
    """#5336 exports direct-composition handlers only; #5352 owns installation."""
    roots = (Path("app/api"), Path("app/mcp"), Path("app/companion"), Path("app/gui"))
    sources = [path for root in roots if root.exists() for path in root.rglob("*.py")]
    exposed = [path for path in sources if "artifact.archive" in path.read_text(encoding="utf-8") or "artifact.restore" in path.read_text(encoding="utf-8")]
    assert exposed == []
