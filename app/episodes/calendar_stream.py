"""``calendar`` stream adapter (ERE-09, #3184).

Spec: ``docs/EPISODE_RESOLUTION_ENGINE/CALENDAR_STREAM_ADAPTER.md``. Read-only
CalDAV (iCloud, app-specific password) poller with an ICS-fallback shape,
registered in the stream registry (``docs/EPISODE_RESOLUTION_ENGINE/stream_registry.md``)
with transport ``module:app.episodes.calendar_stream``.

This module owns everything BEFORE normalization: private-bindings
credential/scope-mapping resolution, the CalDAV transport, and ICS/VEVENT
parsing. It deliberately does **not** import ``app.episodes.segmenter`` (that
would create a circular import: the segmenter's ingestion block imports this
module) and does **not** construct :class:`app.episodes.segmenter.SegmentationSignal`
-- the raw-row-to-``SegmentationSignal`` normalization step
(``_signal_from_calendar_row``) lives in ``segmenter.py`` itself, exactly
mirroring the existing ``_signal_from_heimdal_row`` /
``_signal_from_vault_activity_row`` precedent (Coordinator contract
clarification, #3184: "An additive ingestion block in ``run_segmentation_tick``
... mirroring the vault.activity block IS IN SCOPE").

**Credentials (Constraints, binding): private-bindings ONLY, never repo,
vault, or logs.** Resolution mirrors the Gemini embedding adapter's
env-var secret pattern (``app.llm.gemini_embeddings._resolve_api_key``): read
from environment variables that only the private-bindings constituent (C3,
`docs/architecture/ECOSYSTEM_STRUCTURE_PROPOSAL.md`) populates (gitignored
``.env*`` / host launchd job env -- never committed), and fail LOUD before
any network call if the registry says ``calendar`` is live but nothing is
configured (AC4). No secret value is ever placed in a log line or an
exception message -- only env-var *names* and calendar ids appear there.

**Fail-soft (AC5).** A per-calendar CalDAV fetch failure (network error,
non-2xx, malformed multistatus) raises :class:`CalendarUnreachableError`,
which :func:`read_calendar_raw_items_for_tick` catches per-binding and folds
into a returned ``degraded`` list -- one calendar's unreachability never
aborts another calendar's fetch, and (via the segmenter's ingestion block)
never fails the whole tick. This is a different failure class from
:class:`CalendarCredentialsError` (AC4, config missing): a missing
credential is a misconfiguration that must surface loud, not degrade softly.

**HEIM-6-honest attendee resolution, no register mutation (AC2, Scope).**
:func:`resolve_attendee_readonly` matches an attendee's surface form against
an already-loaded, READ-ONLY snapshot of the shared entity register
(:func:`read_register_snapshot`) and returns exactly one of
:class:`AttendeeResolved` / :class:`AttendeeAmbiguous` / :class:`AttendeeUnresolved`
-- never a bare string, never a silently-asserted canonical identity. Neither
function ever calls ``app.heimdal.entity_register`` (that module's own
``resolve()`` mints a durable provisional entity on a miss -- exactly the
mutation Scope forbids here) nor writes anything to the register directory;
an unresolved attendee gets a LOCAL, deterministic-but-non-durable id
(``cal:unresolved:<hash>``), never an ``ent:prov:`` id (that namespace means
"durably minted in the shared register" and this module mints nothing).
Heimdal itself is untouched by this task (Epic invariant).

**Per-calendar scope mapping (AC6, ERE-08).** Each resolved
:class:`CalendarBinding` carries its own ``scope`` (per-calendar, from
private-bindings config); the segmenter's ingestion block stamps every
signal derived from that calendar with ``binding.scope`` before folding, so
cross-scope discipline applies from the first signal via the ALREADY-SHIPPED
per-scope partitioning in ``fold_signals_into_segments`` -- no new
scope-isolation mechanism is needed here, only correct tagging.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Final, Mapping, Sequence

import yaml

from app.context_dimensions import ContextDimensions
from app.episodes.stream_registry import ConfidenceScore, SignalContract

logger = logging.getLogger(__name__)

CALENDAR_STREAM_ID: Final[str] = "calendar"

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CalendarCredentialsError(RuntimeError):
    """Registry says ``calendar`` is live but private-bindings config is not
    resolvable -- fail-loud (AC4), raised before any network call. Never
    carries a secret value, only env-var names / calendar ids."""


class CalendarUnreachableError(RuntimeError):
    """The calendar endpoint could not be reached this tick (network error,
    non-2xx, malformed response). Caught per-binding by
    :func:`read_calendar_raw_items_for_tick` and reported as ``degraded`` --
    never propagated out of a segmentation tick (AC5)."""


# ---------------------------------------------------------------------------
# Private-bindings credential / scope-mapping resolution (Constraints, AC4, AC6)
# ---------------------------------------------------------------------------

#: A private-bindings-owned JSON array of ``{calendar_id, base_url, username,
#: app_password, calendar_path, scope}`` objects -- the multi-calendar shape
#: (AC6: per-calendar scope mapping).
_ENV_CALENDARS_JSON: Final[str] = "CALDAV_CALENDARS_JSON"

#: Single-calendar shorthand, for the common one-calendar-account case.
_ENV_SINGLE_URL: Final[str] = "CALDAV_URL"
_ENV_SINGLE_USERNAME: Final[str] = "CALDAV_USERNAME"
_ENV_SINGLE_APP_PASSWORD: Final[str] = "CALDAV_APP_PASSWORD"
_ENV_SINGLE_CALENDAR_PATH: Final[str] = "CALDAV_CALENDAR_PATH"
_ENV_SINGLE_SCOPE: Final[str] = "CALDAV_SCOPE"

_REQUIRED_BINDING_FIELDS: Final[tuple[str, ...]] = (
    "base_url",
    "username",
    "app_password",
    "calendar_path",
    "scope",
)


@dataclass(frozen=True)
class CalendarBinding:
    """One calendar's resolved private-bindings CalDAV configuration.

    ``scope`` is the per-calendar scope mapping (AC6): the segmenter tags
    every signal derived from this calendar with this scope, so a
    work-calendar signal can never enter a private-scope segment partition
    (ERE-08 discipline is inherited from the already-shipped per-scope
    isolation in ``fold_signals_into_segments`` -- this binding is only the
    tagging seam).
    """

    calendar_id: str
    base_url: str
    username: str
    app_password: str
    calendar_path: str
    scope: str


def _binding_from_mapping(entry: Mapping[str, Any], *, source: str) -> CalendarBinding:
    missing = [key for key in _REQUIRED_BINDING_FIELDS if not str(entry.get(key, "")).strip()]
    if missing:
        raise CalendarCredentialsError(f"{source}: missing required field(s) {sorted(missing)}")
    calendar_id = entry.get("calendar_id") or entry.get("calendar_path") or source
    return CalendarBinding(
        calendar_id=str(calendar_id).strip(),
        base_url=str(entry["base_url"]).strip(),
        username=str(entry["username"]).strip(),
        app_password=str(entry["app_password"]).strip(),
        calendar_path=str(entry["calendar_path"]).strip(),
        scope=str(entry["scope"]).strip(),
    )


def resolve_calendar_bindings(env: Mapping[str, str] | None = None) -> tuple[CalendarBinding, ...]:
    """Resolve every configured calendar's private-bindings config.

    Fail-loud (:class:`CalendarCredentialsError`) if nothing is configured --
    the registry-live/unconfigured contradiction (AC4). Never reads or
    returns anything from the repo or vault; ``env`` defaults to
    ``os.environ`` (the private-bindings constituent's gitignored ``.env*`` /
    host launchd job env is the only real producer of these variables).
    """
    source = env if env is not None else os.environ
    raw_json = (source.get(_ENV_CALENDARS_JSON) or "").strip()
    if raw_json:
        import json

        try:
            parsed = json.loads(raw_json)
        except (TypeError, ValueError) as exc:
            raise CalendarCredentialsError(f"{_ENV_CALENDARS_JSON} is not valid JSON") from exc
        if not isinstance(parsed, list) or not parsed:
            raise CalendarCredentialsError(f"{_ENV_CALENDARS_JSON} must be a non-empty JSON array")
        bindings: list[CalendarBinding] = []
        for index, entry in enumerate(parsed):
            if not isinstance(entry, Mapping):
                raise CalendarCredentialsError(f"{_ENV_CALENDARS_JSON}[{index}] must be an object")
            bindings.append(_binding_from_mapping(entry, source=f"{_ENV_CALENDARS_JSON}[{index}]"))
        return tuple(bindings)

    single = {
        "calendar_id": "default",
        "base_url": (source.get(_ENV_SINGLE_URL) or "").strip(),
        "username": (source.get(_ENV_SINGLE_USERNAME) or "").strip(),
        "app_password": (source.get(_ENV_SINGLE_APP_PASSWORD) or "").strip(),
        "calendar_path": (source.get(_ENV_SINGLE_CALENDAR_PATH) or "").strip(),
        "scope": (source.get(_ENV_SINGLE_SCOPE) or "").strip(),
    }
    if not any(single[key] for key in _REQUIRED_BINDING_FIELDS):
        raise CalendarCredentialsError(
            "calendar stream is registry-live but no private-bindings CalDAV config is set "
            f"(expected {_ENV_CALENDARS_JSON!r} or all of "
            f"{_ENV_SINGLE_URL!r}/{_ENV_SINGLE_USERNAME!r}/{_ENV_SINGLE_APP_PASSWORD!r}/"
            f"{_ENV_SINGLE_CALENDAR_PATH!r}/{_ENV_SINGLE_SCOPE!r})"
        )
    return (_binding_from_mapping(single, source="CALDAV_* env"),)


# ---------------------------------------------------------------------------
# Transport (read-only CalDAV REPORT; never called by this repo's test suite
# or on this laptop dev environment -- Constraints: "NO live iCloud fetch in
# this environment or the test suite")
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CalendarRawItem:
    """One raw CalDAV resource: a single event's UID, per-resource ETag
    (provenance: AC1 "provenance UID+etag"), and its raw VEVENT ICS text."""

    uid: str
    etag: str
    ics_text: str


#: A transport is any callable resolving one binding's current raw items.
#: Production uses :func:`_default_transport`; tests inject a fixture/fake
#: transport (recorded ICS text or a simulated `CalendarUnreachableError`) --
#: the live-CalDAV receipt is a mac-mini test-channel deliverable, deferred.
CalendarTransport = Callable[[CalendarBinding], Sequence[CalendarRawItem]]

_DAV_NS: Final[str] = "DAV:"
_CALDAV_NS: Final[str] = "urn:ietf:params:xml:ns:caldav"
_CALDAV_TIMEOUT_SECONDS: Final[float] = 15.0

_CALENDAR_QUERY_BODY: Final[str] = (
    '<?xml version="1.0" encoding="utf-8" ?>\n'
    f'<C:calendar-query xmlns:D="{_DAV_NS}" xmlns:C="{_CALDAV_NS}">\n'
    "  <D:prop>\n"
    "    <D:getetag/>\n"
    "    <C:calendar-data/>\n"
    "  </D:prop>\n"
    "  <C:filter>\n"
    '    <C:comp-filter name="VCALENDAR">\n'
    '      <C:comp-filter name="VEVENT"/>\n'
    "    </C:comp-filter>\n"
    "  </C:filter>\n"
    "</C:calendar-query>\n"
)


def _parse_multistatus(xml_text: str) -> list[CalendarRawItem]:
    """Parse a CalDAV ``multistatus`` REPORT response into raw items.

    Never raises on a per-response oddity (a response without calendar-data
    is skipped); raises :class:`CalendarUnreachableError` only when the
    envelope itself is not parseable XML (a malformed response is a
    reachability failure, not a per-event data problem)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise CalendarUnreachableError("calendar: malformed CalDAV multistatus response") from exc

    items: list[CalendarRawItem] = []
    for response in root.findall(f"{{{_DAV_NS}}}response"):
        href_el = response.find(f"{{{_DAV_NS}}}href")
        href = href_el.text.strip() if href_el is not None and href_el.text else ""
        etag = ""
        ics_text = ""
        for propstat in response.findall(f"{{{_DAV_NS}}}propstat"):
            prop = propstat.find(f"{{{_DAV_NS}}}prop")
            if prop is None:
                continue
            etag_el = prop.find(f"{{{_DAV_NS}}}getetag")
            if etag_el is not None and etag_el.text:
                etag = etag_el.text.strip().strip('"')
            data_el = prop.find(f"{{{_CALDAV_NS}}}calendar-data")
            if data_el is not None and data_el.text:
                ics_text = data_el.text
        if not ics_text:
            continue
        event = parse_vevent(ics_text)
        uid = event.uid if event is not None else href
        if not uid:
            continue
        items.append(CalendarRawItem(uid=uid, etag=etag or uid, ics_text=ics_text))
    return items


