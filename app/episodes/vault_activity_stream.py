"""``vault.activity`` stream adapter (ERE-04, #3179).

Spec: ``docs/EPISODE_RESOLUTION_ENGINE/TWO_STREAM_SEGMENTATION_CORE.md`` --
"an outbox consumer on ``ingest.vault.changed`` / ``ingest.object.created`` /
``ingest.object.deleted`` per the ``docs/EVENTS.md`` consumer contract,
enriched with ``extract_context_dimensions_for_note`` frontmatter
dimensions." Registered in the stream registry
(``docs/EPISODE_RESOLUTION_ENGINE/stream_registry.md``) with transport
``outbox:ingest.vault.changed``.

The DB ``outbox`` table's ``delivered_at`` column is a single shared flag the
worker dispatcher owns (docs/EVENTS.md :: Outbox consumer contract) -- a
second logical consumer reading or marking it would race the worker's own
dispatch (indexer/panel handlers already consume these exact topics). This
module never reads or writes ``delivered_at``; it keeps its own independent,
durable, per-consumer position via :mod:`app.episodes.engine_state`,
generalizing the ``heimdal_observation_cursor`` per-consumer-cursor
precedent (``app/heimdal/publish.py``) to the shared ``outbox`` table.
"""

from __future__ import annotations

import json as _json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.db.db import conn_rw
from app.episodes import engine_state
from app.events.types import INGEST_OBJECT_CREATED, INGEST_OBJECT_DELETED, INGEST_VAULT_CHANGED
from app.instance.binding_ids import OUTBOX_QUARANTINE_BINDING_ID
from app.watcher.vault_watcher import extract_context_dimensions_for_note
from scripts.yaml_roundtrip import load_frontmatter

VAULT_ACTIVITY_STREAM_ID = "vault.activity"

# The three outbox topics the README/stream-registry declaration names for
# this stream_id (a registry entry carries one `transport` string for AC3
# binding-existence validation; the real multi-topic fan-in lives here).
VAULT_ACTIVITY_TOPICS: tuple[str, ...] = (
    INGEST_VAULT_CHANGED,
    INGEST_OBJECT_CREATED,
    INGEST_OBJECT_DELETED,
)

_CURSOR_KEY_PREFIX = "cursor:vault.activity:"


@dataclass(frozen=True)
class VaultActivityRow:
    id: str
    topic: str
    created_at: datetime
    payload: Mapping[str, Any]


def _cursor_key(consumer_id: str) -> str:
    return f"{_CURSOR_KEY_PREFIX}{consumer_id}"


def get_vault_activity_cursor(consumer_id: str) -> tuple[datetime | None, str | None]:
    """Read (never mutate) `consumer_id`'s durable position. Unseen -> (None, None) (read from event zero)."""
    state = engine_state.get_state(_cursor_key(consumer_id))
    if not state:
        return None, None
    created_at_raw = state.get("created_at")
    created_at = datetime.fromisoformat(created_at_raw) if created_at_raw else None
    return created_at, state.get("id")


def advance_vault_activity_cursor(consumer_id: str, rows: Sequence[VaultActivityRow]) -> None:
    """Advance `consumer_id`'s cursor past the given (already-durably-processed) rows.

    A no-op on an empty batch. Moves to the max `(created_at, id)` among the
    given rows only -- mirrors `app.heimdal.publish.advance_cursor_for_consumer`.
    """
    if not rows:
        return
    winner = max(rows, key=lambda r: (r.created_at, r.id))
    engine_state.set_state(
        _cursor_key(consumer_id),
        {
            "created_at": winner.created_at.astimezone(timezone.utc).isoformat(),
            "id": winner.id,
        },
    )


