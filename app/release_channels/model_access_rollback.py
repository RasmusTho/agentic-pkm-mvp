"""Pure planning for restoring a previously verified Model Access route.

This module does not write route configuration or perform a deployment. The
release-channel workflow remains the only authority that applies a rollback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Sequence

from app.components.embeddings.legacy import EmbeddingIdentity
from llm_contract import ModelAccessRoute, ModelCapabilities, ModelResolutionRequest


_LOGICAL_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,255}$")
PREFLIGHT_MAX_AGE = timedelta(seconds=30)


class ModelAccessRollbackError(ValueError):
    """No safe, verified, pinned route can satisfy the current request."""


@dataclass(frozen=True)
class PinnedRouteVerification:
    """One pinned route with references to its prior verification and fresh preflight."""

    route: ModelAccessRoute
    path_policy_ref: str
    verification_receipt_ref: str
    verified_at: datetime
    preflight_at: datetime
    pinned: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.route, ModelAccessRoute):
            raise ValueError("rollback route must be a validated ModelAccessRoute")
        for name, value in (
            ("path_policy_ref", self.path_policy_ref),
            ("verification_receipt_ref", self.verification_receipt_ref),
        ):
            if not isinstance(value, str) or _LOGICAL_REF.fullmatch(value) is None:
                raise ValueError(f"{name} must be a safe logical reference")
        if type(self.pinned) is not bool:
            raise ValueError("pinned must be a boolean")
        for name, timestamp in (
            ("verified_at", self.verified_at),
            ("preflight_at", self.preflight_at),
        ):
            if (
                not isinstance(timestamp, datetime)
                or timestamp.tzinfo is None
                or timestamp.utcoffset() is None
            ):
                raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class ModelAccessRollbackPlan:
    """The exact route/path to restore; embedding identity is passed through unchanged."""

    route: ModelAccessRoute
    path_policy_ref: str
    verification_receipt_ref: str
    embedding_identity: EmbeddingIdentity


def _satisfies(
    capabilities: ModelCapabilities,
    request: ModelResolutionRequest,
) -> bool:
    required = request.requirements
    return (
        (
            not (required.structured_output or request.intent.output_schema_ref is not None)
            or capabilities.structured_output
        )
        and (not required.native_tools or capabilities.native_tools)
        and (
            not (required.system_prompt_channel or required.literal_system_role_required)
            or capabilities.system_prompt_channel
        )
        and (
            not (required.deterministic_execution or request.intent.determinism_required)
            or capabilities.deterministic_execution
        )
        and (
            required.embedding_dimension is None
            or capabilities.embedding_dimension == required.embedding_dimension
        )
    )


def plan_model_access_rollback(
    candidates: Sequence[PinnedRouteVerification],
    *,
    current_request: ModelResolutionRequest,
    embedding_identity: EmbeddingIdentity,
    now: datetime | None = None,
    preflight_max_age: timedelta = PREFLIGHT_MAX_AGE,
) -> ModelAccessRollbackPlan:
    """Select the newest verified, pinned, compatible route with fresh preflight.

    The returned plan changes only the completion route and network-path policy.
    The exact current embedding identity is copied through; this helper has no
    embedding reconfiguration authority.
    """

    instant = now or datetime.now(timezone.utc)
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    instant = instant.astimezone(timezone.utc)
    if not isinstance(preflight_max_age, timedelta) or preflight_max_age <= timedelta(0):
        raise ValueError("preflight_max_age must be positive")
    if not isinstance(current_request, ModelResolutionRequest):
        raise ValueError("current_request must use the neutral model-access contract")
    if not isinstance(embedding_identity, EmbeddingIdentity):
        raise ValueError("embedding_identity must be the current embedding identity")

    eligible: list[tuple[PinnedRouteVerification, ModelAccessRoute]] = []
    for candidate in candidates:
        if not isinstance(candidate, PinnedRouteVerification):
            raise ValueError("rollback candidates must be validated pinned-route records")
        if not candidate.pinned:
            continue
        try:
            route = ModelAccessRoute.model_validate(candidate.route.model_dump())
        except ValueError:
            continue
        if route.preflight_status != "passed":
            continue
        verified_at = candidate.verified_at.astimezone(timezone.utc)
        preflight_at = candidate.preflight_at.astimezone(timezone.utc)
        if verified_at > instant or preflight_at > instant:
            continue
        if instant - preflight_at > preflight_max_age:
            continue
        # A passed preflight attests only the exact request it evaluated. Do not
        # rebind that historical receipt to a stronger or otherwise different
        # capability intent, even when the route's declared capability flags fit.
        if route.request != current_request:
            continue
        # A single candidate cannot prove that it differs from a second effective
        # target in the same current resolution group.
        if current_request.intent.independence == "distinct_effective_target":
            continue
        if not _satisfies(route.capabilities, current_request):
            continue
        eligible.append((candidate, route))

    if not eligible:
        raise ModelAccessRollbackError(
            "no fresh, verified, pinned route satisfies the current capability intent"
        )

    latest_verified_at = max(item.verified_at.astimezone(timezone.utc) for item, _route in eligible)
    latest = [
        (item, route)
        for item, route in eligible
        if item.verified_at.astimezone(timezone.utc) == latest_verified_at
    ]
    identities = {(route.model_dump_json(), item.path_policy_ref) for item, route in latest}
    if len(identities) != 1:
        raise ModelAccessRollbackError("latest compatible pinned route is ambiguous")
    selected, rebound_route = min(latest, key=lambda pair: pair[0].verification_receipt_ref)
    return ModelAccessRollbackPlan(
        route=rebound_route,
        path_policy_ref=selected.path_policy_ref,
        verification_receipt_ref=selected.verification_receipt_ref,
        embedding_identity=embedding_identity,
    )


__all__ = [
    "ModelAccessRollbackError",
    "ModelAccessRollbackPlan",
    "PREFLIGHT_MAX_AGE",
    "PinnedRouteVerification",
    "plan_model_access_rollback",
]
