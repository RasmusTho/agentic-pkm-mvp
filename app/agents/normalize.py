from __future__ import annotations
import importlib, inspect
from typing import Any, Dict, Optional

def _resolve():
    candidates = [
        "app.agents.normalizer.agent",
        "app.agents.normalize.agent",
        "app.agents.normalizer",
    ]
    for modname in candidates:
        try:
            mod = importlib.import_module(modname)
            fn = getattr(mod, "run", None) or getattr(mod, "normalize_run", None)
            if callable(fn):
                return fn
        except Exception:
            continue
    raise ImportError("Could not resolve a normalize 'run' function from candidates.")

def _call_with_optional_trace(impl, src_path: str, trace_id: Optional[str]) -> Any:
    try:
        sig = inspect.signature(impl)
        params = sig.parameters
        if "trace_id" in params:
            return impl(src_path, trace_id=trace_id)
        elif len(params) == 1:
            return impl(src_path)
        else:
            # Fallback: prova positionellt, annars utan
            try:
                return impl(src_path, trace_id)
            except TypeError:
                return impl(src_path)
    except TypeError:
        return impl(src_path)

def normalize_run(src_path: str, trace_id: Optional[str] = None) -> Dict[str, Any]:
    impl = _resolve()
    res = _call_with_optional_trace(impl, src_path, trace_id)
    if isinstance(res, dict):
        return res
    # Fallback: om agenten returnerar t.ex. ett id som str
    return {"object_id": res}