def read_vault_activity_for_consumer(consumer_id: str, *, limit: int | None = None) -> list[VaultActivityRow]:
    """Read the next unread vault-activity outbox rows for `consumer_id`, without advancing its cursor.

    Independent of the outbox worker's `delivered_at` -- reads every matching
    row regardless of worker-delivery state except rows whose source binding
    is quarantined as unprovable, ordered `(created_at, id)` ascending
    (docs/EVENTS.md FIFO-by-created_at ordering), strictly after the consumer's
    own last-seen position. Call
    :func:`advance_vault_activity_cursor` explicitly once the batch is
    durably processed downstream (at-least-once delivery, mirrors the
    Heimdal cursor contract).
    """
    created_at, row_id = get_vault_activity_cursor(consumer_id)
    topic_placeholders = ", ".join(["%s"] * len(VAULT_ACTIVITY_TOPICS))
    query = f"SELECT id, topic, payload, created_at FROM outbox WHERE topic IN ({topic_placeholders})"
    params: list[Any] = list(VAULT_ACTIVITY_TOPICS)
    query += " AND vault_binding_id <> %s"
    params.append(OUTBOX_QUARANTINE_BINDING_ID)
    if created_at is not None and row_id is not None:
        query += " AND (created_at, id) > (%s, %s::uuid)"
        params.extend([created_at, row_id])
    query += " ORDER BY created_at ASC, id ASC"
    if limit is not None:
        query += " LIMIT %s"
        params.append(limit)

    rows: list[VaultActivityRow] = []
    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute(query, tuple(params))
            for r in cur.fetchall():
                if isinstance(r, dict):
                    rid, topic, payload, created = r["id"], r["topic"], r["payload"], r["created_at"]
                else:
                    rid, topic, payload, created = r[0], r[1], r[2], r[3]
                if isinstance(payload, str):
                    payload = _json.loads(payload)
                rows.append(
                    VaultActivityRow(
                        id=str(rid), topic=str(topic), created_at=created, payload=dict(payload or {})
                    )
                )
    return rows


_EMPTY_DIMENSIONS: dict[str, Any] = {"scope": None, "sphere_memberships": [], "situated_identity": None}


def _resolve_note_path(payload: Mapping[str, Any], *, vault_root: Path) -> Path | None:
    """Resolve the payload's note reference to a path INSIDE ``vault_root``, or ``None``.

    `ingest.vault.changed` carries `relative_path` (vault-relative) plus
    `vault_path` (absolute at ingest time); `ingest.object.created` /
    `ingest.object.deleted` carry only `path` (absolute at ingest time,
    `app/services/vault_sync.py`). An absolute ingest-time path must never be
    read verbatim: `Path(vault_root) / absolute` discards ``vault_root``
    entirely, so a relocated vault or an explicit ``--vault-root`` override
    would silently read the ingest-time location. Instead every candidate --
    absolute (ingest-time) or relative (could still traverse out via `..`) --
    is containment-checked against the CURRENT ``vault_root`` and rejected
    (``None`` -> empty dimensions) when it does not resolve underneath it;
    never a read outside the engine's own vault root.
    """
    root = Path(vault_root).expanduser().resolve()
    for key in ("relative_path", "vault_path", "path"):
        value = payload.get(key)
        if not (isinstance(value, str) and value.strip()):
            continue
        candidate = Path(value.strip())
        resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
        if resolved == root or not resolved.is_relative_to(root):
            continue
        return resolved
    return None


def resolve_activity_dimensions(row: VaultActivityRow, *, vault_root: Path) -> dict[str, Any]:
    """Best-effort frontmatter dimension enrichment via `extract_context_dimensions_for_note`.

    Never raises: a note that is missing, unreadable, already deleted (e.g.
    the note behind an `ingest.object.deleted` row), or referenced by an
    ingest-time absolute path outside the current ``vault_root``
    (:func:`_resolve_note_path`) yields empty dimensions rather than failing
    the tick -- the row still contributes a bare time-dimension signal.
    """
    note_path = _resolve_note_path(row.payload, vault_root=vault_root)
    if note_path is None:
        return dict(_EMPTY_DIMENSIONS)
    try:
        text = note_path.read_text(encoding="utf-8")
        frontmatter, _body = load_frontmatter(text)
    except Exception:
        return dict(_EMPTY_DIMENSIONS)
    return extract_context_dimensions_for_note(frontmatter)


