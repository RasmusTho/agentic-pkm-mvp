from __future__ import annotations

import hashlib
from typing import Any, Dict


def safe_preview(text: Any) -> Dict[str, Any]:
    value = text if text is not None else ""
    try:
        stringified = value if isinstance(value, str) else str(value)
    except Exception:
        stringified = ""
    encoded = stringified.encode("utf-8", errors="ignore")
    return {
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "chars": len(stringified),
    }


__all__ = ["safe_preview"]
