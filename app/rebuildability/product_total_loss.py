"""Fail-closed Product store readiness for retained-source rebuilds.

This module deliberately covers the object projection only.  Vector, relation,
and queue replay belong to RSC-03.  A Product object row is usable after loss
only when its retained source locator, source-content generation, and replay
recipe are all present and agree with the current retained note.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

import yaml

from app.agents.panel.filters import strip_ai_panels
from app.agents.panel.writeback import strip_ai_status_block
from app.objects import resolve_canonical_object_id

PRODUCT_REPLAY_RECIPE_VERSION = "product-object-replay-v1"
ProductReadinessState = Literal["ready", "empty", "refused", "not_selected"]


class ProductReplayRefusal(RuntimeError):
    """Typed refusal to serve a Product projection with incomplete replay proof."""

    code = "product_replay_refused"


@dataclass(frozen=True)
class ProductReplayTuple:
    """The minimum source-bound identity needed to use one Product row."""

    source_identity: str
    source_generation: str
    recipe_version: str = PRODUCT_REPLAY_RECIPE_VERSION

    def as_dict(self) -> dict[str, str]:
        return {
            "source_identity": self.source_identity,
            "source_generation": self.source_generation,
            "recipe_version": self.recipe_version,
        }


@dataclass(frozen=True)
class _RetainedSource:
    replay: ProductReplayTuple
    title: str
    text: str
    object_id: str


@dataclass(frozen=True)
class ProductReadiness:
    state: ProductReadinessState
    ready: bool
    reason: str
    source_count: int
    projection_count: int
    refused_source_identities: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "ready": self.ready,
            "reason": self.reason,
            "source_count": self.source_count,
            "projection_count": self.projection_count,
            "refused_source_identities": list(self.refused_source_identities),
        }


def product_replay_provenance(
    *,
    source_identity: str,
    source_text: str,
    recipe_version: str = PRODUCT_REPLAY_RECIPE_VERSION,
    allow_empty_source: bool = False,
) -> dict[str, str]:
    """Build the source-bound tuple stamped into a Product object payload."""

    identity = source_identity.strip().replace("\\", "/")
    if not identity:
        raise ProductReplayRefusal("source identity is empty")
    if not source_text.strip() and not allow_empty_source:
        raise ProductReplayRefusal(f"source {identity!r} has no meaning-bearing text")
    if not recipe_version.strip():
        raise ProductReplayRefusal("replay recipe version is empty")
    return ProductReplayTuple(
        source_identity=identity,
        source_generation=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        recipe_version=recipe_version,
    ).as_dict()


def _canonical_source_text(raw_text: str) -> str:
    _frontmatter, body = parse_markdown_text(raw_text)
    del _frontmatter
    return strip_ai_status_block(strip_ai_panels(body)).strip()


def canonical_product_source_text(raw_text: str) -> str:
    """Return the canonical meaning-bearing text used by Product replay."""

    return _canonical_source_text(raw_text)


def canonical_product_body_text(body: str) -> str:
    """Canonicalize an already extracted note body without frontmatter parsing.

    A Markdown body may legitimately begin with ``---`` thematic separators.
    Treating that body as a complete note would make the bounded parser inspect
    the first section as YAML and hash only the suffix. Producers that already
    have the extracted body must use this seam instead of reparsing it.
    """

    return strip_ai_status_block(strip_ai_panels(body)).strip()


def parse_markdown_text(raw_text: str) -> tuple[dict[str, Any], str]:
    """Parse one note using the same bounded frontmatter shape as ingest."""

    lines = raw_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, raw_text.strip()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, raw_text.strip()
    try:
        frontmatter = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError:
        frontmatter = {}
    return (frontmatter if isinstance(frontmatter, dict) else {}), "\n".join(lines[end + 1 :]).strip()


def _retained_sources(vault_root: Path) -> tuple[list[_RetainedSource], list[str]]:
    # Imported lazily because vault-alpha stamps this module's replay tuple.
    # The selected candidates are its production source admission policy.
    from app.ingest.vault_alpha import (
        resolve_vault_note_identity,
        select_source_backed_rebuild_candidates,
    )
    root = vault_root.expanduser().resolve()
    try:
        candidates = select_source_backed_rebuild_candidates(root)
    except Exception as exc:
        return [], [f"retained-source-selection:{type(exc).__name__}"]

    sources: list[_RetainedSource] = []
    failures: list[str] = []
    for path in candidates:
        try:
            relative = path.resolve().relative_to(root).as_posix()
            raw_text = path.read_text(encoding="utf-8")
            frontmatter, body = parse_markdown_text(raw_text)
            text = _canonical_source_text(raw_text)
            replay = ProductReplayTuple(
                **product_replay_provenance(
                    source_identity=relative,
                    source_text=text,
                    allow_empty_source=True,
                )
            )
            note_identity = resolve_vault_note_identity(
                path, vault_root=root, frontmatter=frontmatter, body=body
            )
            object_id = resolve_canonical_object_id(note_identity.note_uuid)
        except Exception as exc:
            failures.append(f"{path.name}:{type(exc).__name__}")
            continue
        sources.append(
            _RetainedSource(
                replay=replay,
                title=path.stem,
                text=text,
                object_id=object_id,
            )
        )
    return sources, failures


def _row_payload(row: Any) -> dict[str, Any] | None:
    payload = row.get("payload") if isinstance(row, dict) else getattr(row, "payload", None)
    return payload if isinstance(payload, dict) else None


def _row_source_identity(row: Any, *, vault_root: Path) -> str:
    """Normalize a row locator for matching replay-less retained projections."""
    raw_source = row.get("source_ref") if isinstance(row, dict) else getattr(row, "source_ref", None)
    if not isinstance(raw_source, str) or not raw_source.strip():
        return ""
    candidate = Path(raw_source).expanduser()
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(vault_root.resolve()).as_posix()
        except ValueError:
            return ""
    return raw_source.strip().replace("\\", "/").lstrip("./")


def _row_object_id(row: Any) -> str:
    raw_object_id = row.get("object_id") if isinstance(row, dict) else getattr(row, "object_id", None)
    return str(raw_object_id).strip() if raw_object_id is not None else ""


def _is_product_row(row: Any) -> bool:
    kind = row.get("kind") if isinstance(row, dict) else getattr(row, "kind", None)
    return kind in {None, "note"}


def _row_replay(payload: dict[str, Any]) -> ProductReplayTuple | None:
    raw = payload.get("replay")
    if not isinstance(raw, dict):
        return None
    source_identity = raw.get("source_identity")
    source_generation = raw.get("source_generation")
    recipe_version = raw.get("recipe_version")
    if not isinstance(source_identity, str) or not source_identity.strip():
        return None
    if not isinstance(source_generation, str) or not source_generation.strip():
        return None
    if not isinstance(recipe_version, str) or not recipe_version.strip():
        return None
    return ProductReplayTuple(
        source_identity=source_identity,
        source_generation=source_generation,
        recipe_version=recipe_version,
    )


def _payload_text(payload: dict[str, Any]) -> str:
    for key in ("text", "content", "raw_text"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def _canonical_payload_text(payload: dict[str, Any]) -> str:
    """Canonicalize stored text according to the producer's capture semantics."""
    if payload.get("replay_text_kind") == "extracted_body":
        return canonical_product_body_text(_payload_text(payload))
    if isinstance(payload.get("content"), str):
        return canonical_product_body_text(str(payload["content"]))
    return _canonical_source_text(_payload_text(payload))


