"""Heimdal Karakeep reading-evidence adapter -- the Karakeep source-egress seam (KMA-03, #3374).

Ratified by ``docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md``
§1 (Heimdal owns watch -> fetch -> attribute -> published event; Mimer owns
cognition from the handoff) and specified by
``docs/KARAKEEP_MIMER_ACQUISITION/FETCH_KARAKEEP_READING_EVIDENCE.md`` (KMA-03)
against the source/identity/publish contract fixed in
``docs/KARAKEEP_MIMER_ACQUISITION/DEFINE_READING_SOURCE_AND_CANDIDATE_CONTRACT.md``
(KMA-01).

This module is the **only** component that reads the Karakeep REST API. It is
read-only: it fetches saved links/notes/highlights, canonicalizes each into a
source snapshot, derives stable identity/revision, stamps
provenance/confidence/attribution/entity-mentions, and publishes the contracted
``heimdal.observation.published.v1`` evidence through the sanctioned
``app.heimdal.publish.publish_full_observation`` seam. It commits the Heimdal
producer cursor only after publication is durable.

Constituent boundary (KMA-INV-4, issue AC 5): this module never imports or
invokes ``app.knowledge_acquisition``, never calls companion capture
(``/api/capture``), and never touches Mimer state. The published observation
log is the entire handoff; refinement begins on the other side of it.

Identity / revision (KMA-01 "Karakeep source item and revision identity"):

- ``source_item_identity = karakeep:<item-id>`` is the stable identity and the
  ``episode_id`` of every revision of that item.
- ``content_identity = sha256:<canonical-source-snapshot>`` hashes the canonical
  JSON of the evidence-bearing snapshot (item id, all evidence fields, deletion
  flag). Credentials, endpoint, fetch timestamps, and cursor values are
  excluded by construction -- they are never part of the snapshot.
- ``publication_profile_identity = sha256:<canonical-stage-versions>``.
- ``observation_id = karakeep:<item-id>:<content-hex>:<profile-hex>`` is one
  immutable publication. Re-fetching identical content at the same profile
  republishes the same idempotency input and is a traced no-op.
- A changed snapshot creates new ``content_identity``/``observation_id``, sets
  ``supersedes`` to the preceding revision, ``revision_of`` null. A same-snapshot
  reprocess through a changed publication profile sets ``revision_of`` to the
  preceding publication of that snapshot, ``supersedes`` null. A source deletion
  is a changed snapshot with ``content: null`` and
  ``content_structure.karakeep.tombstone: true`` that supersedes the prior live
  revision -- never a delete instruction.

Restart / durability (KMA-INV-2/INV-3): the durable, migration-owned observation
log is the source of truth for per-item revision lineage; :class:`KarakeepAdapter`
rebuilds that lineage from the log at the start of every run, so a crash that
loses the in-process producer cursor cannot skip or duplicate evidence -- a
replayed page dedups against the log before the producer cursor advances. The
producer cursor (:class:`KarakeepProducerCursor`) is a resume optimization: it
records the upstream page position and the last durable revision per item, and
advances only after the page's evidence is durable. It never regresses.

Secret containment (KMA-INV-6): the endpoint base URL and API token arrive only
through injected runtime configuration/token references; this module places
neither into fixtures, logs, events, notes, or error messages. Every failure is
reported as a ``reason_code``/``status`` pair -- provider bodies, URLs, headers,
and the token are never echoed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, NoReturn, Optional, Protocol
from urllib.parse import urlsplit

import httpx

from app.events.topic_schema_registry import TopicSchemaViolation
from app.events.types import HEIMDAL_OBSERVATION_PUBLISHED
from app.heimdal.observation_log import read_observations_from
from app.heimdal.publish import publish_full_observation
from app.heimdal.karakeep_service import assert_fetch_ready

logger = logging.getLogger(__name__)

# Adapter identity and fixed provenance chain (KMA-01 published-v1 field map).
ADAPTER_ID = "heimdal_karakeep_adapter"
ADAPTER_VERSION = "contract-v1"
SENSOR = "karakeep_rest"
CAPTURE_CHAIN: list[str] = ["karakeep", "karakeep_rest", "heimdal_karakeep_adapter"]
STAGE_VERSIONS: dict[str, str] = {"karakeep_adapter": ADAPTER_VERSION}

# Envelope source string for the reused outbox envelope (emission provenance).
_PUBLISH_SOURCE = "heimdal_karakeep_adapter"

# Canonical bookmarks feed path on a Karakeep host. The host itself is
# operator-owned and injected (never hardcoded); only the API path shape is
# fixed here.
_BOOKMARKS_PATH = "api/v1/bookmarks"
_HIGHLIGHTS_PATH = "api/v1/highlights"

_DEFAULT_PAGE_SIZE = 50
_DEFAULT_MAX_PAGES = 100
_DEFAULT_TIMEOUT_SECONDS = 30.0

# Content-family kinds this adapter recognizes on the Karakeep source snapshot.
_KIND_LINK = "link"
_KIND_NOTE = "note"
_KIND_HIGHLIGHT = "highlight"


class KarakeepConfigError(ValueError):
    """The injected Karakeep endpoint/config reference is structurally invalid."""


class KarakeepApiError(RuntimeError):
    """A safe, structured Karakeep REST failure.

    ``detail`` is built only from local classifications and the HTTP status.
    Provider bodies, URLs, headers, and the API token are never copied into it
    (KMA-INV-6).
    """

    def __init__(self, reason_code: str, status: int | None, detail: str) -> None:
        self.reason_code = reason_code
        self.status = status
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}")


class MalformedKarakeepItemError(ValueError):
    """One saved item could not be canonicalized; item-scoped, never page-fatal."""


def _raise_detached(error: BaseException) -> NoReturn:
    """Raise a normalized failure without retaining a prior exception graph.

    Keeps a provider transport error's ``__cause__``/``__context__`` (which may
    carry the endpoint URL) out of the surfaced :class:`KarakeepApiError`.
    """
    error.__cause__ = None
    error.__context__ = None
    raise error from None


class KarakeepTokenProvider(Protocol):
    """The credential port consumed by the adapter. Implementations resolve the
    operator-owned token from runtime configuration; the adapter never sees a
    literal token in its own source or fixtures."""

    def get_api_token(self) -> str: ...


@dataclass(frozen=True)
class StaticKarakeepToken:
    """A token provider backed by an already-resolved runtime reference.

    The value is supplied by the caller (e.g. from an environment reference the
    operator owns). It is never logged or placed in an error message.
    """

    token: str

    def get_api_token(self) -> str:
        if not self.token:
            raise KarakeepConfigError("Karakeep API token reference resolved to an empty value")
        return self.token


@dataclass(frozen=True)
class KarakeepConfig:
    """Runtime configuration for one Karakeep source.

    ``base_url`` is an operator-owned private endpoint reference supplied at
    runtime; committed fixtures use placeholders only. ``grant_ref`` points into
    the consent ledger (a reference, not a secret). ``source_id`` names the
    producer-cursor lane so multiple sources never share resume state.
    """

    base_url: str
    source_id: str = "karakeep-default"
    grant_ref: str = "grant:karakeep-source-ingestion"
    scope_hint: str = "operator_reading_inbox"
    page_size: int = _DEFAULT_PAGE_SIZE
    max_pages: int = _DEFAULT_MAX_PAGES

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise KarakeepConfigError(
                "Karakeep base_url must be an absolute http(s) URL with a host "
                "(the operator-owned endpoint is supplied at runtime)"
            )
        if not self.source_id.strip():
            raise KarakeepConfigError("Karakeep source_id must be non-empty")
        if not self.grant_ref.strip():
            raise KarakeepConfigError("Karakeep grant_ref must be a non-empty consent reference")
        if self.page_size <= 0:
            raise KarakeepConfigError("page_size must be positive")
        if self.max_pages <= 0:
            raise KarakeepConfigError("max_pages must be positive")


# ---------------------------------------------------------------------------
# Source snapshot + identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceSnapshot:
    """The canonical, evidence-bearing snapshot of one saved Karakeep item.

    Deterministic and free of credentials/endpoint/fetch-time/cursor values, so
    :meth:`content_identity` is stable across fetches of identical content.
    """

    item_id: str
    item_kind: str
    source_url: Optional[str]
    title: Optional[str]
    text: Optional[str]
    tags: tuple[str, ...]
    created_at: Optional[str]
    updated_at: Optional[str]
    archived: bool
    deleted: bool
    highlights: tuple[str, ...] = ()

    def canonical(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "item_kind": self.item_kind,
            "source_url": self.source_url,
            "title": self.title,
            "text": self.text,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "archived": self.archived,
            "deleted": self.deleted,
            "highlights": list(self.highlights),
        }

    def content_identity(self) -> str:
        canonical = json.dumps(self.canonical(), sort_keys=True, ensure_ascii=False)
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _publication_profile_identity() -> str:
    canonical = json.dumps(STAGE_VERSIONS, sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _hex(identity: str) -> str:
    return identity.split(":", 1)[1]


def episode_id_for(item_id: str) -> str:
    return f"karakeep:{item_id}"


def observation_id_for(item_id: str, content_identity: str, profile_identity: str) -> str:
    return f"{episode_id_for(item_id)}:{_hex(content_identity)}:{_hex(profile_identity)}"


# ---------------------------------------------------------------------------
# Producer cursor (Heimdal-owned source checkpoint)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ItemRevisionMark:
    """The last durable revision of one item, as known to the producer cursor."""

    observation_id: str
    content_identity: str
    profile_identity: str
    sequence: int


@dataclass
class ItemLineage:
    """Durable lineage of one item: its highest-sequence revision plus the full
    set of already-published ``observation_id`` values.

    The full set is what makes idempotency correct across a *revert*: because an
    ``observation_id`` is content+profile keyed and carries no sequence, re-fetching
    content that was published earlier (even if a later edit intervened) reproduces
    an already-durable ``observation_id`` and must be a no-op -- never a new row
    with a duplicate id (KMA-01 "one immutable publication").
    """

    latest: ItemRevisionMark
    observation_ids: set[str] = field(default_factory=set)


@dataclass
class SourceCheckpoint:
    """Per-source producer checkpoint: upstream resume position + per-item lineage."""

    upstream_cursor: Optional[str] = None
    items: dict[str, ItemLineage] = field(default_factory=dict)


class KarakeepProducerCursor:
    """Heimdal-owned producer checkpoint for Karakeep acquisition.

    Records the upstream page cursor plus the last durable revision per item and
    advances only after published evidence is durable (KMA-INV-3). The durable
    observation log is the authoritative lineage store; this cursor is a resume
    cache seeded from the log via :meth:`rebuild_from_log`, so a lost cursor is
    reconstructable and can never cause skipped or duplicated evidence. It is
    process-durable and injectable; the deployment/schedule slices wire a
    cross-process backing through the same injection point.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sources: dict[str, SourceCheckpoint] = {}

    def _checkpoint(self, source_id: str) -> SourceCheckpoint:
        return self._sources.setdefault(source_id, SourceCheckpoint())

    def upstream_cursor(self, source_id: str) -> Optional[str]:
        with self._lock:
            return self._checkpoint(source_id).upstream_cursor

    def item_lineage(self, source_id: str, item_id: str) -> Optional[ItemLineage]:
        with self._lock:
            return self._checkpoint(source_id).items.get(item_id)

    def item_ids(self, source_id: str) -> set[str]:
        with self._lock:
            return set(self._checkpoint(source_id).items)

    def record_revision(self, source_id: str, item_id: str, mark: ItemRevisionMark) -> None:
        """Record a newly durable revision. Monotone: never regresses the latest
        sequence, and accumulates the item's full published ``observation_id`` set."""
        with self._lock:
            checkpoint = self._checkpoint(source_id)
            lineage = checkpoint.items.get(item_id)
            if lineage is None:
                checkpoint.items[item_id] = ItemLineage(latest=mark, observation_ids={mark.observation_id})
                return
            lineage.observation_ids.add(mark.observation_id)
            if mark.sequence >= lineage.latest.sequence:
                lineage.latest = mark

    def advance_upstream(self, source_id: str, cursor: Optional[str]) -> None:
        """Advance the upstream page cursor after a page's evidence is durable."""
        with self._lock:
            self._checkpoint(source_id).upstream_cursor = cursor

    def rebuild_from_log(self, source_id: str) -> None:
        """Seed per-item lineage from the durable observation log (restart path).

        Reads the append-only log, keeps only this source's ``karakeep_rest``
        observations, and records each item's highest-sequence revision plus its
        full set of published ``observation_id`` values. Idempotent -- safe to call
        at the start of every run so a fresh process recovers full lineage before
        deciding any revision. Filtering on the stamped source id keeps multiple
        Karakeep source lanes from contaminating one another's resume state.
        """
        with self._lock:
            checkpoint = self._checkpoint(source_id)
            for row in read_observations_from(0):
                payload = row.envelope.get("payload")
                if not isinstance(payload, Mapping):
                    continue
                provenance = payload.get("provenance")
                if not isinstance(provenance, Mapping) or provenance.get("sensor") != SENSOR:
                    continue
                if provenance.get("karakeep_source_id") != source_id:
                    continue
                observation_id = payload.get("observation_id")
                episode_id = payload.get("episode_id")
                sequence = payload.get("sequence")
                content_identity = provenance.get("content_identity")
                if (
                    not isinstance(observation_id, str)
                    or not isinstance(episode_id, str)
                    or not isinstance(sequence, int)
                    or not isinstance(content_identity, str)
                ):
                    continue
                item_id = episode_id.split(":", 1)[1] if ":" in episode_id else episode_id
                profile_identity = "sha256:" + observation_id.rsplit(":", 1)[1]
                mark = ItemRevisionMark(
                    observation_id=observation_id,
                    content_identity=content_identity,
                    profile_identity=profile_identity,
                    sequence=sequence,
                )
                lineage = checkpoint.items.get(item_id)
                if lineage is None:
                    checkpoint.items[item_id] = ItemLineage(
                        latest=mark, observation_ids={observation_id}
                    )
                    continue
                lineage.observation_ids.add(observation_id)
                if mark.sequence >= lineage.latest.sequence:
                    lineage.latest = mark


