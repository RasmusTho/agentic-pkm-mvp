from __future__ import annotations

import textwrap
import uuid
from pathlib import Path
from typing import Iterable, List, Tuple

import click

from app.agents.classifier.agent import run as classify_run
from app.agents.normalizer.agent import run as normalize_run
from app.agents.qa.agent import answer as qa_answer
from app.agents.panel.filters import strip_ai_panels
from app.ingest.config import DEFAULT_VAULT_ROOT
from app.index.outbox import append_jsonl
from app.knowledge.write_ops import write_note_from_absolute
from app.obs.log import with_trace_id
from app.retrieval.hybrid import get_store
from app.search.service import ingest_object as index_ingest_object
from app.services.companion_note import companion_path
from app.stores import get_object_store
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter

ALPHA_TEST_NOTE_REL = Path("Test") / "Alpha-HumanFlows.md"
# TODO: Panels should be excluded from retrieval/QA indexing; alpha-human-flows only smoke-tests ingestion today.
AI_PANEL_BLOCK = "\n".join(
    [
        "%% AI:Start %%",
        "## AI-instruktion",
        "Fact check: The Earth has two moons.",
        "",
        "## AI-åtgärder",
        "- [ ] Mark this fact as incorrect",
        "",
        "## AI-logg",
        "- Panel inserted by alpha-human-flows",
        "%% AI:End %%",
        "",
    ]
)


def _write_vault_note(vault_root: Path, path: Path, content: str) -> None:
    write_note_from_absolute(path, content, vault_root=vault_root)


def _select_sample_files(vault_root: Path, sample_size: int) -> List[Path]:
    preferred = [
        "Index",
        "Projects",
        "Corpus",
        "Workspace",
        "Domains",
        "Sources",
        "Ontology",
        "Canon",
        "Archive",
        "Ingress",
    ]
    candidates: List[Path] = []
    for name in preferred:
        root = vault_root / name
        if root.exists() and root.is_dir():
            files = sorted(root.rglob("*.md"))
            first = files[0] if files else None
            if first:
                candidates.append(first)
                if len(candidates) >= sample_size:
                    return candidates[:sample_size]
    if len(candidates) < sample_size:
        root_level = sorted(p for p in vault_root.glob("*.md") if p.is_file())
        for path in root_level:
            if path not in candidates:
                candidates.append(path)
            if len(candidates) >= sample_size:
                break
    return candidates[:sample_size]


def _ingest_note(path: Path) -> Tuple[str, dict | None]:
    trace_id = with_trace_id(None)
    text = path.read_text(encoding="utf-8")
    stripped_text = strip_ai_panels(text)
    normalize_res = normalize_run(str(path), trace_id=trace_id)
    sanitize_normalize = dict(normalize_res)
    payload_copy = dict(normalize_res.get("payload") or {})
    if "raw_text" in payload_copy:
        payload_copy["raw_text"] = stripped_text
    payload_copy.setdefault("text", stripped_text)
    sanitize_normalize["payload"] = payload_copy
    object_id = str(normalize_res.get("object_id") or normalize_res.get("uuid") or "").strip()
    if not object_id:
        raise RuntimeError("normalize did not return object_id")
    classify_res = classify_run(object_id, trace_id=trace_id)
    append_jsonl(
        {
            "object_id": object_id,
            "kind": "pipeline",
            "source_ref": str(path),
            "payload": {"normalize": sanitize_normalize, "classify": classify_res},
        }
    )
    try:
        object_uuid = uuid.UUID(object_id)
    except Exception:
        object_uuid = uuid.uuid4()
    title = (normalize_res.get("core6") or {}).get("title")
    payload = {"title": title, "origin": "vault", "source": str(path)}
    try:
        index_ingest_object(
            object_id=object_uuid,
            kind="note",
            source_ref=str(path),
            payload=payload,
            text=stripped_text,
        )
    except Exception:
        pass
    store_payload = {**payload, "text": stripped_text}
    try:
        store = get_object_store()
        store.put(object_uuid, kind="note", source_ref=str(path), payload=store_payload)
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
    classification = classify_res.get("classification") if isinstance(classify_res, dict) else None
    return object_id, classification


