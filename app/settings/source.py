from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class SettingsSource:
    path: str
    mtime: str | None
    sha256: str | None

    def to_payload(self) -> dict[str, str | None]:
        return {"path": self.path, "mtime": self.mtime, "sha256": self.sha256}


def build_source(path: Path) -> SettingsSource:
    if path.exists():
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        mtime = None
        sha = None
    return SettingsSource(path=str(path), mtime=mtime, sha256=sha)
