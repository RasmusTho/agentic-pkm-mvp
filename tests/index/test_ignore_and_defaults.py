from pathlib import Path
from textwrap import dedent

from app.index.build import build_index
from app.vault.paths import get_vault_inbox_dir_rel

RULES = [
    {"when": {"review_state": "inbox"}, "action": "exclude"},
    {"when": {"review_state": "archived"}, "action": "include", "weight": 0.25},
    {"when": {"review_state": "promoted"}, "action": "include", "weight": 1.0},
    {"when": {"review_state": "evergreen"}, "action": "include", "weight": 1.2},
    {"when": {"review_state": "processed"}, "action": "include", "weight": 0.8},
]


def write(p: Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")


def test_ignore_glob_and_path_defaults(tmp_path: Path):
    root = tmp_path / "vault"
    inbox_dir = get_vault_inbox_dir_rel(root)
    write(root / inbox_dir / "a.md", "inbox body")
    write(root / "9_Extras" / "Archive" / "z.md", "archived body")
    write(root / "2_Cards" / "x.md", "processed body")
    write(
        root / "2_Cards" / "y.md",
        dedent(
            """\
    ---
    review_state: evergreen
    ---
    evergreen body
    """
        ),
    )

    idx = build_index(root, RULES, ignore_glob=["_system/**"])

    paths = {p["path"]: p for p in idx}
    assert all("_system" not in p for p in paths)

    names = {Path(p).name for p in paths}
    assert "a.md" not in names
    assert "z.md" in names and abs(paths[next(p for p in paths if p.endswith("z.md"))]["weight"] - 0.25) < 1e-9
    assert "x.md" in names and abs(paths[next(p for p in paths if p.endswith("x.md"))]["weight"] - 0.8) < 1e-9
    assert "y.md" in names and abs(paths[next(p for p in paths if p.endswith("y.md"))]["weight"] - 1.2) < 1e-9
