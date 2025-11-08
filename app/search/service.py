"""
Compatibility shim for legacy import path: `app.search.service`

This tries a series of likely real module locations and re-raises with a clear error
showing what files actually exist in the repo. Keep this until all callers migrate.
"""
import importlib
import sys
from pathlib import Path

_CANDIDATES = [
    "app.services.search",        # e.g. app/services/search.py
    "app.service.search",         # alt naming
    "app.search_service",         # e.g. app/search_service.py
    "app.search.impl",            # e.g. app/search/impl.py
]

_last_err = None
for mod in _CANDIDATES:
    try:
        _m = importlib.import_module(mod)
        for name in getattr(_m, "__all__", []):
            globals()[name] = getattr(_m, name)
        # Fallback: export public attrs
        if not getattr(_m, "__all__", None):
            for k, v in _m.__dict__.items():
                if not k.startswith("_"):
                    globals()[k] = v
        break
    except Exception as e:
        _last_err = e
else:
    # Build a helpful diagnostic
    tree = []
    root = Path(__file__).resolve().parents[2]  # repo root heuristics: .../app/search/service.py -> repo/
    candidates = list(root.glob("app/**/search*.py"))
    tree_lines = "\n".join(f"- {p.relative_to(root)}" for p in candidates) or "(no search*.py files found)"
    raise ImportError(
        "Could not resolve real search service module for legacy import 'app.search.service'.\n"
        f"Tried: {', '.join(_CANDIDATES)}\n"
        f"Discovered candidates:\n{tree_lines}\n"
    ) from _last_err
