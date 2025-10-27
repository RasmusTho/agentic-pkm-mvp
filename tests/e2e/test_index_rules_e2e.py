from pathlib import Path
from textwrap import dedent

from app.index.build import build_index, query

RULES_CFG = [
    {"when": {"review_state": "inbox"}, "action": "exclude"},
    {"when": {"review_state": "archived"}, "action": "include", "weight": 0.25},
    {"when": {"review_state": "promoted"}, "action": "include", "weight": 1.0},
    {"when": {"review_state": "evergreen"}, "action": "include", "weight": 1.2},
]

def write(p: Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")

def test_inbox_is_not_returned_but_promoted_is(tmp_path: Path):
    root = tmp_path / "vault"
    inbox = root / "@Inbox" / "inbox_note.md"
    promoted = root / "2_Cards" / "Concepts" / "promoted_note.md"

    write(inbox, dedent("""\
    ---
    uuid: "X1"
    title: "Raw capture"
    review_state: "inbox"
    ---
    Galaxy data and rough capture text.
    """))

    write(promoted, dedent("""\
    ---
    uuid: "X2"
    title: "Refined concept"
    review_state: "promoted"
    ---
    Galaxy data refined and linked.
    """))

    idx = build_index(root, RULES_CFG)

    hits = query(idx, "galaxy")
    paths = [Path(p).name for p, _ in hits]

    assert "promoted_note.md" in paths
    assert "inbox_note.md" not in paths
