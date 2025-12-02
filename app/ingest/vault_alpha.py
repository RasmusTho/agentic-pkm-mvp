from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

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


_EXCLUDED_TOP = {"System", "Templates", ".obsidian"}
_ALLOWED_TOP = {"Concepts"}
_TEST_NOTE_REL = Path("Test") / "Alpha-HumanFlows.md"


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


def _existing_mirror_uuid(vault_root: Path, rel_path: Path) -> str:
    mirror_dir = vault_root / Path("System/Metadata/VaultMirror") / rel_path.parent
    if not mirror_dir.exists():
        return ""
    for cand in sorted(mirror_dir.glob("*.md")):
        try:
            fm, _ = load_frontmatter(cand.read_text(encoding="utf-8"))
            existing = str(fm.get("uuid") or fm.get("id") or "").strip()
            source_ref = str(fm.get("source_ref") or "").strip()
            if existing and source_ref == str(rel_path):
                return existing
        except Exception:
            continue
    return ""


def _write_mirror(vault_root: Path, rel_path: Path, *, note_uuid: str, title: str, review_state: str, maturity: str) -> Path:
    mirror_path = vault_root / note_log_path(note_uuid, rel_path)
    mirror_path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "uuid": note_uuid,
        "title": title,
        "kind": "note",
        "origin": "vault",
        "source_ref": str(rel_path),
        "review_state": review_state,
        "maturity": maturity,
    }
    body = f"Mirror for {rel_path}"
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


def _ingest_single(path: Path, *, vault_root: Path, trace_id: str) -> str:
    rel_path = path.relative_to(vault_root)
    raw_text = path.read_text(encoding="utf-8")
    frontmatter, body = load_frontmatter(raw_text)
    note_uuid = str(frontmatter.get("uuid") or frontmatter.get("id") or "").strip()
    if not note_uuid:
        note_uuid = _existing_mirror_uuid(vault_root, rel_path) or str(uuid.uuid4())
    title = str(frontmatter.get("title") or _derive_title(body, path))
    review_state = str(frontmatter.get("review_state") or "provisional")
    maturity = str(frontmatter.get("maturity") or "note")
    stripped_body = strip_ai_panels(body)
    stripped_text = stripped_body.strip()

    mirror_path = vault_root / note_log_path(note_uuid, rel_path)
    if not mirror_path.exists():
        _write_mirror(vault_root, rel_path, note_uuid=note_uuid, title=title, review_state=review_state, maturity=maturity)

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
    }

    # Persist into the classic ObjectStore for classifier compatibility
    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload=payload,
        source_ref=str(path),
        created_at=datetime.now(timezone.utc),
    )
    ObjectStore().save_object(obj, emit_outbox=False, trace_id=trace_id)

    try:
        classify_res = classify_run(note_uuid, trace_id=trace_id)
    except Exception:
        classify_res = {}

    try:
        object_uuid = uuid.UUID(note_uuid)
    except Exception:
        object_uuid = uuid.uuid4()

    try:
        get_object_store().put(object_uuid, kind="note", source_ref=str(path), payload={"title": title, "origin": "vault", "source": str(path), "text": stripped_text})
    except Exception:
        pass

    try:
        get_store().add_document(doc_id=str(object_uuid), text=stripped_text, source_ref=str(path))
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


def run_vault_alpha_ingest(vault_root: Path, *, max_notes: int = 200, include_test_note: bool = False) -> VaultAlphaSummary:
    vault_root = vault_root.expanduser().resolve()
    candidates, included_folders = _select_candidates(vault_root, include_test_note=include_test_note, max_notes=max_notes)
    ingested = 0
    for path in candidates:
        try:
            trace_id = with_trace_id(None)
            _ingest_single(path, vault_root=vault_root, trace_id=trace_id)
            ingested += 1
        except Exception:
            continue
    return VaultAlphaSummary(scanned=len(candidates), ingested=ingested, included_folders=included_folders)


__all__ = ["run_vault_alpha_ingest", "VaultAlphaSummary"]
