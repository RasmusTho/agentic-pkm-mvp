"""Read-only CLI adapter for explicitly supplied rebuildability snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import click

from app.rebuildability.mirror_doctor import (
    DurablePath,
    DurablePathClass,
    ProjectionRecord,
    SourceRecord,
    diagnose_mirror_corruption,
)


def _items(payload: Mapping[str, Any], key: str) -> Iterable[Mapping[str, Any]]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise click.ClickException(f"snapshot field {key!r} must be a list of objects")
    return value


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _flag(value: object) -> bool:
    return value is True


def _load_snapshot(path: Path):
    """Parse one explicit operator-selected snapshot without discovering any state."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise click.ClickException("rebuildability snapshot is unreadable") from exc
    if not isinstance(payload, Mapping):
        raise click.ClickException("rebuildability snapshot must be an object")
    inventory = [
        DurablePath(
            path=_text(item.get("path")) or "",
            classification=(
                DurablePathClass(value)
                if (value := _text(item.get("classification"))) is not None
                else None
            ),
            owner=_text(item.get("owner")),
            rebuild_or_retention_source=_text(item.get("rebuild_or_retention_source")),
            sole_meaning_authority=_flag(item.get("sole_meaning_authority")),
            sole_action_authority=_flag(item.get("sole_action_authority")),
        )
        for item in _items(payload, "inventory")
    ]
    sources = [
        SourceRecord(
            identity=_text(item.get("identity")) or "",
            generation=_text(item.get("generation")) or "",
        )
        for item in _items(payload, "sources")
    ]
    projections = [
        ProjectionRecord(
            projection_id=_text(item.get("projection_id")) or "",
            source_identity=_text(item.get("source_identity")),
            source_generation=_text(item.get("source_generation")),
            recipe_version=_text(item.get("recipe_version")),
            index_identity=_text(item.get("index_identity")),
            expected_index_identity=_text(item.get("expected_index_identity")),
            db_source_generation=_text(item.get("db_source_generation")),
            sole_meaning_authority=_flag(item.get("sole_meaning_authority")),
            sole_action_authority=_flag(item.get("sole_action_authority")),
        )
        for item in _items(payload, "projections")
    ]
    return inventory, sources, projections


@click.command(
    name="rebuildability-doctor",
    help="Diagnose one explicitly supplied rebuildability snapshot without mutation or discovery.",
)
@click.option(
    "--snapshot",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Explicit JSON snapshot from owner-native readers; never scanned or repaired by this command.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit the redacted machine-readable report.")
@click.option("--strict", is_flag=True, help="Exit 2 when the snapshot has typed findings.")
def rebuildability_doctor(snapshot: Path, as_json: bool, strict: bool) -> None:
    """Render a digest-only report from a caller-selected, read-only snapshot."""

    inventory, sources, projections = _load_snapshot(snapshot)
    report = diagnose_mirror_corruption(
        inventory=inventory,
        sources=sources,
        projections=projections,
    )
    if as_json:
        click.echo(json.dumps(report.as_dict(), sort_keys=True))
    else:
        click.echo("healthy" if report.healthy else "findings: " + ", ".join(
            finding.code.value for finding in report.findings
        ))
    if strict and not report.healthy:
        raise click.exceptions.Exit(2)


__all__ = ["rebuildability_doctor"]
