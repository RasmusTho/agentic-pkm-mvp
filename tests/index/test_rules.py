from app.index.rules import compile_rules, score_for

RULES_CFG = [
    {"when": {"review_state": "inbox"}, "action": "soft_exclude", "weight": 0.05},
    {"when": {"review_state": "archived"}, "action": "include", "weight": 0.25},
    {"when": {"review_state": "reviewed"}, "action": "include", "weight": 1.0},
    {"when": {"maturity": "evergreen"}, "action": "include", "weight": 1.2},
    {"when": {"review_state": "evergreen"}, "action": "include", "weight": 1.2},
]


def test_inbox_is_soft_excluded_with_low_weight() -> None:
    rules = compile_rules(RULES_CFG)
    include, weight = score_for({"review_state": "inbox"}, rules)
    assert include is True and abs(weight - 0.05) < 1e-9


def test_archived_included_low_weight() -> None:
    rules = compile_rules(RULES_CFG)
    include, weight = score_for({"review_state": "archived"}, rules)
    assert include is True and abs(weight - 0.25) < 1e-9


def test_reviewed_weight_1_0() -> None:
    rules = compile_rules(RULES_CFG)
    include, weight = score_for({"review_state": "reviewed"}, rules)
    assert include is True and abs(weight - 1.0) < 1e-9


def test_evergreen_weight_1_2() -> None:
    rules = compile_rules(RULES_CFG)
    include, weight = score_for({"maturity": "evergreen"}, rules)
    assert include is True and abs(weight - 1.2) < 1e-9


def test_legacy_evergreen_review_state_still_gets_1_2() -> None:
    rules = compile_rules(RULES_CFG)
    include, weight = score_for({"review_state": "evergreen"}, rules)
    assert include is True and abs(weight - 1.2) < 1e-9


def test_default_include_weight_when_no_rule() -> None:
    rules = compile_rules(RULES_CFG)
    include, weight = score_for({"review_state": "provisional"}, rules, default_weight=0.8)
    assert include is True and abs(weight - 0.8) < 1e-9


def test_soft_exclude_without_weight_defaults_to_full_exclusion() -> None:
    rules = compile_rules([{"when": {}, "action": "soft_exclude"}])
    include, weight = score_for({}, rules)
    assert include is False and weight == 0.0
