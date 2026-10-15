"""Fixed, source-authorized ERE qualification profile.

The native qualification operation owns the process and channel envelope.  This
module owns the smaller ERE admission contract that runs inside that envelope:
the candidate, TEST operation, source bindings, and local-day window are
admitted first; source readers are then called with those exact constraints;
normalization happens only after the read boundary; and durable effects cross a
``WriteGuard`` through a finite effect inventory.

The profile deliberately has no credential transport and no real-day success
path.  A live operator run is parent acceptance on #3175.  This profile emits
sanitized synthetic-control evidence for deterministic qualification only.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import hashlib
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


if TYPE_CHECKING:
    from app.write_guard import WriteGuard


PROFILE: Final[str] = "episode-resolution.real-day.v1"
TIMEZONE_NAME: Final[str] = "Europe/Stockholm"
ADMITTED_SOURCES: Final[frozenset[str]] = frozenset(
    {"heimdal.observations", "vault.activity", "calendar"}
)
ALLOWED_EFFECTS: Final[frozenset[str]] = frozenset(
    {"proposal", "pending_binding", "closure", "projection", "outbox"}
)
FORBIDDEN_EFFECTS: Final[frozenset[str]] = frozenset(
    {
        "source_write",
        "calendar_write",
        "delete",
        "accept",
        "promote",
        "human_recut",
        "cross_scope_fusion",
    }
)
_SHA = re.compile(r"^[0-9a-f]{40,64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SECRET_KEY_PARTS = ("password", "secret", "token", "credential", "private_key")


class EreProfileRefusal(RuntimeError):
    """A bounded, content-free refusal from the ERE profile admission seam."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("ERE qualification refused: " + reason)


@dataclass(frozen=True)
class LocalDayWindow:
    """Timezone-aware half-open interval for one selected Stockholm day."""

    selected_date: date
    timezone: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.timezone != TIMEZONE_NAME:
            raise EreProfileRefusal("unsupported_local_timezone")
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise EreProfileRefusal("day_window_must_be_timezone_aware")
        if self.start >= self.end or self.start.astimezone(ZoneInfo(self.timezone)).date() != self.selected_date:
            raise EreProfileRefusal("invalid_day_window")

    def contains(self, instant: datetime) -> bool:
        if instant.tzinfo is None:
            return False
        return self.start <= instant < self.end


@dataclass(frozen=True)
class EreBinding:
    """Opaque identity and scope for one admitted ERE source binding."""

    source_id: str
    binding_id: str
    scope: str
    consent_ref: str | None = None
    calendar_id: str | None = None

    @property
    def identity(self) -> str:
        return self.calendar_id if self.source_id == "calendar" and self.calendar_id else self.binding_id


@dataclass(frozen=True)
class EreAdmission:
    """Validated, immutable input envelope for one profile operation."""

    profile: str
    source_sha: str
    image_digest: str
    channel: str
    operation_id: str
    window: LocalDayWindow
    bindings: Mapping[str, EreBinding]

    def __post_init__(self) -> None:
        if self.profile != PROFILE or self.channel != "test":
            raise EreProfileRefusal("profile_or_channel_mismatch")
        if set(self.bindings) != ADMITTED_SOURCES:
            raise EreProfileRefusal("source_binding_inventory_mismatch")


class SourceReader(Protocol):
    """A production reader constrained by the exact binding and day window."""

    def __call__(self, binding: EreBinding, window: LocalDayWindow) -> Iterable[Mapping[str, Any]]: ...


