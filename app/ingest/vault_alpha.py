from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Sequence, Set, Tuple

import click
import yaml

from app.agents.classifier.agent import run as classify_run
from app.agents.panel.filters import strip_ai_panels
from app.ingest.config import resolve_ingest_config
from app.index.outbox import append_jsonl
from app.observability.ingest_meta import record_ingest_run
from app.obs.log import with_trace_id
from app.retrieval.hybrid import get_store
from app.search.service import ingest_object as index_ingest_object
from app.services.companion_note import (
    CompanionNote,
    read_companion,
    scan_attachments,
    write_companion,
)
from app.services.note_uuid import ensure_note_uuid
from app.store.object_store import DomainObject, ObjectStore
from app.stores import get_object_store
from app.vault.layout import ensure_vault_layout


@dataclass
class VaultAlphaSummary:
    scanned: int
    ingested: int
    included_folders: List[str]
    force: bool = False
    malformed: int = 0
    malformed_notes: List[str] = field(default_factory=list)
    errors: int = 0
    error_notes: List[str] = field(default_factory=list)
    processed_notes: List[str] = field(default_factory=list)
    skipped_locked: int = 0
    locked_examples: List[str] = field(default_factory=list)
    skipped_invalid: int = 0
    invalid_examples: List[str] = field(default_factory=list)
    invalid_report_path: str | None = None


_TEST_NOTE_REL = Path("Test") / "Alpha-HumanFlows.md"


def _is_locked_error(exc: Exception) -> bool:
    return isinstance(exc, OSError) and getattr(exc, "errno", None) == 35


_LOCKED_FILES_LOG_ENV = "LOCKED_FILES_LOG_PATH"
_LOCKED_FILES_LOG_DEFAULT = Path("/app/tmp/locked-files.jsonl")

_VAULT_NOTE_UUID_NAMESPACE = uuid.UUID("b6b2d8b3-8f2a-4a75-9c65-4c4a0d36b3b8")


def _is_permission_denied_error(exc: Exception) -> bool:
    return isinstance(exc, OSError) and getattr(exc, "errno", None) in {1, 13, 30}


def _locked_files_log_path() -> Path:
    raw = os.getenv(_LOCKED_FILES_LOG_ENV)
    return Path(raw).expanduser() if raw else _LOCKED_FILES_LOG_DEFAULT


def _append_locked_path(rel_display: str) -> None:
    log_path = _locked_files_log_path()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"path": rel_display}) + "\n")
    except Exception:
        pass


def _read_locked_paths() -> list[str]:
    log_path = _locked_files_log_path()
    if not log_path.exists():
        return []
    paths: list[str] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            payload = None
        value = None
        if isinstance(payload, dict):
            value = payload.get("path") or payload.get("rel_path") or payload.get("source_ref")
        if value:
            paths.append(str(value))
        else:
            paths.append(raw)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in paths:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _write_locked_paths(paths: list[str]) -> None:
    log_path = _locked_files_log_path()
    if not paths:
        try:
            log_path.unlink()
        except FileNotFoundError:
            pass
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps({"path": path}) for path in paths) + "\n"
    log_path.write_text(payload, encoding="utf-8")



_INVALID_FILES_LOG_ENV = "INGEST_INVALID_REPORT_PATH"
_INVALID_FILES_LOG_DEFAULT = Path("/app/tmp/ingest-invalid.jsonl")


class InvalidNoteError(Exception):
    def __init__(self, message: str, *, error_type: str) -> None:
        super().__init__(message)
        self.error_type = error_type


def _invalid_files_log_path() -> Path:
    raw = os.getenv(_INVALID_FILES_LOG_ENV)
    return Path(raw).expanduser() if raw else _INVALID_FILES_LOG_DEFAULT


def _reset_invalid_files_log() -> None:
    log_path = _invalid_files_log_path()
    try:
        log_path.unlink()
    except FileNotFoundError:
        pass


