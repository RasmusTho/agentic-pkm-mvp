from __future__ import annotations

import hashlib
import uuid
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

import click

from app.agents.classifier.agent import run as classify_run
from app.agents.panel.filters import strip_ai_panels
from app.index.outbox import append_jsonl
from app.obs.log import with_trace_id
from app.retrieval.hybrid import get_store
from app.search.service import ingest_object as index_ingest_object
from app.services.note_log import note_log_path
from app.store.object_store import DomainObject, ObjectStore
from app.stores import get_object_store
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter


@dataclass
class VaultAlphaSummary:
    scanned: int
    ingested: int
    included_folders: List[str]
    force: bool = False


_EXCLUDED_TOP = {"System", "Templates", ".obsidian"}
_ALLOWED_TOP = {"Concepts"}
_TEST_NOTE_REL = Path("Test") / "Alpha-HumanFlows.md"


def _compute_ingest_fingerprint(stripped_text: str, path: Path) -> dict[str, int | str]:
    return {
        "text_sha256": hashlib.sha256(stripped_text.encode("utf-8")).hexdigest(),
        "mtime_ns": path.stat().st_mtime_ns,
    }


def _derive_title(body: str, path: Path) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("---"):
            continue
        if stripped.startswith("#"):
            candidate = stripped.lstrip("#").strip()
            if candidate:
                return candidate
        else:
            return stripped
    return path.stem


def _normalize_uuid(raw: str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, (list, tuple)):
        if not raw:
            return ""
        return _normalize_uuid(raw[0])
    value = str(raw).strip()
    if value.startswith("[[") and value.endswith("]]"):
        value = value[2:-2].strip()
    return value


def _uuid_wikilink(note_uuid: str) -> str:
    return f"[[{note_uuid}]]"


def _is_wikilink(raw: str | None) -> bool:
    if raw is None:
        return False
    if isinstance(raw, (list, tuple)):
        if not raw:
            return False
        return _is_wikilink(raw[0])
    value = str(raw).strip()
    return value.startswith("[[") and value.endswith("]]")


def _load_mirror_frontmatter(vault_root: Path, rel_path: Path) -> tuple[Path | None, dict, str]:
    mirror_dir = vault_root / Path("System/Metadata/VaultMirror") / rel_path.parent
    if not mirror_dir.exists():
        return None, {}, ""
    for cand in sorted(mirror_dir.glob("*.md")):
        try:
            fm, body = load_frontmatter(cand.read_text(encoding="utf-8"))
            source_ref = str(fm.get("source_ref") or "").strip()
            if source_ref == str(rel_path):
                return cand, fm, body
        except Exception:
            continue
    return None, {}, ""


def _existing_mirror_uuid(vault_root: Path, rel_path: Path) -> str:
    _, fm, _ = _load_mirror_frontmatter(vault_root, rel_path)
    return _normalize_uuid(fm.get("uuid") or fm.get("id") or "")


def _ensure_note_uuid_frontmatter(path: Path, frontmatter: dict, body: str, note_uuid: str, *, rel_path: Path) -> tuple[str, bool]:
    existing_uuid_raw = frontmatter.get("uuid")
    existing_uuid = _normalize_uuid(existing_uuid_raw)
    existing_id_raw = frontmatter.get("id")
    existing_id = _normalize_uuid(existing_id_raw)

    if existing_uuid:
        if existing_uuid != note_uuid:
            click.echo(
                f"Warning: {rel_path} frontmatter uuid {existing_uuid} differs from derived {note_uuid}; using frontmatter uuid.",
                err=True,
            )
            note_uuid = existing_uuid
        if not _is_wikilink(existing_uuid_raw):
            updated_frontmatter = dict(frontmatter)
            updated_frontmatter["uuid"] = _uuid_wikilink(existing_uuid)
            path.write_text(dump_frontmatter(updated_frontmatter, body), encoding="utf-8")
            return existing_uuid, True
        return existing_uuid, False

    if existing_id:
        if existing_id != note_uuid:
            click.echo(
                f"Warning: {rel_path} frontmatter id {existing_id} differs from derived {note_uuid}; using frontmatter id.",
                err=True,
            )
        updated_frontmatter = dict(frontmatter)
        updated_frontmatter["uuid"] = _uuid_wikilink(existing_id)
        path.write_text(dump_frontmatter(updated_frontmatter, body), encoding="utf-8")
        return existing_id, True

    updated_frontmatter = dict(frontmatter)
    updated_frontmatter["uuid"] = _uuid_wikilink(note_uuid)
    path.write_text(dump_frontmatter(updated_frontmatter, body), encoding="utf-8")
    return note_uuid, True


