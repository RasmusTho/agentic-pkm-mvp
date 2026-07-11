"""Pure renderer for the read-only Daily Briefing day-start card."""

from __future__ import annotations

import html
from typing import Any, Mapping
from urllib.parse import quote, urlsplit

from companion_ui.workspace.briefing_listen import render_briefing_listen_affordance


def render_day_start_card_html(
    briefing: Mapping[str, Any] | None,
    *,
    tts_available: bool = False,
    tts_unavailable_reason: str | None = None,
) -> str:
    data = dict(briefing or {})
    state = str(data.get("state") or "unreadable")
    if state not in {"pending", "unreadable", "degraded", "full"}:
        state = "unreadable"
    date_label = html.escape(str(data.get("date") or "Today"))

    if state == "pending":
        content = (
            '<p data-testid="day-start-pending">Today\'s briefing isn\'t ready yet.</p>'
            '<p class="day-start-note">It will appear here after today\'s generation runs.</p>'
        )
    elif state == "unreadable":
        content = (
            '<p data-testid="day-start-unreadable">Today\'s briefing exists but cannot be read.</p>'
            '<p class="day-start-note">No older briefing is being shown in its place.</p>'
        )
    else:
        preview = html.escape(str(data.get("preview") or "Your briefing is ready."))
        sections = _render_sections(data.get("sections"))
        degraded = _render_degraded(data) if state == "degraded" else ""
        speech_text = _speech_text(data)
        listen = render_briefing_listen_affordance(
            briefing_text=speech_text,
            tts_available=tts_available,
            unavailable_reason=tts_unavailable_reason,
        )
        content = (
            f'<p class="day-start-preview" data-testid="day-start-preview">{preview}</p>'
            f"{degraded}"
            '<details data-testid="day-start-read" class="day-start-read">'
            '<summary>Read briefing</summary>'
            f'<div class="day-start-full">{sections}</div></details>'
            f"{listen}"
        )

    return (
        '<section class="day-start-card" data-testid="day-start-card" '
        f'data-briefing-state="{state}" data-authority="read-only-projection" '
        'data-read-only="true" aria-label="Today\'s briefing">'
        '<header><span class="day-start-kicker">Daily briefing</span>'
        f'<time>{date_label}</time></header>{content}</section>'
    )


def _render_degraded(data: Mapping[str, Any]) -> str:
    names = [html.escape(str(name).replace("_", " ")) for name in data.get("degraded_sections", [])]
    label = ", ".join(names) or "a named section"
    return (
        '<p class="day-start-degraded" data-testid="day-start-degraded">'
        f"Degraded today: {label} unavailable.</p>"
    )


def _render_sections(raw_sections: Any) -> str:
    if not isinstance(raw_sections, list):
        return ""
    return "".join(_render_section(section) for section in raw_sections if isinstance(section, Mapping))


def _render_section(section: Mapping[str, Any]) -> str:
    name = html.escape(str(section.get("name") or "section").replace("_", " ").title())
    status = str(section.get("status") or "degraded")
    if status == "degraded":
        reason = html.escape(str(section.get("reason") or "unavailable today"))
        body = f'<p class="day-start-section-degraded">Unavailable today: {reason}</p>'
    else:
        raw_items = section.get("items")
        items = raw_items if isinstance(raw_items, list) else []
        body = "<ul>" + "".join(_render_item(item) for item in items if isinstance(item, Mapping)) + "</ul>"
    return f'<section class="day-start-section" data-section-status="{html.escape(status)}"><h3>{name}</h3>{body}</section>'


def _render_item(item: Mapping[str, Any]) -> str:
    label = next(
        (str(item[key]) for key in ("summary", "title", "key", "object_id") if item.get(key)),
        "Briefing item",
    )
    provenance: list[str] = []
    for key in ("artifact_path", "target_ref", "receipt_path"):
        value = item.get(key)
        if isinstance(value, str) and value:
            provenance.append(_render_ref(value))
    surfaced = item.get("surfaced_refs")
    if isinstance(surfaced, (list, tuple)):
        for ref in surfaced:
            if isinstance(ref, Mapping) and isinstance(ref.get("ref"), str):
                provenance.append(_render_ref(str(ref["ref"])))
    provenance_html = " · ".join(provenance) or "source recorded in briefing"
    return f'<li><span>{html.escape(label)}</span><small class="day-start-provenance">Source: {provenance_html}</small></li>'


def _render_ref(target: str) -> str:
    cleaned = target.strip().replace("\\", "/")
    try:
        parsed = urlsplit(cleaned)
    except ValueError:
        parsed = None
    safe = parsed is not None and (
        (not parsed.scheme and not parsed.netloc and not cleaned.startswith("/"))
        or parsed.scheme.lower() in {"http", "https"}
    )
    label = html.escape(target)
    if not safe:
        return f'<span data-blocked-ref="true">{label}</span>'
    if parsed is not None and parsed.scheme.lower() in {"http", "https"}:
        href = quote(target, safe="/:#?=&%")
    else:
        href = "/?note_path=" + quote(target, safe="")
    return f'<a href="{html.escape(href, quote=True)}">{label}</a>'


def _speech_text(data: Mapping[str, Any]) -> str:
    lines = [str(data.get("preview") or "Daily briefing")]
    for section in data.get("sections", []):
        if not isinstance(section, Mapping):
            continue
        lines.append(str(section.get("name") or "section").replace("_", " "))
        if section.get("status") == "degraded":
            lines.append("unavailable today")
            continue
        for item in section.get("items", []):
            if isinstance(item, Mapping):
                for key in ("summary", "title", "key", "object_id"):
                    if item.get(key):
                        lines.append(str(item[key]))
                        break
    return "\n".join(lines)


__all__ = ["render_day_start_card_html"]
