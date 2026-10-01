"""Fresh, hash-bound provider catalogs and conservative latest-compatible selection.

Catalog data is descriptive only. The caller still supplies an allowlist of
models/transports and capability requirements; this module never grants a new
provider or capability because a provider returned a new model ID.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import threading
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from llm_contract import (
    CatalogSnapshotRef,
    ModelCapabilities,
    ModelCapabilityRequirements,
    Sha256Digest,
    TransportId,
)


CATALOG_REFRESH_TTL = timedelta(minutes=5)
CATALOG_MAX_STALE_AGE = timedelta(hours=24)
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")
_SENSITIVE_MODEL_ID = re.compile(
    r"(?:https?://|@|\bsk-(?:ant-)?[a-z0-9_-]{8,}\b|\b(?:bearer|api[_-]?key|token|secret)\s*[:=])",
    re.IGNORECASE,
)
_REASONING_EFFORT = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class CatalogError(RuntimeError):
    """Sanitized failure to refresh, validate, or use a model catalog."""

    def __init__(
        self,
        code: Literal[
            "catalog_unavailable",
            "catalog_stale",
            "catalog_invalid",
            "catalog_auth_failed",
        ],
    ):
        self.code = code
        super().__init__(code)


def _utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return value.astimezone(timezone.utc)


class CatalogModelDescriptor(BaseModel):
    """One provider-reported model intersected with declared transport facts."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    model: str = Field(min_length=1, max_length=256)
    transports: tuple[TransportId, ...] = Field(min_length=1)
    capabilities: ModelCapabilities
    literal_system_role_supported: bool = False
    reasoning_efforts: tuple[str, ...] = ()
    release_at: datetime | None = None
    replacement_model: str | None = Field(default=None, max_length=256)
    deprecated: bool = False
    sunset_at: datetime | None = None
    context_window: int | None = Field(default=None, ge=1, le=10_000_000)
    max_output_tokens: int | None = Field(default=None, ge=1, le=10_000_000)
    local_modified_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_descriptor(self) -> "CatalogModelDescriptor":
        if not _MODEL_ID.fullmatch(self.model) or _SENSITIVE_MODEL_ID.search(self.model):
            raise ValueError("catalog model identifier is invalid")
        if len(self.transports) != len(set(self.transports)):
            raise ValueError("catalog transports must be unique")
        if tuple(sorted(self.transports)) != self.transports:
            raise ValueError("catalog transports must be sorted")
        if len(self.reasoning_efforts) != len(set(self.reasoning_efforts)):
            raise ValueError("catalog reasoning efforts must be unique")
        if tuple(sorted(self.reasoning_efforts)) != self.reasoning_efforts:
            raise ValueError("catalog reasoning efforts must be sorted")
        if any(not _REASONING_EFFORT.fullmatch(value) for value in self.reasoning_efforts):
            raise ValueError("catalog reasoning effort is invalid")
        if self.replacement_model is not None and (
            not _MODEL_ID.fullmatch(self.replacement_model)
            or _SENSITIVE_MODEL_ID.search(self.replacement_model)
        ):
            raise ValueError("catalog replacement model identifier is invalid")
        for field_name in ("release_at", "sunset_at", "local_modified_at"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, _utc(value, field=field_name))
        if self.sunset_at is not None and self.release_at is not None:
            if self.sunset_at < self.release_at:
                raise ValueError("catalog sunset must not precede release")
        return self


