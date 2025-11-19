from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Iterable, Mapping

from app.orchestrator.handler import OrchestratorContext
from app.services import note_update
from app.services.note_update import DEFAULT_SNAPSHOT_DIR, NoteUpdateResult, process_note_update

logger = logging.getLogger(__name__)


def _hash_text(text: str) -> str:
    return hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()


class NoteWatcherService:
    def __init__(
        self,
        vault_root: Path,
        *,
        snapshot_dir: Path | None = None,
        glob_pattern: str = "*.md",
    ) -> None:
        self.vault_root = Path(vault_root).resolve()
        self.snapshot_dir = snapshot_dir or DEFAULT_SNAPSHOT_DIR
        self.glob_pattern = glob_pattern
        self.last_scan: dict[str, int] = {"checked": 0, "processed": 0, "skipped": 0, "errors": 0}
        self.last_errors: list[tuple[Path, Exception]] = []
        self.last_skipped: list[Path] = []

    def scan_vault_once(self, ctx: OrchestratorContext | Mapping[str, object] | None) -> list[NoteUpdateResult]:
        results: list[NoteUpdateResult] = []
        checked = processed = skipped = errors = 0
        self.last_errors.clear()
        self.last_skipped.clear()

        for note_path in self._iter_note_paths():
            try:
                content = note_path.read_text(encoding="utf-8")
            except Exception as exc:  # pragma: no cover - defensive
                errors += 1
                self.last_errors.append((note_path, exc))
                logger.warning("failed to read note %s: %s", note_path, exc)
                continue

            frontmatter = note_update._extract_frontmatter(content)  # type: ignore[attr-defined]
            note_uuid = str(frontmatter.get("uuid") or "").strip()
            if not note_uuid:
                skipped += 1
                self.last_skipped.append(note_path)
                logger.debug("skip note without uuid: %s", note_path)
                continue
            checked += 1
            if not self._note_changed(note_path, note_uuid, content):
                skipped += 1
                self.last_skipped.append(note_path)
                logger.debug("note unchanged: %s", note_path)
                continue

            try:
                result = process_note_update(note_path, ctx, snapshot_dir=self.snapshot_dir)
            except Exception as exc:  # pragma: no cover - defensive
                errors += 1
                self.last_errors.append((note_path, exc))
                logger.exception("note update failed for %s", note_path)
                continue

            results.append(result)
            processed += 1
            logger.info(
                "note updated: %s (events=%s, dispatched=%s)",
                note_path,
                result.events_count,
                result.dispatch_count,
            )

        self.last_scan = {
            "checked": checked,
            "processed": processed,
            "skipped": skipped,
            "errors": errors,
        }
        return results

    def _iter_note_paths(self) -> Iterable[Path]:
        if self.vault_root.is_file():
            yield self.vault_root
            return
        for path in sorted(self.vault_root.rglob(self.glob_pattern)):
            if path.is_file():
                yield path

    def _note_changed(self, note_path: Path, note_uuid: str, content: str) -> bool:
        snapshot_path = Path(self.snapshot_dir) / f"{note_uuid}.md"
        if not snapshot_path.exists():
            return True
        try:
            snapshot_text = snapshot_path.read_text(encoding="utf-8")
        except Exception:  # pragma: no cover - defensive
            return True

        snapshot_hash = _hash_text(snapshot_text)
        note_hash = _hash_text(content)
        return note_hash != snapshot_hash


__all__ = ["NoteWatcherService"]
