"""Source-bound replay for the complete Product projection composition.

RSC-03 keeps the replay decision separate from effect execution. Retained
source records rebuild the owner-native object, vector, and relation seams;
durable outbox events are copied into a deduplicated pending-work ledger. A
JSONL audit record, an unknown event, or an orphaned source cannot enter that
ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol
from uuid import UUID

from app.components.embeddings import EmbeddingIdentity
from app.instance.binding_ids import (
    COMPATIBILITY_BINDING_ID,
    OUTBOX_GLOBAL_BINDING_ID,
    OUTBOX_QUARANTINE_BINDING_ID,
)
from app.rebuildability.product_total_loss import (
    ProductReplayRefusal,
    ProductReplayTuple,
    canonical_product_source_text,
    parse_markdown_text,
    product_replay_provenance,
)
RECONSTRUCTABLE_QUEUE_EVENTS = frozenset(
    {
        "index.embedding.requested",
        "panel.scan.requested",
        "promote.intent.created",
        "note.move.workbench",
    }
)
_RETAINED_SOURCE_AUTHORITY = object()
_DB_OUTBOX_AUTHORITY = object()


class ObjectProjectionSink(Protocol):
    """Structural owner-native object projection seam.

    The protocol is kept local because ``app.stores`` is a deprecated import
    surface. Concrete Product store providers already satisfy this contract.
    """

    def put(self, object_id: UUID, *, kind: str, source_ref: str, payload: dict[str, Any]) -> None: ...


class VectorProjectionSink(Protocol):
    """Structural owner-native vector projection seam."""

    def get_identity(self) -> EmbeddingIdentity | None: ...

    def upsert(
        self,
        object_id: UUID,
        *,
        kind: str,
        source_ref: str,
        payload: dict[str, Any],
        embedding: list[float],
        model: str,
        identity: EmbeddingIdentity,
    ) -> None: ...


class RelationProjectionSink(Protocol):
    """Structural owner-native relation projection seam."""

    def link(self, src: UUID, dst: UUID, *, rel: str, payload: dict[str, Any]) -> None: ...

    def add_membership(
        self,
        src: UUID,
        *,
        rel: str,
        value: str,
        payload: dict[str, Any],
    ) -> None: ...


class ProjectionQueueSink(Protocol):
    def enqueue(self, work: "DurableProjectionWork") -> bool: ...


class ProjectionEmbeddingSource(Protocol):
    identity: EmbeddingIdentity

    def embed_text(self, text: str) -> list[float]: ...


class ProductProjectionReplayRefusal(ProductReplayRefusal):
    """Typed refusal for an incomplete or non-canonical projection replay."""

    code = "product_projection_replay_refused"


@dataclass(frozen=True)
class ProjectionRelation:
    src_id: UUID
    dst_id: UUID
    relation_type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetainedProjectionSource:
    """One retained source record and its declared derived relationships."""

    object_id: UUID
    source_identity: str
    text: str
    payload: dict[str, Any]
    embedding: list[float]
    embedding_identity: EmbeddingIdentity
    relations: tuple[ProjectionRelation, ...] = ()
    memberships: tuple[tuple[str, str, dict[str, Any]], ...] = ()
    _authority: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authority is not _RETAINED_SOURCE_AUTHORITY:
            raise ProductProjectionReplayRefusal(
                "projection sources must be loaded from a retained source authority"
            )

    @classmethod
    def from_retained_file(
        cls,
        *,
        vault_root: Path,
        source_identity: str,
        object_id: UUID,
        payload: dict[str, Any],
        embedding_source: ProjectionEmbeddingSource,
        relations: Iterable[ProjectionRelation] = (),
        memberships: Iterable[tuple[str, str, dict[str, Any]]] = (),
    ) -> "RetainedProjectionSource":
        """Load source text and identity from the retained vault owner seam."""

        root = vault_root.expanduser().resolve()
        identity = source_identity.strip().replace("\\", "/")
        path = (root / identity).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ProductProjectionReplayRefusal(
                f"retained source {source_identity!r} escapes the selected vault"
            ) from exc
        if not path.is_file():
            raise ProductProjectionReplayRefusal(
                f"retained source {identity!r} is not a regular file"
            )
        raw_text = path.read_text(encoding="utf-8")
        frontmatter, _body = parse_markdown_text(raw_text)
        if str(frontmatter.get("uuid") or "") != str(object_id):
            raise ProductProjectionReplayRefusal(
                f"retained source {identity!r} does not own object {object_id}"
            )
        text = canonical_product_source_text(raw_text)
        embedding = list(embedding_source.embed_text(text))
        embedding_identity = embedding_source.identity
        stamped = dict(payload)
        stamped["text"] = text
        stamped["replay"] = product_replay_provenance(
            source_identity=identity,
            source_text=text,
        )
        return cls(
            object_id=object_id,
            source_identity=identity,
            text=text,
            payload=stamped,
            embedding=list(embedding),
            embedding_identity=embedding_identity,
            relations=tuple(relations),
            memberships=tuple(memberships),
            _authority=_RETAINED_SOURCE_AUTHORITY,
        )

    @property
    def replay(self) -> ProductReplayTuple:
        try:
            return ProductReplayTuple(
                **product_replay_provenance(
                    source_identity=self.source_identity,
                    source_text=self.text,
                )
            )
        except ProductReplayRefusal as exc:
            raise ProductProjectionReplayRefusal(str(exc)) from exc

    @property
    def canonical_payload(self) -> dict[str, Any]:
        payload = dict(self.payload)
        expected = self.replay.as_dict()
        if payload.get("replay") != expected:
            raise ProductProjectionReplayRefusal(
                f"source {self.source_identity!r} has mismatched replay provenance"
            )
        if str(payload.get("text") or "") != self.text:
            raise ProductProjectionReplayRefusal(
                f"source {self.source_identity!r} has mismatched canonical text"
            )
        return payload


@dataclass(frozen=True)
class DurableProjectionWork:
    """A pending event copied from the canonical DB outbox contract."""

    row_id: str
    vault_binding_id: str
    envelope: dict[str, Any]
    event_id: str
    event: str
    source_identity: str
    replay: ProductReplayTuple
    payload: dict[str, Any] = field(default_factory=dict)
    source_kind: str = "db_outbox"
    _authority: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authority is not _DB_OUTBOX_AUTHORITY:
            raise ProductProjectionReplayRefusal(
                "projection work must be loaded from the canonical DB outbox"
            )

    @classmethod
    def _from_db_outbox_row(
        cls,
        row: Mapping[str, Any],
        *,
        eligible_binding_ids: frozenset[str],
    ) -> "DurableProjectionWork":
        row_id = str(row.get("id") or "").strip()
        binding_id = str(row.get("vault_binding_id") or "").strip()
        topic = str(row.get("topic") or "").strip()
        envelope = row.get("payload")
        if not row_id or not binding_id or binding_id not in eligible_binding_ids or not topic or not isinstance(envelope, Mapping):
            raise ProductProjectionReplayRefusal("malformed canonical DB outbox row")
        event_id = str(envelope.get("event_id") or "").strip()
        trace_id = str(envelope.get("trace_id") or "").strip()
        source = str(envelope.get("source") or "").strip()
        timestamp = str(envelope.get("timestamp") or "").strip()
        inner = envelope.get("payload")
        if (
            not event_id
            or not trace_id
            or not source
            or not timestamp
            or not isinstance(inner, Mapping)
        ):
            raise ProductProjectionReplayRefusal(
                f"DB outbox row {row_id!r} has an incomplete event envelope"
            )
        if str(envelope.get("event") or "") != topic:
            raise ProductProjectionReplayRefusal(
                f"DB outbox row {row_id!r} topic does not match its event envelope"
            )
        source_identity = str(inner.get("source_identity") or "").strip()
        replay_raw = inner.get("replay")
        if not source_identity or not isinstance(replay_raw, Mapping):
            raise ProductProjectionReplayRefusal(
                f"DB outbox row {row_id!r} has no source-bound replay payload"
            )
        try:
            replay = ProductReplayTuple(
                source_identity=str(replay_raw["source_identity"]),
                source_generation=str(replay_raw["source_generation"]),
                recipe_version=str(replay_raw["recipe_version"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProductProjectionReplayRefusal(
                f"DB outbox row {row_id!r} has malformed replay provenance"
            ) from exc
        return cls(
            row_id=row_id,
            vault_binding_id=binding_id,
            envelope=dict(envelope),
            event_id=event_id,
            event=topic,
            source_identity=source_identity,
            replay=replay,
            payload=dict(inner),
            _authority=_DB_OUTBOX_AUTHORITY,
        )


def load_durable_projection_work(
    conn: Any,
    *,
    eligible_binding_ids: tuple[str, ...],
    required_binding_stamp: Mapping[str, object] | None = None,
) -> list[DurableProjectionWork]:
    """Read pending work from the canonical DB outbox without acknowledging it."""

    if not eligible_binding_ids:
        raise ProductProjectionReplayRefusal("no selected DB outbox binding authority")
    placeholders = ", ".join("%s" for _ in eligible_binding_ids)
    params: tuple[object, ...] = (
        OUTBOX_QUARANTINE_BINDING_ID,
        *eligible_binding_ids,
    )
    binding_filter = f"vault_binding_id in ({placeholders})"
    if required_binding_stamp is not None:
        binding_id = str(required_binding_stamp["vault_binding_id"])
        binding_filter += (
            " and (vault_binding_id in (%s, %s) or (vault_binding_id = %s "
            "and payload #>> '{meta,vault_binding_id}' = %s "
            "and payload #>> '{meta,binding_authority}' = %s "
            "and payload #>> '{meta,binding_authorization_epoch}' = %s "
            "and payload #>> '{meta,binding_revision}' = %s "
            "and payload #>> '{meta,vault_root}' = %s))"
        )
        params = (
            *params,
            COMPATIBILITY_BINDING_ID,
            OUTBOX_GLOBAL_BINDING_ID,
            binding_id,
            binding_id,
            str(required_binding_stamp["binding_authority"]),
            str(required_binding_stamp["binding_authorization_epoch"]),
            str(required_binding_stamp["binding_revision"]),
            str(required_binding_stamp["vault_root"]),
        )
    cursor = conn.cursor()
    try:
        cursor.execute(
            "select id, topic, payload, vault_binding_id from outbox "
            "where delivered_at is null and vault_binding_id <> %s and "
            + binding_filter
            + " order by created_at asc, id asc",
            params,
        )
        rows = cursor.fetchall()
    finally:
        close = getattr(cursor, "close", None)
        if close is not None:
            close()
    binding_set = frozenset(eligible_binding_ids)
    return [
        DurableProjectionWork._from_db_outbox_row(
            dict(row), eligible_binding_ids=binding_set
        )
        for row in rows
    ]


@dataclass
class ProjectionReplayQueue:
    """In-memory test double for the durable DB-outbox-backed queue view."""

    pending: dict[str, DurableProjectionWork] = field(default_factory=dict)

    def enqueue(self, work: DurableProjectionWork) -> bool:
        existing = self.pending.get(work.event_id)
        if existing is not None:
            if existing != work:
                raise ProductProjectionReplayRefusal(
                    f"event {work.event_id!r} has conflicting durable replay payload"
                )
            return False
        self.pending[work.event_id] = work
        return True


class DbOutboxProjectionQueue:
    """Read-only queue projection backed by canonical undelivered DB rows.

    The database outbox remains the durable queue and worker authority. Replay
    does not copy rows into process memory or execute them; this adapter only
    confirms that a work item came from the selected durable row set.
    """

    def __init__(
        self,
        conn: Any,
        *,
        eligible_binding_ids: tuple[str, ...],
        required_binding_stamp: Mapping[str, object] | None = None,
    ) -> None:
        self._conn = conn
        self._eligible_binding_ids = eligible_binding_ids
        self._required_binding_stamp = required_binding_stamp

    @property
    def pending(self) -> dict[str, DurableProjectionWork]:
        return {
            work.event_id: work
            for work in load_durable_projection_work(
                self._conn,
                eligible_binding_ids=self._eligible_binding_ids,
                required_binding_stamp=self._required_binding_stamp,
            )
        }

    def enqueue(self, work: "DurableProjectionWork") -> bool:
        durable = self.pending
        existing = durable.get(work.event_id)
        if existing != work:
            raise ProductProjectionReplayRefusal(
                f"event {work.event_id!r} is not the selected durable DB outbox row"
            )
        return False


@dataclass(frozen=True)
class ProductProjectionTargets:
    objects: ObjectProjectionSink
    vectors: VectorProjectionSink
    relations: RelationProjectionSink
    queue: ProjectionQueueSink


@dataclass(frozen=True)
class ProjectionReplaySummary:
    sources: int
    object_rows: int
    vector_rows: int
    relation_rows: int
    membership_rows: int
    queued_work: int
    duplicate_work: int


def _validate_sources(
    sources: list[RetainedProjectionSource],
) -> dict[str, RetainedProjectionSource]:
    by_identity: dict[str, RetainedProjectionSource] = {}
    object_ids: dict[UUID, str] = {}
    for source in sources:
        if source.source_identity in by_identity:
            raise ProductProjectionReplayRefusal(
                f"duplicate retained source identity {source.source_identity!r}"
            )
        if source.object_id in object_ids:
            raise ProductProjectionReplayRefusal(
                f"object identity {source.object_id} is claimed by both "
                f"{object_ids[source.object_id]!r} and {source.source_identity!r}"
            )
        source.canonical_payload
        if len(source.embedding) != source.embedding_identity.dim:
            raise ProductProjectionReplayRefusal(
                f"source {source.source_identity!r} has an embedding dimension mismatch"
            )
        by_identity[source.source_identity] = source
        object_ids[source.object_id] = source.source_identity

    known_ids = set(object_ids)
    relation_keys: set[tuple[UUID, UUID, str]] = set()
    for source in sources:
        for relation in source.relations:
            if relation.src_id != source.object_id:
                raise ProductProjectionReplayRefusal(
                    f"relation {relation.relation_type!r} is not owned by its retained source"
                )
            if relation.src_id not in known_ids or relation.dst_id not in known_ids:
                raise ProductProjectionReplayRefusal(
                    f"relation {relation.relation_type!r} references an unknown object"
                )
            key = (relation.src_id, relation.dst_id, relation.relation_type)
            if key in relation_keys:
                raise ProductProjectionReplayRefusal(f"duplicate relation {key!r}")
            relation_keys.add(key)
    return by_identity


def _validate_work(
    work_items: list[DurableProjectionWork],
    sources: dict[str, RetainedProjectionSource],
) -> None:
    seen_ids: set[str] = set()
    for work in work_items:
        if not work.event_id.strip():
            raise ProductProjectionReplayRefusal("durable replay event id is empty")
        if work.event_id in seen_ids:
            raise ProductProjectionReplayRefusal(f"duplicate replay event {work.event_id!r}")
        seen_ids.add(work.event_id)
        if work.source_kind != "db_outbox":
            raise ProductProjectionReplayRefusal(
                f"event {work.event_id!r} is not from the canonical DB outbox"
            )
        if work.event not in RECONSTRUCTABLE_QUEUE_EVENTS:
            raise ProductProjectionReplayRefusal(
                f"event {work.event!r} is not a reconstructable Product queue event"
            )
        source = sources.get(work.source_identity)
        if source is None:
            raise ProductProjectionReplayRefusal(
                f"event {work.event_id!r} has an orphaned source identity"
            )
        if work.replay != source.replay:
            raise ProductProjectionReplayRefusal(
                f"event {work.event_id!r} has mismatched replay provenance"
            )


def _validate_embedding_targets(
    sources: list[RetainedProjectionSource], targets: ProductProjectionTargets
) -> None:
    if not sources:
        return
    expected = sources[0].embedding_identity
    if any(source.embedding_identity != expected for source in sources[1:]):
        raise ProductProjectionReplayRefusal(
            "retained sources use mixed embedding identities"
        )
    target_identity = targets.vectors.get_identity()
    if target_identity is not None and target_identity != expected:
        raise ProductProjectionReplayRefusal(
            "target vector projection has a conflicting embedding identity"
        )


def rebuild_product_projections(
    sources: Iterable[RetainedProjectionSource],
    work_items: Iterable[DurableProjectionWork],
    targets: ProductProjectionTargets,
) -> ProjectionReplaySummary:
    """Replay all Product projections after validating the complete source set.

    Validation happens before the first write, then every sink uses its owner
    contract's idempotent upsert/link operation. Calling this function twice
    therefore has the same canonical result as calling it once.
    """

    source_list = list(sources)
    work_list = list(work_items)
    by_identity = _validate_sources(source_list)
    _validate_work(work_list, by_identity)
    _validate_embedding_targets(source_list, targets)

    relation_rows = 0
    membership_rows = 0
    for source in source_list:
        payload = source.canonical_payload
        targets.objects.put(
            source.object_id,
            kind=str(payload.get("kind") or "note"),
            source_ref=source.source_identity,
            payload=payload,
        )
        targets.vectors.upsert(
            source.object_id,
            kind=str(payload.get("kind") or "note"),
            source_ref=source.source_identity,
            payload=payload,
            embedding=list(source.embedding),
            model=source.embedding_identity.model,
            identity=source.embedding_identity,
        )
        for relation in source.relations:
            relation_payload = dict(relation.payload)
            relation_payload["replay"] = source.replay.as_dict()
            targets.relations.link(
                relation.src_id,
                relation.dst_id,
                rel=relation.relation_type,
                payload=relation_payload,
            )
            relation_rows += 1
        for relation_type, value, membership_payload in source.memberships:
            payload_copy = dict(membership_payload)
            payload_copy["replay"] = source.replay.as_dict()
            targets.relations.add_membership(
                source.object_id,
                rel=relation_type,
                value=value,
                payload=payload_copy,
            )
            membership_rows += 1

    queued_work = 0
    duplicate_work = 0
    for work in work_list:
        if targets.queue.enqueue(work):
            queued_work += 1
        else:
            duplicate_work += 1

    return ProjectionReplaySummary(
        sources=len(source_list),
        object_rows=len(source_list),
        vector_rows=len(source_list),
        relation_rows=relation_rows,
        membership_rows=membership_rows,
        queued_work=queued_work,
        duplicate_work=duplicate_work,
    )


__all__ = [
    "DbOutboxProjectionQueue",
    "DurableProjectionWork",
    "ProjectionRelation",
    "ProjectionReplayQueue",
    "ProjectionReplaySummary",
    "ProductProjectionReplayRefusal",
    "ProductProjectionTargets",
    "RECONSTRUCTABLE_QUEUE_EVENTS",
    "RetainedProjectionSource",
    "load_durable_projection_work",
    "rebuild_product_projections",
]
