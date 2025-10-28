from pathlib import Path
from textwrap import dedent

from app.index.build import build_index, query

RULES_CFG = [
    {"when": {"review_state": "inbox"}, "action": "soft_exclude", "weight": 0.05},
    {"when": {"review_state": "archived"}, "action": "include", "weight": 0.25},
    {"when": {"review_state": "promoted"}, "action": "include", "weight": 1.0},
    {"when": {"review_state": "evergreen"}, "action": "include", "weight": 1.2},
]

def write(p: Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")

def test_inbox_is_deprioritized_but_promoted_leads(tmp_path: Path):
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
    assert len(hits) == 2
    first_path, first_score = hits[0]
    second_path, second_score = hits[1]
    assert Path(first_path).name == "promoted_note.md"
    assert Path(second_path).name == "inbox_note.md"
    assert first_score > second_score
