"""``youtube-sources`` CLI group (YSS-10 source-list portion, #6611).

``python -m app.cli youtube-sources list [--json]`` is a thin read-only
projection over :meth:`SourceRegistry.list_all`
(``app/knowledge_acquisition/source_registry.py``). It never writes the
registry and never calls a provider.

Output is secret-free by construction (INV-YSS-5): only the allowlisted
fields below are projected. ``account_binding_id``, ``collection_ref``,
``cursor``, ``provenance`` and the stored ``last_error.detail`` are never
emitted, and a stored ``last_error`` is reduced to a well-formed reason code
plus its timestamp. Backend failures report a fixed reason code, never the
exception text (which can carry DSN or driver detail).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import click

_REASON_CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


def _safe_timestamp(value: Any) -> str | None:
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).isoformat()
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return text


def _safe_last_error(error: Any) -> dict[str, str | None] | None:
    """Reduce a stored ``{reason_code, detail, at}`` to a safe reason code and time.

    ``detail`` is arbitrary caller data and is always dropped. A reason code
    that is not a plain snake_case token is reported as ``null`` rather than
    echoed, so the presence of an error stays visible without its content.
    """

    if not isinstance(error, Mapping):
        return None
    code = error.get("reason_code")
    safe_code = code if isinstance(code, str) and _REASON_CODE_RE.match(code) else None
    return {"reason_code": safe_code, "at": _safe_timestamp(error.get("at"))}


def _policy_mode(policy: Any) -> str | None:
    if isinstance(policy, Mapping):
        mode = policy.get("mode")
        if isinstance(mode, str):
            return mode
    return None


def _project_binding(binding: Any) -> dict[str, Any]:
    return {
        "binding_id": binding.binding_id,
        "kind": binding.collection_kind,
        "title": binding.title,
        "enabled": binding.enabled,
        "interval_seconds": binding.poll_interval_seconds,
        "policy": _policy_mode(binding.acquisition_policy),
        "last_success_at": _safe_timestamp(binding.last_success_at),
        "last_error": _safe_last_error(binding.last_error),
    }


def _format_row(row: dict[str, Any]) -> str:
    error = row["last_error"]
    if error is None:
        error_text = "-"
    else:
        error_text = error["reason_code"] or "unreported"
    return (
        f"{row['binding_id']}  {row['kind']}  {'enabled' if row['enabled'] else 'disabled'}  "
        f"every {row['interval_seconds']}s  policy={row['policy'] or '-'}  "
        f"last_success={row['last_success_at'] or '-'}  last_error={error_text}  "
        f"{json.dumps(row['title'], ensure_ascii=False)}"
    )


@click.group(name="youtube-sources", help="Inspect YouTube source bindings.")
def youtube_sources() -> None:
    ...


@youtube_sources.command(name="list", help="List YouTube source bindings (read-only).")
@click.option("--json", "as_json", is_flag=True, help="Emit a JSON array.")
def list_sources(as_json: bool) -> None:
    from app.knowledge_acquisition.source_registry import (
        SourceRegistry,
        SourceRegistrySchemaMissingError,
    )

    try:
        bindings = SourceRegistry.for_runtime().list_all()
        rows = [_project_binding(binding) for binding in bindings]
    except Exception as exc:  # backend detail may carry DSN/driver text; never echo it
        reason = (
            "source_registry_schema_missing"
            if isinstance(exc, SourceRegistrySchemaMissingError)
            else "source_registry_unavailable"
        )
        if as_json:
            click.echo(json.dumps({"error": {"reason_code": reason}}), err=True)
        else:
            click.echo(f"youtube-sources list failed: reason_code={reason}", err=True)
        raise SystemExit(1) from None

    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False))
        return
    if not rows:
        click.echo("No YouTube source bindings.")
        return
    for row in rows:
        click.echo(_format_row(row))