def _append_invalid_path(rel_display: str, exc: Exception) -> None:
    log_path = _invalid_files_log_path()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "path": rel_display,
            "exception_type": getattr(exc, "error_type", type(exc).__name__),
            "message": str(exc),
        }
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _decode_note_text(raw_bytes: bytes) -> str:
    if b"\x00" in raw_bytes:
        raise InvalidNoteError("null byte detected", error_type="NullByteError")
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidNoteError(f"unicode decode error: {exc}", error_type="UnicodeDecodeError") from exc


def _is_ignored(rel_path: str, ignore_glob: Sequence[str]) -> bool:
    return any(fnmatch.fnmatch(rel_path, pattern) for pattern in ignore_glob)


def _compute_ingest_fingerprint(stripped_text: str, path: Path) -> dict[str, int | str]:
    return {
        "text_sha256": hashlib.sha256(stripped_text.encode("utf-8")).hexdigest(),
        "mtime_ns": path.stat().st_mtime_ns,
    }


def _normalize_title(value: str) -> str | None:
    cleaned = " ".join(value.split())
    return cleaned or None


def _frontmatter_title(frontmatter: dict) -> str | None:
    raw = frontmatter.get("title")
    value = _coerce_to_str(raw)
    if value is None:
        return None
    return _normalize_title(value)


def _derive_title(body: str, path: Path) -> str:
    first_non_empty: str | None = None
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            hashes = len(stripped) - len(stripped.lstrip("#"))
            if hashes == 1:
                candidate = _normalize_title(stripped[1:])
                if candidate:
                    return candidate
        if first_non_empty is None:
            first_non_empty = stripped
    if first_non_empty:
        candidate = _normalize_title(first_non_empty)
        if candidate:
            return candidate
    return _normalize_title(path.stem) or "Untitled"


def _coerce_to_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)) and len(value) == 1:
        return _coerce_to_str(value[0])
    return None


def _normalize_uuid(raw: object | None) -> str:
    if raw is None:
        return ""
    value = _coerce_to_str(raw)
    if value is None:
        return ""
    value = value.strip()
    if value.startswith("[[") and value.endswith("]]"):
        value = value[2:-2].strip()
    return value


def _find_companion_by_fingerprint(
    vault_root: Path, text_sha256: str, title: str | None
) -> str:
    """
    Find a companion UUID by content hash, with an optional title guard.

    The title guard prevents false matches when two notes have identical body
    text but different titles (e.g. template-based notes or very short notes).
    Returns an empty string if no unambiguous match is found.
    """
    if not text_sha256:
        return ""
    from app.services.companion_note import find_companion_by_content_hash

    found = find_companion_by_content_hash(vault_root, text_sha256)
    if found is None:
        return ""
    if title:
        expected_title = _normalize_title(title)
        companion_title = _normalize_title(found.title) if found.title else None
        if companion_title != expected_title:
            return ""
    return found.uuid


def _sanitize_uuid(raw: str) -> tuple[str, bool]:
    if not raw:
        return "", False
    try:
        uuid.UUID(raw)
    except Exception:
        return "", True
    return raw, False


def _derive_note_uuid(
    frontmatter_uuid: str,
    companion_uuid: str,
    rel_path: Path,
    *,
    invalid_frontmatter: bool = False,
) -> str:
    if frontmatter_uuid:
        return frontmatter_uuid
    if companion_uuid:
        return companion_uuid
    if invalid_frontmatter:
        return uuid.uuid4().hex
    return str(uuid.uuid5(_VAULT_NOTE_UUID_NAMESPACE, rel_path.as_posix()))



def _load_frontmatter_with_reporting(raw_text: str, path: Path) -> tuple[dict, str, bool]:
    """
    Safe frontmatter loader that logs malformed YAML and returns a flag.
    """
    if not raw_text.startswith("---"):
        return {}, raw_text, False
    parts = raw_text.split("---", 2)
    if len(parts) < 3:
        return {}, raw_text, False
    fm_block = parts[1]
    body = parts[2]
    try:
        data = yaml.safe_load(fm_block) or {}
        if not isinstance(data, dict):
            data = {}
        return data, body.lstrip("\n"), False
    except yaml.YAMLError as exc:
        click.echo(f"Warning: Malformed frontmatter in {path}: {exc}", err=True)
        return {}, body.lstrip("\n"), True