def _default_transport(binding: CalendarBinding) -> Sequence[CalendarRawItem]:
    """Production CalDAV REPORT transport: read-only, basic-auth via the
    app-specific password, bounded 15s timeout. Never logs or echoes
    ``binding.app_password``. Exercised only via the mac-mini test channel
    (deferred receipt); this repo's test suite always injects a fake
    ``transport``."""
    import httpx

    url = binding.base_url.rstrip("/") + "/" + binding.calendar_path.lstrip("/")
    try:
        response = httpx.request(
            "REPORT",
            url,
            auth=(binding.username, binding.app_password),
            headers={"Content-Type": "application/xml; charset=utf-8", "Depth": "1"},
            content=_CALENDAR_QUERY_BODY.encode("utf-8"),
            timeout=_CALDAV_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise CalendarUnreachableError(
            f"calendar {binding.calendar_id}: CalDAV request failed (network error)"
        ) from exc
    if response.status_code >= 400:
        raise CalendarUnreachableError(
            f"calendar {binding.calendar_id}: CalDAV request failed (HTTP {response.status_code})"
        )
    return _parse_multistatus(response.text)


def read_calendar_raw_items_for_tick(
    *,
    bindings: Sequence[CalendarBinding] | None = None,
    transport: CalendarTransport | None = None,
) -> tuple[list[tuple[CalendarBinding, CalendarRawItem]], list[str]]:
    """Fetch raw CalDAV items for every configured private-bindings calendar.

    Fails LOUD (:class:`CalendarCredentialsError`) if bindings do not resolve
    at all -- OUTSIDE any per-binding try/except, so a misconfiguration is
    never mistaken for a transient unreachable-calendar degradation (AC4).
    Each binding's fetch is independent: one calendar's
    :class:`CalendarUnreachableError` is caught HERE and folds into the
    returned ``degraded`` list -- it never aborts another calendar's fetch
    (AC5, "a missing stream never stalls segmentation").

    Returns ``(items, degraded)`` where ``items`` is a list of
    ``(binding, raw_item)`` pairs (each item carries its own calendar's scope
    context via ``binding``) and ``degraded`` is the list of
    ``calendar_id``s that could not be reached this tick.
    """
    resolved_bindings = bindings if bindings is not None else resolve_calendar_bindings()
    transport_fn = transport if transport is not None else _default_transport

    items: list[tuple[CalendarBinding, CalendarRawItem]] = []
    degraded: list[str] = []
    for binding in resolved_bindings:
        try:
            raw_items = transport_fn(binding)
        except CalendarUnreachableError as exc:
            logger.warning("calendar stream degraded for %s: %s", binding.calendar_id, exc)
            degraded.append(binding.calendar_id)
            continue
        for raw in raw_items:
            items.append((binding, raw))
    return items, degraded


# ---------------------------------------------------------------------------
# ICS / VEVENT parsing (RFC 5545 subset -- UID, SUMMARY, DTSTART, DTEND,
# LOCATION, ATTENDEE)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CalendarAttendee:
    """One VEVENT ``ATTENDEE`` line: the display surface form to resolve
    (``CN=`` parameter when present, else the raw ``mailto:`` value) plus the
    raw property value for provenance/debugging."""

    surface_form: str
    raw: str


@dataclass(frozen=True)
class ParsedCalendarEvent:
    uid: str
    summary: str | None
    dtstart: datetime | None
    dtend: datetime | None
    location: str | None
    attendees: tuple[CalendarAttendee, ...]


_DT_UTC_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$")
_DT_LOCAL_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})$")
_DATE_ONLY_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_ATTENDEE_CN_RE = re.compile(r"CN=([^;:]+)", re.IGNORECASE)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _unfold_ics_lines(text: str) -> list[str]:
    """RFC 5545 line unfolding: a line starting with a single space/tab is a
    continuation of the previous physical line."""
    raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines: list[str] = []
    for raw in raw_lines:
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
            continue
        lines.append(raw)
    return lines


