"""Stream Registry and Signal Contract (ERE-01, #3176).

Spec: ``docs/EPISODE_RESOLUTION_ENGINE/STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md``.
Canonical human inventory: ``docs/EPISODE_RESOLUTION_ENGINE/README.md`` §
Input-source inventory.

The owner requires that every Episode Resolution Engine input source is
**identified and part of the architecture** -- never an implicit list buried
inside the segmenter. This module makes streams first-class:

- :class:`SignalContract` -- the normalized shape every stream must deliver
  to the segmenter (bitemporal, per-dimension confidence, provenance ref).
- :class:`StreamRegistryEntry` / :class:`StreamRegistry` -- the declared
  contract for each *source* (status, transport, consent class, cadence,
  owner constituent), loaded fail-loud from a markdown-first declaration
  (``docs/EPISODE_RESOLUTION_ENGINE/stream_registry.md``), consistent with
  the ``_heimdal/settings.md`` markdown-first precedent
  (``app.heimdal.settings_notes``): the human-legible doc is the declaration
  surface, this module is the code mirror that loads and validates it.

Adding a future stream (calendar, location, ambient audio) is a registry
entry + adapter, never an engine change -- enforced by
``app.episodes.segmenter`` consuming only ``StreamRegistry.live_entries()``
(AC5), never a hardcoded source list.

Fail-loud discipline (Constraints, binding): a missing declaration file, an
empty/malformed fenced block, a `status` outside the four declared classes,
a `live` entry missing `transport`/`consent_class`/`cadence`, or a `live`
entry naming a transport with no runtime binding are all hard errors --
never a silent default/empty registry (mirrors HEIM-3/HEIM-10 "explicit
absence, never silent" discipline applied to this substrate).
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from app.context_dimensions import ContextDimensions

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The five Episode dimensions (time / space / protagonist / goal / causation)
# a signal or a registered stream can evidence.
DIMENSIONS: frozenset[str] = frozenset({"time", "space", "protagonist", "goal", "causation"})

STATUS_LIVE = "live"
STATUS_PLANNED = "planned"
STATUS_FUTURE = "future"
STATUS_EXCLUDED = "excluded"
_VALID_STATUSES: frozenset[str] = frozenset({STATUS_LIVE, STATUS_PLANNED, STATUS_FUTURE, STATUS_EXCLUDED})

# Mirrors the Heimdal confidence block's `calibration` enum
# (schemas/events/heimdal.observation.published.v1.schema.json #/properties/confidence).
CALIBRATION_VALUES: frozenset[str] = frozenset({"calibrated", "heuristic", "by_construction"})

DEFAULT_REGISTRY_DOC: Path = (
    Path(__file__).resolve().parents[2] / "docs" / "EPISODE_RESOLUTION_ENGINE" / "stream_registry.md"
)

_FENCE = re.compile(r"(?s)```yaml stream-registry\s*(?P<body>.+?)```")

# Transport binding prefixes (AC3): a `live` entry's transport must resolve
# through one of these two mechanisms -- a registered outbox topic constant
# in `app.events.types`, or an importable runtime consumer module (the
# generalized shape of "observation-log consumer path": every live,
# non-outbox stream in the canonical inventory -- heimdal.observations,
# chat.sessions, decision.receipts, heimdal.attention -- is read through a
# concrete runtime module exactly like `app.heimdal.observation_log`).
_TOPIC_PREFIX = "outbox:"
_MODULE_PREFIX = "module:"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StreamRegistryError(RuntimeError):
    """Raised for malformed/missing stream-registry declarations (AC2).

    Fail-loud: no caller of :func:`load_registry` ever receives a silently
    empty or partially-defaulted registry.
    """


class UnknownTransportError(StreamRegistryError):
    """Raised when a `live` entry names a transport with no runtime binding (AC3)."""


class UnregisteredStreamError(StreamRegistryError):
    """Raised when a caller (the segmenter entrypoint, AC5) asks to consume a
    `stream_id` that is not a registered `live` entry."""


class SignalContractError(RuntimeError):
    """Raised for malformed :class:`SignalContract` / :class:`ConfidenceScore` instances (AC1)."""


# ---------------------------------------------------------------------------
# Signal contract (AC1) -- the normalized shape every stream delivers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfidenceScore:
    """One per-dimension confidence score.

    Mirrors the Heimdal confidence block (§2 of the observation schema):
    a structured `{score, calibration}` pair, never a bare scalar.
    """

    score: float
    calibration: str
    method: str | None = None
    model_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.score, (int, float)) or isinstance(self.score, bool):
            raise SignalContractError(f"ConfidenceScore.score must be a number, got {self.score!r}")
        if not (0.0 <= float(self.score) <= 1.0):
            raise SignalContractError(f"ConfidenceScore.score must be in [0, 1], got {self.score!r}")
        if self.calibration not in CALIBRATION_VALUES:
            raise SignalContractError(
                f"ConfidenceScore.calibration must be one of {sorted(CALIBRATION_VALUES)}, got {self.calibration!r}"
            )


@dataclass(frozen=True)
class SignalContract:
    """The normalized shape every stream must deliver to the segmenter.

    - Bitemporal (mirrors `heimdal.observation.published.v1` HEIM-10):
      ``observed_at_start``/``observed_at_end`` are reality time,
      ``emitted_at`` is separately when the signal was emitted/ingested.
    - ``dimensions_fed``: which of the five Episode dimensions this signal
      evidences, each with its own :class:`ConfidenceScore` (per-axis,
      never a single scalar).
    - ``scope_binding``: optional SSI-01 shape (`app.context_dimensions`).
    - ``provenance_ref``: back-reference to the source record (observation
      id, outbox event id, note path+hash).
    """

    stream_id: str
    signal_id: str
    observed_at_start: str
    emitted_at: str
    dimensions_fed: Mapping[str, ConfidenceScore]
    provenance_ref: str
    observed_at_end: str | None = None
    scope_binding: ContextDimensions | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("stream_id", self.stream_id),
            ("signal_id", self.signal_id),
            ("observed_at_start", self.observed_at_start),
            ("emitted_at", self.emitted_at),
            ("provenance_ref", self.provenance_ref),
        ):
            if not isinstance(value, str) or not value.strip():
                raise SignalContractError(f"SignalContract.{name} must be a non-empty string, got {value!r}")
        if not isinstance(self.dimensions_fed, Mapping) or not self.dimensions_fed:
            raise SignalContractError(
                "SignalContract.dimensions_fed must be a non-empty mapping of dimension -> ConfidenceScore"
            )
        for dim, confidence in self.dimensions_fed.items():
            if dim not in DIMENSIONS:
                raise SignalContractError(
                    f"SignalContract.dimensions_fed key {dim!r} is not one of {sorted(DIMENSIONS)}"
                )
            if not isinstance(confidence, ConfidenceScore):
                raise SignalContractError(
                    f"SignalContract.dimensions_fed[{dim!r}] must be a ConfidenceScore, got {type(confidence)!r}"
                )
        if self.scope_binding is not None and not isinstance(self.scope_binding, ContextDimensions):
            raise SignalContractError(
                f"SignalContract.scope_binding must be a ContextDimensions or None, got {type(self.scope_binding)!r}"
            )


# ---------------------------------------------------------------------------
# Registry entry contract -- one declared contract per stream source
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StreamRegistryEntry:
    """One declared registry entry: `stream_id`, `status`, `transport`,
    `consent_class`, `cadence`, `owner_constituent`, plus which Episode
    dimensions the stream feeds.

    Required-field discipline depends on `status` (Constraints: "no silent
    default streams"): a `live` entry must fully declare `transport`,
    `consent_class`, `cadence`, and at least one fed dimension; `planned` /
    `future` / `excluded` entries may leave those unset (they name a source
    that is not yet, or will never be, consumed).
    """

    stream_id: str
    status: str
    owner_constituent: str
    dimensions_fed: tuple[str, ...] = ()
    transport: str | None = None
    consent_class: str | None = None
    cadence: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.stream_id, str) or not self.stream_id.strip():
            raise StreamRegistryError(f"registry entry has missing/invalid stream_id (got {self.stream_id!r})")
        if self.status not in _VALID_STATUSES:
            raise StreamRegistryError(
                f"{self.stream_id}: status must be one of {sorted(_VALID_STATUSES)}, got {self.status!r}"
            )
        if not isinstance(self.owner_constituent, str) or not self.owner_constituent.strip():
            raise StreamRegistryError(f"{self.stream_id}: owner_constituent is required and must be non-empty")
        for dim in self.dimensions_fed:
            if dim not in DIMENSIONS:
                raise StreamRegistryError(
                    f"{self.stream_id}: dimensions_fed entry {dim!r} is not one of {sorted(DIMENSIONS)}"
                )
        if self.status == STATUS_LIVE:
            if not self.transport or not str(self.transport).strip():
                raise StreamRegistryError(f"{self.stream_id}: status=live requires a non-empty transport")
            if not self.consent_class or not str(self.consent_class).strip():
                raise StreamRegistryError(f"{self.stream_id}: status=live requires a non-empty consent_class")
            if not self.cadence or not str(self.cadence).strip():
                raise StreamRegistryError(f"{self.stream_id}: status=live requires a non-empty cadence")
            if not self.dimensions_fed:
                raise StreamRegistryError(f"{self.stream_id}: status=live requires at least one dimensions_fed entry")


@dataclass(frozen=True)
class StreamRegistry:
    """The full loaded registry: `stream_id` -> :class:`StreamRegistryEntry`."""

    entries: Mapping[str, StreamRegistryEntry]

    def get(self, stream_id: str) -> StreamRegistryEntry | None:
        return self.entries.get(stream_id)

    def by_status(self, status: str) -> tuple[StreamRegistryEntry, ...]:
        return tuple(entry for entry in self.entries.values() if entry.status == status)

    def live_entries(self) -> tuple[StreamRegistryEntry, ...]:
        return self.by_status(STATUS_LIVE)

    def stream_ids(self) -> frozenset[str]:
        return frozenset(self.entries.keys())


# ---------------------------------------------------------------------------
# Transport binding (AC3)
# ---------------------------------------------------------------------------


def _known_outbox_topics() -> frozenset[str]:
    import app.events.types as event_types

    return frozenset(
        value for key, value in vars(event_types).items() if key.isupper() and isinstance(value, str)
    )


def _resolve_transport_binding(transport: str | None, *, stream_id: str) -> None:
    if not transport:
        raise UnknownTransportError(f"{stream_id}: status=live requires a resolvable transport binding")
    if transport.startswith(_TOPIC_PREFIX):
        topic = transport[len(_TOPIC_PREFIX) :]
        if topic not in _known_outbox_topics():
            raise UnknownTransportError(
                f"{stream_id}: transport {transport!r} names an outbox topic not registered in app.events.types"
            )
        return
    if transport.startswith(_MODULE_PREFIX):
        module_path = transport[len(_MODULE_PREFIX) :]
        # Existence check only (find_spec), deliberately NOT import_module:
        # some consumer paths live in the interaction layer (app.chat), and
        # the registry must verify the binding without executing/importing
        # across the interaction-protected boundary (importlinter.ini).
        try:
            spec_found = importlib.util.find_spec(module_path)
        except (ImportError, ValueError) as exc:
            raise UnknownTransportError(
                f"{stream_id}: transport {transport!r} names a runtime module that does not exist ({exc})"
            ) from exc
        if spec_found is None:
            raise UnknownTransportError(
                f"{stream_id}: transport {transport!r} names a runtime module that does not exist"
            )
        return
    raise UnknownTransportError(
        f"{stream_id}: transport {transport!r} is not a recognized binding "
        f"(expected {_TOPIC_PREFIX!r}<outbox-topic> or {_MODULE_PREFIX!r}<dotted.module.path>)"
    )


def _validate_live_transports(registry: StreamRegistry) -> None:
    for entry in registry.live_entries():
        _resolve_transport_binding(entry.transport, stream_id=entry.stream_id)


# ---------------------------------------------------------------------------
# Markdown-first loader (AC2, AC4)
# ---------------------------------------------------------------------------


def _get_str(raw: Mapping[str, Any], key: str, *, source: str, index: int, required: bool) -> str | None:
    value = raw.get(key)
    if value is None:
        if required:
            raise StreamRegistryError(f"{source}: streams[{index}].{key} is required")
        return None
    if not isinstance(value, str):
        raise StreamRegistryError(f"{source}: streams[{index}].{key} must be a string, got {type(value)!r}")
    return value


def _entry_from_mapping(raw: Any, *, source: str, index: int) -> StreamRegistryEntry:
    if not isinstance(raw, Mapping):
        raise StreamRegistryError(f"{source}: streams[{index}] must be a mapping, got {type(raw)!r}")
    raw_dimensions = raw.get("dimensions_fed") or ()
    if not isinstance(raw_dimensions, (list, tuple)):
        raise StreamRegistryError(f"{source}: streams[{index}].dimensions_fed must be a list")
    stream_id = _get_str(raw, "stream_id", source=source, index=index, required=True)
    status = _get_str(raw, "status", source=source, index=index, required=True)
    owner_constituent = _get_str(raw, "owner_constituent", source=source, index=index, required=True)
    assert stream_id is not None and status is not None and owner_constituent is not None
    try:
        return StreamRegistryEntry(
            stream_id=stream_id,
            status=status,
            owner_constituent=owner_constituent,
            dimensions_fed=tuple(raw_dimensions),
            transport=_get_str(raw, "transport", source=source, index=index, required=False),
            consent_class=_get_str(raw, "consent_class", source=source, index=index, required=False),
            cadence=_get_str(raw, "cadence", source=source, index=index, required=False),
            notes=_get_str(raw, "notes", source=source, index=index, required=False),
        )
    except StreamRegistryError:
        raise
    except TypeError as exc:
        raise StreamRegistryError(f"{source}: streams[{index}] malformed: {exc}") from exc


def parse_registry_markdown(text: str, *, source: str = "<memory>") -> StreamRegistry:
    """Parse the markdown-first declaration (a fenced ```yaml stream-registry
    block``) into a validated :class:`StreamRegistry`. Fail-loud on every
    malformed shape -- never returns a silently empty/partial registry.
    """
    match = _FENCE.search(text)
    if match is None:
        raise StreamRegistryError(
            f"{source}: no fenced 'yaml stream-registry' block found -- malformed declaration"
        )
    body = match.group("body").strip()
    if not body:
        raise StreamRegistryError(f"{source}: fenced 'yaml stream-registry' block is empty -- malformed declaration")
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError as exc:
        raise StreamRegistryError(f"{source}: fenced block is not valid YAML: {exc}") from exc
    if not isinstance(data, Mapping) or "streams" not in data:
        raise StreamRegistryError(f"{source}: fenced block must be a mapping with a top-level 'streams' key")
    streams = data["streams"]
    if not isinstance(streams, list) or not streams:
        raise StreamRegistryError(
            f"{source}: 'streams' must be a non-empty list -- no silent default/empty registry"
        )

    entries: dict[str, StreamRegistryEntry] = {}
    for index, raw in enumerate(streams):
        entry = _entry_from_mapping(raw, source=source, index=index)
        if entry.stream_id in entries:
            raise StreamRegistryError(f"{source}: duplicate stream_id {entry.stream_id!r}")
        entries[entry.stream_id] = entry

    registry = StreamRegistry(entries=entries)
    _validate_live_transports(registry)
    return registry


def load_registry(path: Path | str | None = None) -> StreamRegistry:
    """Load + validate the stream registry from its markdown-first
    declaration (default: ``docs/EPISODE_RESOLUTION_ENGINE/stream_registry.md``).

    Fail-loud: a missing file is a hard error, never a silent empty registry.
    This is the one production entrypoint every other caller (the segmenter
    entrypoint, `app.episodes.segmenter`, CLI, tests) goes through.
    """
    doc_path = Path(path) if path is not None else DEFAULT_REGISTRY_DOC
    if not doc_path.exists():
        raise StreamRegistryError(
            f"stream registry declaration not found at {doc_path} -- fail-loud, no silent default streams"
        )
    text = doc_path.read_text(encoding="utf-8")
    return parse_registry_markdown(text, source=str(doc_path))


__all__ = [
    "CALIBRATION_VALUES",
    "DEFAULT_REGISTRY_DOC",
    "DIMENSIONS",
    "STATUS_EXCLUDED",
    "STATUS_FUTURE",
    "STATUS_LIVE",
    "STATUS_PLANNED",
    "ConfidenceScore",
    "SignalContract",
    "SignalContractError",
    "StreamRegistry",
    "StreamRegistryEntry",
    "StreamRegistryError",
    "UnknownTransportError",
    "UnregisteredStreamError",
    "load_registry",
    "parse_registry_markdown",
]
