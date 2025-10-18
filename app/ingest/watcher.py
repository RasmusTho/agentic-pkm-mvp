from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from app.ingest.service import ingest_text
from app.settings import settings

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".txt", ".md"}


def find_candidate_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.glob("**/*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def process_file(path: Path, processed_dir: Path) -> None:
    text = path.read_text(encoding="utf-8")
    response = ingest_text(text, origin=str(path), title_hint=path.stem, tags=[])
    logger.info(
        "watcher.processed",
        extra={"source": str(path), "dest": response.path, "chunks": len(response.chunks)},
    )
    processed_dir.mkdir(parents=True, exist_ok=True)
    destination = processed_dir / path.name
    path.rename(destination)


def process_once() -> int:
    watch_root = Path(settings.watch_dir).expanduser()
    processed_dir = watch_root / settings.processed_dir

    watch_root.mkdir(parents=True, exist_ok=True)
    count = 0
    for candidate in find_candidate_files(watch_root):
        if processed_dir in candidate.parents:
            continue
        try:
            process_file(candidate, processed_dir)
            count += 1
        except Exception as exc:  # pragma: no cover - logged
            logger.exception("watcher.failed", extra={"source": str(candidate), "error": str(exc)})
    return count


def cli() -> None:
    processed = process_once()
    print(f"Processed {processed} file(s)")


if __name__ == "__main__":  # pragma: no cover
    cli()
