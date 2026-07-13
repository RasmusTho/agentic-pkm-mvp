"""Policy-driven temporal review posture with no artifact or retrieval mutation."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

TRUTH_JUDGMENT_COPY = (
    "Temporal posture is a review-timing signal, not a truth judgment. "
    "It does not change validity, visibility, ranking, or canonical content."
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class TemporalPolicyEntry(_StrictModel):
    kind: Literal["external_source", "external_projection", "historical_external_source"]
    mode: Literal["age_review", "historical"]
    permitted_timestamp_fields: tuple[str, ...] = ()
    review_interval_days: int | None = None
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def _mode_contract(self) -> "TemporalPolicyEntry":
        fields = self.permitted_timestamp_fields
        if len(fields) != len(set(fields)) or any(not field.strip() for field in fields):
            raise ValueError("permitted timestamp fields must be unique and non-empty")
        if self.mode == "age_review":
            if not fields or self.review_interval_days is None or self.review_interval_days < 1:
                raise ValueError("age_review requires fields and a positive interval")
        elif fields or self.review_interval_days is not None:
            raise ValueError("historical mode cannot carry date-aging configuration")
        supported_fields = {
            "external_source": {"source_updated_at", "source_published_at"},
            "external_projection": {"source_observed_at"},
            "historical_external_source": set(),
        }[self.kind]
        if not set(fields).issubset(supported_fields):
            raise ValueError("timestamp field is not permitted for this artifact kind")
        return self


class TemporalPolicy(_StrictModel):
    policy_schema: Literal["temporal-posture-policy.v1"] = Field(alias="schema")
    version: str = Field(pattern=r"^temporal-posture\.v[1-9][0-9]*$")
    owner: str = Field(min_length=1)
    effective_at: datetime
    allowlist: tuple[TemporalPolicyEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _policy_contract(self) -> "TemporalPolicy":
        if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
            raise ValueError("effective_at must be timezone-aware")
        kinds = [entry.kind for entry in self.allowlist]
        if len(kinds) != len(set(kinds)):
            raise ValueError("allowlisted kinds must be unique")
        return self


class TemporalOverlay(_StrictModel):
    posture: Literal["unknown", "historical", "review_due"]
    reason: str = Field(min_length=1)
    evidence_field: str | None = None
    evidence_at: datetime | None = None
    evaluated_at: datetime
    policy_version: str


class TemporalEvaluation(_StrictModel):
    overlay: TemporalOverlay | None = None
    diagnostic: str = Field(min_length=1)
    disclaimer: str = TRUTH_JUDGMENT_COPY


class TemporalCorpusReceipt(_StrictModel):
    policy_version: str
    evaluated_at: datetime
    artifact_count: int
    overlay_count: int
    unknown_count: int
    historical_count: int
    review_due_count: int
    no_overlay_count: int
    diagnostics: dict[str, int]


def _unknown(
    *,
    reason: str,
    evaluated_at: datetime,
    policy_version: str,
    evidence_field: str | None = None,
) -> TemporalEvaluation:
    return TemporalEvaluation(
        overlay=TemporalOverlay(
            posture="unknown",
            reason=reason,
            evidence_field=evidence_field,
            evaluated_at=evaluated_at,
            policy_version=policy_version,
        ),
        diagnostic=reason,
    )


def _parse_permitted_date(value: object) -> tuple[datetime | None, str | None]:
    if not isinstance(value, str) or not value.strip():
        return None, "permitted_date_malformed"
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError:
        return None, "permitted_date_malformed"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None, "permitted_date_timezone_ambiguous"
    return parsed, None


def derive_temporal_posture(
    *,
    artifact: Mapping[str, Any],
    policy: object,
    evaluated_at: datetime,
) -> TemporalEvaluation:
    """Derive secondary presentation metadata from explicit permitted fields only."""

    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        return TemporalEvaluation(diagnostic="evaluation_time_invalid")
    try:
        parsed_policy = TemporalPolicy.model_validate(policy)
    except (ValidationError, TypeError, ValueError):
        return TemporalEvaluation(diagnostic="policy_invalid")
    if parsed_policy.effective_at > evaluated_at:
        return TemporalEvaluation(diagnostic="policy_not_effective")

    kind = artifact.get("kind")
    entry = next((item for item in parsed_policy.allowlist if item.kind == kind), None)
    if entry is None:
        return TemporalEvaluation(diagnostic="kind_not_allowlisted")

    if entry.mode == "historical":
        return TemporalEvaluation(
            overlay=TemporalOverlay(
                posture="historical",
                reason="policy_designated_historical",
                evaluated_at=evaluated_at,
                policy_version=parsed_policy.version,
            ),
            diagnostic="policy_designated_historical",
        )

    evidence_field = next(
        (field for field in entry.permitted_timestamp_fields if field in artifact), None
    )
    if evidence_field is None:
        return _unknown(
            reason="permitted_date_missing",
            evaluated_at=evaluated_at,
            policy_version=parsed_policy.version,
        )
    evidence_at, error = _parse_permitted_date(artifact[evidence_field])
    if error is not None or evidence_at is None:
        return _unknown(
            reason=error or "permitted_date_malformed",
            evidence_field=evidence_field,
            evaluated_at=evaluated_at,
            policy_version=parsed_policy.version,
        )
    if evidence_at > evaluated_at:
        return _unknown(
            reason="permitted_date_in_future",
            evidence_field=evidence_field,
            evaluated_at=evaluated_at,
            policy_version=parsed_policy.version,
        )

    interval = timedelta(days=entry.review_interval_days or 0)
    if evaluated_at - evidence_at < interval:
        return TemporalEvaluation(diagnostic="review_not_due")
    return TemporalEvaluation(
        overlay=TemporalOverlay(
            posture="review_due",
            reason="policy_review_interval_elapsed",
            evidence_field=evidence_field,
            evidence_at=evidence_at,
            evaluated_at=evaluated_at,
            policy_version=parsed_policy.version,
        ),
        diagnostic="policy_review_interval_elapsed",
    )


def render_temporal_signals(
    evaluation: TemporalEvaluation,
    *,
    source_index_drift: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Render independent time-review and source/index-drift signals."""

    return {
        "copy": evaluation.disclaimer,
        "temporal_posture": (
            evaluation.overlay.model_dump(mode="json") if evaluation.overlay is not None else None
        ),
        "source_index_drift": dict(source_index_drift) if source_index_drift is not None else None,
    }