def _select_candidates(
    vault_root: Path,
    *,
    include_folders: List[str] | None,
    ignore_glob: Sequence[str],
    include_test_note: bool,
    max_notes: int,
) -> Tuple[List[Path], List[str]]:
    candidates: List[Path] = []
    included_folders = include_folders or ["."]
    vault_root = vault_root.expanduser().resolve()

    for folder in included_folders:
        if folder == ".":
            root = vault_root
        else:
            root = vault_root / folder
        if not root.exists() or not root.is_dir():
            continue
        for path in sorted(root.rglob("*.md")):
            try:
                rel_path = path.relative_to(vault_root)
            except ValueError:
                continue
            rel_display = str(rel_path)
            if rel_display.startswith("."):
                continue
            if not path.is_file():
                continue
            if include_test_note is False and rel_path == _TEST_NOTE_REL:
                continue
            if _is_ignored(rel_display, ignore_glob):
                continue
            candidates.append(path)

    if max_notes > 0:
        candidates = candidates[:max_notes]

    return candidates, included_folders


def _store_object_count(store: ObjectStore) -> int:
    try:
        objs = getattr(store, "_objects", None)
        if isinstance(objs, dict):
            return len(objs)
    except Exception:
        pass
    try:
        from app.stores.pg import PgObjectStore, _connect  # type: ignore

        if isinstance(store, PgObjectStore):
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT count(*) FROM store_objects")
                    row = cur.fetchone()
                    if row:
                        return int(row[0]) if isinstance(row, (list, tuple)) else int(row.get("count", 0))
    except Exception:
        pass
    return 0