def _parse_ics_datetime(value: str) -> datetime | None:
    """Parse an ICS ``DTSTART``/``DTEND`` value: UTC (``Z`` suffix), a bare
    local datetime, or an all-day ``VALUE=DATE``. No TZID offset table in v1
    (a local/TZID datetime is treated as UTC-naive-to-UTC, a documented
    best-effort posture, never a crash) -- ``None`` on anything unparseable,
    the caller skips the item fail-loud rather than guessing a time."""
    value = value.strip()
    match = _DT_UTC_RE.match(value)
    if match:
        y, mo, d, h, mi, s = (int(g) for g in match.groups())
        return datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)
    match = _DT_LOCAL_RE.match(value)
    if match:
        y, mo, d, h, mi, s = (int(g) for g in match.groups())
        return datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)
    match = _DATE_ONLY_RE.match(value)
    if match:
        y, mo, d = (int(g) for g in match.groups())
        return datetime(y, mo, d, tzinfo=timezone.utc)
    return None


def parse_vevent(ics_text: str) -> ParsedCalendarEvent | None:
    """Parse the first ``VEVENT`` block in ``ics_text``. ``None`` when no
    ``UID`` is present (an event without a stable identity can never satisfy
    AC1's provenance-ref requirement, so it is skipped fail-loud rather than
    folded under a synthesized id)."""
    lines = _unfold_ics_lines(ics_text)
    in_event = False
    uid: str | None = None
    summary: str | None = None
    dtstart: datetime | None = None
    dtend: datetime | None = None
    location: str | None = None
    attendees: list[CalendarAttendee] = []

    for line in lines:
        if not line:
            continue
        stripped_upper = line.strip().upper()
        if stripped_upper == "BEGIN:VEVENT":
            in_event = True
            continue
        if stripped_upper == "END:VEVENT":
            break
        if not in_event or ":" not in line:
            continue
        prop, _, value = line.partition(":")
        name = prop.split(";", 1)[0].strip().upper()
        params = prop[len(name) :]
        if name == "UID":
            uid = value.strip()
        elif name == "SUMMARY":
            summary = value.strip() or None
        elif name == "DTSTART":
            dtstart = _parse_ics_datetime(value)
        elif name == "DTEND":
            dtend = _parse_ics_datetime(value)
        elif name == "LOCATION":
            location = value.strip() or None
        elif name == "ATTENDEE":
            cn_match = _ATTENDEE_CN_RE.search(params)
            surface = cn_match.group(1).strip() if cn_match else value.strip()
            if surface:
                attendees.append(CalendarAttendee(surface_form=surface, raw=value.strip()))

    if uid is None:
        return None
    return ParsedCalendarEvent(
        uid=uid,
        summary=summary,
        dtstart=dtstart,
        dtend=dtend,
        location=location,
        attendees=tuple(attendees),
    )


