"""``youtube-sources`` CLI group (YSS-10 source-list portion, #6611).

``python -m app.cli youtube-sources list [--json]`` is a thin read-only
projection over :meth:`SourceRegistry.list_all`
(``app/knowledge_acquisition/source_registry.py``), opened through
:meth:`SourceRegistry.for_runtime_read_only` so it never bootstraps schema.
It never writes the registry and never calls a provider.

Output is secret-free by construction (INV-YSS-5): only the allowlisted
fields below are projected. ``account_binding_id``, ``collection_ref``,
``cursor``, ``provenance`` and the stored ``last_error.detail`` are never
emitted, a stored ``last_error`` is reduced to a known reason code plus its
timestamp, and a ``title`` containing any listed binding's collection ref or
account binding id (see :func:`_safe_title`) is reported as null. Titles are
written through ``json.dumps`` in both modes, so control characters are
escaped rather than emitted raw.
Backend failures report a fixed reason code, never the exception text (which
can carry DSN or driver detail).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

import click

# Every reason code a production writer stores in ``last_error``:
# ``playlist_discovery.SAFE_REASON_CODES`` (also the youtube_oauth degradation
# codes) plus the subscription-feed codes from ``channel_rss_discovery``. Any
# other stored value is withheld as null, never echoed.
KNOWN_LAST_ERROR_REASON_CODES: frozenset[str] = frozenset(
    {
        "auth_missing",
        "auth_key_missing",
        "auth_expired",
        "auth_revoked",
        "auth_disconnected",
        "quota_exhausted",
        "api_unavailable",
        "network_error",
        "source_gone",
        "policy_unsupported",
        "policy_conflict",
        "paused_source",
        "inbox_missing",
        "source_mismatch",
        "rss_feed_unavailable",
        "rss_feed_too_large",
        "rss_feed_invalid",
        "filter_metadata_unavailable",
    }
)


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

    ``detail`` is arbitrary caller data and is always dropped. The registry
    accepts any non-empty ``reason_code``, so one outside
    :data:`KNOWN_LAST_ERROR_REASON_CODES` is reported as ``null`` rather than
    echoed; the presence of an error stays visible without its content.
    """

    if not isinstance(error, Mapping):
        return None
    code = error.get("reason_code")
    safe_code = code if isinstance(code, str) and code in KNOWN_LAST_ERROR_REASON_CODES else None
    return {"reason_code": safe_code, "at": _safe_timestamp(error.get("at"))}


def _policy_mode(policy: Any) -> str | None:
    if isinstance(policy, Mapping):
        mode = policy.get("mode")
        if isinstance(mode, str):
            return mode
    return None


# Refs shorter than this (Liked videos is ``LL``) match case-sensitively so a
# title such as "All music" is not withheld for containing "ll".
_CASEFOLD_MIN_REF_LENGTH = 4


def _identifier_forms(bindings: Sequence[Any]) -> tuple[frozenset[str], frozenset[str]]:
    """Every actual identifier in the listing: (case-sensitive, casefolded) forms."""

    exact: set[str] = set()
    folded: set[str] = set()
    for binding in bindings:
        ref = binding.collection_ref
        if isinstance(ref, str) and ref.strip():
            ref = ref.strip()
            if len(ref) < _CASEFOLD_MIN_REF_LENGTH:
                exact.add(ref)
            else:
                folded.add(ref.casefold())
        account = binding.account_binding_id
        if isinstance(account, str) and account.strip():
            account = account.strip().casefold()
            folded.update({account, account.replace("-", "")})
    return frozenset(exact), frozenset(folded)


def _safe_title(title: Any, identifiers: tuple[frozenset[str], frozenset[str]]) -> str | None:
    """Project the display title, or ``null`` when it contains a listed identifier.

    ``title`` is display text (the Takeout importer even falls back to the raw
    channel/playlist id). It is withheld whole -- never partially redacted --
    when any listed binding's ``collection_ref`` or ``account_binding_id``
    occurs anywhere in it (plain substring, no token boundary). This filters
    only those known literal values; it is not a general secret detector, and
    any other title is shown as stored.
    """

    if not isinstance(title, str) or not title.strip():
        return None
    exact, folded = identifiers
    lowered = title.casefold()
    if (
        any(value in title for value in exact)
        or any(value in lowered for value in folded)
    ):
        return None
    return title


def _project_binding(binding: Any, identifiers: tuple[frozenset[str], frozenset[str]]) -> dict[str, Any]:
    return {
        "binding_id": binding.binding_id,
        "kind": binding.collection_kind,
        "title": _safe_title(binding.title, identifiers),
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
        f"{json.dumps(row['title'], ensure_ascii=False) if row['title'] is not None else '(untitled)'}"
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
        bindings = SourceRegistry.for_runtime_read_only().list_all()
        identifiers = _identifier_forms(bindings)
        rows = [_project_binding(binding, identifiers) for binding in bindings]
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
