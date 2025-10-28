from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

@dataclass
class Rule:
    when: Dict[str, Any]
    action: str
    weight: Optional[float] = None

def compile_rules(rules_cfg: List[Dict[str, Any]]) -> List[Rule]:
    out: List[Rule] = []
    for r in rules_cfg:
        out.append(Rule(when=r["when"], action=r["action"], weight=r.get("weight")))
    return out

def match_rule(rule: Rule, meta: Dict[str, Any]) -> bool:
    for k, v in rule.when.items():
        if meta.get(k) != v:
            return False
    return True

def score_for(meta: Dict[str, Any], rules: List[Rule], default_weight: float = 1.0) -> tuple[bool, float]:
    decision_include = True
    weight = default_weight
    for r in rules:
        if match_rule(r, meta):
            if r.action == "exclude":
                return (False, 0.0)
            if r.action == "soft_exclude":
                soft_weight = r.weight if r.weight is not None else 0.0
                weight = float(soft_weight)
                decision_include = weight > 0.0
                continue
            if r.action == "include":
                weight = r.weight if r.weight is not None else weight
                decision_include = True
    return (decision_include, weight)
