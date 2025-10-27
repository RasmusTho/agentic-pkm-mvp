from __future__ import annotations

from typing import Any

from app.services import vault_sync


class PgSink:
    def update_path(self, uuid_value: str, new_path: str) -> None:
        vault_sync.update_path(uuid_value, new_path)

    def upsert_object_from_note(self, path: str, frontmatter: dict[str, Any], body: str, fm_changed: bool, body_changed: bool) -> None:
        vault_sync.upsert_object_from_note(path, frontmatter, body, fm_changed, body_changed)


__all__ = ["PgSink"]
