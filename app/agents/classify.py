from __future__ import annotations
import importlib, inspect
from typing import Any, Dict, Optional

def _resolve():
    candidates = [
        "app.agents.classifier.agent",
        "app.agents.classifier",
        "app.agents.classify.agent",
    ]
    for modname in candidates:
        try:
            mod = importlib.import_module(modname)
            fn = getattr(mod, "run", None) or getattr(mod, "classify_run", None)
            if callable(fn):
                return fn
        except Exception:
            continue
    raise ImportError("Could not resolve a classifier 'run' function from candidates.")

def _call_with_optional_trace(impl, object_id: str, trace_id: Optional[str]) -> Any:
    try:
        sig = inspect.signature(impl)
        params = sig.parameters
        if "trace_id" in params:
            return impl(object_id, trace_id=trace_id)
        elif len(params) == 1:
            return impl(object_id)
        else:
            try:
                return impl(object_id, trace_id)
            except TypeError:
                return impl(object_id)
    except TypeError:
        return impl(object_id)

def classify_run(object_id: str, trace_id: Optional[str] = None) -> Dict[str, Any]:
    # Kör underliggande agent
    impl = _resolve()
    out = _call_with_optional_trace(impl, object_id, trace_id)

    # Normalisera output till {"classification": {...}}
    if isinstance(out, dict) and "classification" in out:
        value = out["classification"]
    elif isinstance(out, dict) and {"type","trust","confidence"}.issubset(out.keys()):
        value = out
    else:
        value = {"type": "note", "trust": "provisional", "confidence": 0.6, "raw": out}

    # Persistence of the classification decision is owned by the resolved
    # classifier agent (``app.agents.classifier.agent.run`` -> ``insert_decision``,
    # the one WriteGuard-gated receipt-log writer), which fails loud. This shim is
    # a thin output-normalizer over that agent; it deliberately does NOT persist a
    # second, redundant decision row.
    #
    # It previously wrote its own ``classification`` decision through the
    # deprecated ``app.stores.decisions.put_decision`` inside a
    # ``try: ... except Exception: pass`` — a third silent-swallow site (feat
    # #2969, slice 1). That write duplicated the resolved agent's persistence and
    # swallowed every failure; both are removed so a classification-decision
    # failure surfaces via the resolved agent rather than being lost here.
    return {"classification": value}
