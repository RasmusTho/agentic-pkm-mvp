"""KA-01 tests for immutable raw-record persistence and dedup identity.

Per SOURCE_PLUGIN_CONTRACT.md § Identity and dedup: `content_identity` is a
hash of acquired content, dedup is keyed on
`(source_kind, item_ref, content_identity)`, and a changed source yields a new
record while the prior record is left untouched (never overwritten).
"""

from __future__ import annotations

import pytest

from app import objects as object_store_module
from app.knowledge_acquisition import youtube_plugin as plugin
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