_PRODUCER_CURSOR = KarakeepProducerCursor()


def reset_producer_cursor() -> None:
    """Test-only reset hook, mirroring the other Heimdal memory-store resets."""
    global _PRODUCER_CURSOR
    _PRODUCER_CURSOR = KarakeepProducerCursor()


def default_producer_cursor() -> KarakeepProducerCursor:
    return _PRODUCER_CURSOR


# ---------------------------------------------------------------------------
# Acquisition result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ItemError:
    """One item- or page-scoped failure. ``item_id`` is None for a page failure."""

    item_id: Optional[str]
    reason_code: str
    detail: str


@dataclass(frozen=True)
class AcquisitionResult:
    """Summary of one acquisition run. Carries no secret-bearing fields."""

    fetched: int
    published: tuple[str, ...]
    noops: int
    item_errors: tuple[ItemError, ...]
    pages_read: int
    stopped_early: bool
    upstream_cursor: Optional[str]


# ---------------------------------------------------------------------------
# The adapter
# ---------------------------------------------------------------------------


class KarakeepAdapter:
    """Read-only Karakeep acquisition into the Heimdal published-evidence handoff."""

    def __init__(
        self,
        *,
        config: KarakeepConfig,
        token_provider: KarakeepTokenProvider,
        http: httpx.Client | None = None,
        cursor: KarakeepProducerCursor | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        publish: Callable[..., Any] = publish_full_observation,
        fetch_ready: Callable[[], None] | None = None,
    ) -> None:
        self._config = config
        self._tokens = token_provider
        self._http = http or httpx.Client()
        self._cursor = cursor or default_producer_cursor()
        self._timeout = timeout_seconds
        self._publish = publish
        self._fetch_ready = fetch_ready or self._default_fetch_ready

    # -- public API ---------------------------------------------------------

    def acquire(self) -> AcquisitionResult:
        """Fetch bounded pages, publish contracted evidence, advance the cursor.

        Idempotent and crash-safe: rebuilds per-item lineage from the durable log
        first (restart recovery), publishes each new revision, and advances the
        producer cursor only after a page's evidence is durable. A page fetch
        failure stops the run before advancing past that page, so a retry replays
        it and dedups against the log rather than skipping evidence
        (KMA-INV-2/INV-3). One malformed item dead-letters only itself.
        """
        # Required production gate before any Karakeep API request.
        self._fetch_ready()
        source_id = self._config.source_id
        self._cursor.rebuild_from_log(source_id)

        published: list[str] = []
        item_errors: list[ItemError] = []
        fetched = 0
        pages_read = 0
        noops = 0
        stopped_early = False

        highlights = self._fetch_all_highlights()
        cursor_token = self._cursor.upstream_cursor(source_id)
        scan_started_at_first_page = cursor_token is None
        seen_item_ids: set[str] = set()
        completed_scan = False
        for _ in range(self._config.max_pages):
            try:
                page = self._fetch_page(cursor_token)
            except KarakeepApiError as exc:
                # Page-scoped failure: legible, secret-safe, and NON-advancing.
                # The producer cursor stays at this page so a retry replays it.
                logger.warning(
                    "Karakeep acquisition[%s]: page fetch stopped (reason=%s status=%s)",
                    source_id,
                    exc.reason_code,
                    exc.status,
                )
                item_errors.append(ItemError(None, exc.reason_code, exc.detail))
                stopped_early = True
                break

            pages_read += 1
            page_items = [
                {
                    **raw,
                    "highlights": highlights.get(raw_id, ()) if isinstance(raw_id := raw.get("id"), str) else (),
                }
                for raw in page.items
            ]
            seen_item_ids.update(raw["id"] for raw in page.items if isinstance(raw.get("id"), str))
            page_published, page_noops, page_errors = self._process_items(page_items)
            fetched += len(page.items)
            published.extend(page_published)
            noops += page_noops
            item_errors.extend(page_errors)

            # The page's evidence is durable (each publish returned before we get
            # here); only now advance the upstream cursor past it (KMA-INV-3).
            cursor_token = page.next_cursor
            self._cursor.advance_upstream(source_id, cursor_token)
            if page.next_cursor is None:
                completed_scan = True
                break

        # Karakeep deletes bookmarks outright. Only a complete snapshot can
        # safely turn an absent previously-published item into a tombstone.
        if completed_scan and scan_started_at_first_page:
            for item_id in self._cursor.item_ids(source_id) - seen_item_ids:
                outcome = self._publish_snapshot(_disappeared_snapshot(item_id))
                if outcome is None:
                    noops += 1
                else:
                    published.append(outcome)

        return AcquisitionResult(
            fetched=fetched,
            published=tuple(published),
            noops=noops,
            item_errors=tuple(item_errors),
            pages_read=pages_read,
            stopped_early=stopped_early,
            upstream_cursor=self._cursor.upstream_cursor(source_id),
        )

    # -- item processing ----------------------------------------------------

    def _process_items(
        self, items: Sequence[Mapping[str, Any]]
    ) -> tuple[list[str], int, list[ItemError]]:
        published: list[str] = []
        item_errors: list[ItemError] = []
        noops = 0
        source_id = self._config.source_id
        for raw in items:
            item_id = raw.get("id") if isinstance(raw, Mapping) else None
            try:
                snapshot = _canonicalize_item(raw)
            except MalformedKarakeepItemError as exc:
                logger.warning(
                    "Karakeep acquisition[%s]: dead-lettered malformed item (id=%s): %s",
                    source_id,
                    item_id,
                    exc,
                )
                item_errors.append(
                    ItemError(item_id if isinstance(item_id, str) else None, "malformed_item", str(exc))
                )
                continue

            try:
                outcome = self._publish_snapshot(snapshot)
            except TopicSchemaViolation as exc:
                # Item-scoped: a single item that cannot assemble valid evidence
                # dead-letters only itself and never advances a cursor
                # (KMA-INV-5). A transient durable-write failure is NOT caught
                # here -- it propagates so the run stops before the cursor
                # advances and a retry replays it (KMA-INV-3). The detail carries
                # no source content -- only the validator's structural reason.
                logger.warning(
                    "Karakeep acquisition[%s]: dead-lettered item with invalid evidence (id=%s): %s",
                    source_id,
                    snapshot.item_id,
                    exc,
                )
                item_errors.append(ItemError(snapshot.item_id, "invalid_evidence", str(exc)))
                continue

            if outcome is None:
                noops += 1
            else:
                published.append(outcome)
        return published, noops, item_errors

    def _publish_snapshot(self, snapshot: SourceSnapshot) -> Optional[str]:
        """Publish one snapshot as contracted evidence; return its observation_id.

        Returns ``None`` for a traced no-op (identical content at the same
        publication profile as the latest durable revision of this item).
        """
        source_id = self._config.source_id
        content_identity = snapshot.content_identity()
        profile_identity = _publication_profile_identity()
        observation_id = observation_id_for(snapshot.item_id, content_identity, profile_identity)

        lineage = self._cursor.item_lineage(source_id, snapshot.item_id)
        if lineage is not None and observation_id in lineage.observation_ids:
            # This exact immutable publication is already durable -- a re-fetch of
            # identical content at the same profile, even after an intervening
            # edit was reverted. Traced no-op; never a new row with a duplicate
            # observation_id (KMA-01 idempotency).
            logger.info(
                "Karakeep acquisition[%s]: no-op re-fetch of %s (observation already durable)",
                source_id,
                observation_id,
            )
            return None

        if lineage is None:
            sequence = 0
            revision_of: Optional[str] = None
            supersedes: Optional[str] = None
        elif lineage.latest.content_identity != content_identity:
            # Source update (or tombstone): new content supersedes the prior.
            sequence = lineage.latest.sequence + 1
            revision_of = None
            supersedes = lineage.latest.observation_id
        else:
            # Same snapshot content, changed publication profile: a reprocess
            # revision (same content_identity as latest but a new observation_id).
            sequence = lineage.latest.sequence + 1
            revision_of = lineage.latest.observation_id
            supersedes = None

        payload = _assemble_payload(
            snapshot,
            observation_id=observation_id,
            content_identity=content_identity,
            source_id=source_id,
            sequence=sequence,
            revision_of=revision_of,
            supersedes=supersedes,
            grant_ref=self._config.grant_ref,
            scope_hint=self._config.scope_hint,
        )
        row = self._publish(
            topic=HEIMDAL_OBSERVATION_PUBLISHED,
            payload=payload,
            source=_PUBLISH_SOURCE,
            stage_versions=STAGE_VERSIONS,
        )
        # The publish seam dedups an identical revision to None; either way the
        # revision is now durable, so record it before the cursor advances.
        self._cursor.record_revision(
            source_id,
            snapshot.item_id,
            ItemRevisionMark(
                observation_id=observation_id,
                content_identity=content_identity,
                profile_identity=profile_identity,
                sequence=sequence,
            ),
        )
        if row is None:
            logger.info(
                "Karakeep acquisition[%s]: publish deduped %s to the existing durable row",
                source_id,
                observation_id,
            )
            return None
        return observation_id

    # -- HTTP ---------------------------------------------------------------

    def _default_fetch_ready(self) -> None:
        assert_fetch_ready(
            env={
                "KARAKEEP_BASE_URL": self._config.base_url,
                "KARAKEEP_API_TOKEN": self._tokens.get_api_token(),
            },
            http=self._http,
        )

    def _fetch_all_highlights(self) -> dict[str, tuple[str, ...]]:
        """Fetch paginated highlights and group their text by bookmark id."""
        grouped: dict[str, list[str]] = {}
        cursor_token: Optional[str] = None
        for _ in range(self._config.max_pages):
            params: dict[str, str] = {"limit": str(self._config.page_size)}
            if cursor_token:
                params["cursor"] = cursor_token
            body = self._request_json(_HIGHLIGHTS_PATH, params)
            entries = body.get("highlights")
            if not isinstance(entries, list) or not all(isinstance(entry, Mapping) for entry in entries):
                _raise_detached(KarakeepApiError("api_unavailable", None, "Karakeep highlights had an invalid items shape"))
            for entry in entries:
                bookmark_id = entry.get("bookmarkId") or entry.get("bookmark_id")
                text = entry.get("content") or entry.get("text") or entry.get("highlight")
                if isinstance(bookmark_id, str) and isinstance(text, str) and text:
                    grouped.setdefault(bookmark_id, []).append(text)
            cursor_token = body.get("nextCursor")
            if cursor_token is None:
                return {key: tuple(values) for key, values in grouped.items()}
            if not isinstance(cursor_token, str) or not cursor_token:
                _raise_detached(KarakeepApiError("api_unavailable", None, "Karakeep highlights cursor was invalid"))
        _raise_detached(KarakeepApiError("api_unavailable", None, "Karakeep highlights exceeded page limit"))

    def _fetch_page(self, cursor_token: Optional[str]) -> "_Page":
        params: dict[str, str] = {"limit": str(self._config.page_size)}
        if cursor_token:
            params["cursor"] = cursor_token
        body = self._request_json(_BOOKMARKS_PATH, params)
        items = body.get("bookmarks")
        if not isinstance(items, list) or not all(isinstance(item, Mapping) for item in items):
            _raise_detached(KarakeepApiError("api_unavailable", None, "Karakeep page had an invalid items shape"))
        next_cursor = body.get("nextCursor")
        if next_cursor is not None and (not isinstance(next_cursor, str) or not next_cursor):
            _raise_detached(KarakeepApiError("api_unavailable", None, "Karakeep page cursor was invalid"))
        return _Page(items=list(items), next_cursor=next_cursor)

    def _request_json(self, path: str, params: Mapping[str, str]) -> Mapping[str, Any]:
        url = self._config.base_url.rstrip("/") + "/" + path
        token = self._tokens.get_api_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

        try:
            response = self._http.get(
                url, params=params, headers=headers, timeout=self._timeout
            )
        except httpx.TimeoutException:
            _raise_detached(KarakeepApiError("api_unavailable", None, "Karakeep request timed out"))
        except httpx.TransportError:
            _raise_detached(KarakeepApiError("network_error", None, "Karakeep transport failed"))

        status = response.status_code
        if status >= 400:
            _raise_detached(_mapped_http_error(status))

        try:
            body = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            _raise_detached(
                KarakeepApiError("api_unavailable", status, "Karakeep returned invalid JSON")
            )
        if not isinstance(body, Mapping):
            _raise_detached(
                KarakeepApiError("api_unavailable", status, "Karakeep returned an invalid page shape")
            )
        return body


