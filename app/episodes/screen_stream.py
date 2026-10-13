"""Normalize consented Heimdal screen observations for the ERE.

The registry declares which axes the screen stream can evidence. Each
published span remains a distinct signal, and confidence is carried only for
axes supported by that observation's confidence block. This module reads no
capture source and never changes consent state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from app.context_dimensions import ContextDimensions
from app.episodes.stream_registry import ConfidenceScore, SignalContract, SignalContractError
from app.heimdal.observation_log import ObservationRow

SCREEN_STREAM_ID = "screen"
SCREEN_CONSUMER_ID = "mimer.episode_resolution_engine.screen"
SCREEN_MODALITY = "screen"
OBSERVATION_TOPIC = "heimdal.observation.published"


class ScreenSignalContractError(ValueError):
    """A published screen observation cannot be admitted as an ERE signal."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _payload(row: ObservationRow) -> Mapping[str, Any] | None:
    envelope = row.envelope
    value = envelope.get("payload") if isinstance(envelope, Mapping) else None
    return value if isinstance(value, Mapping) else None


def observation_modality(row: ObservationRow) -> str | None:
    payload = _payload(row)
    value = payload.get("modality") if payload is not None else None
    return value if isinstance(value, str) else None


def _timestamp(payload: Mapping[str, Any], field: str) -> tuple[str, datetime]:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ScreenSignalContractError(f"missing_{field}")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScreenSignalContractError(f"invalid_{field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ScreenSignalContractError(f"timezone_missing_{field}")
    return text, parsed


def _confidence_score(
    confidence: Mapping[str, Any], axis: str, *, required: bool
) -> ConfidenceScore | None:
    value = confidence.get(axis)
    if value is None and not required:
        return None
    if not isinstance(value, Mapping):
        raise ScreenSignalContractError(f"missing_confidence_axis_{axis}")
    score = value.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise ScreenSignalContractError(f"invalid_confidence_axis_{axis}")
    calibration = value.get("calibration")
    if not isinstance(calibration, str) or not calibration.strip():
        raise ScreenSignalContractError(f"invalid_confidence_calibration_{axis}")
    try:
        return ConfidenceScore(
            score=float(score),
            calibration=calibration,
            method=value.get("method") if isinstance(value.get("method"), str) else None,
            model_ref=value.get("model_ref") if isinstance(value.get("model_ref"), str) else None,
        )
    except (TypeError, ValueError, SignalContractError) as exc:
        raise ScreenSignalContractError(f"invalid_confidence_axis_{axis}") from exc


def screen_dimensions(row: ObservationRow) -> Mapping[str, str]:
    """Return the source span's app/window/scope/goal boundaries."""
    payload = _payload(row)
    if payload is None or payload.get("modality") != SCREEN_MODALITY:
        return {}
    content_structure = payload.get("content_structure")
    span = content_structure.get("span") if isinstance(content_structure, Mapping) else None
    raw = span.get("dimensions") if isinstance(span, Mapping) else None
    if not isinstance(raw, Mapping):
        raise ScreenSignalContractError("missing_span_dimensions")
    result: dict[str, str] = {}
    for key in ("app", "window", "scope", "goal"):
        value = raw.get(key)
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            raise ScreenSignalContractError(f"invalid_span_dimension_{key}")
        result[key] = value
    return result


def screen_observation_to_signal_contract(row: ObservationRow) -> SignalContract | None:
    """Map one published screen span to the declared ERE signal shape.

    Other Heimdal modalities return ``None``. Screen observations must carry
    the existing ``consent.grant_ref`` and span provenance produced by the
    governed Heimdal publish path; the registry does not create consent.
    """
    payload = _payload(row)
    if payload is None or payload.get("modality") != SCREEN_MODALITY:
        return None
    if row.topic != OBSERVATION_TOPIC:
        raise ScreenSignalContractError("unexpected_observation_topic")

    observation_id = payload.get("observation_id")
    if not isinstance(observation_id, str) or not observation_id.strip():
        raise ScreenSignalContractError("missing_observation_id")

    observed_at_start, start = _timestamp(payload, "observed_at_start")
    observed_at_end, end = _timestamp(payload, "observed_at_end")
    if end < start:
        raise ScreenSignalContractError("span_end_before_start")

    consent = payload.get("consent")
    grant_ref = consent.get("grant_ref") if isinstance(consent, Mapping) else None
    if not isinstance(grant_ref, str) or not grant_ref.strip():
        raise ScreenSignalContractError("missing_consent_grant_ref")

    provenance = payload.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ScreenSignalContractError("missing_provenance")
    content_identity = provenance.get("content_identity")
    capture_chain = provenance.get("capture_chain")
    if not isinstance(content_identity, str) or not content_identity.strip():
        raise ScreenSignalContractError("missing_provenance_content_identity")
    if not isinstance(capture_chain, list) or not capture_chain:
        raise ScreenSignalContractError("missing_provenance_capture_chain")

    span = screen_dimensions(row)
    confidence = payload.get("confidence")
    if not isinstance(confidence, Mapping):
        raise ScreenSignalContractError("missing_confidence")

    # A valid span boundary is time evidence by construction. The other axes
    # retain the source's per-axis confidence objects instead of collapsing
    # them into one scalar.
    attribution_confidence = _confidence_score(confidence, "attribution", required=True)
    activity_confidence = _confidence_score(confidence, "activity_summary", required=True)
    # The required=True calls reject missing axes; assert the narrower type
    # explicitly so the contract map cannot accidentally admit None.
    assert attribution_confidence is not None
    assert activity_confidence is not None
    dimensions: dict[str, ConfidenceScore] = {
        "time": ConfidenceScore(
            score=1.0,
            calibration="by_construction",
            method="screen_span_bounds",
        ),
        "protagonist": attribution_confidence,
        "goal": activity_confidence,
    }
    entity_confidence = _confidence_score(confidence, "entity_mention", required=False)
    if entity_confidence is not None and any(span.get(key) for key in ("app", "window", "scope")):
        dimensions["space"] = entity_confidence
    causation_confidence = _confidence_score(confidence, "causation", required=False)
    if causation_confidence is not None:
        dimensions["causation"] = causation_confidence

    emitted_at = row.created_at
    if not isinstance(emitted_at, datetime) or emitted_at.tzinfo is None or emitted_at.utcoffset() is None:
        raise ScreenSignalContractError("invalid_emitted_at")
    scope_hint = payload.get("scope_hint")
    if scope_hint is not None and not isinstance(scope_hint, str):
        raise ScreenSignalContractError("invalid_scope_hint")

    return SignalContract(
        stream_id=SCREEN_STREAM_ID,
        signal_id=observation_id,
        observed_at_start=observed_at_start,
        observed_at_end=observed_at_end,
        emitted_at=emitted_at.isoformat(),
        dimensions_fed=dimensions,
        scope_binding=ContextDimensions(scope=scope_hint) if scope_hint and scope_hint.strip() else None,
        # Keep provenance tied to the published source record rather than to
        # the registry route. SCREEN activation can replay observations that
        # the legacy generic Heimdal consumer already recorded under this
        # identity; `stream_id` remains the modality-specific route.
        provenance_ref=f"heimdal.observations:{observation_id}",
    )


__all__ = [
    "OBSERVATION_TOPIC",
    "SCREEN_CONSUMER_ID",
    "SCREEN_MODALITY",
    "SCREEN_STREAM_ID",
    "ScreenSignalContractError",
    "observation_modality",
    "screen_dimensions",
    "screen_observation_to_signal_contract",
]