def _ensure_test_note(path: Path, *, vault_root: Path, dry_run: bool) -> Tuple[str, bool]:
    if path.exists():
        frontmatter, body = load_frontmatter(path.read_text(encoding="utf-8"))
        existing_uuid = str(frontmatter.get("uuid") or "").strip()
        if existing_uuid:
            return existing_uuid, False
        new_uuid = str(uuid.uuid4())
        if not dry_run:
            frontmatter["uuid"] = new_uuid
            _write_vault_note(vault_root, path, dump_frontmatter(frontmatter, body))
        return new_uuid, not dry_run
    new_uuid = str(uuid.uuid4())
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        body_lines = [
            "Alpha Human Flows test note for orchestration.",
            "",
            AI_PANEL_BLOCK.rstrip(),
            "",
        ]
        body = "\n".join(body_lines)
        frontmatter = {"uuid": new_uuid, "title": path.stem}
        _write_vault_note(vault_root, path, dump_frontmatter(frontmatter, body))
    return new_uuid, not dry_run


def _ensure_ai_panel(path: Path, *, vault_root: Path, dry_run: bool) -> bool:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if "## AI-instruktion" in text:
        return False
    if dry_run:
        return True
    updated = text.rstrip() + ("\n\n" if text and not text.endswith("\n") else "") + AI_PANEL_BLOCK
    _write_vault_note(vault_root, path, updated)
    return True


def _set_promotion_fields(path: Path, *, vault_root: Path, dry_run: bool) -> bool:
    frontmatter, body = load_frontmatter(path.read_text(encoding="utf-8"))
    changed = False
    if frontmatter.get("review_state") != "promoted":
        frontmatter["review_state"] = "promoted"
        changed = True
    if frontmatter.get("maturity") != "evergreen":
        frontmatter["maturity"] = "evergreen"
        changed = True
    if changed and not dry_run:
        _write_vault_note(vault_root, path, dump_frontmatter(frontmatter, body))
    return changed


def _run_ask_queries(queries: Iterable[str]) -> List[Tuple[str, dict]]:
    results: List[Tuple[str, dict]] = []
    for query in queries:
        try:
            ans = qa_answer(query)
        except Exception as exc:  # pragma: no cover - defensive
            ans = {"answer": f"error: {exc}", "sources": []}
        results.append((query, ans if isinstance(ans, dict) else {}))
    return results


def _format_sources(sources: list | None, vault_root: Path) -> List[str]:
    if not sources:
        return []
    lines: List[str] = []
    for src in sources:
        if not isinstance(src, dict):
            continue
        path_text = src.get("source_ref") or src.get("source") or ""
        if path_text:
            try:
                p = Path(path_text)
                if p.is_absolute() and vault_root in p.parents:
                    path_text = str(p.relative_to(vault_root))
            except Exception:
                pass
        doc_id = src.get("doc_id") or src.get("id") or "-"
        lines.append(f"{path_text or '-'} [uuid:{doc_id}]")
    return lines


def _render_checklist(sample_size: int) -> str:
    lines = [
        f"[ ] A: Sample ingest of up to {sample_size} notes (normalize + classify + index)",
        "[ ] B: Ensure Test/Alpha-HumanFlows.md exists with UUID frontmatter",
        "[ ] C: Run pipeline on test note and report companion note path",
        "[ ] D: Add AI panel with wrong fact and re-run ingest",
        "[ ] E: Mark test note as promoted/evergreen and re-run ingest",
        "[ ] F: Run ASK queries and show answers + sources",
    ]
    return "\n".join(lines)


