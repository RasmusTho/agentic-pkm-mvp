"""Read rendered Compose bind options with the running renderer's defaults."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
import re
import subprocess

_VERSION = re.compile(r"^v?(\d+)\.\d+\.\d+")


def effective_create_host_path(bind: Mapping[str, object]) -> object:
    """Return a rendered bind's ``create_host_path``, resolving an omitted key.

    Compose 5 (compose-go v2.10.0+) renders ``create_host_path`` as an opt-out flag
    that omits ``true``; earlier renderers omit ``false``. An absent key therefore
    has opposite meanings, so it is resolved from the renderer that produced it.
    """
    if "create_host_path" in bind:
        return bind["create_host_path"]
    return omitted_create_host_path_default(compose_major_version())


def omitted_create_host_path_default(major: int) -> bool:
    return major >= 5


@lru_cache(maxsize=1)
def compose_major_version() -> int:
    output = subprocess.run(
        ["docker", "compose", "version", "--short"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    match = _VERSION.match(output)
    if match is None:
        raise RuntimeError(f"unparsable docker compose version: {output!r}")
    return int(match.group(1))