def evaluate_product_store_readiness(
    vault_root: Path | None,
    projection_rows: Iterable[Any],
) -> ProductReadiness:
    """Return a non-authorizing, fail-closed readiness result for Product objects.

    ``projection_rows`` is intentionally supplied by the StorePort caller.  The
    function never repairs, deletes, or falls back to process memory.
    """

    if vault_root is None:
        return ProductReadiness("not_selected", True, "no vault selected", 0, 0)

    sources, source_failures = _retained_sources(vault_root)
    rows = [row for row in projection_rows if _is_product_row(row)]
    if not sources and not source_failures:
        return ProductReadiness("empty", True, "no retained Product sources", 0, 0)
    if source_failures:
        return ProductReadiness(
            "refused",
            False,
            "retained source inventory is unreadable",
            len(sources),
            len(rows),
            tuple(sorted(source_failures)),
        )
    if not sources:
        return ProductReadiness("refused", False, "projection has no retained source set", 0, len(rows))

    retained_identities = {source.replay.source_identity for source in sources}
    by_identity: dict[str, list[tuple[ProductReplayTuple, dict[str, Any], str]]] = {}
    corrupt: list[str] = []
    for row in rows:
        payload = _row_payload(row)
        if payload is None:
            if _row_source_identity(row, vault_root=vault_root) in retained_identities:
                corrupt.append("projection-row")
            continue
        replay = _row_replay(payload)
        if replay is None:
            if _row_source_identity(row, vault_root=vault_root) in retained_identities:
                corrupt.append("projection-row")
            continue
        if replay.source_identity not in retained_identities:
            continue
        by_identity.setdefault(replay.source_identity, []).append(
            (replay, payload, _row_object_id(row))
        )

    refused: list[str] = list(corrupt)
    for source in sources:
        observed = by_identity.get(source.replay.source_identity, [])
        observed_payload = observed[0][1] if len(observed) == 1 else None
        observed_text = _canonical_payload_text(observed_payload or {})
        if (
            len(observed) != 1
            or observed[0][0] != source.replay
            or observed_text != source.text
            or observed[0][2] != source.object_id
        ):
            refused.append(source.replay.source_identity)
    if refused:
        return ProductReadiness(
            "refused",
            False,
            "Product projection requires source-bound reconstruction and integrity verification",
            len(sources),
            len(rows),
            tuple(sorted(set(refused))),
        )
    return ProductReadiness("ready", True, "source-bound Product projection verified", len(sources), len(rows))


__all__ = [
    "PRODUCT_REPLAY_RECIPE_VERSION",
    "ProductReadiness",
    "ProductReplayRefusal",
    "ProductReplayTuple",
    "canonical_product_body_text",
    "canonical_product_source_text",
    "evaluate_product_store_readiness",
    "product_replay_provenance",
]