def resolve_bundle_target_for_outbox_row_id(
    row_id: str, *, vault_root: Path
) -> tuple[str | None, Path | None]:
    """Resolve one ``vault.activity:<row_id>`` provenance ref to its bundle-mutation target
    (ERE-05, #3180 Finding 1): ``(object_id, note_path)``.

    ``object_id`` is the ``store_objects``/``store_vector_index`` primary key -- read straight off
    the outbox event payload's own ``uuid``/``object_id`` key when present (``ingest.object.created``
    /``ingest.object.updated``/``ingest.object.metadata`` all carry one, see
    ``app/services/vault_sync.py`` and ``app/api/routes/ingest.py``), else read from the resolved
    note's own frontmatter ``uuid`` (``ingest.vault.changed`` carries only a path, never a bare
    ``uuid`` key in its payload). ``note_path`` is the same vault-relative-path resolution
    :func:`resolve_activity_dimensions` already performs (:func:`_resolve_note_path`), returned so
    the caller can also stamp the note's own frontmatter through the guarded write seam -- one DB
    read serves both the DB-side and vault-serialized bundle-mutation targets.

    Never raises: a missing/already-purged outbox row, a note referenced outside the current
    ``vault_root``, or an unreadable/deleted note all yield ``(None, None)`` (or a resolved
    ``note_path`` with ``object_id=None`` when only the frontmatter read fails) -- callers treat
    this as "no bundle to mutate for this artifact_ref" and skip it, never failing the whole tick
    (mirrors :func:`resolve_activity_dimensions`'s best-effort posture; outbox rows are never
    purged -- historical `to_correct` reconciliation, run ticks after the founding tick, resolves
    exactly like a fresh lookup).
    """
    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM outbox WHERE id = %s::uuid", (row_id,))
            row = cur.fetchone()
    if row is None:
        return None, None
    payload = row["payload"] if isinstance(row, dict) else row[0]
    if isinstance(payload, str):
        payload = _json.loads(payload)
    payload = dict(payload or {})

    note_path = _resolve_note_path(payload, vault_root=vault_root)

    raw_object_id = payload.get("uuid") or payload.get("object_id")
    if isinstance(raw_object_id, str) and raw_object_id.strip():
        return raw_object_id.strip(), note_path

    if note_path is None:
        return None, None
    try:
        text = note_path.read_text(encoding="utf-8")
        frontmatter, _body = load_frontmatter(text)
    except Exception:
        return None, note_path
    fm_uuid = frontmatter.get("uuid")
    return (fm_uuid.strip() if isinstance(fm_uuid, str) and fm_uuid.strip() else None), note_path


def resolve_scope_for_outbox_row_id(row_id: str, *, vault_root: Path) -> str | None:
    """Resolve one ``vault.activity:<row_id>`` provenance ref to its artifact's TRUE scope, or
    ``None`` when it cannot be determined (ERE-08 #3183, Finding 1 -- the cross-scope gate needs the
    artifact's real scope, never a scope forced by its caller).

    Reads the (never-purged) outbox row, resolves the note it references (:func:`_resolve_note_path`),
    and returns the SAME scope dimension segmentation itself assigns
    (:func:`app.episodes.segmenter._signal_from_vault_activity_row` uses
    ``resolve_activity_dimensions(...).get("scope")``, i.e.
    ``extract_context_dimensions_for_note``'s ``scope``/``domain`` frontmatter read). Best-effort,
    never raises: a missing/purged row, a note outside ``vault_root``, or an unreadable/deleted note
    yields ``None`` -- the caller treats an unresolvable scope conservatively."""
    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM outbox WHERE id = %s::uuid", (row_id,))
            row = cur.fetchone()
    if row is None:
        return None
    payload = row["payload"] if isinstance(row, dict) else row[0]
    if isinstance(payload, str):
        payload = _json.loads(payload)
    payload = dict(payload or {})

    note_path = _resolve_note_path(payload, vault_root=vault_root)
    if note_path is None:
        return None
    try:
        text = note_path.read_text(encoding="utf-8")
        frontmatter, _body = load_frontmatter(text)
    except Exception:
        return None
    scope = extract_context_dimensions_for_note(frontmatter).get("scope")
    return scope.strip() if isinstance(scope, str) and scope.strip() else None


__all__ = [
    "VAULT_ACTIVITY_STREAM_ID",
    "VAULT_ACTIVITY_TOPICS",
    "VaultActivityRow",
    "advance_vault_activity_cursor",
    "get_vault_activity_cursor",
    "read_vault_activity_for_consumer",
    "resolve_bundle_target_for_outbox_row_id",
    "resolve_activity_dimensions",
    "resolve_scope_for_outbox_row_id",
]
