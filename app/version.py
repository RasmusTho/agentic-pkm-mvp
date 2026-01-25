SOT_BASELINE = "v5.5"
SOT_FORWARD = "v5.6"
SOT_LABEL = "baseline v5.5 (Reality-MVP), forward v5.6 (LangGraph + Reasoning)"
SOT_VERSION = SOT_BASELINE


def get_sot_version() -> str:
    return SOT_VERSION


def get_sot_metadata() -> dict:
    return {
        "baseline": SOT_BASELINE,
        "forward_line": SOT_FORWARD,
        "label": SOT_LABEL,
    }


__all__ = ["SOT_BASELINE", "SOT_FORWARD", "SOT_LABEL", "SOT_VERSION", "get_sot_version", "get_sot_metadata"]
