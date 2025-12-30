from __future__ import annotations

from app.ingest.vault_alpha import _normalize_uuid


def test_normalize_uuid_accepts_wikilink_list() -> None:
    raw = [[["[[aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa]]"]]]
    assert _normalize_uuid(raw) == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def test_normalize_uuid_accepts_plain_string() -> None:
    raw = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert _normalize_uuid(raw) == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
