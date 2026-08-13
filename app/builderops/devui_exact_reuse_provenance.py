"""Fail-closed Git-object provenance for the narrow devUI exact-reuse route.

The validator deliberately never opens a declaration or source path from a
worktree.  Every authoritative byte is read with ``git cat-file`` from the
candidate commit or its reachable source commit.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


DECLARATION_PATH = "config/builderops/devui_exact_reuse_declaration.json"
_GOOGLE = "https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Space+Grotesk:wght@300;400;500;600&display=swap"
_BUNNY = "https://fonts.bunny.net/css?family=jetbrains-mono:400,500&display=swap"
_APPROVED_IMPORTS = (_GOOGLE, _BUNNY)
_KEYS = frozenset({"schema_version", "source", "remote_font_imports", "source_tokens", "font_fallback", "transforms", "state_matrix"})
_SOURCE_KEYS = frozenset({"commit", "path", "blob_oid"})
_TOKENS = ("--font-ui", "--font-display", "--font-mono")
_PRIMITIVES = {
    "--font-display": "'EB Garamond', Georgia, serif",
    "--font-ui": "'Space Grotesk', system-ui, sans-serif",
    "--font-mono": "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
}
_TRANSFORMS = ("drop_remote_font_imports", "use_declared_local_font_fallback")
_STATES = ("normal", "empty", "loading", "degraded", "error", "narrow", "200%", "keyboard", "screen-reader", "print", "javascript-off")
_FALLBACK = "system-ui, sans-serif"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ExactReuseProvenanceError(ValueError):
    """The candidate cannot prove the narrow exact-reuse contract."""


@dataclass(frozen=True)
class ExactReuseReceipt:
    candidate_sha: str
    declaration_blob_oid: str
    source_commit: str
    source_blob_oid: str
    remote_font_imports: tuple[str, str]
    state_matrix: tuple[str, ...]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(("git", "-C", str(repo), *args), text=True, capture_output=True)
    if result.returncode:
        raise ExactReuseProvenanceError("required immutable Git object is unavailable")
    return result.stdout


def _exact_commit(repo: Path, candidate_sha: str) -> str:
    if not _HEX40.fullmatch(candidate_sha):
        raise ExactReuseProvenanceError("candidate must be a full committed SHA")
    resolved = _git(repo, "rev-parse", f"{candidate_sha}^{{commit}}").strip()
    if resolved != candidate_sha:
        raise ExactReuseProvenanceError("candidate SHA must resolve exactly")
    return resolved


def _regular_blob(repo: Path, commit: str, path: str) -> tuple[str, bytes]:
    if not path or path.startswith("/") or ".." in Path(path).parts:
        raise ExactReuseProvenanceError("invalid object path")
    row = _git(repo, "ls-tree", commit, "--", path).strip()
    parts = row.split(maxsplit=3)
    if len(parts) != 4 or parts[0] != "100644" or parts[1] != "blob" or parts[3] != path:
        raise ExactReuseProvenanceError("path is not an exact regular blob")
    oid = parts[2]
    return oid, _git(repo, "cat-file", "blob", oid).encode()


def _declaration(repo: Path, candidate: str) -> tuple[str, dict[str, object]]:
    oid, raw = _regular_blob(repo, candidate, DECLARATION_PATH)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExactReuseProvenanceError("candidate declaration is not valid JSON") from exc
    if not isinstance(value, dict) or set(value) != _KEYS:
        raise ExactReuseProvenanceError("candidate declaration schema is closed")
    return oid, value


def validate_exact_reuse(repo_root: Path, candidate_sha: str) -> ExactReuseReceipt:
    candidate = _exact_commit(repo_root, candidate_sha)
    declaration_oid, declaration = _declaration(repo_root, candidate)
    source = declaration["source"]
    if not isinstance(source, dict) or set(source) != _SOURCE_KEYS:
        raise ExactReuseProvenanceError("source declaration is closed")
    commit, path, claimed_blob = source["commit"], source["path"], source["blob_oid"]
    if not all(isinstance(value, str) for value in (commit, path, claimed_blob)) or not _HEX40.fullmatch(commit) or not _HEX40.fullmatch(claimed_blob):
        raise ExactReuseProvenanceError("source identity is invalid")
    if subprocess.run(("git", "-C", str(repo_root), "merge-base", "--is-ancestor", commit, candidate)).returncode:
        raise ExactReuseProvenanceError("source commit is not reachable from candidate")
    source_oid, source_bytes = _regular_blob(repo_root, commit, path)
    if source_oid != claimed_blob:
        raise ExactReuseProvenanceError("source blob does not match declaration")
    imports = declaration["remote_font_imports"]
    if not isinstance(imports, list) or tuple(imports) != _APPROVED_IMPORTS:
        raise ExactReuseProvenanceError("remote fonts are not the hardcoded approved literals")
    source_text = source_bytes.decode("utf-8", errors="strict")
    # Every import form counts.  Matching only ``url('...')`` would let a
    # residual quoted import evade the literal allowlist.
    import_forms = re.findall(r"@import\s+([^;]+);", source_text)
    if len(import_forms) != 2 or tuple(re.findall(r"@import\s+url\(['\"]([^'\"]+)['\"]\)", source_text)) != _APPROVED_IMPORTS:
        raise ExactReuseProvenanceError("source imports are not the approved literal pair")
    parsed_primitives = {
        name: value.strip()
        for name, value in re.findall(r"(--font-(?:display|ui|mono))\s*:\s*([^;]+);", source_text)
    }
    if parsed_primitives != _PRIMITIVES:
        raise ExactReuseProvenanceError("source primitives are not the pinned parsed values")
    if declaration["source_tokens"] != list(_TOKENS) or declaration["font_fallback"] != _FALLBACK or declaration["transforms"] != list(_TRANSFORMS) or declaration["state_matrix"] != list(_STATES):
        raise ExactReuseProvenanceError("fallback, transforms, or state matrix is invalid")
    return ExactReuseReceipt(candidate, declaration_oid, commit, source_oid, _APPROVED_IMPORTS, _STATES)


def build_review_input(repo_root: Path, candidate_sha: str) -> ExactReuseReceipt:
    """Return only a receipt bound to a full committed candidate SHA and blob."""
    return validate_exact_reuse(repo_root, candidate_sha)