class CatalogSnapshot(BaseModel):
    """Immutable catalog payload whose digest binds every routing-relevant field."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    snapshot_ref: CatalogSnapshotRef
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    transport_id: TransportId
    source_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    fetched_at: datetime
    freshness: Literal["fresh", "stale"]
    models: tuple[CatalogModelDescriptor, ...] = Field(min_length=1, max_length=4096)
    snapshot_hash: Sha256Digest

    @model_validator(mode="after")
    def _validate_snapshot(self) -> "CatalogSnapshot":
        object.__setattr__(self, "fetched_at", _utc(self.fetched_at, field="fetched_at"))
        if len({model.model for model in self.models}) != len(self.models):
            raise ValueError("catalog snapshot contains duplicate model IDs")
        for model in self.models:
            if model.provider != self.provider or self.transport_id not in model.transports:
                raise ValueError("catalog descriptor does not match snapshot provider/transport")
            if model.release_at is not None and model.release_at > self.fetched_at:
                raise ValueError("catalog release time cannot follow the snapshot fetch time")
        if self.snapshot_hash != self.compute_hash():
            raise ValueError("catalog snapshot hash does not match its content")
        return self

    def _hash_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"snapshot_hash"})

    def compute_hash(self) -> str:
        payload = json.dumps(
            self._hash_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(payload).hexdigest()

    @classmethod
    def create(
        cls,
        *,
        provider: str,
        transport_id: str,
        source_id: str,
        fetched_at: datetime,
        models: Iterable[CatalogModelDescriptor],
        freshness: Literal["fresh", "stale"] = "fresh",
    ) -> "CatalogSnapshot":
        normalized_models = tuple(sorted(models, key=lambda item: item.model))
        ref = f"catalog.{provider}_{transport_id}"
        payload: dict[str, Any] = {
            "snapshot_ref": ref,
            "provider": provider,
            "transport_id": transport_id,
            "source_id": source_id,
            "fetched_at": _utc(fetched_at, field="fetched_at"),
            "freshness": freshness,
            "models": normalized_models,
        }
        candidate = cls.model_construct(**payload, snapshot_hash="sha256:" + "0" * 64)
        digest = candidate.compute_hash()
        return cls(**payload, snapshot_hash=digest)

    def with_freshness(self, freshness: Literal["fresh", "stale"]) -> "CatalogSnapshot":
        if self.freshness == freshness:
            return self
        return self.create(
            provider=self.provider,
            transport_id=self.transport_id,
            source_id=self.source_id,
            fetched_at=self.fetched_at,
            models=self.models,
            freshness=freshness,
        )


class CatalogSelectionPolicy(BaseModel):
    """Caller-owned allowlist and capability requirements for one temporary route."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    accepted_models: tuple[str, ...] = Field(min_length=1)
    accepted_transports: tuple[TransportId, ...] = Field(min_length=1)
    required_capabilities: ModelCapabilityRequirements = Field(
        default_factory=ModelCapabilityRequirements
    )
    reasoning_effort: str | None = None
    pinned_model: str

    @model_validator(mode="after")
    def _validate_policy(self) -> "CatalogSelectionPolicy":
        if self.pinned_model not in self.accepted_models:
            raise ValueError("pinned model must be explicitly accepted by policy")
        if len(self.accepted_models) != len(set(self.accepted_models)):
            raise ValueError("accepted model IDs must be unique")
        if len(self.accepted_transports) != len(set(self.accepted_transports)):
            raise ValueError("accepted transports must be unique")
        if self.reasoning_effort is not None and not _REASONING_EFFORT.fullmatch(
            self.reasoning_effort
        ):
            raise ValueError("requested reasoning effort is invalid")
        return self


