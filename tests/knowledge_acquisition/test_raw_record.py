"""KA-01 tests for immutable raw-record persistence and dedup identity.

Per SOURCE_PLUGIN_CONTRACT.md § Identity and dedup: `content_identity` is a
hash of acquired content, dedup is keyed on
`(source_kind, item_ref, content_identity)`, and a changed source yields a new
record while the prior record is left untouched (never overwritten).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
from datetime import datetime, timezone

import pytest

from app import objects as object_store_module
from app.knowledge_acquisition import youtube_plugin as plugin
from app.knowledge_acquisition.raw_record import (
    RawRecordIntegrityError,
    get_raw_record,
    persist_raw_record,
    raw_record_object_id,
)
from app.objects import DomainObject, ObjectStore
from app.stores import reset_store_backends

FAKE_URL = "https://www.youtube.com/watch?v=abcdefghijk"


@pytest.fixture(autouse=True)
def _memory_store(monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()
    object_store_module._MEMORY_STORE.clear()
    yield
    reset_store_backends()
    object_store_module._MEMORY_STORE.clear()


def _info_with_caption(title: str = "Original Title") -> dict:
    return {
        "id": "abcdefghijk",
        "title": title,
        "channel": "Test Channel",
        "channel_id": "UC123",
        "upload_date": "20260101",
        "duration": 600,
        "description": "desc",
        "chapters": [],
        "tags": ["a"],
        "language": "en",
        "thumbnail": "https://example.com/thumb.jpg",
        "subtitles": {"en": [{"ext": "vtt", "url": "https://example.com/manual.vtt"}]},
        "automatic_captions": {},
    }


def test_refetch_unchanged_is_traced_noop(monkeypatch):
    info = _info_with_caption()
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info)
    monkeypatch.setattr(plugin, "fetch_caption_body", lambda url: "same transcript body")

    first = plugin.fetch(FAKE_URL)
    assert first.is_new is True

    second = plugin.fetch(FAKE_URL)
    assert second.is_new is False
    assert second.object_id == first.object_id
    assert second.content_identity == first.content_identity


def test_changed_content_new_record(monkeypatch):
    info_v1 = _info_with_caption(title="Original Title")
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info_v1)
    monkeypatch.setattr(plugin, "fetch_caption_body", lambda url: "original transcript body")

    first = plugin.fetch(FAKE_URL)
    assert first.is_new is True

    # Upstream content changed (e.g. title edited, or transcript re-captioned).
    info_v2 = _info_with_caption(title="Updated Title")
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info_v2)
    monkeypatch.setattr(plugin, "fetch_caption_body", lambda url: "updated transcript body")

    second = plugin.fetch(FAKE_URL)

    assert second.is_new is True
    assert second.object_id != first.object_id
    assert second.content_identity != first.content_identity

    # Prior record is untouched.
    from app.knowledge_acquisition.raw_record import get_raw_record

    prior = get_raw_record(first.object_id)
    assert prior is not None
    assert prior["metadata"]["title"] == "Original Title"
    assert prior["caption_body"] == "original transcript body"

    updated = get_raw_record(second.object_id)
    assert updated is not None
    assert updated["metadata"]["title"] == "Updated Title"
    assert updated["caption_body"] == "updated transcript body"


def test_raw_identity_is_atomic_first_write_wins_under_concurrency() -> None:
    barrier = threading.Barrier(2)

    def persist(marker: str):
        barrier.wait(timeout=5)
        return persist_raw_record(
            source_kind="youtube_url",
            item_ref="abcdefghijk",
            content_identity="sha256:concurrent-raw",
            payload={"marker": marker},
            source_ref=f"test:{marker}",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(persist, ("a", "b")))

    assert sorted(result.is_new for result in results) == [False, True]
    assert results[0].record == results[1].record
    stored = get_raw_record(results[0].object_id)
    assert stored == results[0].record


def test_get_raw_record_rejects_non_raw_kind() -> None:
    object_id = raw_record_object_id(
        source_kind="youtube_url",
        item_ref="abcdefghijk",
        content_identity="sha256:not-raw",
    )
    ObjectStore().save_object(
        DomainObject(
            uuid=str(object_id),
            kind="knowledge_acquisition.normalized_transcript",
            payload={"source_kind": "youtube_url"},
            source_ref="test:not-raw",
            created_at=datetime.now(timezone.utc),
        ),
        emit_outbox=False,
    )

    with pytest.raises(RawRecordIntegrityError):
        get_raw_record(object_id)