def slugify_summary(text: str) -> str:
    """Normalize an event ``SUMMARY`` into the provisional goal-dimension
    proxy token (mirrors ``vault_activity_stream``'s sphere-membership
    proxy: no explicit project/goal field exists on a calendar event, so the
    title is the closest available goal/context binding)."""
    slug = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    return slug or text.strip().lower()


# ---------------------------------------------------------------------------
# Three-state attendee resolution -- READ-ONLY, never mutates the shared
# entity register (HEIM-6/HEIM-11, Scope: "no register mutation")
# ---------------------------------------------------------------------------

_REGISTER_DIR: Final[str] = "_heimdal/register"
_LIFECYCLE_MERGED: Final[str] = "merged"
_LIFECYCLE_CANONICAL: Final[str] = "canonical"


@dataclass(frozen=True)
class RegisterEntrySnapshot:
    """A read-only snapshot of one entity register note's identity-relevant
    fields -- just enough to exact-match a surface form, never a mutation
    handle."""

    entity_id: str
    label: str
    aliases: tuple[str, ...]
    lifecycle: str


def read_register_snapshot(*, vault_root: Path) -> tuple[RegisterEntrySnapshot, ...]:
    """Read-only snapshot of the shared entity register's notes.

    NEVER mutates: no mint/merge/write call anywhere in this module, and no
    import of ``app.heimdal.entity_register``'s mutating API (Heimdal is
    untouched by this task -- Epic invariant). Mirrors
    ``vault_activity_stream.resolve_activity_dimensions``'s pattern of
    reading frontmatter directly rather than depending on a heavier module.
    A missing register directory (no Heimdal register built yet) yields an
    empty snapshot -- attendee resolution degrades to all-``unresolved``,
    never a crash.
    """
    register_root = Path(vault_root) / _REGISTER_DIR
    if not register_root.exists():
        return ()
    entries: list[RegisterEntrySnapshot] = []
    for note_path in sorted(register_root.glob("*.md")):
        try:
            text = note_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.startswith("---"):
            continue
        _, _, rest = text.partition("---\n")
        frontmatter_text, _, _ = rest.partition("\n---")
        try:
            data = yaml.safe_load(frontmatter_text) or {}
        except yaml.YAMLError:
            continue
        entity_id = data.get("entity_id")
        if not entity_id:
            continue
        entries.append(
            RegisterEntrySnapshot(
                entity_id=str(entity_id),
                label=str(data.get("label", "")),
                aliases=tuple(str(a) for a in (data.get("aliases") or ())),
                lifecycle=str(data.get("lifecycle", "provisional")),
            )
        )
    return tuple(entries)


