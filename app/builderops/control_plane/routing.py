"""Delivery-manifest routing for the BuilderOps control-plane client.

The client loads the *addressed* repository's delivery manifest and selects an
advisory policy/TCD route by ``(RepoRef, stack, task-class)``. Routing is
strictly non-transitive: a manifest resolved for one repository is never reused
or inferred for another, even when they share a stack or task class. Missing or
ambiguous manifests, and any attempt to derive repository authority implicitly
(for example from the current working directory), fail closed.

Client-selected policy is advisory request-formation only. It is never
privileged authority; BCP-05 independently re-resolves the protected-base
delivery manifest and host credential mapping before any privileged effect.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class RoutingError(RuntimeError):
    """Base class for fail-closed delivery-manifest routing errors."""


class RepoRefError(RoutingError):
    """Raised when a repository reference is missing or ambiguous."""


class ManifestError(RoutingError):
    """Raised when a manifest document is malformed or ambiguous."""


class ManifestNotFoundError(RoutingError):
    """Raised when the addressed repository has no loaded manifest."""


class RouteResolutionError(RoutingError):
    """Raised when a ``(stack, task-class)`` route is absent or ambiguous."""


@dataclass(frozen=True)
class RepoRef:
    """Canonical, unambiguous ``owner/name`` GitHub repository reference."""

    owner: str
    name: str

    def __post_init__(self) -> None:
        owner = self.owner.strip()
        name = self.name.strip()
        if not owner or not name or owner in {".", ".."} or name in {".", ".."}:
            raise RepoRefError("repository owner and name are mandatory and unambiguous")
        object.__setattr__(self, "owner", owner)
        object.__setattr__(self, "name", name)

    @property
    def canonical(self) -> str:
        return f"{self.owner}/{self.name}".lower()

    @classmethod
    def parse(cls, value: str | None) -> "RepoRef":
        """Parse ``owner/name``; a blank, partial, or ambiguous value fails closed.

        There is deliberately no current-working-directory or git-remote
        inference here: repository authority must be named explicitly by the
        caller so no implicit CWD-derived repo can authorize a mutation.
        """
        if not value or not isinstance(value, str) or not value.strip():
            raise RepoRefError("a repository reference is required; none was provided")
        candidate = value.strip()
        if _REPOSITORY.fullmatch(candidate) is None:
            raise RepoRefError(f"repository reference is not a valid owner/name: {candidate!r}")
        owner, name = candidate.split("/", 1)
        return cls(owner=owner, name=name)


@dataclass(frozen=True)
class RoutePolicy:
    """Advisory route for one ``(RepoRef, stack, task-class)`` triple.

    ``repository`` binds the policy to the repo it was resolved for, which is
    what makes routing non-transitive: a policy carried out of one repo's
    manifest can never masquerade as another repo's.
    """

    repository: str
    stack: str
    task_class: str
    policy: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeliveryManifest:
    """One repository's routing table, keyed by ``(stack, task-class)``."""

    repository: RepoRef
    routes: Mapping[tuple[str, str], RoutePolicy]

    def resolve(self, stack: str, task_class: str) -> RoutePolicy:
        stack_key = _require_identifier(stack, "stack")
        task_key = _require_identifier(task_class, "task-class")
        try:
            return self.routes[(stack_key, task_key)]
        except KeyError as exc:
            raise RouteResolutionError(
                f"no delivery route for ({self.repository.canonical}, "
                f"{stack_key}, {task_key})"
            ) from exc

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "DeliveryManifest":
        if not isinstance(document, Mapping):
            raise ManifestError("delivery manifest must be a mapping")
        repo_ref = RepoRef.parse(document.get("repository"))
        raw_routes = document.get("routes", [])
        if not isinstance(raw_routes, list):
            raise ManifestError("delivery manifest routes must be a list")
        routes: dict[tuple[str, str], RoutePolicy] = {}
        for raw in raw_routes:
            if not isinstance(raw, Mapping):
                raise ManifestError("each delivery route must be a mapping")
            stack = _require_identifier(raw.get("stack"), "stack")
            task_class = _require_identifier(raw.get("task_class"), "task-class")
            policy_raw = raw.get("policy", {})
            if not isinstance(policy_raw, Mapping):
                raise ManifestError("delivery route policy must be a mapping")
            key = (stack, task_class)
            if key in routes:
                raise ManifestError(
                    f"ambiguous duplicate route ({stack}, {task_class}) in "
                    f"{repo_ref.canonical} manifest"
                )
            routes[key] = RoutePolicy(
                repository=repo_ref.canonical,
                stack=stack,
                task_class=task_class,
                policy=dict(policy_raw),
            )
        return cls(repository=repo_ref, routes=routes)


class DeliveryManifestRegistry:
    """Registry that resolves routes only for explicitly loaded repositories."""

    def __init__(self, manifests: Mapping[str, DeliveryManifest]) -> None:
        self._manifests = dict(manifests)

    @classmethod
    def from_documents(cls, documents: list[Mapping[str, Any]]) -> "DeliveryManifestRegistry":
        manifests: dict[str, DeliveryManifest] = {}
        for document in documents:
            manifest = DeliveryManifest.from_document(document)
            key = manifest.repository.canonical
            if key in manifests:
                raise ManifestError(f"duplicate delivery manifest for repository {key}")
            manifests[key] = manifest
        return cls(manifests)

    @classmethod
    def from_directory(cls, directory: Path | str) -> "DeliveryManifestRegistry":
        root = Path(directory)
        if not root.is_dir():
            raise ManifestError(f"delivery manifest directory does not exist: {root}")
        documents: list[Mapping[str, Any]] = []
        for path in sorted(root.glob("*.json")):
            try:
                documents.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError) as exc:
                raise ManifestError(f"delivery manifest is unreadable: {path}") from exc
        return cls.from_documents(documents)

    def manifest_for(self, repo_ref: RepoRef) -> DeliveryManifest:
        """Return only the addressed repo's manifest; never borrow another's."""
        try:
            return self._manifests[repo_ref.canonical]
        except KeyError as exc:
            raise ManifestNotFoundError(
                f"no delivery manifest is loaded for repository {repo_ref.canonical}"
            ) from exc

    def resolve_route(
        self, repo_ref: RepoRef, stack: str, task_class: str
    ) -> RoutePolicy:
        """Resolve the advisory route for one explicit ``(RepoRef, stack, task)``.

        The repo's own manifest is the only source consulted; a route from a
        different repository's manifest is never substituted, even when the
        stack and task-class match.
        """
        manifest = self.manifest_for(repo_ref)
        return manifest.resolve(stack, task_class)


def _require_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value.strip()) is None:
        raise ManifestError(f"{label} must be a bounded non-empty identifier")
    return value.strip()


__all__ = [
    "DeliveryManifest",
    "DeliveryManifestRegistry",
    "ManifestError",
    "ManifestNotFoundError",
    "RepoRef",
    "RepoRefError",
    "RoutePolicy",
    "RouteResolutionError",
    "RoutingError",
]
