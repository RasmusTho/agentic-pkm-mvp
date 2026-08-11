"""Single declaration site for behavior-shaping environment defaults (SET-4 / SETTINGS-02).

Audit finding F3: the same operational knob carried different literal defaults at
different call sites — ``LLM_TIMEOUT`` defaulted to 12s / 60s / 120s and
``WATCHER_ENABLE`` to ``"0"`` / ``"1"`` — so two components silently disagreed
about one knob and nobody had decided the value. Every such default is now declared
exactly once here and read through the accessors below.

Call sites MUST NOT re-inline ``os.getenv("<registered-key>", "<literal>")`` for a
registered key; the SET-4 gate (``tests/architecture/test_single_default_registry.py``)
fails when they do.

A deliberate *no-default* read — ``os.getenv("WATCHER_ENABLE")`` in the watcher CLI,
which distinguishes "operator never set it" from an explicit value — is not a default
declaration and is intentionally not covered by the registry or the gate.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class EnvDefault:
    """One behavior-shaping env key, its single declared default, and why."""

    key: str
    default: str
    rationale: str


# One declaration per behavior-shaping env key. F3 divergence resolutions live in
# each entry's ``rationale`` so the chosen value and its reason travel with the value.
ENV_DEFAULTS: dict[str, EnvDefault] = {
    entry.key: entry
    for entry in (
        EnvDefault(
            key="LLM_TIMEOUT",
            default="60",
            rationale=(
                "Unified from 12s/60s/120s (F3). 60s is the plurality of call sites "
                "and a safe middle ground: 12s spuriously timed out larger local "
                "generations; 120s was overly generous. Every site reads this one env "
                "var, so an operator needing longer sets LLM_TIMEOUT explicitly."
            ),
        ),
        EnvDefault(
            key="LLM_TEMPERATURE",
            default="0",
            rationale="Preserves deterministic generation when no vault setting or bootstrap override is present.",
        ),
        EnvDefault(
            key="REASONING_MODEL",
            default="llama3.1:8b",
            rationale="Preserves the legacy reasoning-provider model until its one-release bootstrap override retires.",
        ),
        EnvDefault(
            key="MERGE_LLM_MODEL",
            default="llama3.1:8b",
            rationale="Preserves the legacy merge-model fallback until its one-release bootstrap override retires.",
        ),
        EnvDefault(
            key="RERANK_PROVIDER",
            default="none",
            rationale="Preserves the disabled reranker implementation when no vault setting or bootstrap override is present.",
        ),
        EnvDefault(
            key="RERANK_TOP_K",
            default="100",
            rationale="Preserves the historical rerank candidate limit until its one-release bootstrap override retires.",
        ),
        EnvDefault(
            key="WATCHER_ENABLE",
            default="1",
            rationale=(
                "Unified from '0' (app/watcher/config.py) and '1' "
                "(app/watcher/registry.py) (F3) to the ruled default-on watcher "
                "posture. The #2005 no-vault guard still idles the watcher to disabled "
                "when no vault is bound, so default-on stays boot-safe."
            ),
        ),
    )
}


def env_default(key: str) -> str:
    """Return the single declared default literal for a registered key."""
    return ENV_DEFAULTS[key].default


def env_str(key: str) -> str:
    """Read a registered env key, falling back to its single declared default."""
    return os.getenv(key, ENV_DEFAULTS[key].default)


def env_float(key: str) -> float:
    """Read a registered env key as a float, via its single declared default."""
    return float(env_str(key))