def summarize_temporal_corpus(
    *,
    artifacts: Sequence[Mapping[str, Any]],
    policy: object,
    evaluated_at: datetime,
) -> TemporalCorpusReceipt:
    """Return a content-free, fixed-clock report without altering the input corpus."""

    evaluations = [
        derive_temporal_posture(artifact=artifact, policy=policy, evaluated_at=evaluated_at)
        for artifact in artifacts
    ]
    diagnostics = Counter(item.diagnostic for item in evaluations)
    postures = Counter(item.overlay.posture for item in evaluations if item.overlay is not None)
    try:
        policy_version = TemporalPolicy.model_validate(policy).version
    except (ValidationError, TypeError, ValueError):
        policy_version = "invalid"
    return TemporalCorpusReceipt(
        policy_version=policy_version,
        evaluated_at=evaluated_at,
        artifact_count=len(artifacts),
        overlay_count=sum(postures.values()),
        unknown_count=postures["unknown"],
        historical_count=postures["historical"],
        review_due_count=postures["review_due"],
        no_overlay_count=len(artifacts) - sum(postures.values()),
        diagnostics=dict(sorted(diagnostics.items())),
    )


__all__ = [
    "TRUTH_JUDGMENT_COPY",
    "TemporalCorpusReceipt",
    "TemporalEvaluation",
    "TemporalOverlay",
    "TemporalPolicy",
    "TemporalPolicyEntry",
    "derive_temporal_posture",
    "render_temporal_signals",
    "summarize_temporal_corpus",
]
