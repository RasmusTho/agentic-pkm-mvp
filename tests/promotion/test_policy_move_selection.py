from app.promotion.policy import pick_target  # expected API
from pathlib import Path

def test_pick_target_matches_first_rule():
    meta = {"kind":"card","category":"concept"}
    move_policy = {
        "enabled": True,
        "targets":[
            {"when":{"kind":"card","category":"concept"},"path":"2_Cards/Concepts"},
            {"when":{"kind":"card","category":"people"},"path":"2_Cards/People"},
        ],
        "default_target":"2_Cards/Concepts"
    }
    assert pick_target(meta, move_policy) == Path("2_Cards/Concepts")

def test_pick_target_falls_back_to_default():
    meta = {"kind":"source","type":"written"}
    move_policy = {
        "enabled": True,
        "targets":[
            {"when":{"kind":"card","category":"people"},"path":"2_Cards/People"},
        ],
        "default_target":"2_Cards/Concepts"
    }
    assert pick_target(meta, move_policy) == Path("2_Cards/Concepts")
