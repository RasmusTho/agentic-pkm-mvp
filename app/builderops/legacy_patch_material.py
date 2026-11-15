"""Compose bounded patch evidence without conferring ownership or custody."""
from __future__ import annotations

import hashlib
from pathlib import Path

from app.builderops.legacy_patch_application import verify_application
from app.builderops.legacy_patch_backup import read_patch_backup
from app.builderops.legacy_selected_files import read_selected
from app.builderops.legacy_tracked_index import inspect_index


def verify_material(*, root: Path, index: Path, backup: Path, baseline: dict[str, bytes],
                    baseline_oids: dict[str, str], selected_sha256: dict[str, str],
                    patch_sha256: str) -> dict[str, object]:
    """Compare two complete observations; caller must independently prove HEAD and writer identity."""
    if len(baseline) != 2 or set(baseline) != set(baseline_oids) or set(baseline) != set(selected_sha256):
        raise ValueError("patch material requires exactly the same two paths")
    for name, data in baseline.items():
        oid = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if oid != baseline_oids[name]:
            raise ValueError("baseline bytes differ from supplied blob id")

    def observe() -> tuple[str, dict[str, bytes], bytes]:
        return (inspect_index(index, baseline_oids), read_selected(root, selected_sha256),
                read_patch_backup(backup, patch_sha256))

    first = observe()
    verify_application(baseline, selected_sha256, first[2], patch_sha256)
    if observe() != first:
        raise ValueError("patch material changed during comparison")
    return {"index_sha256": first[0], "file_sha256": dict(selected_sha256), "patch_sha256": patch_sha256}