def _ingest_single(path: Path, *, vault_root: Path, trace_id: str, raw_text: str | None = None) -> str:
    rel_path = path.relative_to(vault_root)
    if raw_text is None:
        raw_text = _decode_note_text(path.read_bytes())
    if "\x00" in raw_text:
        raise InvalidNoteError("null byte detected", error_type="NullByteError")
    frontmatter, body, _ = _load_frontmatter_with_reporting(raw_text, path)
    frontmatter_uuid_raw = _normalize_uuid(frontmatter.get("uuid") or frontmatter.get("id") or "")
    frontmatter_uuid, frontmatter_invalid = _sanitize_uuid(frontmatter_uuid_raw)
    if frontmatter_invalid:
        click.echo(
            f"Warning: {rel_path} has invalid frontmatter uuid {frontmatter_uuid_raw}; generating a new uuid.",
            err=True,
        )
    companion = read_companion(vault_root, frontmatter_uuid) if frontmatter_uuid else None
    companion_uuid = companion.uuid if companion else ""
    # Frontmatter is the canonical identity; companion is the system surface.
    if frontmatter_uuid and companion_uuid and frontmatter_uuid != companion_uuid:
        click.echo(
            f"Warning: {rel_path} companion uuid {companion_uuid} differs from frontmatter uuid {frontmatter_uuid}; using frontmatter uuid.",
            err=True,
        )

    title = _frontmatter_title(frontmatter) or _derive_title(body, path)
    review_state = str(frontmatter.get("review_state") or "provisional")
    maturity = str(frontmatter.get("maturity") or "note")
    domain = str(frontmatter.get("domain") or "").strip() or "unscoped"
    stripped_body = strip_ai_panels(body)
    stripped_text = stripped_body.strip()
    ingest_fingerprint = _compute_ingest_fingerprint(stripped_text, path)
    text_sha256 = str(ingest_fingerprint.get("text_sha256") or "")

    fingerprint_uuid = ""
    if not frontmatter_uuid and not companion_uuid:
        fingerprint_uuid = _find_companion_by_fingerprint(vault_root, text_sha256, title)

    if frontmatter_invalid:
        note_uuid = _derive_note_uuid(frontmatter_uuid, companion_uuid, rel_path, invalid_frontmatter=True)
    else:
        note_uuid = _derive_note_uuid(frontmatter_uuid, companion_uuid or fingerprint_uuid, rel_path)

    try:
        write_companion(
            vault_root,
            CompanionNote(
                uuid=note_uuid,
                source_ref=str(rel_path),
                title=title,
                content_hash=text_sha256,
                ingest_state="tracked",
                last_ingested=datetime.now(timezone.utc).isoformat(),
                created_by_instance="",
                attachments=scan_attachments(stripped_text),
            ),
        )
    except OSError as exc:
        if _is_locked_error(exc) or _is_permission_denied_error(exc):
            click.echo(
                f"Warning: could not write companion for {rel_path}; continuing without companion update ({exc})",
                err=True,
            )
        else:
            raise

    core6 = {
        "id": note_uuid,
        "title": title,
        "review_state": review_state,
        "origin": "vault",
        "domain": domain,
    }

    payload = {
        "core6": core6,
        "raw_text": stripped_text,
        "text": stripped_text,
        "source_path": str(path),
        "maturity": maturity,
        "domain": domain,
        "ingest_fingerprint": ingest_fingerprint,
    }

    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload=payload,
        source_ref=str(path),
        created_at=datetime.now(timezone.utc),
    )
    # Legacy ObjectStore keeps classifier/normalizer flows working with memory fallback during tests.
    ObjectStore().save_object(obj, emit_outbox=False, trace_id=trace_id)

    try:
        classify_res = classify_run(note_uuid, trace_id=trace_id)
    except Exception:
        classify_res = {}

    try:
        object_uuid = uuid.UUID(note_uuid)
    except Exception:
        object_uuid = uuid.uuid4()

    store_payload = {
        "title": title,
        "origin": "vault",
        "source": str(path),
        "domain": domain,
        "text": stripped_text,
        "ingest_fingerprint": ingest_fingerprint,
    }

    try:
        # Store abstraction (memory/pg) used by ASK/status/hybrid warm-loads.
        get_object_store().put(
            object_uuid,
            kind="note",
            source_ref=str(path),
            payload=store_payload,
        )
    except Exception:
        pass

    try:
        get_store().add_document(
            doc_id=str(object_uuid),
            text=stripped_text,
            source_ref=str(path),
            payload=store_payload,
        )
    except Exception:
        pass

    try:
        index_ingest_object(
            object_id=object_uuid,
            kind="note",
            source_ref=str(path),
            payload={"title": title, "origin": "vault", "source": str(path), "domain": domain},
            text=stripped_text,
        )
    except Exception:
        pass

    normalize_payload = {
        "event": "ingest.normalize",
        "object_id": note_uuid,
        "core6": core6,
        "payload": payload,
        "trace_id": trace_id,
    }
    try:
        append_jsonl(
            {
                "object_id": note_uuid,
                "kind": "pipeline",
                "source_ref": str(path),
                "payload": {"normalize": normalize_payload, "classify": classify_res},
            }
        )
    except Exception:
        pass

    return note_uuid


def run_vault_alpha_ingest(
    vault_root: Path,
    *,
    max_notes: int = 200,
    include_test_note: bool = False,
    force: bool = False,
    resume_from: Iterable[str] | None = None,
) -> VaultAlphaSummary:
    vault_root = vault_root.expanduser().resolve()
    ensure_vault_layout(vault_root)
    ingest_config = resolve_ingest_config(vault_root)
    candidates, included_folders = _select_candidates(
        vault_root,
        include_folders=ingest_config.include_folders,
        ignore_glob=ingest_config.ignore_glob,
        include_test_note=include_test_note,
        max_notes=max_notes,
    )
    return _ingest_candidates(
        vault_root,
        candidates=candidates,
        included_folders=included_folders,
        force=force,
        resume_from=resume_from,
    )


