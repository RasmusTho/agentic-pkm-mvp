from __future__ import annotations

import click
from pathlib import Path

from app.ingest.vault_alpha import run_vault_alpha_ingest_paths
from app.cli.panel import run_panels_for_uuids
from app.watcher.vault_watcher import VaultWatcher
from app.store.object_store import ObjectStore
from app.agents.panel_agent.policy import watcher_may_run_panel
from scripts.yaml_roundtrip import load_frontmatter


def _echo_summary(summary: dict) -> None:
    click.echo(
        "Watcher summary: "
        f"changed={summary['changed']} "
        f"ingest_attempted={summary['ingest_attempted']} ingested={summary['ingested']} "
        f"panel_candidates={summary['panel_candidates']} panel_runs={summary['panel_runs']} "
        f"panel_promotions={summary['panel_promotions']} "
        f"skipped_policy={summary['panel_skipped_policy']} skipped_limit={summary['panel_skipped_limit']} "
        f"errors={summary['errors']} dry_run={summary['dry_run']} limit_exceeded={summary['limit_exceeded']}"
    )


def _read_frontmatter(note_path: Path) -> dict:
    try:
        frontmatter, _ = load_frontmatter(note_path.read_text(encoding="utf-8"))
        if not isinstance(frontmatter, dict):
            return {}
        return frontmatter
    except Exception:
        return {}


def _note_uuid_from_frontmatter(frontmatter: dict) -> str | None:
    raw = frontmatter.get("uuid") or ""
    if isinstance(raw, str):
        value = raw.strip()
    else:
        value = str(raw).strip()
    if value.startswith("[[") and value.endswith("]]"):
        value = value[2:-2].strip()
    return value or None


def _hydrate_store_with_markdown(note_uuid: str, note_path: Path) -> None:
    try:
        markdown = note_path.read_text(encoding="utf-8")
    except Exception:
        return
    store = ObjectStore()
    obj = store.get_object(note_uuid)
    if obj is None:
        return
    payload = dict(obj.payload or {})
    payload["raw_text"] = markdown
    obj.payload = payload
    store.save_object(obj, emit_outbox=False, trace_id=None)


@click.command(
    name="vault-watcher-run",
    help="Single-shot vault watcher: detects changed notes via snapshot, ingests them, and optionally runs PanelAgent runtime.",
)
@click.option(
    "--vault-root",
    type=click.Path(path_type=Path),
    default=None,
    help="Vault root (defaults to VAULT_ROOT or DEFAULT_VAULT_ROOT).",
)
@click.option(
    "--snapshot-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Snapshot file path (stores path→mtime). Defaults to <vault>/.agentic-pkm/vault_watcher_state.json.",
)
@click.option("--skip-panel", is_flag=True, help="Skip running PanelAgent runtime.")
@click.option(
    "--emit-only",
    is_flag=True,
    help="Only emit panel.intent.created for panels (skip runtime) when panel runs are enabled.",
)
@click.option("--dry-run", is_flag=True, help="Preview changed notes without running ingest or panel runtime.")
@click.option(
    "--max-notes",
    type=int,
    default=50,
    show_default=True,
    help="Maximum number of changed notes to process; if exceeded, watcher aborts unless --force is set.",
)
@click.option("--force", is_flag=True, help="Override max-notes safety guard.")
def vault_watcher_run(
    vault_root: Path | None,
    snapshot_path: Path | None,
    skip_panel: bool,
    emit_only: bool,
    dry_run: bool,
    max_notes: int,
    force: bool,
) -> None:
    from app.cli import _resolve_vault_root_path

    resolved = _resolve_vault_root_path(vault_root, allow_env=True, fallback_to_default=True)
    if resolved is None:
        raise click.BadParameter("Vault root could not be resolved.")
    if not resolved.exists() or not resolved.is_dir():
        raise click.BadParameter(f"Vault root not found or not a directory: {resolved}")

    watcher = VaultWatcher(resolved, snapshot_path=snapshot_path)
    result = watcher.run(save=False)

    summary = {
        "changed": len(result.changed),
        "ingest_attempted": 0,
        "ingested": 0,
        "panel_candidates": 0,
        "panel_runs": 0,
        "panel_promotions": 0,
        "panel_skipped_policy": 0,
        "panel_skipped_limit": 0,
        "errors": 0,
        "dry_run": dry_run,
        "limit_exceeded": False,
    }

    policy_allowed_paths: list[Path] = []
    for path in result.changed:
        frontmatter = _read_frontmatter(path)
        note_uuid = _note_uuid_from_frontmatter(frontmatter)
        if watcher_may_run_panel(frontmatter):
            policy_allowed_paths.append(path)
        else:
            summary["panel_skipped_policy"] += 1

    summary["panel_candidates"] = len(policy_allowed_paths)

    if summary["changed"] == 0:
        _echo_summary(summary)
        if not dry_run:
            watcher.refresh_snapshot()
        return

    if not force and summary["changed"] > max_notes:
        summary["limit_exceeded"] = True
        summary["panel_skipped_limit"] = summary["changed"]
        click.echo(
            f"Changed notes ({summary['changed']}) exceed max-notes={max_notes}; aborting watcher run. "
            "Use --force to override."
        )
        _echo_summary(summary)
        raise SystemExit(1)

    if dry_run:
        _echo_summary(summary)
        return

    summary["ingest_attempted"] = summary["changed"]
    ingest_summary = run_vault_alpha_ingest_paths(resolved, result.changed, force=False)
    summary["ingested"] = ingest_summary.ingested
    summary["errors"] += ingest_summary.errors

    if not skip_panel and policy_allowed_paths:
        panel_targets: list[str] = []
        for note_path in policy_allowed_paths:
            refreshed_frontmatter = _read_frontmatter(note_path)
            note_uuid = _note_uuid_from_frontmatter(refreshed_frontmatter)
            if not note_uuid:
                click.echo(f"Warning: unable to resolve uuid for {note_path}; skipping panel run.", err=True)
                summary["errors"] += 1
                continue
            _hydrate_store_with_markdown(note_uuid, note_path)
            panel_targets.append(note_uuid)
        processed, with_panels, promotions, errors, messages = run_panels_for_uuids(
            tuple(panel_targets), emit_only=emit_only
        )
        for msg in messages:
            click.echo(msg, err=True)
        summary["panel_runs"] = with_panels
        summary["panel_promotions"] = promotions
        summary["errors"] += errors
    else:
        click.echo("Panel runtime skipped (no candidates or --skip-panel set).")

    _echo_summary(summary)

    # refresh snapshot after mutations (ingest/panel may update mtimes/frontmatter)
    watcher.refresh_snapshot()

    if summary["errors"] > 0:
        raise SystemExit(1)


__all__ = ["vault_watcher_run"]
