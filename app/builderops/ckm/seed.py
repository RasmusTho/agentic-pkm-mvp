"""Seed the Capability Evidence Graph from its reviewed repository taxonomy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.builderops.ckm.store import CkmStore


class SeedManifestError(ValueError):
    """Raised when the checked-in CKM seed manifest is structurally invalid."""


@dataclass(frozen=True)
class SeedCapability:
    slug: str
    stable_key: str
    name: str
    definition: str
    parent: str | None
    boundary_ref: str | None
    seed_source: str


DEFAULT_MANIFEST_PATH = Path(__file__).with_name("seed") / "capabilities.yaml"
REPO_ROOT = Path(__file__).resolve().parents[3]


def _source_path(seed_source: str, repo_root: Path) -> Path:
    path_text = seed_source.split("::", 1)[0].strip()
    if not path_text:
        raise SeedManifestError(f"seed_source must begin with a repository path: {seed_source!r}")
    return repo_root / path_text


def load_manifest(path: Path = DEFAULT_MANIFEST_PATH, *, repo_root: Path = REPO_ROOT) -> list[SeedCapability]:
    """Load and validate a seed manifest without mutating the CEG."""

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SeedManifestError(f"unable to read seed manifest {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("capabilities"), list):
        raise SeedManifestError("seed manifest must contain a capabilities list")

    entries: list[SeedCapability] = []
    seen: set[str] = set()
    seen_stable_keys: set[str] = set()
    seen_names: set[str] = set()
    for raw in payload["capabilities"]:
        if not isinstance(raw, dict):
            raise SeedManifestError("every capability entry must be a mapping")
        try:
            entry = SeedCapability(
                slug=raw["id"],
                stable_key=raw["stable_key"],
                name=raw["name"],
                definition=raw["definition"],
                parent=raw.get("parent"),
                boundary_ref=raw.get("boundary_ref"),
                seed_source=raw["seed_source"],
            )
        except KeyError as exc:
            raise SeedManifestError(f"capability entry lacks required field {exc.args[0]!r}") from exc
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                entry.slug,
                entry.stable_key,
                entry.name,
                entry.definition,
                entry.seed_source,
            )
        ):
            raise SeedManifestError(f"capability {entry.slug!r} has an empty required field")
        if entry.parent is not None and not isinstance(entry.parent, str):
            raise SeedManifestError(f"capability {entry.slug!r} parent must be a slug or null")
        if entry.slug in seen:
            raise SeedManifestError(f"duplicate capability slug: {entry.slug}")
        if entry.stable_key in seen_stable_keys:
            raise SeedManifestError(f"duplicate capability stable_key: {entry.stable_key}")
        if entry.name in seen_names:
            # Display names remain unique even though stable_key owns identity.
            raise SeedManifestError(f"duplicate capability name: {entry.name}")
        if not _source_path(entry.seed_source, repo_root).is_file():
            raise SeedManifestError(f"seed source does not resolve: {entry.seed_source}")
        seen.add(entry.slug)
        seen_stable_keys.add(entry.stable_key)
        seen_names.add(entry.name)
        entries.append(entry)

    by_slug = {entry.slug: entry for entry in entries}
    for entry in entries:
        if entry.parent is not None and entry.parent not in by_slug:
            raise SeedManifestError(f"unknown parent {entry.parent!r} for {entry.slug!r}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(slug: str) -> None:
        if slug in visiting:
            raise SeedManifestError(f"parent cycle detected at capability {slug!r}")
        if slug in visited:
            return
        visiting.add(slug)
        parent = by_slug[slug].parent
        if parent is not None:
            visit(parent)
        visiting.remove(slug)
        visited.add(slug)

    for entry in entries:
        visit(entry.slug)
    return entries


def seed_capabilities(
    store: CkmStore,
    *,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    repo_root: Path = REPO_ROOT,
) -> dict[str, int]:
    """Idempotently upsert reviewed seed capabilities into *store*."""

    entries = load_manifest(manifest_path, repo_root=repo_root)
    by_slug = {entry.slug: entry for entry in entries}
    seeded: dict[str, Any] = {}
    changed = 0

    def seed_one(entry: SeedCapability) -> None:
        nonlocal changed
        if entry.slug in seeded:
            return
        parent_id = None
        if entry.parent is not None:
            seed_one(by_slug[entry.parent])
            parent_id = seeded[entry.parent].id
        provenance = f"seeded:{entry.seed_source}"
        identity_key = f"seed:{entry.stable_key}"
        existing = store.get_capability_by_identity_key(identity_key)
        if existing is not None and (
            existing.name == entry.name
            and existing.definition == entry.definition
            and existing.parent_id == parent_id
            and existing.lifecycle == "confirmed"
            and existing.existence_provenance == provenance
            and existing.boundary_ref == entry.boundary_ref
        ):
            seeded[entry.slug] = existing
            return
        seeded[entry.slug] = store.upsert_capability(
            name=entry.name,
            definition=entry.definition,
            parent_id=parent_id,
            lifecycle="confirmed",
            existence_provenance=provenance,
            boundary_ref=entry.boundary_ref,
            identity_key=identity_key,
        )
        changed += 1

    for entry in entries:
        seed_one(entry)
    return {"seeded": len(entries), "changed": changed}