@dataclass(frozen=True)
class _Page:
    items: list[Mapping[str, Any]]
    next_cursor: Optional[str]


def _mapped_http_error(status: int) -> KarakeepApiError:
    """Map an HTTP status to a secret-free reason code (never echoes the body)."""
    if status in (401, 403):
        reason_code = "auth_failed"
    elif status == 429:
        reason_code = "rate_limited"
    elif status >= 500:
        reason_code = "api_unavailable"
    else:
        reason_code = "api_unavailable"
    return KarakeepApiError(reason_code, status, f"Karakeep request failed with HTTP {status}")


# ---------------------------------------------------------------------------
# Canonicalization + payload assembly
# ---------------------------------------------------------------------------


def _optional_str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _canonicalize_item(raw: Mapping[str, Any]) -> SourceSnapshot:
    """Canonicalize one Karakeep bookmark into a :class:`SourceSnapshot`.

    Raises :class:`MalformedKarakeepItemError` (item-scoped) when identity-bearing
    fields are missing or unrecognized -- the caller dead-letters only that item.
    """
    item_id = raw.get("id")
    if not isinstance(item_id, str) or not item_id:
        raise MalformedKarakeepItemError("saved item is missing a string id")

    created_at = _optional_str(raw.get("createdAt"))
    updated_at = _optional_str(raw.get("modifiedAt")) or _optional_str(raw.get("updatedAt"))
    if created_at is None and updated_at is None:
        raise MalformedKarakeepItemError(f"item {item_id} has no upstream timestamp")

    deleted = bool(raw.get("deleted", False))
    archived = bool(raw.get("archived", False))
    tags = _canonical_tags(raw.get("tags"))
    highlights = _canonical_highlights(raw.get("highlights"))

    content = raw.get("content")
    content_type = content.get("type") if isinstance(content, Mapping) else None
    note = _optional_str(raw.get("note"))
    title = _optional_str(raw.get("title"))
    source_url: Optional[str] = None
    text: Optional[str] = None
    kind: str

    if deleted:
        # A tombstone carries no live content; identity still derives from the id.
        kind = content_type if isinstance(content_type, str) and content_type else _KIND_LINK
        kind = _map_kind(kind)
    elif content_type == "link" or (isinstance(content, Mapping) and content.get("url")):
        kind = _KIND_LINK
        if isinstance(content, Mapping):
            source_url = _optional_str(content.get("url"))
            title = title or _optional_str(content.get("title"))
        text = _combine_evidence(note, highlights)
    elif content_type in ("text", "note"):
        kind = _KIND_NOTE
        text = _optional_str(content.get("text")) if isinstance(content, Mapping) else None
        text = text or note
    elif content_type == "highlight":
        kind = _KIND_HIGHLIGHT
        text = _optional_str(content.get("text")) if isinstance(content, Mapping) else None
        text = text or note
    elif note is not None:
        kind = _KIND_NOTE
        text = note
    else:
        raise MalformedKarakeepItemError(f"item {item_id} has an unrecognized content shape")

    if deleted:
        text = None
        source_url = None
        title = None

    return SourceSnapshot(
        item_id=item_id,
        item_kind=kind,
        source_url=source_url,
        title=title,
        text=text,
        tags=tags,
        created_at=created_at,
        updated_at=updated_at,
        archived=archived,
        deleted=deleted,
        highlights=highlights,
    )