class CatalogRouteTarget(BaseModel):
    """Exact temporary route plus the catalog version that justified selecting it."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider: str
    model: str
    transport_id: TransportId
    reasoning_effort: str | None
    catalog_snapshot_ref: CatalogSnapshotRef
    catalog_snapshot_hash: Sha256Digest
    capabilities: ModelCapabilities
    literal_system_role_supported: bool


class CatalogCache:
    """Small in-memory cache with a five-minute refresh and one-day stale ceiling."""

    def __init__(
        self,
        *,
        refresh_ttl: timedelta = CATALOG_REFRESH_TTL,
        max_stale_age: timedelta = CATALOG_MAX_STALE_AGE,
    ) -> None:
        if refresh_ttl <= timedelta(0) or max_stale_age < refresh_ttl:
            raise ValueError("catalog freshness bounds are invalid")
        self._refresh_ttl = refresh_ttl
        self._max_stale_age = max_stale_age
        self._snapshots: dict[tuple[str, str], CatalogSnapshot] = {}
        self._lock = threading.Lock()

    def get(
        self,
        *,
        provider: str,
        transport_id: str,
        loader: Callable[[datetime], CatalogSnapshot],
        now: datetime | None = None,
    ) -> CatalogSnapshot:
        fixed_time = _utc(now, field="now") if now is not None else None
        key = (provider, transport_id)
        with self._lock:
            current_time = fixed_time or datetime.now(timezone.utc)
            cached = self._snapshots.get(key)
            if cached is not None:
                age = current_time - cached.fetched_at
                if age < timedelta(0):
                    raise CatalogError("catalog_invalid")
                if age <= self._refresh_ttl:
                    return cached.with_freshness("fresh")

            try:
                refreshed = loader(current_time)
                validation_time = fixed_time or datetime.now(timezone.utc)
                if (
                    refreshed.provider != provider
                    or refreshed.transport_id != transport_id
                    or refreshed.freshness != "fresh"
                    or refreshed.fetched_at > validation_time
                ):
                    raise CatalogError("catalog_invalid")
                self._snapshots[key] = refreshed
                return refreshed
            except CatalogError as exc:
                if exc.code != "catalog_unavailable":
                    raise
                if cached is None:
                    raise
                failure_time = fixed_time or datetime.now(timezone.utc)
                age = failure_time - cached.fetched_at
                if age < timedelta(0) or age > self._max_stale_age:
                    raise CatalogError("catalog_stale") from None
                return cached.with_freshness("stale")
            except Exception:
                # Unexpected adapter or contract failures are not provider outages and
                # must not be hidden by serving a stale route.
                raise CatalogError("catalog_invalid") from None


def select_latest_compatible(
    snapshot: CatalogSnapshot,
    policy: CatalogSelectionPolicy,
    *,
    now: datetime | None = None,
    max_stale_age: timedelta = CATALOG_MAX_STALE_AGE,
) -> CatalogRouteTarget:
    """Select only from caller-approved descriptors and verifiable source order."""

    current_time = _utc(now or datetime.now(timezone.utc), field="now")
    if snapshot.provider != policy.provider:
        raise CatalogError("catalog_invalid")
    age = current_time - snapshot.fetched_at
    if age < timedelta(0) or age > max_stale_age:
        raise CatalogError("catalog_stale")

    required = policy.required_capabilities
    candidates = [
        item
        for item in snapshot.models
        if item.model in policy.accepted_models
        and set(item.transports).intersection(policy.accepted_transports)
        and not item.deprecated
        and (item.sunset_at is None or item.sunset_at > current_time)
        and all(
            not getattr(required, field)
            or bool(getattr(item.capabilities, field))
            for field in (
                "structured_output",
                "native_tools",
                "system_prompt_channel",
                "deterministic_execution",
            )
        )
        and (
            not required.literal_system_role_required
            or item.literal_system_role_supported
        )
        and (
            required.embedding_dimension is None
            or item.capabilities.embedding_dimension == required.embedding_dimension
        )
        and (
            policy.reasoning_effort is None
            or policy.reasoning_effort in item.reasoning_efforts
        )
    ]
    if not candidates:
        raise CatalogError("catalog_unavailable")

    stale = snapshot.freshness == "stale" or age > CATALOG_REFRESH_TTL
    if stale:
        chosen = next((item for item in candidates if item.model == policy.pinned_model), None)
        if chosen is None:
            raise CatalogError("catalog_stale")
        return _route_target(snapshot, chosen, policy)

    chosen_by_time = _newest_by_release_time(candidates)
    chosen_by_replacement = (
        _newest_by_replacement(candidates) if len(candidates) > 1 else None
    )
    if (
        chosen_by_time is not None
        and chosen_by_replacement is not None
        and chosen_by_time.model != chosen_by_replacement.model
    ):
        # Conflicting source evidence must not silently select either target.
        chosen = None
    else:
        chosen = chosen_by_time or chosen_by_replacement
    if chosen is None:
        chosen = next((item for item in candidates if item.model == policy.pinned_model), None)
    if chosen is None:
        raise CatalogError("catalog_unavailable")
    return _route_target(snapshot, chosen, policy)


def _newest_by_release_time(
    candidates: list[CatalogModelDescriptor],
) -> CatalogModelDescriptor | None:
    if any(item.release_at is None for item in candidates):
        return None
    ordered = sorted(candidates, key=lambda item: item.release_at or datetime.min.replace(tzinfo=timezone.utc))
    if len(ordered) > 1 and ordered[-1].release_at == ordered[-2].release_at:
        return None
    return ordered[-1]


def _newest_by_replacement(
    candidates: list[CatalogModelDescriptor],
) -> CatalogModelDescriptor | None:
    by_id = {item.model: item for item in candidates}
    terminals: list[CatalogModelDescriptor] = []
    for candidate in candidates:
        current = candidate
        visited: set[str] = set()
        while True:
            if current.model in visited:
                return None
            visited.add(current.model)
            if current.replacement_model is None:
                terminals.append(current)
                break
            replacement = by_id.get(current.replacement_model)
            if replacement is None:
                return None
            current = replacement
    if not terminals or len({item.model for item in terminals}) != 1:
        return None
    return terminals[0]


def _route_target(
    snapshot: CatalogSnapshot,
    descriptor: CatalogModelDescriptor,
    policy: CatalogSelectionPolicy,
) -> CatalogRouteTarget:
    transport = next(
        item
        for item in descriptor.transports
        if item in policy.accepted_transports
    )
    return CatalogRouteTarget(
        provider=descriptor.provider,
        model=descriptor.model,
        transport_id=transport,
        reasoning_effort=policy.reasoning_effort,
        catalog_snapshot_ref=snapshot.snapshot_ref,
        catalog_snapshot_hash=snapshot.snapshot_hash,
        capabilities=descriptor.capabilities,
        literal_system_role_supported=descriptor.literal_system_role_supported,
    )


__all__ = [
    "CATALOG_MAX_STALE_AGE",
    "CATALOG_REFRESH_TTL",
    "CatalogCache",
    "CatalogError",
    "CatalogModelDescriptor",
    "CatalogRouteTarget",
    "CatalogSelectionPolicy",
    "CatalogSnapshot",
    "select_latest_compatible",
]
