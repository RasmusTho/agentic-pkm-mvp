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
from app.ingest.episode_ref import episode_ref_from_frontmatter
from app.domain.state_axes import normalize_artifact_state_axes, normalize_review_state
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.objects import (
    retained_vault_uuid_to_canonical_id_map,
    resolve_object_store_port,
)

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
    review_state: str
    episode_ref: str | list[str]
    text: str
    vault_uuid: str
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


def parse_bounded_frontmatter(
    raw_text: str,
) -> tuple[dict[str, Any], str, yaml.YAMLError | None]:
    """Parse frontmatter using whole-line delimiters shared by all producers.

    Splitting on the ``---`` token is unsafe because that token can occur in a
    valid YAML scalar. The opening and closing delimiters are therefore
    recognized only as complete lines; the body is returned without reparsing
    it as Markdown frontmatter.
    """
    lines = raw_text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, raw_text, None
    closing = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing is None:
        return {}, raw_text, None
    body = "".join(lines[closing + 1 :]).lstrip("\n")
    try:
        frontmatter = yaml.safe_load("".join(lines[1:closing])) or {}
    except yaml.YAMLError as exc:
        return {}, body, exc
    return (frontmatter if isinstance(frontmatter, dict) else {}), body, None


def parse_markdown_text(raw_text: str) -> tuple[dict[str, Any], str]:
    """Parse one note using the shared bounded frontmatter parser."""

    frontmatter, body, _error = parse_bounded_frontmatter(raw_text)
    return frontmatter, body.strip()


def _canonical_object_ids_for_sources(vault_uuids: Iterable[str]) -> dict[str, str]:
    """Resolve retained identities with one binding-scoped inventory lookup."""
    values = tuple(dict.fromkeys(str(value) for value in vault_uuids))
    if not values:
        return {}
    binding = resolve_object_store_port()
    if binding.backend != "pg":
        return {value: value for value in values}

    binding_id = str(getattr(binding.store, "vault_binding_id", COMPATIBILITY_BINDING_ID))
    loaded = retained_vault_uuid_to_canonical_id_map(vault_binding_id=binding_id)
    return {value: loaded.get(value, value) for value in values}


def _retained_sources(vault_root: Path) -> tuple[list[_RetainedSource], list[str]]:
    # Imported lazily because vault-alpha stamps this module's replay tuple.
    # The selected candidates are its production source admission policy.
    from app.ingest.vault_alpha import (
        _derive_title,
        _frontmatter_title,
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
            frontmatter, body, frontmatter_error = parse_bounded_frontmatter(raw_text)
            if frontmatter_error is not None:
                failures.append(f"{relative}:malformed-frontmatter")
                continue
            text = canonical_product_body_text(body)
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
        except Exception as exc:
            failures.append(f"{path.name}:{type(exc).__name__}")
            continue
        sources.append(
            _RetainedSource(
                replay=replay,
                title=_frontmatter_title(frontmatter) or _derive_title(body, path),
                review_state=normalize_artifact_state_axes(
                    frontmatter, default_review_state="provisional"
                )["review_state"],
                episode_ref=episode_ref_from_frontmatter(frontmatter),
                text=text,
                vault_uuid=note_identity.note_uuid,
                object_id="",
            )
        )
    claims: dict[str, list[str]] = {}
    for source in sources:
        claims.setdefault(source.vault_uuid, []).append(source.replay.source_identity)
    for vault_uuid, source_identities in claims.items():
        if len(source_identities) > 1:
            failures.append(
                f"duplicate-retained-vault-uuid:{vault_uuid}"
            )
    if failures:
        return sources, failures
    if sources:
        try:
            object_ids = _canonical_object_ids_for_sources(source.vault_uuid for source in sources)
        except Exception as exc:
            failures.append(f"canonical-object-id-map:{type(exc).__name__}")
            return sources, failures
        sources = [
            _RetainedSource(
                replay=source.replay,
                title=source.title,
                review_state=source.review_state,
                episode_ref=source.episode_ref,
                text=source.text,
                vault_uuid=source.vault_uuid,
                object_id=object_ids.get(source.vault_uuid, source.vault_uuid),
            )
            for source in sources
        ]
    return sources, failures


def _row_payload(row: Any) -> dict[str, Any] | None:
    payload = row.get("payload") if isinstance(row, dict) else getattr(row, "payload", None)
    return payload if isinstance(payload, dict) else None


def _row_source_identity(row: Any, *, vault_root: Path) -> str:
    """Normalize a row locator for matching replay-less retained projections."""
    raw_source = row.get("source_ref") if isinstance(row, dict) else getattr(row, "source_ref", None)
    if not isinstance(raw_source, str) or not raw_source.strip():
        return ""
    root = vault_root.expanduser().resolve()
    normalized = raw_source.strip().replace("\\", "/")
    candidate = Path(normalized).expanduser()
    try:
        resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
        return resolved.relative_to(root).as_posix()
    except ValueError:
        # Empty, absolute-outside, and traversal locators are all unusable
        # source provenance. They must fail readiness rather than normalize
        # into a different retained source identity.
        return ""


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


def _row_projection_metadata(payload: dict[str, Any]) -> tuple[Any, Any, Any]:
    """Read the canonical note metadata carried by Product projections."""
    core6 = payload.get("core6")
    core6 = core6 if isinstance(core6, dict) else {}
    title = payload.get("title", core6.get("title"))
    raw_review_state = payload.get("review_state", core6.get("review_state"))
    normalized_review_state = normalize_review_state(raw_review_state)
    review_state = normalized_review_state or raw_review_state
    episode_ref = payload.get("episode_ref")
    return title, review_state, episode_ref


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
    by_identity: dict[str, list[tuple[ProductReplayTuple, dict[str, Any], str, str]]] = {}
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
            (replay, payload, _row_object_id(row), _row_source_identity(row, vault_root=vault_root))
        )

    refused: list[str] = list(corrupt)
    for source in sources:
        observed = by_identity.get(source.replay.source_identity, [])
        observed_payload = observed[0][1] if len(observed) == 1 else None
        observed_text = _canonical_payload_text(observed_payload or {})
        observed_title, observed_review_state, observed_episode_ref = _row_projection_metadata(
            observed_payload or {}
        )
        if (
            len(observed) != 1
            or observed[0][0] != source.replay
            or observed_text != source.text
            or observed_title != source.title
            or observed_review_state != source.review_state
            or observed_episode_ref != source.episode_ref
            or observed[0][2] != source.object_id
            or observed[0][3] != source.replay.source_identity
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
    "parse_bounded_frontmatter",
    "parse_markdown_text",
    "product_replay_provenance",
]
