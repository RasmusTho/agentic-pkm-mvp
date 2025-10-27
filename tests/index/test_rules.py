from app.index.rules import compile_rules, score_for

RULES_CFG = [
    {"when": {"review_state": "inbox"}, "action": "exclude"},
    {"when": {"review_state": "archived"}, "action": "include", "weight": 0.25},
    {"when": {"review_state": "promoted"}, "action": "include", "weight": 1.0},
    {"when": {"review_state": "evergreen"}, "action": "include", "weight": 1.2},
]

def test_inbox_is_excluded():
    rules = compile_rules(RULES_CFG)
    include, weight = score_for({"review_state": "inbox"}, rules)
    assert include is False and weight == 0.0

def test_archived_included_low_weight():
    rules = compile_rules(RULES_CFG)
    include, weight = score_for({"review_state": "archived"}, rules)
    assert include is True and abs(weight - 0.25) < 1e-9

def test_promoted_weight_1_0():
    rules = compile_rules(RULES_CFG)
    include, weight = score_for({"review_state": "promoted"}, rules)
    assert include is True and abs(weight - 1.0) < 1e-9

def test_evergreen_weight_1_2():
    rules = compile_rules(RULES_CFG)
    include, weight = score_for({"review_state": "evergreen"}, rules)
    assert include is True and abs(weight - 1.2) < 1e-9

def test_default_include_weight_when_no_rule():
    rules = compile_rules(RULES_CFG)
    include, weight = score_for({"review_state": "processed"}, rules, default_weight=0.8)
    assert include is True and abs(weight - 0.8) < 1e-9