Normalizer = Callable[[str, Mapping[str, Any]], Any]
EffectWriter = Callable[[tuple[Any, ...], EreAdmission], Any]


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str):
                yield key.lower()
            yield from _walk_keys(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_keys(child)


def _reject_secret_material(value: Any) -> None:
    for key in _walk_keys(value):
        if any(part in key for part in _SECRET_KEY_PARTS):
            raise EreProfileRefusal("credential_material_in_profile_manifest")


def _required_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _OPAQUE_ID.fullmatch(value):
        raise EreProfileRefusal(f"{field}_invalid")
    return value


def _parse_window(local_day: Any, *, now: datetime) -> LocalDayWindow:
    if not isinstance(local_day, str):
        raise EreProfileRefusal("local_day_missing")
    try:
        selected = date.fromisoformat(local_day)
        zone = ZoneInfo(TIMEZONE_NAME)
    except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise EreProfileRefusal("local_day_invalid") from exc
    # Keep the native qualification module importable without Product runtime
    # dependencies. The calendar adapter remains the source of truth when the
    # profile actually admits a day.
    from app.episodes.calendar_stream import _CALDAV_TIME_RANGE_FUTURE, _CALDAV_TIME_RANGE_PAST

    now_local = now.astimezone(zone)
    # The profile is for one completed day.  Its range must also be reachable
    # through the calendar adapter's finite query window.
    if selected >= now_local.date():
        raise EreProfileRefusal("local_day_not_completed")
    start = datetime.combine(selected, datetime.min.time(), tzinfo=zone)
    end = start + timedelta(days=1)
    if start < now.astimezone(UTC) - _CALDAV_TIME_RANGE_PAST or end > now.astimezone(UTC) + _CALDAV_TIME_RANGE_FUTURE:
        raise EreProfileRefusal("local_day_outside_calendar_window")
    return LocalDayWindow(selected, TIMEZONE_NAME, start, end)


def _registry_entries(registry: Any) -> dict[str, Any]:
    # Keep importing the native qualification envelope independent of the
    # Product stream models. Registry loading happens only after admission has
    # established that this profile is actually being executed.
    from app.episodes.stream_registry import StreamRegistry

    if isinstance(registry, StreamRegistry):
        return {entry.stream_id: entry for entry in registry.live_entries()}
    if isinstance(registry, Mapping):
        entries = registry.get("streams", registry)
        if isinstance(entries, Mapping):
            return dict(entries)
        if isinstance(entries, Sequence) and not isinstance(entries, (str, bytes)):
            return {str(entry.get("stream_id")): entry for entry in entries if isinstance(entry, Mapping)}
    if isinstance(registry, Sequence) and not isinstance(registry, (str, bytes)):
        return {str(entry.get("stream_id")): entry for entry in registry if isinstance(entry, Mapping)}
    raise EreProfileRefusal("stream_registry_invalid")


def _is_live(entry: Any) -> bool:
    from app.episodes.stream_registry import STATUS_LIVE

    return getattr(entry, "status", None) == STATUS_LIVE or (
        isinstance(entry, Mapping) and entry.get("status") == STATUS_LIVE
    )


def _binding(raw: Any, source_id: str) -> EreBinding:
    if not isinstance(raw, Mapping):
        raise EreProfileRefusal(f"{source_id}_binding_invalid")
    binding_id = _required_id(raw.get("binding_id") or raw.get("id"), f"{source_id}_binding_id")
    scope = _required_id(raw.get("scope"), f"{source_id}_scope")
    consent = raw.get("consent_ref") or raw.get("grant_ref")
    if source_id == "heimdal.observations":
        consent = _required_id(consent, "heimdal_consent_ref")
    elif consent is not None:
        consent = _required_id(consent, f"{source_id}_consent_ref")
    calendar_id = None
    if source_id == "calendar":
        calendar_id = _required_id(raw.get("calendar_id") or raw.get("id"), "calendar_id")
    return EreBinding(source_id, binding_id, scope, consent, calendar_id)


def admit_profile(
    manifest: Mapping[str, Any],
    *,
    registry: Any | None = None,
    now: datetime | None = None,
) -> EreAdmission:
    """Validate profile identity, registry status, exact bindings and day."""
    if not isinstance(manifest, Mapping):
        raise EreProfileRefusal("manifest_invalid")
    _reject_secret_material(manifest)
    profile = manifest.get("profile_version") or manifest.get("profile")
    if profile != PROFILE:
        raise EreProfileRefusal("profile_not_admitted")
    source_sha = manifest.get("source_sha")
    image_digest = manifest.get("image_digest")
    if not isinstance(source_sha, str) or not _SHA.fullmatch(source_sha):
        raise EreProfileRefusal("candidate_sha_invalid")
    if not isinstance(image_digest, str) or not _DIGEST.fullmatch(image_digest):
        raise EreProfileRefusal("candidate_digest_invalid")
    channel = manifest.get("channel")
    if channel != "test":
        raise EreProfileRefusal("test_channel_required")
    operation_id = manifest.get("operation_id")
    try:
        valid_operation_id = isinstance(operation_id, str) and str(UUID(operation_id)) == operation_id
    except (ValueError, AttributeError):
        valid_operation_id = False
    if not valid_operation_id:
        raise EreProfileRefusal("operation_id_invalid")
    assert isinstance(operation_id, str)
    requested = manifest.get("sources", manifest.get("source_ids", tuple(ADMITTED_SOURCES)))
    try:
        requested_sources = set(requested) if isinstance(requested, Sequence) and not isinstance(requested, (str, bytes)) else set()
    except TypeError:
        requested_sources = set()
    if requested_sources != ADMITTED_SOURCES:
        raise EreProfileRefusal("source_inventory_not_admitted")
    if registry is None:
        from app.episodes.stream_registry import load_registry

        registry = load_registry()
    live = _registry_entries(registry)
    if any(source not in live or not _is_live(live[source]) for source in ADMITTED_SOURCES):
        raise EreProfileRefusal("registered_live_source_missing")
    raw_bindings = manifest.get("bindings", manifest.get("source_bindings"))
    if not isinstance(raw_bindings, Mapping) or set(raw_bindings) != ADMITTED_SOURCES:
        raise EreProfileRefusal("source_binding_inventory_mismatch")
    bindings = MappingProxyType({source: _binding(raw_bindings[source], source) for source in ADMITTED_SOURCES})
    scopes = {binding.scope for binding in bindings.values()}
    if len(scopes) != 1:
        raise EreProfileRefusal("test_vault_scope_mismatch")
    window = _parse_window(manifest.get("local_date", manifest.get("selected_local_date")), now=now or datetime.now(UTC))
    return EreAdmission(PROFILE, source_sha, image_digest, channel, operation_id, window, bindings)


def _instant(record: Mapping[str, Any]) -> datetime | None:
    value = next((record.get(key) for key in ("observed_at", "observed_at_start", "start", "dtstart") if record.get(key) is not None), None)
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _record_matches(source_id: str, record: Mapping[str, Any], binding: EreBinding, window: LocalDayWindow) -> bool:
    if record.get("stream_id") not in (None, source_id):
        return False
    identity = record.get("calendar_id") if source_id == "calendar" else record.get("binding_id", record.get("source_binding_id"))
    if identity != binding.identity:
        return False
    if record.get("scope", record.get("vault_scope")) != binding.scope:
        return False
    if source_id == "heimdal.observations" and record.get("consent_ref", record.get("grant_ref")) != binding.consent_ref:
        return False
    instant = _instant(record)
    return instant is not None and window.contains(instant)


def _opaque_ref(source_id: str, record: Mapping[str, Any], binding: EreBinding) -> str:
    candidate = record.get("signal_id") or record.get("record_id") or record.get("provenance_ref")
    raw = f"{source_id}|{binding.identity}|{candidate!s}".encode()
    return "ref:" + hashlib.sha256(raw).hexdigest()[:24]


def read_admitted_sources(
    admission: EreAdmission,
    readers: Mapping[str, SourceReader],
    *,
    normalize: Normalizer | None = None,
) -> tuple[tuple[Any, ...], dict[str, tuple[str, ...]]]:
    """Read and normalize only records admitted at the source boundary."""
    if set(readers) != ADMITTED_SOURCES:
        raise EreProfileRefusal("source_reader_inventory_mismatch")
    normalized: list[Any] = []
    evidence: dict[str, tuple[str, ...]] = {}
    for source_id in ("heimdal.observations", "vault.activity", "calendar"):
        binding = admission.bindings[source_id]
        try:
            rows = readers[source_id](binding, admission.window)
            if isinstance(rows, (str, bytes, Mapping)):
                raise TypeError("reader must return an iterable of records")
            admitted_rows = [row for row in rows if isinstance(row, Mapping) and _record_matches(source_id, row, binding, admission.window)]
        except EreProfileRefusal:
            raise
        except Exception as exc:
            raise EreProfileRefusal(f"{source_id}_reader_refused") from exc
        evidence[source_id] = tuple(_opaque_ref(source_id, row, binding) for row in admitted_rows)
        if normalize is None:
            normalized.extend(admitted_rows)
        else:
            try:
                normalized.extend(normalize(source_id, row) for row in admitted_rows)
            except Exception as exc:
                raise EreProfileRefusal(f"{source_id}_normalization_refused") from exc
    return tuple(normalized), evidence


def _scope_values(records: Iterable[Any]) -> set[str]:
    scopes: set[str] = set()
    for record in records:
        if isinstance(record, Mapping):
            scope = record.get("scope", record.get("vault_scope"))
            if isinstance(scope, str):
                scopes.add(scope)
    return scopes


def run_profile(
    manifest: Mapping[str, Any],
    *,
    readers: Mapping[str, SourceReader],
    normalize: Normalizer | None = None,
    effects: Mapping[str, EffectWriter] | None = None,
    write_guard: WriteGuard | None = None,
    cross_scope_flow: Callable[[tuple[str, ...]], Mapping[str, Any] | None] | None = None,
    registry: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Production profile entrypoint used by the fixed qualification envelope."""
    if write_guard is None:
        from app.write_guard import DEFAULT_WRITE_GUARD

        write_guard = DEFAULT_WRITE_GUARD
    admission = admit_profile(manifest, registry=registry, now=now)
    effect_writers = dict(effects or {})
    unknown = set(effect_writers) - ALLOWED_EFFECTS
    prohibited = unknown | (set(effect_writers) & FORBIDDEN_EFFECTS)
    if prohibited:
        raise EreProfileRefusal("effect_not_admitted:" + ",".join(sorted(prohibited)))
    records, refs = read_admitted_sources(admission, readers, normalize=normalize)
    scopes = _scope_values(records)
    if len(scopes) > 1:
        if cross_scope_flow is None:
            raise EreProfileRefusal("cross_scope_flow_required")
        flow = cross_scope_flow(tuple(sorted(scopes)))
        if not isinstance(flow, Mapping) or not flow.get("flow_id") or not flow.get("receipt"):
            raise EreProfileRefusal("cross_scope_receipt_required")
    else:
        flow = None
    if any(
        isinstance(record, Mapping)
        and (record.get("human_cut") is True or record.get("segmentation") in {"accepted", "re-cut"})
        for record in records
    ) and effect_writers:
        # The qualification profile has no mutation path for a terminal human
        # cut.  A later ERE operation may append a separately governed result,
        # but this bounded actor must refuse before invoking any writer.
        raise EreProfileRefusal("human_recut_terminal")
    effect_counts: dict[str, int] = {}
    payload = tuple(records)
    for effect_name, writer in effect_writers.items():
        write_guard.assert_writes_allowed("episode-resolution.real-day." + effect_name)
        writer(payload, admission)
        effect_counts[effect_name] = 1
    return {
        "profile_version": PROFILE,
        "evidence_kind": "synthetic_control",
        "synthetic_control": True,
        "real_day_acceptance": False,
        "candidate": {"source_sha": admission.source_sha, "image_digest": admission.image_digest},
        "channel": admission.channel,
        "operation_id": admission.operation_id,
        "local_day": admission.window.selected_date.isoformat(),
        "interval": {
            "timezone": TIMEZONE_NAME,
            "start": admission.window.start.isoformat(),
            "end": admission.window.end.isoformat(),
            "closed": False,
        },
        "bindings": {
            source: {
                "binding_id": binding.binding_id,
                "identity": binding.identity,
                "scope": binding.scope,
                **({"consent_ref": binding.consent_ref} if binding.consent_ref else {}),
            }
            for source, binding in admission.bindings.items()
        },
        "reads": {source: {"count": len(values), "references": list(values)} for source, values in refs.items()},
        "effects": effect_counts,
        "cross_scope_flow": {"flow_id": flow["flow_id"]} if isinstance(flow, Mapping) else None,
    }


__all__ = [
    "ADMITTED_SOURCES",
    "ALLOWED_EFFECTS",
    "EreAdmission",
    "EreBinding",
    "EreProfileRefusal",
    "LocalDayWindow",
    "PROFILE",
    "admit_profile",
    "read_admitted_sources",
    "run_profile",
]
