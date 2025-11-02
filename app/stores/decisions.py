from typing import Any, Dict
from .provider import get_stores

def put_decision(*, object_id: str, agent: str, kind: str, key: str, value: Dict[str, Any]) -> Dict[str, str]:
    _, decisions = get_stores()
    return decisions.put(object_id=object_id, agent=agent, kind=kind, key=key, value=value)