@dataclass(frozen=True)
class AttendeeResolved:
    """``resolved``: exactly one register match, never guessed (HEIM-6)."""

    entity_id: str
    confidence: float


@dataclass(frozen=True)
class AttendeeAmbiguous:
    """``ambiguous``: more than one register match, no winner asserted."""

    candidates: tuple[AttendeeResolved, ...]


@dataclass(frozen=True)
class AttendeeUnresolved:
    """``unresolved``: no register match. ``entity_id`` is a LOCAL,
    deterministic-but-non-durable placeholder -- deliberately NOT an
    ``ent:prov:`` id (that namespace means "durably minted in the shared
    register"; this module mints nothing, per Scope: "no register
    mutation")."""

    entity_id: str
    surface_form: str


AttendeeResolution = AttendeeResolved | AttendeeAmbiguous | AttendeeUnresolved


def _local_unresolved_id(surface_form: str) -> str:
    digest = hashlib.sha1(surface_form.strip().lower().encode("utf-8")).hexdigest()[:16]
    return f"cal:unresolved:{digest}"


def resolve_attendee_readonly(
    surface_form: str,
    *,
    known_entries: Sequence[RegisterEntrySnapshot] = (),
) -> AttendeeResolution:
    """Three-state resolution (HEIM-6/HEIM-11) against an ALREADY-LOADED,
    read-only register snapshot -- never mints, never merges, never writes.

    Mirrors ``EntityRegister.resolve()``'s exact label/alias matching rule
    (over non-``merged`` entries) WITHOUT its mutating miss-branch: a match
    still yields ``resolved``/``ambiguous`` exactly as the register would,
    but a miss returns :class:`AttendeeUnresolved` carrying a local
    placeholder id instead of durably minting a provisional register entry.
    """
    needle = surface_form.strip().lower()
    matches = [
        entry
        for entry in known_entries
        if entry.lifecycle != _LIFECYCLE_MERGED
        and needle in {entry.label.strip().lower(), *(a.strip().lower() for a in entry.aliases)}
    ]
    if not matches:
        return AttendeeUnresolved(entity_id=_local_unresolved_id(surface_form), surface_form=surface_form)
    if len(matches) == 1:
        confidence = 1.0 if matches[0].lifecycle == _LIFECYCLE_CANONICAL else 0.5
        return AttendeeResolved(entity_id=matches[0].entity_id, confidence=confidence)
    ranked = tuple(
        AttendeeResolved(entity_id=m.entity_id, confidence=1.0 if m.lifecycle == _LIFECYCLE_CANONICAL else 0.5)
        for m in matches
    )
    return AttendeeAmbiguous(candidates=ranked)