def _write_mirror(
    vault_root: Path,
    rel_path: Path,
    *,
    note_uuid: str,
    title: str,
    review_state: str,
    maturity: str,
    ingest_fingerprint: dict[str, int | str],
    existing_frontmatter: dict | None = None,
    existing_body: str | None = None,
) -> Path:
    mirror_path = vault_root / note_log_path(note_uuid, rel_path)
    mirror_path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = dict(existing_frontmatter or {})
    frontmatter.update(
        {
            "uuid": note_uuid,
            "title": title,
            "kind": "note",
            "origin": "vault",
            "source_ref": str(rel_path),
            "review_state": review_state,
            "maturity": maturity,
            "ingest_fingerprint": ingest_fingerprint,
        }
    )
    body = existing_body if (existing_body or "").strip() else f"Mirror for {rel_path}"
    mirror_path.write_text(dump_frontmatter(frontmatter, body), encoding="utf-8")
    return mirror_path


def _select_candidates(vault_root: Path, *, include_test_note: bool, max_notes: int) -> Tuple[List[Path], List[str]]:
    candidates: List[Path] = []
    included_folders: List[str] = []
    roots: List[Path] = []
    for folder in sorted(_ALLOWED_TOP):
        root = vault_root / folder
        if root.exists() and root.is_dir():
            included_folders.append(folder)
            roots.append(root)
    if include_test_note:
        test_path = vault_root / _TEST_NOTE_REL
        if test_path.exists():
            roots.append(test_path)
            if "Test" not in included_folders:
                included_folders.append("Test")
    for root in roots:
        if root.is_file() and root.suffix.lower() == ".md":
            candidates.append(root)
            continue
        for path in sorted(root.rglob("*.md")):
            rel = path.relative_to(vault_root)
            top = rel.parts[0] if rel.parts else ""
            if top in _EXCLUDED_TOP:
                continue
            candidates.append(path)
            if max_notes > 0 and len(candidates) >= max_notes:
                return candidates[:max_notes], included_folders
    if max_notes > 0:
        return candidates[:max_notes], included_folders
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


