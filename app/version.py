from __future__ import annotations

import os
import subprocess

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


def _git_rev_parse_head() -> str:
    """Shell out to git to get the current HEAD SHA for local (non-Docker) dev runs."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3.0,
        )
        sha = result.stdout.strip()
        if sha:
            return sha
    except Exception:
        pass
    return "unknown"


def get_runtime_version() -> dict:
    """Return the runtime identity of the running process.

    In a Docker image built with ``--build-arg VCS_REF=<sha>``, both env vars
    are set at image build time via ``ENV VCS_REF=$VCS_REF``.  Outside Docker
    (local dev), ``VCS_REF`` falls back to a live ``git rev-parse HEAD`` call
    and ``BUILT_AT`` falls back to an empty string.

    The static SoT constants (``SOT_BASELINE`` etc.) are doc/governance
    identifiers and are intentionally *not* returned here.
    """
    git_sha = os.environ.get("VCS_REF") or _git_rev_parse_head()
    built_at = os.environ.get("BUILT_AT", "")
    return {"git_sha": git_sha, "built_at": built_at}


__all__ = [
    "SOT_BASELINE",
    "SOT_FORWARD",
    "SOT_LABEL",
    "SOT_VERSION",
    "get_sot_version",
    "get_sot_metadata",
    "get_runtime_version",
]