def run_vault_alpha_ingest_paths(
    vault_root: Path, paths: Sequence[Path], *, force: bool = False, resume_from: Iterable[str] | None = None
) -> VaultAlphaSummary:
    vault_root = vault_root.expanduser().resolve()
    ensure_vault_layout(vault_root)
    candidates: List[Path] = []
    included_folders: List[str] = []

    for raw in paths:
        resolved = raw.expanduser()
        if not resolved.is_absolute():
            resolved = vault_root / resolved
        resolved = resolved.resolve()
        try:
            rel_path = resolved.relative_to(vault_root)
        except ValueError:
            raise click.BadParameter(f"Path {resolved} is outside vault root {vault_root}")
        candidates.append(resolved)
        if rel_path.parts:
            top = rel_path.parts[0]
            if top not in included_folders:
                included_folders.append(top)

    return _ingest_candidates(
        vault_root,
        candidates=candidates,
        included_folders=included_folders,
        force=force,
        resume_from=resume_from,
    )


def run_vault_alpha_ingest_locked_only(vault_root: Path, *, force: bool = False) -> VaultAlphaSummary:
    vault_root = vault_root.expanduser().resolve()
    ensure_vault_layout(vault_root)
    locked_paths = _read_locked_paths()
    if not locked_paths:
        return VaultAlphaSummary(scanned=0, ingested=0, included_folders=[], force=force)
    summary = run_vault_alpha_ingest_paths(
        vault_root,
        [Path(path) for path in locked_paths],
        force=force,
        resume_from=None,
    )
    remaining = [path for path in locked_paths if path not in summary.processed_notes]
    _write_locked_paths(remaining)
    return summary