def _map_kind(value: str) -> str:
    if value in ("text", "note"):
        return _KIND_NOTE
    if value == "highlight":
        return _KIND_HIGHLIGHT
    return _KIND_LINK


def _canonical_tags(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    names: set[str] = set()
    for entry in value:
        if isinstance(entry, str) and entry:
            names.add(entry)
        elif isinstance(entry, Mapping):
            name = entry.get("name")
            if isinstance(name, str) and name:
                names.add(name)
    return tuple(sorted(names))


def _canonical_highlights(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(text for text in value if isinstance(text, str) and text)


def _combine_evidence(note: Optional[str], highlights: tuple[str, ...]) -> Optional[str]:
    parts = ([note] if note else []) + list(highlights)
    return "\n\n".join(parts) if parts else None


def _disappeared_snapshot(item_id: str) -> SourceSnapshot:
    """Stable tombstone for a bookmark absent from a complete source scan."""
    return SourceSnapshot(
        item_id=item_id,
        item_kind=_KIND_LINK,
        source_url=None,
        title=None,
        text=None,
        tags=(),
        created_at=None,
        updated_at="1970-01-01T00:00:00+00:00",
        archived=False,
        deleted=True,
    )


def _assemble_payload(
    snapshot: SourceSnapshot,
    *,
    observation_id: str,
    content_identity: str,
    source_id: str,
    sequence: int,
    revision_of: Optional[str],
    supersedes: Optional[str],
    grant_ref: str,
    scope_hint: str,
) -> dict[str, Any]:
    """Build the ``heimdal.observation.published.v1`` payload for one snapshot.

    Imported lazily so this module's import graph carries no dependency that a
    static check for the Mimer boundary could confuse -- assembly is a pure
    Heimdal publish concern.
    """
    from app.heimdal.publish import assemble_observation_payload

    episode_id = episode_id_for(snapshot.item_id)
    timestamped = snapshot.created_at is not None
    observed_at_start = snapshot.created_at or snapshot.updated_at
    assert observed_at_start is not None  # guaranteed by _canonicalize_item

    attributions = [
        {
            "mention_id": "operator-recorder",
            "role": "recorder",
            "resolution": "resolved",
            "confidence": 1.0,
            "basis": "capture_context",
        }
    ]
    entity_mentions = [
        {
            "mention_id": f"karakeep-tag:{tag}",
            "surface_form": tag,
            "kind_hint": "tag",
            "resolution": "unresolved",
            "confidence": None,
        }
        for tag in snapshot.tags
    ]
    confidence = {
        "source_integrity": {
            "score": 1.0,
            "method": "karakeep_api_snapshot",
            "calibration": "by_construction",
        },
        "attribution": {
            "score": 1.0,
            "method": "operator_source_grant",
            "calibration": "by_construction",
        },
        "temporal": {
            "score": 1.0 if timestamped else 0.5,
            "method": "karakeep_created_at" if timestamped else "karakeep_inferred_timestamp",
            "calibration": "by_construction" if timestamped else "heuristic",
        },
    }
    content_structure: dict[str, Any] = {
        "karakeep": {
            "item_kind": snapshot.item_kind,
            "source_item_identity": episode_id,
            "tombstone": snapshot.deleted,
        }
    }
    if snapshot.source_url is not None:
        content_structure["karakeep"]["source_url"] = snapshot.source_url
    if snapshot.tags:
        content_structure["karakeep"]["tags"] = list(snapshot.tags)
    if snapshot.highlights:
        content_structure["karakeep"]["highlights"] = list(snapshot.highlights)

    raw_ref = f"raw:karakeep:{snapshot.item_id}:{_hex(content_identity)[:8]}"
    provenance = {
        "sensor": SENSOR,
        "capture_chain": list(CAPTURE_CHAIN),
        "content_identity": content_identity,
        "stage_versions": dict(STAGE_VERSIONS),
        "raw_ref": raw_ref,
        # Producer-lane id (not a secret, not part of content identity): keeps
        # multiple Karakeep source lanes from sharing resume state on rebuild.
        "karakeep_source_id": source_id,
    }
    consent = {
        "basis": "self_record",
        "granted_by": "operator",
        "third_party": "marked",
        "grant_ref": grant_ref,
    }

    return assemble_observation_payload(
        observation_id=observation_id,
        episode_id=episode_id,
        observed_at_start=observed_at_start,
        clock_basis="device_metadata" if timestamped else "inferred",
        attributions=attributions,
        entity_mentions=entity_mentions,
        confidence=confidence,
        provenance=provenance,
        consent=consent,
        sensitivity="private",
        scope_hint=scope_hint,
        sequence=sequence,
        revision_of=revision_of,
        supersedes=supersedes,
        modality=None,
        content=snapshot.text,
        content_structure=content_structure,
        raw_ref=raw_ref,
    )


__all__ = [
    "ADAPTER_ID",
    "ADAPTER_VERSION",
    "AcquisitionResult",
    "CAPTURE_CHAIN",
    "ItemError",
    "ItemLineage",
    "ItemRevisionMark",
    "KarakeepAdapter",
    "KarakeepApiError",
    "KarakeepConfig",
    "KarakeepConfigError",
    "KarakeepProducerCursor",
    "KarakeepTokenProvider",
    "MalformedKarakeepItemError",
    "SENSOR",
    "SourceSnapshot",
    "StaticKarakeepToken",
    "default_producer_cursor",
    "episode_id_for",
    "observation_id_for",
    "reset_producer_cursor",
]
