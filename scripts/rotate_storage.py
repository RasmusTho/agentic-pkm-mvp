"""Rotate DuckDB and provenance log artifacts into timestamped archives."""

from __future__ import annotations

import argparse
import shutil
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DUCKDB_PATH = ROOT / "storage" / "agent.duckdb"
PROVENANCE_PATH = ROOT / "provenance.jsonl"
DEFAULT_ARCHIVE = ROOT / "storage" / "archive"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rotate storage artifacts to archive.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_ARCHIVE,
        help="Directory for archived copies (default: storage/archive).",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy instead of move; useful when the process should keep original files.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="When used with --copy, truncate originals after copying.",
    )
    parser.add_argument(
        "--no-touch",
        action="store_true",
        help="Do not recreate empty placeholder files after rotation.",
    )
    parser.add_argument(
        "--max-backups",
        type=int,
        default=10,
        help="Maximum number of archives to retain per file (default: 10).",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=None,
        help="Delete archives older than this many days (default: disabled).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show actions without modifying files.",
    )
    return parser.parse_args()


def _timestamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")


def rotate_file(
    source: Path,
    archive_dir: Path,
    *,
    copy: bool,
    truncate: bool,
    touch: bool,
    dry_run: bool,
    max_backups: int,
    max_age_days: int | None,
) -> None:
    if not source.exists():
        print(f"Skipping {source} (not found)")
        return

    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = _timestamp()
    destination = archive_dir / f"{source.name}.{stamp}"
    action = "Copy" if copy else "Move"
    print(f"{action} {source} -> {destination}")
    if not dry_run:
        if copy:
            shutil.copy2(source, destination)
            if truncate:
                if source.suffix == ".jsonl":
                    source.write_text("", encoding="utf-8")
                else:
                    source.unlink(missing_ok=True)
                    source.touch()
        else:
            shutil.move(str(source), destination)

        if touch and not source.exists():
            if source.suffix == ".jsonl":
                source.write_text("", encoding="utf-8")
            else:
                source.touch()

        _enforce_max_backups(archive_dir, source.name, max_backups, max_age_days)


def _enforce_max_backups(
    folder: Path,
    base_name: str,
    max_items: int,
    max_age_days: int | None,
) -> None:
    candidates = sorted(
        folder.glob(f"{base_name}.*"),
        key=lambda path: path.stat().st_mtime,
    )
    excess = len(candidates) - max_items
    for path in candidates[: max(0, excess)]:
        print(f"Removing old archive {path}")
        path.unlink(missing_ok=True)

    if max_age_days is not None:
        cutoff = datetime.now(tz=UTC).timestamp() - max_age_days * 86400
        for path in candidates:
            if path.stat().st_mtime < cutoff:
                print(f"Removing expired archive {path}")
                path.unlink(missing_ok=True)


def main() -> None:
    args = parse_args()
    targets: tuple[Path, ...] = (DUCKDB_PATH, PROVENANCE_PATH)
    for target in targets:
        rotate_file(
            target,
            args.output_dir,
            copy=args.copy,
            truncate=args.truncate,
            touch=not args.no_touch,
            dry_run=args.dry_run,
            max_backups=args.max_backups,
            max_age_days=args.max_age_days,
        )


if __name__ == "__main__":
    main()
