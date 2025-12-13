SOT_BASELINE = "v4.10"
SOT_FORWARD = "v5.4"
SOT_LABEL = "baseline v4.10 (Reality-MVP), forward v5.4 (PanelAgent + Watchers)"

# Backward-compatibility alias used by older callers; returns the locked baseline.
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
