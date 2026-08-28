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
    "XMLHttpRequest",
    "sendBeacon",
    "window.open",
    ".assign(",
    ".replace(",
    "import(",
    "eval(",
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


def _blob_oid_bytes(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()  # noqa: S324 - Git SHA-1 object identity


def _blob_oid(path: Path) -> str:
    return _blob_oid_bytes(path.read_bytes())


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


def _immutable_source_texts(
    repo_root: Path, source: dict[str, Any]
) -> dict[str, str]:
    texts: dict[str, str] = {}
    for path, expected_oid in source["objects"].items():
        payload = _git_bytes(repo_root, "show", f"{source['commit']}:{path}")
        if _blob_oid_bytes(payload) != expected_oid:
            raise DevuiCandidateProvenanceError(
                f"reviewed source object changed: {path}"
            )
        texts[path] = payload.decode("utf-8")
    return texts


def _validate_bindings(
    manifest: dict[str, Any],
    *,
    inventory: dict[str, str],
    source_texts: dict[str, str],
    candidate_texts: dict[str, str],
) -> None:
    source = manifest["source"]
    bound_files: set[str] = set()
    for binding in manifest.get("bindings", []):
        source_path = binding.get("source_path")
        if source_path not in source["objects"] or source_path not in source_texts:
            raise DevuiCandidateProvenanceError("binding names an unverified source")
        if not set(binding.get("transforms", [])).issubset(_ALLOWED_TRANSFORMS):
            raise DevuiCandidateProvenanceError("binding uses an unreviewed transform")
        patterns = binding.get("source_patterns")
        if not isinstance(patterns, list) or not patterns:
            raise DevuiCandidateProvenanceError("binding requires exact source anchors")
        for pattern in patterns:
            if not isinstance(pattern, str) or not pattern or pattern not in source_texts[source_path]:
                raise DevuiCandidateProvenanceError(
                    f"binding anchor is absent from immutable source: {source_path}"
                )
        candidate_files = binding.get("candidate_files", [])
        candidate_patterns = binding.get("candidate_patterns")
        shared_patterns = binding.get("shared_patterns")
        if not isinstance(candidate_patterns, dict) or set(candidate_patterns) != set(candidate_files):
            raise DevuiCandidateProvenanceError(
                "binding must cover every named candidate file with exact anchors"
            )
        if not isinstance(shared_patterns, dict) or set(shared_patterns) != set(candidate_files):
            raise DevuiCandidateProvenanceError(
                "binding must cover every candidate file with shared source anchors"
            )
        for candidate_file in candidate_files:
            if candidate_file not in candidate_texts:
                raise DevuiCandidateProvenanceError(
                    "binding names a candidate outside the verified inventory"
                )
            anchors = candidate_patterns[candidate_file]
            if not isinstance(anchors, list) or not anchors:
                raise DevuiCandidateProvenanceError(
                    "binding requires exact candidate anchors"
                )
            for anchor in anchors:
                if (
                    not isinstance(anchor, str)
                    or not anchor
                    or anchor not in candidate_texts[candidate_file]
                ):
                    raise DevuiCandidateProvenanceError(
                        f"binding anchor is absent from candidate: {candidate_file}"
                    )
            common_anchors = shared_patterns[candidate_file]
            if not isinstance(common_anchors, list) or not common_anchors:
                raise DevuiCandidateProvenanceError(
                    "binding requires shared source-to-candidate anchors"
                )
            for anchor in common_anchors:
                if (
                    not isinstance(anchor, str)
                    or not anchor
                    or anchor not in source_texts[source_path]
                    or anchor not in candidate_texts[candidate_file]
                ):
                    raise DevuiCandidateProvenanceError(
                        f"shared binding anchor is not present on both sides: {candidate_file}"
                    )
        bound_files.update(candidate_files)
    if bound_files != set(inventory):
        raise DevuiCandidateProvenanceError("every candidate file must have a source binding")


def _validate_candidate_tokens(*, candidate_text: str, token_source: str) -> None:
    source_tokens = set(re.findall(r"(--[a-z0-9-]+)\s*:", token_source))
    candidate_tokens = set(re.findall(r"var\((--[a-z0-9-]+)\)", candidate_text))
    if not candidate_tokens.issubset(source_tokens):
        raise DevuiCandidateProvenanceError(
            "candidate uses a token absent from the immutable accepted source"
        )


def _validate_browser_safety(candidate_texts: dict[str, str]) -> str:
    combined = "\n".join(candidate_texts.values())
    if re.search(r"(?:https?:)?//", combined, flags=re.IGNORECASE):
        raise DevuiCandidateProvenanceError(
            "candidate contains an external or scheme-relative URL"
        )
    if re.search(
        r"@import|url\s*\(", candidate_texts["devui.css"], flags=re.IGNORECASE
    ):
        raise DevuiCandidateProvenanceError(
            "candidate CSS can leave the committed asset set"
        )
    if any(capability in combined for capability in _PROHIBITED_BROWSER_CAPABILITIES):
        raise DevuiCandidateProvenanceError(
            "candidate contains stateful, mutating, or unreviewed browser capability"
        )
    if len(re.findall(r"\bfetch\s*\(", combined)) != 2:
        raise DevuiCandidateProvenanceError(
            "candidate must contain exactly the two reviewed API reads"
        )
    if combined.count(
        'fetch("/api/devui/overview", {method: "GET", cache: "no-store"})'
    ) != 1:
        raise DevuiCandidateProvenanceError(
            "Overview must perform exactly one fixed GET API read"
        )
    if combined.count(
        'fetch(`/api/devui/focus?subject=${encodeURIComponent(subject)}`, {method: "GET", cache: "no-store"})'
    ) != 1:
        raise DevuiCandidateProvenanceError(
            "Focus must perform exactly one subject-bound GET API read"
        )
    if combined.count('href="/devui/overview"') != 1:
        raise DevuiCandidateProvenanceError(
            "candidate must contain exactly one literal Overview return"
        )
    return combined


def validate_devui_exact_reuse_candidate(
    repo_root: Path, *, revision: str
) -> dict[str, str]:
    """Validate inventory, Git objects, closed transforms, and browser safety."""

    if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise DevuiCandidateProvenanceError(
            "an explicit canonical reviewed commit SHA is required"
        )
    reviewed_commit = _git(repo_root, "rev-parse", f"{revision}^{{commit}}")
    if reviewed_commit != revision:
        raise DevuiCandidateProvenanceError(
            "reviewed revision did not resolve to the supplied commit SHA"
        )
    manifest = _load_manifest(repo_root, revision=reviewed_commit)
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
    source_texts = _immutable_source_texts(repo_root, source)

    transforms = manifest.get("transform_allowlist")
    if (
        not isinstance(transforms, list)
        or not all(isinstance(transform, str) for transform in transforms)
        or set(transforms) != _ALLOWED_TRANSFORMS
        or len(transforms) != len(_ALLOWED_TRANSFORMS)
    ):
        raise DevuiCandidateProvenanceError("transform allowlist is not the closed #4836 set")
    candidate_texts = {
        name: (candidate_root / name).read_text(encoding="utf-8")
        for name in actual_names
    }
    _validate_bindings(
        manifest,
        inventory=inventory,
        source_texts=source_texts,
        candidate_texts=candidate_texts,
    )

    combined = _validate_browser_safety(candidate_texts)

    _validate_candidate_tokens(
        candidate_text=combined,
        token_source=source_texts["app/web/static/colors_and_type.css"],
    )

    if _git(repo_root, "rev-parse", f"{reviewed_commit}:{subtree}") != candidate["tree"]:
        raise DevuiCandidateProvenanceError("revision does not contain the exact candidate tree")
    for name, oid in inventory.items():
        if _git(repo_root, "rev-parse", f"{reviewed_commit}:{subtree}/{name}") != oid:
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
