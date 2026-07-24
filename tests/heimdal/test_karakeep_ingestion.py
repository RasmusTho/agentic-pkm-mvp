"""Contract tests for the Heimdal Karakeep reading-evidence adapter (KMA-03, #3374).

All egress runs through ``httpx.MockTransport`` -- no network. The tests exercise
the real publish seam (``app.heimdal.publish.publish_full_observation`` onto the
in-memory observation log) so the published evidence is validated against the
canonical ``heimdal.observation.published.v1`` schema by construction.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Iterable

import httpx
import pytest

from app.events.topic_schema_registry import validate_topic_payload
from app.events.types import HEIMDAL_OBSERVATION_PUBLISHED
from app.heimdal import karakeep_ingest
from app.heimdal.karakeep_ingest import (
    KarakeepAdapter,
    KarakeepConfig,
    KarakeepProducerCursor,
    StaticKarakeepToken,
)
from app.heimdal.observation_log import (
    read_observations_from,
    reset_memory_observation_log,
)

pytestmark = pytest.mark.not_pg

# Placeholders only -- a private endpoint/token never appears in a committed
# fixture (KMA-INV-6). These sentinels double as redaction canaries in test 4.
_BASE_URL = "https://karakeep.private.example"
_SECRET_TOKEN = "kk-secret-token-DO-NOT-LEAK"


@pytest.fixture(autouse=True)
def _reset_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_memory_observation_log()
    karakeep_ingest.reset_producer_cursor()


# ---------------------------------------------------------------------------
# Fake Karakeep REST server
# ---------------------------------------------------------------------------


class _FakeKarakeep:
    """A cursor-paginated Karakeep bookmarks endpoint over ``httpx.MockTransport``."""

    def __init__(self, pages: list[list[dict[str, Any]]]) -> None:
        self._pages = pages
        self.highlights: list[dict[str, Any]] = []
        self.fail_pages: dict[int, int] = {}  # page index -> HTTP status
        self.requests: list[httpx.Request] = []

    def _index(self, request: httpx.Request) -> int:
        cursor = request.url.params.get("cursor")
        return 0 if cursor is None else int(cursor.split(":", 1)[1])

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/":
            return httpx.Response(200, request=request, text="ok")
        if request.url.path.endswith("/api/v1/highlights"):
            return httpx.Response(200, request=request, json={"highlights": self.highlights, "nextCursor": None})
        idx = self._index(request)
        if idx in self.fail_pages:
            # A provider error body that embeds secret-looking material; the
            # adapter must never echo any of it into its surfaced error.
            return httpx.Response(
                self.fail_pages[idx],
                request=request,
                json={"error": "denied", "echo": _SECRET_TOKEN, "endpoint": _BASE_URL},
            )
        items = self._pages[idx] if idx < len(self._pages) else []
        next_cursor = f"page:{idx + 1}" if idx + 1 < len(self._pages) else None
        return httpx.Response(200, request=request, json={"bookmarks": items, "nextCursor": next_cursor})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def _adapter(fake: _FakeKarakeep, *, cursor: KarakeepProducerCursor | None = None) -> KarakeepAdapter:
    return KarakeepAdapter(
        config=KarakeepConfig(base_url=_BASE_URL, source_id="karakeep-test"),
        token_provider=StaticKarakeepToken(_SECRET_TOKEN),
        http=fake.client(),
        cursor=cursor,
    )


def _link(item_id: str, url: str, *, note: str | None = None, tags: Iterable[str] = (), created: str = "2026-07-10T08:15:00+02:00") -> dict[str, Any]:
    return {
        "id": item_id,
        "createdAt": created,
        "modifiedAt": created,
        "archived": False,
        "note": note,
        "tags": [{"name": t} for t in tags],
        "content": {"type": "link", "url": url, "title": f"title-{item_id}"},
    }


def _note(item_id: str, text: str, *, created: str = "2026-07-10T09:00:00+02:00") -> dict[str, Any]:
    return {
        "id": item_id,
        "createdAt": created,
        "modifiedAt": created,
        "archived": False,
        "tags": [],
        "content": {"type": "text", "text": text},
    }


def _highlight(item_id: str, text: str, *, created: str = "2026-07-10T10:00:00+02:00") -> dict[str, Any]:
    return {
        "id": item_id,
        "createdAt": created,
        "modifiedAt": created,
        "archived": False,
        "tags": [],
        "content": {"type": "highlight", "text": text},
    }


def _payloads() -> list[dict[str, Any]]:
    rows = read_observations_from(0)
    return [r.envelope["payload"] for r in rows]


def _by_episode(payloads: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for p in payloads:
        out.setdefault(p["episode_id"], []).append(p)
    return out


def test_fetches_bookmark_highlights_from_highlights_api() -> None:
    fake = _FakeKarakeep([[_link("item-highlighted", "https://example.com/a", note="saved note")]])
    fake.highlights = [{"bookmarkId": "item-highlighted", "content": "important passage"}]

    result = _adapter(fake).acquire()

    assert len(result.published) == 1
    payload = _by_episode(_payloads())["karakeep:item-highlighted"][0]
    assert payload["content"] == "saved note\n\nimportant passage"
    assert payload["content_structure"]["karakeep"]["highlights"] == ["important passage"]
    assert any(request.url.path.endswith("/api/v1/highlights") for request in fake.requests)


def test_disappeared_bookmark_publishes_tombstone_revision() -> None:
    cursor = KarakeepProducerCursor()
    first = _adapter(_FakeKarakeep([[_link("item-gone", "https://example.com/a")]]), cursor=cursor).acquire()
    second = _adapter(_FakeKarakeep([[]]), cursor=cursor).acquire()

    assert len(first.published) == 1
    assert len(second.published) == 1
    payloads = _by_episode(_payloads())["karakeep:item-gone"]
    assert payloads[-1]["content"] is None
    assert payloads[-1]["content_structure"]["karakeep"]["tombstone"] is True
    assert payloads[-1]["supersedes"] == first.published[0]


def test_adapter_calls_fetch_readiness_gate_before_source_egress() -> None:
    fake = _FakeKarakeep([[_link("item-1", "https://example.com/a")]])
    calls: list[str] = []

    def ready() -> None:
        calls.append("ready")
        assert fake.requests == []

    adapter = KarakeepAdapter(
        config=KarakeepConfig(base_url=_BASE_URL, source_id="karakeep-test"),
        token_provider=StaticKarakeepToken(_SECRET_TOKEN),
        http=fake.client(),
        fetch_ready=ready,
    )
    adapter.acquire()
    assert calls == ["ready"]


# ---------------------------------------------------------------------------
# AC 1
# ---------------------------------------------------------------------------


def test_incremental_fetch_attributes_and_publishes_reading_evidence() -> None:
    fake = _FakeKarakeep(
        [
            [_link("item-1", "https://example.com/a", note="a saved note", tags=["reading", "ai"]), _note("item-2", "a standalone note")],
            [_highlight("item-3", "a highlighted passage")],
        ]
    )
    result = _adapter(fake).acquire()

    assert result.fetched == 3
    assert len(result.published) == 3
    assert result.noops == 0
    assert result.item_errors == ()
    assert result.pages_read == 2
    assert not result.stopped_early

    payloads = _payloads()
    assert len(payloads) == 3
    for payload in payloads:
        # Published evidence validates against the canonical schema.
        validate_topic_payload(HEIMDAL_OBSERVATION_PUBLISHED, payload)
        assert payload["episode_id"].startswith("karakeep:")
        assert payload["observation_id"].startswith(payload["episode_id"] + ":")
        prov = payload["provenance"]
        assert prov["sensor"] == "karakeep_rest"
        assert prov["capture_chain"] == ["karakeep", "karakeep_rest", "heimdal_karakeep_adapter"]
        assert prov["content_identity"].startswith("sha256:")
        assert prov["content_hash"].startswith("sha256:")
        assert set(payload["confidence"]) == {"source_integrity", "attribution", "temporal"}
        assert payload["attributions"][0]["mention_id"] == "operator-recorder"
        assert payload["attributions"][0]["role"] == "recorder"
        assert payload["consent"]["grant_ref"] == "grant:karakeep-source-ingestion"
        assert payload["sequence"] == 0  # first revision of each distinct item

    by_ep = _by_episode(payloads)
    link_payload = by_ep["karakeep:item-1"][0]
    assert link_payload["content_structure"]["karakeep"]["item_kind"] == "link"
    assert link_payload["content_structure"]["karakeep"]["source_url"] == "https://example.com/a"
    assert link_payload["clock_basis"] == "device_metadata"
    assert link_payload["observed_at_start"] == "2026-07-10T08:15:00+02:00"
    # Entity mentions are derived from source tags only when present.
    mention_surfaces = {m["surface_form"] for m in link_payload["entity_mentions"]}
    assert mention_surfaces == {"reading", "ai"}
    assert all(m["resolution"] == "unresolved" for m in link_payload["entity_mentions"])
    assert by_ep["karakeep:item-2"][0]["content"] == "a standalone note"
    assert by_ep["karakeep:item-2"][0]["entity_mentions"] == []
    assert by_ep["karakeep:item-3"][0]["content_structure"]["karakeep"]["item_kind"] == "highlight"

    # Restart-safe / incremental: a second run over identical source is all no-ops
    # and appends no new evidence (the producer cursor + log dedup).
    second = _adapter(fake, cursor=karakeep_ingest.default_producer_cursor()).acquire()
    assert second.noops == 3
    assert second.published == ()
    assert len(_payloads()) == 3


# ---------------------------------------------------------------------------
# AC 2
# ---------------------------------------------------------------------------


def test_duplicate_is_noop_and_changed_revision_preserves_lineage() -> None:
    shared = KarakeepProducerCursor()

    fake_v1 = _FakeKarakeep([[_link("item-9", "https://example.com/x", note="first note")]])
    first = KarakeepAdapter(
        config=KarakeepConfig(base_url=_BASE_URL, source_id="karakeep-test"),
        token_provider=StaticKarakeepToken(_SECRET_TOKEN),
        http=fake_v1.client(),
        cursor=shared,
    ).acquire()
    assert len(first.published) == 1
    prior_observation_id = first.published[0]

    # Duplicate revision -> traced no-op, no new row.
    dup = KarakeepAdapter(
        config=KarakeepConfig(base_url=_BASE_URL, source_id="karakeep-test"),
        token_provider=StaticKarakeepToken(_SECRET_TOKEN),
        http=fake_v1.client(),
        cursor=shared,
    ).acquire()
    assert dup.noops == 1
    assert dup.published == ()
    assert len(_payloads()) == 1

    # Changed content -> new revision lineage, prior evidence untouched.
    fake_v2 = _FakeKarakeep([[_link("item-9", "https://example.com/x", note="edited note")]])
    changed = KarakeepAdapter(
        config=KarakeepConfig(base_url=_BASE_URL, source_id="karakeep-test"),
        token_provider=StaticKarakeepToken(_SECRET_TOKEN),
        http=fake_v2.client(),
        cursor=shared,
    ).acquire()
    assert len(changed.published) == 1

    payloads = _by_episode(_payloads())["karakeep:item-9"]
    assert len(payloads) == 2
    prior = next(p for p in payloads if p["observation_id"] == prior_observation_id)
    newer = next(p for p in payloads if p["observation_id"] != prior_observation_id)
    assert prior["sequence"] == 0
    assert prior["supersedes"] is None
    assert newer["sequence"] == 1
    assert newer["supersedes"] == prior_observation_id
    assert newer["revision_of"] is None
    # The prior published content is preserved (not overwritten).
    assert prior["content"] == "first note"
    assert newer["content"] == "edited note"


# ---------------------------------------------------------------------------
# AC 3
# ---------------------------------------------------------------------------


def test_page_failure_replays_before_producer_cursor_advance() -> None:
    pages = [
        [_link("item-a", "https://example.com/a"), _link("item-b", "https://example.com/b")],
        [_link("item-c", "https://example.com/c")],
    ]

    # First run: page 0 publishes, page 1 fails -> stop before advancing past it.
    fake = _FakeKarakeep([list(p) for p in pages])
    fake.fail_pages = {1: 503}
    cursor = KarakeepProducerCursor()
    partial = _adapter(fake, cursor=cursor).acquire()

    assert len(partial.published) == 2
    assert partial.stopped_early
    assert [e.reason_code for e in partial.item_errors] == ["api_unavailable"]
    # Producer cursor points AT the failed page, never beyond it.
    assert partial.upstream_cursor == "page:1"
    episodes = _by_episode(_payloads())
    assert set(episodes) == {"karakeep:item-a", "karakeep:item-b"}  # page 1 not durable

    # Simulate a crash that lost the producer cursor: a fresh cursor re-fetches
    # from page 0. Page 0 items dedup against the durable log (no duplicates);
    # page 1 now succeeds and is published. Evidence is neither skipped nor
    # duplicated and per-item sequence never regresses.
    healthy = _FakeKarakeep([list(p) for p in pages])
    replay = _adapter(healthy, cursor=KarakeepProducerCursor()).acquire()

    assert replay.noops == 2  # page 0 items replayed as no-ops
    assert len(replay.published) == 1  # page 1 item-c now published
    assert not replay.stopped_early

    payloads = _payloads()
    assert len(payloads) == 3  # exactly a,b,c -- no duplicate a/b rows
    observation_ids = [p["observation_id"] for p in payloads]
    assert len(observation_ids) == len(set(observation_ids))
    assert set(_by_episode(payloads)) == {"karakeep:item-a", "karakeep:item-b", "karakeep:item-c"}
    assert all(p["sequence"] == 0 for p in payloads)


# ---------------------------------------------------------------------------
# AC 4
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "reason_code"),
    [(401, "auth_failed"), (403, "auth_failed"), (429, "rate_limited"), (503, "api_unavailable")],
)
def test_failures_are_bounded_and_credentials_are_redacted(
    status: int, reason_code: str, caplog: pytest.LogCaptureFixture
) -> None:
    fake = _FakeKarakeep([[_link("item-1", "https://example.com/a")]])
    fake.fail_pages = {0: status}
    with caplog.at_level("DEBUG"):
        result = _adapter(fake).acquire()

    assert result.published == ()
    assert result.stopped_early
    assert [e.reason_code for e in result.item_errors] == [reason_code]

    # No secret token or private endpoint anywhere the failure is surfaced.
    detail = result.item_errors[0].detail
    assert _SECRET_TOKEN not in detail
    assert _BASE_URL not in detail
    assert str(status) in detail
    # The API token is a true secret: it must not appear in ANY log record
    # (it never reaches the URL httpx logs -- it rides the Authorization header).
    all_log_text = "\n".join(rec.getMessage() for rec in caplog.records)
    assert _SECRET_TOKEN not in all_log_text
    # The adapter's OWN log lines must not echo the private endpoint (KMA-INV-6);
    # httpx's generic request logging is outside the adapter's surface.
    adapter_log_text = "\n".join(
        rec.getMessage() for rec in caplog.records if rec.name == "app.heimdal.karakeep_ingest"
    )
    assert adapter_log_text  # the adapter did log the bounded failure
    assert _BASE_URL not in adapter_log_text


def test_malformed_item_is_dead_lettered_and_isolated() -> None:
    good = _link("item-good", "https://example.com/good")
    missing_id = {"createdAt": "2026-07-10T08:15:00+02:00", "content": {"type": "link", "url": "https://x"}}
    no_timestamp = {"id": "item-bad-time", "content": {"type": "text", "text": "hi"}}
    fake = _FakeKarakeep([[good, missing_id, no_timestamp]])

    result = _adapter(fake).acquire()

    assert len(result.published) == 1  # only the good item
    reasons = sorted(e.reason_code for e in result.item_errors)
    assert reasons == ["malformed_item", "malformed_item"]
    assert not result.stopped_early  # one bad item never aborts the page
    episodes = set(_by_episode(_payloads()))
    assert episodes == {"karakeep:item-good"}


# ---------------------------------------------------------------------------
# Identity integrity, lineage completeness, and per-item isolation
# (contract cases surfaced by independent review of AC 1-4)
# ---------------------------------------------------------------------------


def test_content_revert_is_noop_not_duplicate_observation_id() -> None:
    """A -> B -> A: reverting to earlier content reproduces an already-durable
    observation_id and must be a no-op, never a duplicate-id row (KMA-01)."""
    shared = KarakeepProducerCursor()

    def _run(note: str) -> Any:
        fake = _FakeKarakeep([[_link("item-r", "https://example.com/r", note=note)]])
        return KarakeepAdapter(
            config=KarakeepConfig(base_url=_BASE_URL, source_id="karakeep-test"),
            token_provider=StaticKarakeepToken(_SECRET_TOKEN),
            http=fake.client(),
            cursor=shared,
        ).acquire()

    first = _run("content-A")
    assert len(first.published) == 1
    _run("content-B")  # edit
    revert = _run("content-A")  # revert to the original content

    assert revert.published == ()
    assert revert.noops == 1
    payloads = _by_episode(_payloads())["karakeep:item-r"]
    assert len(payloads) == 2  # exactly A(seq0) and B(seq1) -- no third row
    observation_ids = [p["observation_id"] for p in payloads]
    assert len(observation_ids) == len(set(observation_ids))  # no duplicate ids
    assert first.published[0] in observation_ids


def test_tombstone_supersedes_prior_without_deleting_it() -> None:
    shared = KarakeepProducerCursor()
    live = _FakeKarakeep([[_link("item-t", "https://example.com/t", note="live note")]])
    first = KarakeepAdapter(
        config=KarakeepConfig(base_url=_BASE_URL, source_id="karakeep-test"),
        token_provider=StaticKarakeepToken(_SECRET_TOKEN),
        http=live.client(),
        cursor=shared,
    ).acquire()
    prior_id = first.published[0]

    deleted_item = _link("item-t", "https://example.com/t", note="live note")
    deleted_item["deleted"] = True
    tomb = _FakeKarakeep([[deleted_item]])
    result = KarakeepAdapter(
        config=KarakeepConfig(base_url=_BASE_URL, source_id="karakeep-test"),
        token_provider=StaticKarakeepToken(_SECRET_TOKEN),
        http=tomb.client(),
        cursor=shared,
    ).acquire()

    assert len(result.published) == 1
    payloads = _by_episode(_payloads())["karakeep:item-t"]
    assert len(payloads) == 2  # prior live evidence is preserved, not deleted
    tombstone = next(p for p in payloads if p["observation_id"] != prior_id)
    validate_topic_payload(HEIMDAL_OBSERVATION_PUBLISHED, tombstone)
    assert tombstone["content"] is None
    assert tombstone["content_structure"]["karakeep"]["tombstone"] is True
    assert tombstone["supersedes"] == prior_id
    assert tombstone["sequence"] == 1
    prior = next(p for p in payloads if p["observation_id"] == prior_id)
    assert prior["content"] == "live note"  # untouched


def test_inferred_timestamp_when_created_at_absent() -> None:
    item = {
        "id": "item-i",
        "modifiedAt": "2026-07-11T12:00:00+02:00",  # no createdAt
        "content": {"type": "text", "text": "note with only a modified time"},
        "tags": [],
    }
    fake = _FakeKarakeep([[item]])
    result = _adapter(fake).acquire()

    assert len(result.published) == 1
    payload = _payloads()[0]
    validate_topic_payload(HEIMDAL_OBSERVATION_PUBLISHED, payload)
    assert payload["observed_at_start"] == "2026-07-11T12:00:00+02:00"
    assert payload["clock_basis"] == "inferred"
    assert payload["confidence"]["temporal"]["method"] == "karakeep_inferred_timestamp"
    assert payload["confidence"]["temporal"]["calibration"] == "heuristic"


def test_same_snapshot_reprocess_creates_revision_of_lineage(monkeypatch: pytest.MonkeyPatch) -> None:
    """A changed publication profile over the same content is a reprocess:
    revision_of the prior publication, supersedes null (KMA-01)."""
    shared = KarakeepProducerCursor()
    item = _link("item-p", "https://example.com/p", note="stable content")

    first = KarakeepAdapter(
        config=KarakeepConfig(base_url=_BASE_URL, source_id="karakeep-test"),
        token_provider=StaticKarakeepToken(_SECRET_TOKEN),
        http=_FakeKarakeep([[item]]).client(),
        cursor=shared,
    ).acquire()
    prior_id = first.published[0]

    # Simulate an adapter publication-profile bump; content is unchanged.
    monkeypatch.setattr(karakeep_ingest, "STAGE_VERSIONS", {"karakeep_adapter": "contract-v2"})
    reprocessed = KarakeepAdapter(
        config=KarakeepConfig(base_url=_BASE_URL, source_id="karakeep-test"),
        token_provider=StaticKarakeepToken(_SECRET_TOKEN),
        http=_FakeKarakeep([[item]]).client(),
        cursor=shared,
    ).acquire()

    assert len(reprocessed.published) == 1
    payloads = _by_episode(_payloads())["karakeep:item-p"]
    assert len(payloads) == 2
    newer = next(p for p in payloads if p["observation_id"] != prior_id)
    assert newer["revision_of"] == prior_id
    assert newer["supersedes"] is None
    assert newer["sequence"] == 1
    # Same underlying content identity, distinct publication.
    assert newer["provenance"]["content_identity"] == next(
        p for p in payloads if p["observation_id"] == prior_id
    )["provenance"]["content_identity"]


def test_invalid_evidence_item_is_isolated_but_infra_failure_stops() -> None:
    """A schema-invalid item dead-letters only itself (KMA-INV-5); a transient
    durable-write failure propagates so the run stops before advancing (KMA-INV-3)."""
    from app.events.topic_schema_registry import TopicSchemaViolation

    good = _link("item-good", "https://example.com/good")
    poison = _link("item-poison", "https://example.com/poison")
    real_publish = karakeep_ingest.publish_full_observation

    def _publish_schema_reject(*, topic: str, payload: dict[str, Any], **kw: Any) -> Any:
        if payload["episode_id"] == "karakeep:item-poison":
            raise TopicSchemaViolation(topic=topic, schema_ref="test", reason="synthetic")
        return real_publish(topic=topic, payload=payload, **kw)

    fake = _FakeKarakeep([[good, poison]])
    result = KarakeepAdapter(
        config=KarakeepConfig(base_url=_BASE_URL, source_id="karakeep-test"),
        token_provider=StaticKarakeepToken(_SECRET_TOKEN),
        http=fake.client(),
        cursor=KarakeepProducerCursor(),
        publish=_publish_schema_reject,
    ).acquire()
    assert len(result.published) == 1  # good item published
    assert [e.reason_code for e in result.item_errors] == ["invalid_evidence"]
    assert not result.stopped_early
    assert set(_by_episode(_payloads())) == {"karakeep:item-good"}

    # A transient infra failure must NOT be swallowed as a dead-letter.
    reset_memory_observation_log()

    def _publish_infra_down(*, topic: str, payload: dict[str, Any], **kw: Any) -> Any:
        raise RuntimeError("durable write unavailable")

    with pytest.raises(RuntimeError):
        KarakeepAdapter(
            config=KarakeepConfig(base_url=_BASE_URL, source_id="karakeep-test"),
            token_provider=StaticKarakeepToken(_SECRET_TOKEN),
            http=_FakeKarakeep([[good]]).client(),
            cursor=KarakeepProducerCursor(),
            publish=_publish_infra_down,
        ).acquire()


# ---------------------------------------------------------------------------
# AC 5
# ---------------------------------------------------------------------------


def test_adapter_stops_at_published_handoff() -> None:
    module_path = Path(karakeep_ingest.__file__)
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    # The production adapter never reaches across the constituent boundary into
    # Mimer/KAP or companion capture (KMA-INV-4, AC 5). This is an import-level
    # check on executable code -- the module docstring may still *name* the
    # forbidden surfaces to document the boundary.
    forbidden_prefixes = (
        "app.knowledge_acquisition",
        "app.heimdal.candidate_projection",
        "app.heimdal.candidate_writeback",
        "app.heimdal.capture_adapter",
        "app.heimdal.capture_note",
        "app.heimdal.capture_runtime",
        "app.api.routes",  # /api/capture route module family
    )
    leaked = {name for name in imported if name.startswith(forbidden_prefixes)}
    assert leaked == set(), f"adapter imports across the boundary: {leaked}"

    # Positively: a run publishes to the handoff log and nothing beyond it.
    fake = _FakeKarakeep([[_link("item-1", "https://example.com/a")]])
    result = _adapter(fake).acquire()
    assert len(result.published) == 1
    rows = read_observations_from(0)
    assert len(rows) == 1
    assert rows[0].topic == HEIMDAL_OBSERVATION_PUBLISHED