def _ingest_single(path: Path, *, vault_root: Path, trace_id: str) -> str:
    rel_path = path.relative_to(vault_root)
    raw_text = path.read_text(encoding="utf-8")
    frontmatter, body = load_frontmatter(raw_text)
    mirror_path, mirror_frontmatter, mirror_body = _load_mirror_frontmatter(vault_root, rel_path)
    frontmatter_uuid = _normalize_uuid(frontmatter.get("uuid") or frontmatter.get("id") or "")
    mirror_uuid = _normalize_uuid(mirror_frontmatter.get("uuid") or mirror_frontmatter.get("id") or "")
    note_uuid = frontmatter_uuid or mirror_uuid or str(uuid.uuid4())
    # Frontmatter is the canonical identity; mirror is a log to help heal missing metadata.
    if frontmatter_uuid and mirror_uuid and frontmatter_uuid != mirror_uuid:
        click.echo(
            f"Warning: {rel_path} mirror uuid {mirror_uuid} differs from frontmatter uuid {frontmatter_uuid}; using frontmatter uuid.",
            err=True,
        )

    note_uuid, rewrote_uuid = _ensure_note_uuid_frontmatter(path, frontmatter, body, note_uuid, rel_path=rel_path)
    updated_frontmatter = dict(frontmatter)
    updated_frontmatter["uuid"] = _uuid_wikilink(note_uuid)
    if "ingest_fingerprint" in updated_frontmatter:
        updated_frontmatter.pop("ingest_fingerprint", None)
        rewrote_uuid = True
    if rewrote_uuid:
        path.write_text(dump_frontmatter(updated_frontmatter, body), encoding="utf-8")
    frontmatter = updated_frontmatter

    title = str(frontmatter.get("title") or _derive_title(body, path))
    review_state = str(frontmatter.get("review_state") or "provisional")
    maturity = str(frontmatter.get("maturity") or "note")
    stripped_body = strip_ai_panels(body)
    stripped_text = stripped_body.strip()
    ingest_fingerprint = _compute_ingest_fingerprint(stripped_text, path)

    try:
        mtime_ns = int(ingest_fingerprint.get("mtime_ns", 0))
        if mtime_ns > 0:
            os.utime(path, ns=(mtime_ns, mtime_ns))
    except Exception:
        pass

    _write_mirror(
        vault_root,
        rel_path,
        note_uuid=note_uuid,
        title=title,
        review_state=review_state,
        maturity=maturity,
        ingest_fingerprint=ingest_fingerprint,
        existing_frontmatter=mirror_frontmatter if mirror_path else None,
        existing_body=mirror_body if mirror_path else None,
    )

    core6 = {
        "id": note_uuid,
        "title": title,
        "review_state": review_state,
        "origin": "vault",
    }

    payload = {
        "core6": core6,
        "raw_text": stripped_text,
        "text": stripped_text,
        "source_path": str(path),
        "maturity": maturity,
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
            payload={"title": title, "origin": "vault", "source": str(path)},
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


def run_vault_alpha_ingest(vault_root: Path, *, max_notes: int = 200, include_test_note: bool = False, force: bool = False) -> VaultAlphaSummary:
    vault_root = vault_root.expanduser().resolve()
    store = get_object_store()
    candidates, included_folders = _select_candidates(vault_root, include_test_note=include_test_note, max_notes=max_notes)

    store_count = _store_object_count(store)
    mirror_root = vault_root / "System/Metadata/VaultMirror"
    has_mirrors = mirror_root.exists() and any(mirror_root.rglob("*.md"))
    cold_rebuild = not force and store_count == 0 and has_mirrors
    if cold_rebuild:
        click.echo(
            "Vault mirrors exist but vault store is empty (0 objects). Treating this as a cold rebuild from the vault (no fingerprint skips)."
        )

    ingested = 0
    for path in candidates:
        try:
            rel_path = path.relative_to(vault_root)
            raw_text = path.read_text(encoding="utf-8")
            frontmatter, body = load_frontmatter(raw_text)
            frontmatter_uuid = _normalize_uuid(frontmatter.get("uuid") or frontmatter.get("id") or "")
            mirror_path, mirror_frontmatter, _ = _load_mirror_frontmatter(vault_root, rel_path)
            mirror_uuid = _normalize_uuid(mirror_frontmatter.get("uuid") or mirror_frontmatter.get("id") or "")
            note_uuid = frontmatter_uuid or mirror_uuid
            stripped_text = strip_ai_panels(body).strip()
            ingest_fingerprint = _compute_ingest_fingerprint(stripped_text, path)
            should_skip = False
            if note_uuid and not force and not cold_rebuild:
                parsed_uuid = None
                try:
                    parsed_uuid = uuid.UUID(note_uuid)
                except Exception:
                    parsed_uuid = None
                existing = store.get(parsed_uuid) if parsed_uuid else None
                if existing is not None:
                    payload = existing.get("payload") or {}
                    stored_fp = payload.get("ingest_fingerprint")
                    mirror_fp = mirror_frontmatter.get("ingest_fingerprint")
                    if stored_fp and mirror_fp:
                        if stored_fp == mirror_fp == ingest_fingerprint:
                            should_skip = True
            if should_skip:
                continue

            trace_id = with_trace_id(None)
            _ingest_single(path, vault_root=vault_root, trace_id=trace_id)
            ingested += 1
        except Exception:
            continue
    return VaultAlphaSummary(scanned=len(candidates), ingested=ingested, included_folders=included_folders, force=force)


__all__ = ["run_vault_alpha_ingest", "VaultAlphaSummary"]
