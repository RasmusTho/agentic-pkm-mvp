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

    # Persistera beslutet (tysta fel om stores inte är wired)
    try:
        from app.stores.decisions import put_decision
        put_decision(object_id=object_id, agent="classifier", kind="classify", key="classification", value=value)
    except Exception:
        pass

    return {"classification": value}