def _ingest_candidates(
    vault_root: Path,
    *,
    candidates: Sequence[Path],
    included_folders: List[str],
    force: bool,
    resume_from: Iterable[str] | None,
    record_locked: bool = True,
) -> VaultAlphaSummary:
    store = get_object_store()

    store_count = _store_object_count(store)
    companions_dir = vault_root / "_system/companions"
    has_companions = companions_dir.exists() and any(companions_dir.glob("*.md"))
    cold_rebuild = not force and store_count == 0 and has_companions
    if cold_rebuild:
        click.echo(
            "Companion notes exist but vault store is empty (0 objects). Treating this as a cold rebuild from the vault (no fingerprint skips)."
        )

    ingested = 0
    malformed: List[str] = []
    errors: List[str] = []
    processed: Set[str] = set(resume_from or [])
    skipped_locked = 0
    locked_examples: List[str] = []
    skipped_invalid = 0
    invalid_examples: List[str] = []
    invalid_report_path = _invalid_files_log_path()
    _reset_invalid_files_log()

    def _record_locked(rel_display: str) -> None:
        nonlocal skipped_locked
        skipped_locked += 1
        if len(locked_examples) < 3:
            locked_examples.append(rel_display)
        if record_locked:
            _append_locked_path(rel_display)

    def _record_invalid(rel_display: str, exc: Exception) -> None:
        nonlocal skipped_invalid
        skipped_invalid += 1
        if len(invalid_examples) < 5:
            invalid_examples.append(rel_display)
        _append_invalid_path(rel_display, exc)

    for path in candidates:
        try:
            rel_path = path.relative_to(vault_root)
            rel_display = str(rel_path)
            if rel_display in processed:
                continue
            try:
                raw_bytes = path.read_bytes()
            except OSError as exc:
                if _is_locked_error(exc):
                    _record_locked(rel_display)
                    continue
                raise
            try:
                raw_text = _decode_note_text(raw_bytes)
            except InvalidNoteError as exc:
                _record_invalid(rel_display, exc)
                continue
            frontmatter, body, fm_error = _load_frontmatter_with_reporting(raw_text, path)
            if fm_error:
                malformed.append(rel_display)
                continue
            frontmatter_uuid_raw = _normalize_uuid(frontmatter.get("uuid") or frontmatter.get("id") or "")
            needs_uuid_write = not bool(frontmatter_uuid_raw)
            title = _frontmatter_title(frontmatter) or _derive_title(body, path)
            stripped_text = strip_ai_panels(body).strip()
            ingest_fingerprint = _compute_ingest_fingerprint(stripped_text, path)
            frontmatter_uuid, frontmatter_invalid = _sanitize_uuid(frontmatter_uuid_raw)
            text_sha256 = str(ingest_fingerprint.get("text_sha256") or "")
            companion = read_companion(vault_root, frontmatter_uuid) if frontmatter_uuid else None
            companion_uuid = companion.uuid if companion else ""
            fingerprint_uuid = ""
            if not frontmatter_uuid and not companion_uuid:
                fingerprint_uuid = _find_companion_by_fingerprint(vault_root, text_sha256, title)
                if fingerprint_uuid:
                    companion = read_companion(vault_root, fingerprint_uuid)
            if frontmatter_invalid:
                note_uuid = _derive_note_uuid(frontmatter_uuid, companion_uuid, rel_path, invalid_frontmatter=True)
            else:
                note_uuid = _derive_note_uuid(frontmatter_uuid, companion_uuid or fingerprint_uuid, rel_path)
            if needs_uuid_write and note_uuid:
                try:
                    ensure_note_uuid(path, preferred_uuid=note_uuid)
                except OSError as exc:
                    if _is_locked_error(exc) or _is_permission_denied_error(exc):
                        click.echo(
                            f"Warning: could not persist uuid for {rel_display}; continuing without file rewrite ({exc})",
                            err=True,
                        )
                    else:
                        raise
            should_skip = False
            if note_uuid and not force and not cold_rebuild:
                parsed_uuid = None
                try:
                    parsed_uuid = uuid.UUID(note_uuid)
                except Exception:
                    parsed_uuid = None
                existing = store.get(parsed_uuid) if parsed_uuid else None
                if existing is not None:
                    companion_for_skip = companion or (read_companion(vault_root, note_uuid) if note_uuid else None)
                    companion_hash = companion_for_skip.content_hash if companion_for_skip else None
                    if companion_hash and companion_hash == text_sha256:
                        should_skip = True
            if should_skip:
                continue

            trace_id = with_trace_id(None)
            try:
                _ingest_single(path, vault_root=vault_root, trace_id=trace_id, raw_text=raw_text)
            except TypeError:
                _ingest_single(path, vault_root=vault_root, trace_id=trace_id)
            ingested += 1
            processed.add(rel_display)
        except OSError as exc:
            rel_display = str(rel_path) if "rel_path" in locals() else str(path)
            if _is_locked_error(exc):
                _record_locked(rel_display)
                continue
            errors.append(rel_display)
            click.echo(f"Error ingesting {rel_display}: {exc}", err=True)
            continue
        except InvalidNoteError as exc:
            rel_display = str(rel_path) if "rel_path" in locals() else str(path)
            _record_invalid(rel_display, exc)
            continue
        except Exception as exc:
            rel_display = str(rel_path) if "rel_path" in locals() else str(path)
            errors.append(rel_display)
            click.echo(f"Error ingesting {rel_display}: {exc}", err=True)
            continue
    summary = VaultAlphaSummary(
        scanned=len(candidates),
        ingested=ingested,
        included_folders=included_folders,
        force=force,
        malformed=len(malformed),
        malformed_notes=malformed,
        errors=len(errors),
        error_notes=errors,
        processed_notes=sorted(processed),
        skipped_locked=skipped_locked,
        locked_examples=locked_examples,
        skipped_invalid=skipped_invalid,
        invalid_examples=invalid_examples,
        invalid_report_path=str(invalid_report_path) if skipped_invalid > 0 else None,
    )
    if skipped_locked > 0:
        example = locked_examples[0] if locked_examples else "-"
        click.echo(f"Skipped {skipped_locked} locked files (errno=35). Example: {example}")
    if skipped_invalid > 0:
        example = invalid_examples[0] if invalid_examples else "-"
        click.echo(f"Skipped {skipped_invalid} invalid files. Example: {example}")
    try:
        record_ingest_run(
            "vault",
            scanned=summary.scanned,
            ingested=summary.ingested,
            errors=summary.errors,
            malformed=summary.malformed,
            ok=summary.errors == 0,
            message=None if summary.errors == 0 else "ingest errors",
        )
    except Exception:
        pass
    return summary


__all__ = [
    "run_vault_alpha_ingest",
    "run_vault_alpha_ingest_paths",
    "run_vault_alpha_ingest_locked_only",
    "VaultAlphaSummary",
]
