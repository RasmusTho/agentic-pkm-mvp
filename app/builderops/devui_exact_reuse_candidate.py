"""Fail-closed provenance check for the exact #4836 visual candidate.

This is intentionally not a reusable provenance framework.  It understands
one manifest, one committed candidate subtree, and the closed transformations
authorized for Issue #4836.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


_MANIFEST = Path(
    "companion-ui/companion-app/companion_ui/workspace/devui_candidate_provenance.json"
)
_ALLOWED_TRANSFORMS = {
    "content_binding",
    "interaction_binding",
    "layout_reflow",
    "local_system_font_no_egress_normalization",
}
_PROHIBITED_BROWSER_CAPABILITIES = (
    "localStorage",
    "sessionStorage",
    "indexedDB",
    "serviceWorker",
    "WebSocket",
    "EventSource",
    'method: "POST"',
    'method: "PUT"',
    'method: "PATCH"',
    'method: "DELETE"',
)


class DevuiCandidateProvenanceError(ValueError):
    """The exact #4836 candidate is not bound to its reviewed source."""


def _git_bytes(repo_root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise DevuiCandidateProvenanceError(detail or "git object read failed")
    return result.stdout


def _git(repo_root: Path, *args: str) -> str:
    return _git_bytes(repo_root, *args).decode("utf-8").strip()


def _blob_oid(path: Path) -> str:
    payload = path.read_bytes()
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()  # noqa: S324 - Git SHA-1 object identity


def _tree_oid(inventory: dict[str, str]) -> str:
    payload = b"".join(
        b"100644 " + name.encode("utf-8") + b"\0" + bytes.fromhex(oid)
        for name, oid in sorted(inventory.items())
    )
    header = f"tree {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()  # noqa: S324 - Git SHA-1 object identity


def _load_manifest(repo_root: Path, *, revision: str | None) -> dict[str, Any]:
    worktree_bytes = (repo_root / _MANIFEST).read_bytes()
    manifest_bytes = worktree_bytes
    if revision is not None:
        manifest_bytes = _git_bytes(repo_root, "show", f"{revision}:{_MANIFEST.as_posix()}")
        if worktree_bytes != manifest_bytes:
            raise DevuiCandidateProvenanceError(
                "working manifest differs from the reviewed revision"
            )
    value = json.loads(manifest_bytes.decode("utf-8"))
    if value.get("schema") != "yggdrasil-constrained-reuse.v1" or value.get("issue") != 4836:
        raise DevuiCandidateProvenanceError("unexpected candidate provenance identity")
    return value


def validate_devui_exact_reuse_candidate(
    repo_root: Path, *, revision: str
) -> dict[str, str]:
    """Validate inventory, Git objects, closed transforms, and browser safety."""

    if not isinstance(revision, str) or not revision.strip():
        raise DevuiCandidateProvenanceError(
            "an explicit reviewed Git revision is required"
        )
    manifest = _load_manifest(repo_root, revision=revision)
    source = manifest["source"]
    candidate = manifest["candidate"]
    subtree = candidate["subtree"]
    inventory = candidate["inventory"]
    candidate_root = repo_root / subtree

    actual_names = sorted(
        path.relative_to(candidate_root).as_posix()
        for path in candidate_root.rglob("*")
        if path.is_file()
    )
    if actual_names != sorted(inventory):
        raise DevuiCandidateProvenanceError("candidate inventory is incomplete or contains extras")
    actual_inventory = {name: _blob_oid(candidate_root / name) for name in actual_names}
    if actual_inventory != inventory:
        raise DevuiCandidateProvenanceError("candidate blob identity changed")
    if _tree_oid(actual_inventory) != candidate["tree"]:
        raise DevuiCandidateProvenanceError("candidate tree identity changed")

    if _git(repo_root, "rev-parse", f"{source['commit']}^{{commit}}") != source["commit"]:
        raise DevuiCandidateProvenanceError("reviewed source commit is unavailable")
    if _git(repo_root, "rev-parse", f"{source['commit']}:app/web/static") != source["tree"]:
        raise DevuiCandidateProvenanceError("reviewed source tree changed")
    for path, oid in source["objects"].items():
        if _git(repo_root, "rev-parse", f"{source['commit']}:{path}") != oid:
            raise DevuiCandidateProvenanceError(f"reviewed source object changed: {path}")

    transforms = manifest.get("transform_allowlist")
    if set(transforms or []) != _ALLOWED_TRANSFORMS or len(transforms) != len(_ALLOWED_TRANSFORMS):
        raise DevuiCandidateProvenanceError("transform allowlist is not the closed #4836 set")
    bound_files: set[str] = set()
    for binding in manifest.get("bindings", []):
        if binding.get("source_path") not in source["objects"]:
            raise DevuiCandidateProvenanceError("binding names an unverified source")
        if not set(binding.get("transforms", [])).issubset(_ALLOWED_TRANSFORMS):
            raise DevuiCandidateProvenanceError("binding uses an unreviewed transform")
        bound_files.update(binding.get("candidate_files", []))
    if bound_files != set(inventory):
        raise DevuiCandidateProvenanceError("every candidate file must have a source binding")

    texts = {
        name: (candidate_root / name).read_text(encoding="utf-8")
        for name in actual_names
    }
    combined = "\n".join(texts.values())
    if re.search(r"(?:https?:)?//", combined, flags=re.IGNORECASE):
        raise DevuiCandidateProvenanceError("candidate contains an external or scheme-relative URL")
    if re.search(r"@import|url\s*\(", texts["devui.css"], flags=re.IGNORECASE):
        raise DevuiCandidateProvenanceError("candidate CSS can leave the committed asset set")
    if any(capability in combined for capability in _PROHIBITED_BROWSER_CAPABILITIES):
        raise DevuiCandidateProvenanceError("candidate contains stateful or mutating browser capability")
    if combined.count('fetch("/api/devui/overview"') != 1:
        raise DevuiCandidateProvenanceError("Overview must perform exactly one fixed API read")
    if combined.count("fetch(`/api/devui/focus?subject=${encodeURIComponent(subject)}`") != 1:
        raise DevuiCandidateProvenanceError("Focus must perform exactly one subject-bound API read")

    token_source = (repo_root / "app/web/static/colors_and_type.css").read_text(encoding="utf-8")
    source_tokens = set(re.findall(r"(--[a-z0-9-]+)\s*:", token_source))
    candidate_tokens = set(re.findall(r"var\((--[a-z0-9-]+)\)", combined))
    if not candidate_tokens.issubset(source_tokens):
        raise DevuiCandidateProvenanceError("candidate uses a token absent from the accepted source")

    if _git(repo_root, "rev-parse", f"{revision}:{subtree}") != candidate["tree"]:
        raise DevuiCandidateProvenanceError("revision does not contain the exact candidate tree")
    for name, oid in inventory.items():
        if _git(repo_root, "rev-parse", f"{revision}:{subtree}/{name}") != oid:
            raise DevuiCandidateProvenanceError(f"revision candidate blob changed: {name}")

    return {
        "candidate_subtree": subtree,
        "inventory_status": "complete",
        "source_objects_status": "verified",
        "transform_binding_status": "closed_allowlist",
        "no_egress_status": "verified",
    }


__all__ = [
    "DevuiCandidateProvenanceError",
    "validate_devui_exact_reuse_candidate",
]