def run_alpha_human_flows(
    vault_root: Path,
    *,
    dry_run: bool,
    sample_size: int,
    explain_only: bool = False,
    reset_outbox: bool = False,
) -> None:
    """
    Orchestrates alpha human flows end-to-end:
    Flow A ingest sample notes, Flow B ensure Test/Alpha-HumanFlows.md exists,
    Flow C ingest + report mirror path, Flow D add AI panel and reingest,
    Flow E set promoted/evergreen frontmatter and reingest, Flow F run ASK queries.
    """
    if explain_only:
        click.echo(_render_checklist(sample_size))
        return
    vault_root = vault_root.expanduser()
    if not vault_root.exists() or not vault_root.is_dir():
        raise click.BadParameter(f"Vault root not found or not a directory: {vault_root}")

    if reset_outbox and not dry_run:
        from app.index.outbox import DEFAULT_OUTBOX_PATH
        import os

        outbox_path = Path(os.environ.get("INDEX_OUTBOX_PATH", str(DEFAULT_OUTBOX_PATH))).expanduser()
        outbox_path.parent.mkdir(parents=True, exist_ok=True)
        outbox_path.write_text("", encoding="utf-8")
        click.echo(f"reset outbox: {outbox_path}")

    click.echo(f"Vault root: {vault_root}")

    click.echo("1) Flow A – sample ingest")
    samples = _select_sample_files(vault_root, sample_size)
    if not samples:
        click.echo("   no sample files found")
    for path in samples:
        if dry_run:
            click.echo(f"   [dry-run] would ingest {path}")
            continue
        try:
            object_id, _ = _ingest_note(path)
            click.echo(f"   ingested {path} (object_id={object_id})")
        except Exception as exc:  # pragma: no cover - defensive
            click.echo(f"   error ingesting {path}: {exc}")

    click.echo("2) Flow B – ensure test note")
    test_note_path = vault_root / ALPHA_TEST_NOTE_REL
    test_uuid, created = _ensure_test_note(test_note_path, vault_root=vault_root, dry_run=dry_run)
    status = "created" if created and not dry_run else "existing"
    click.echo(f"   test note: {test_note_path} ({status}, uuid={test_uuid})")

    click.echo("3) Flow C – ingest test note and locate companion")
    vault_rel = test_note_path.relative_to(vault_root)
    companion_note_path = companion_path(test_uuid)
    click.echo(f"   vault path: {vault_rel}")
    if dry_run:
        click.echo("   [dry-run] skipping ingestion")
        click.echo(f"   companion path would be: {companion_note_path}")
    else:
        try:
            _, classification = _ingest_note(test_note_path)
            click.echo(f"   ingested test note, companion path: {companion_note_path}")
            if classification:
                click.echo(f"   classification: {classification}")
            else:
                click.echo("   classification: not available")
        except Exception as exc:  # pragma: no cover - defensive
            click.echo(f"   error ingesting test note: {exc}")

    click.echo("4) Flow D – ensure AI panel and reingest")
    panel_needed = _ensure_ai_panel(test_note_path, vault_root=vault_root, dry_run=dry_run)
    if panel_needed:
        click.echo("   AI panel inserted" + (" [dry-run]" if dry_run else ""))
    else:
        click.echo("   AI panel already present")
    if not dry_run:
        try:
            _, panel_class = _ingest_note(test_note_path)
            preserved = "## AI-instruktion" in test_note_path.read_text(encoding="utf-8")
            click.echo(
                f"   reingest after panel: ok (preserved={preserved}, classification={'ok' if panel_class else 'n/a'})"
            )
            click.echo("   Panel warning: manually verify ASK answers are not contaminated by panel text.")
        except Exception as exc:  # pragma: no cover - defensive
            click.echo(f"   reingest failed: {exc}")
    else:
        click.echo("   [dry-run] reingest skipped")

    click.echo("5) Flow E – promote/evergreen and reingest")
    if not test_note_path.exists() and dry_run:
        click.echo("   [dry-run] test note not written; skipping promotion changes")
    else:
        promo_changed = _set_promotion_fields(test_note_path, vault_root=vault_root, dry_run=dry_run)
        if promo_changed:
            click.echo("   promotion fields set" + (" [dry-run]" if dry_run else ""))
        else:
            click.echo("   promotion fields already set")
    if not dry_run:
        try:
            _ingest_note(test_note_path)
            click.echo(f"   reingest after promotion: ok (mirror: {mirror_path})")
        except Exception as exc:  # pragma: no cover - defensive
            click.echo(f"   reingest failed: {exc}")
    else:
        click.echo("   [dry-run] reingest skipped")

    click.echo("6) Flow F – ASK queries")
    queries = [
        "What does the Alpha Human Flows test note say?",
        "Explain briefly how Active / Warm / Cold zones work in my system.",
    ]
    if dry_run:
        for query in queries:
            click.echo(f"   [dry-run] ASK: \"{query}\" (skipped)")
    else:
        results = _run_ask_queries(queries)
        for query, result in results:
            answer_text = result.get("answer") or result.get("response") or ""
            sources = result.get("sources") or []
            click.echo(f"   ASK: \"{query}\"")
            click.echo(f"     ANSWER: {textwrap.shorten(str(answer_text), width=220, placeholder='...')}")
            formatted = _format_sources(sources, vault_root)
            if formatted:
                click.echo("     SOURCES:")
                for entry in formatted:
                    click.echo(f"       - {entry}")
            else:
                click.echo("     SOURCES: none")
