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

    The Dockerfile declares ``ARG VCS_REF=unknown`` so an image built without
    ``--build-arg`` (e.g. a plain compose ``build: .`` with no build args) bakes
    the literal sentinel ``"unknown"`` into the image env. That sentinel is
    treated here as *not set* so the git fallback still runs; otherwise the
    deployed ``/version`` would report ``"unknown"`` instead of the real SHA.

    The static SoT constants (``SOT_BASELINE`` etc.) are doc/governance
    identifiers and are intentionally *not* returned here.
    """
    env_sha = (os.environ.get("VCS_REF") or "").strip()
    git_sha = env_sha if env_sha and env_sha != "unknown" else _git_rev_parse_head()
    env_built_at = (os.environ.get("BUILT_AT") or "").strip()
    built_at = env_built_at if env_built_at and env_built_at != "unknown" else ""
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