# ---------------------------------------------------------------------------
# ERE-01 SignalContract normalization (AC1: bitemporal, per-dimension
# confidence, provenance ref)
# ---------------------------------------------------------------------------

#: Per-dimension (score, calibration) for the calendar stream's declared
#: contract (spec: "dimensions_fed: {time: high, protagonist: medium, space:
#: medium, goal: medium}"). ``time`` is `by_construction` (DTSTART/DTEND are
#: exact fields on the event, not inferred); the rest are `heuristic`
#: (three-state attendee matching, freeform LOCATION text, title-derived
#: goal proxy).
_DIMENSION_CONFIDENCE: Final[dict[str, tuple[float, str]]] = {
    "time": (0.95, "by_construction"),
    "protagonist": (0.6, "heuristic"),
    "space": (0.6, "heuristic"),
    "goal": (0.5, "heuristic"),
}


def _iso(value: datetime) -> str:
    dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def calendar_event_to_signal_contract(
    *,
    uid: str,
    etag: str,
    event: ParsedCalendarEvent,
    scope: str,
    emitted_at: datetime | None = None,
) -> SignalContract:
    """Normalize one parsed calendar event into the ERE-01
    :class:`~app.episodes.stream_registry.SignalContract` -- the declared,
    schema-validated shape every stream must deliver (AC1). Distinct from
    the segmentation-internal ``SegmentationSignal`` the tick actually folds
    (that normalization lives in ``segmenter._signal_from_calendar_row``,
    matching the module's docstring "SignalContract ... not a content
    carrier" split already established by ERE-01/ERE-04)."""
    if event.dtstart is None:
        raise ValueError(f"calendar event {uid!r} has no usable DTSTART -- cannot build a SignalContract")

    dimensions: dict[str, ConfidenceScore] = {}
    score, calibration = _DIMENSION_CONFIDENCE["time"]
    dimensions["time"] = ConfidenceScore(score=score, calibration=calibration)
    if event.attendees:
        score, calibration = _DIMENSION_CONFIDENCE["protagonist"]
        dimensions["protagonist"] = ConfidenceScore(score=score, calibration=calibration)
    if event.location:
        score, calibration = _DIMENSION_CONFIDENCE["space"]
        dimensions["space"] = ConfidenceScore(score=score, calibration=calibration)
    if event.summary:
        score, calibration = _DIMENSION_CONFIDENCE["goal"]
        dimensions["goal"] = ConfidenceScore(score=score, calibration=calibration)

    return SignalContract(
        stream_id=CALENDAR_STREAM_ID,
        signal_id=f"{uid}:{etag}",
        observed_at_start=_iso(event.dtstart),
        observed_at_end=_iso(event.dtend) if event.dtend is not None else None,
        emitted_at=_iso(emitted_at if emitted_at is not None else datetime.now(timezone.utc)),
        dimensions_fed=dimensions,
        provenance_ref=f"calendar:{uid}:{etag}",
        scope_binding=ContextDimensions(scope=scope) if scope else None,
    )


__all__ = [
    "CALENDAR_STREAM_ID",
    "AttendeeAmbiguous",
    "AttendeeResolution",
    "AttendeeResolved",
    "AttendeeUnresolved",
    "CalendarAttendee",
    "CalendarBinding",
    "CalendarCredentialsError",
    "CalendarRawItem",
    "CalendarTransport",
    "CalendarUnreachableError",
    "ParsedCalendarEvent",
    "RegisterEntrySnapshot",
    "calendar_event_to_signal_contract",
    "parse_vevent",
    "read_calendar_raw_items_for_tick",
    "read_register_snapshot",
    "resolve_attendee_readonly",
    "resolve_calendar_bindings",
    "slugify_summary",
]
