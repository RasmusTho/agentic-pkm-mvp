"""Canonical GitHub repository set for local dispatcher coordination."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping

DEFAULT_REPOS = ("RasmusTho/agentic-pkm-mvp", "RasmusTho/bifrost")
EXTRA_REPOS_ENV = "DISPATCHER_EXTRA_GITHUB_REPOS"
LEGACY_EXTRA_REPOS_ENV = "BUILDEROPS_BOOTSTRAP_REPO"

_REPOSITORY_ID = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


class RepositoryConfigurationError(ValueError):
    """Raised when an explicitly configured repository identity is malformed."""


def normalize_repositories(repositories: Iterable[str]) -> tuple[str, ...]:
    """Validate and deduplicate explicit ``owner/repository`` identities."""
    normalized: list[str] = []
    seen: set[str] = set()
    for value in repositories:
        if not isinstance(value, str):
            raise RepositoryConfigurationError("repository identity must be text")
        repository = value.strip()
        if not _REPOSITORY_ID.fullmatch(repository):
            raise RepositoryConfigurationError(
                f"invalid GitHub repository identity: {repository!r}"
            )
        identity = repository.casefold()
        if identity not in seen:
            seen.add(identity)
            normalized.append(repository)
    return tuple(normalized)


def configured_repositories(
    environ: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Return the required defaults plus comma-separated opt-in repositories.

    ``DISPATCHER_EXTRA_GITHUB_REPOS`` extends the two canonical Yggdrasil repos;
    it cannot silently remove either one from the live pickup set.
    """
    source = os.environ if environ is None else environ
    raw = source.get(EXTRA_REPOS_ENV, "")
    extras: list[str] = []
    if raw.strip():
        configured_extras = [part.strip() for part in raw.split(",")]
        if any(not repository for repository in configured_extras):
            raise RepositoryConfigurationError(
                f"{EXTRA_REPOS_ENV} must be a comma-separated list of owner/repository identities"
            )
        extras.extend(configured_extras)

    # Keep the existing startup setting as a compatibility input. Its legacy
    # whitespace-separated values now extend the required defaults, matching
    # the shared pickup/status configuration instead of replacing it.
    legacy_raw = source.get(LEGACY_EXTRA_REPOS_ENV, "")
    if legacy_raw.strip():
        extras.extend(legacy_raw.replace(",", " ").split())
    return normalize_repositories((*DEFAULT_REPOS, *extras))
