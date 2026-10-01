"""Conservative, inspectable content router for YouTube source notes (YSNV2-07).

The router is an input to module composition, never a replacement renderer. It is a
deterministic, model-free scan of normalized transcript segments against closed, reviewable cue
tables (English and Swedish, the two D6 languages):

- a profile is admitted only when its cues occur in at least ``min_evidence_segments`` distinct,
  time-bounded (anchorable) segments spanning at least ``min_cue_families`` cue families and at
  least ``min_segment_share`` of the anchorable segments;
- at most ``MAX_PROFILES`` (two) admitted profiles are returned, ranked by score;
- every admitted profile carries its anchored evidence so the decision is inspectable;
- insufficient evidence, or any exception while routing, yields the generic spine
  (``profiles == ()``) with an explicit ``fallback_reason``. Routing never raises.

This module performs no persistence, vault, or model calls.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence

from app.knowledge_acquisition.evidence_synthesis import validate_resolvable_anchor

GENERIC_PROFILE = "generic"
MAX_PROFILES = 2
FALLBACK_INSUFFICIENT = "insufficient_confidence"
FALLBACK_FAILED = "routing_failed"


def _patterns(*phrases: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)") for phrase in phrases)


@dataclass(frozen=True)
class ProfileDefinition:
    """One routable content profile: a closed table of cue families."""

    profile_id: str
    cue_families: Mapping[str, tuple[re.Pattern[str], ...]]


@dataclass(frozen=True)
class RouterConfig:
    min_cue_families: int = 2
    min_evidence_segments: int = 3
    min_segment_share: float = 0.25
    max_profiles: int = MAX_PROFILES

    def __post_init__(self) -> None:
        if self.max_profiles < 1:
            raise ValueError("max_profiles must be at least 1")
        if self.min_cue_families < 2:
            raise ValueError("min_cue_families must be at least 2 for a conservative route")
        if self.min_evidence_segments < 2:
            raise ValueError("min_evidence_segments must be at least 2")
        if not 0.0 < self.min_segment_share <= 1.0:
            raise ValueError("min_segment_share must be in (0, 1]")


DEFAULT_ROUTER_CONFIG = RouterConfig()

DECISION_FRAMEWORK = ProfileDefinition(
    profile_id="decision_framework",
    cue_families={
        "options": _patterns(
            "option", "options", "alternative", "alternatives", "choose between", "either",
            "alternativ", "alternativen", "välja mellan", "antingen",
        ),
        "criteria": _patterns(
            "criteria", "criterion", "trade-off", "trade-offs", "tradeoff", "tradeoffs",
            "pros and cons", "weigh", "kriterier", "kriterium", "avvägning", "avvägningen",
            "för- och nackdelar", "väga",
        ),
        "decision": _patterns(
            "decide", "decision", "framework", "rule of thumb", "beslut", "besluta",
            "ramverk", "ramverket", "tumregel",
        ),
    },
)
DOCUMENTARY_SCIENCE = ProfileDefinition(
    profile_id="documentary_science",
    cue_families={
        "evidence": _patterns(
            "study", "studies", "research", "researchers", "scientists", "evidence",
            "studie", "studien", "forskning", "forskare", "forskarna", "belägg",
        ),
        "method": _patterns(
            "measured", "measurement", "sample", "method", "experiment", "control group", "data",
            "mätte", "mätning", "urval", "metod", "metoden", "kontrollgrupp", "kontrollgruppen",
        ),
        "findings": _patterns(
            "found that", "results show", "suggests that", "uncertain", "hypothesis", "theory",
            "visade att", "resultaten visar", "tyder på", "osäker", "osäkert", "hypotes", "teori",
        ),
    },
)
INITIAL_PROFILES: tuple[ProfileDefinition, ...] = (DECISION_FRAMEWORK, DOCUMENTARY_SCIENCE)


@dataclass(frozen=True)
class ProfileEvidence:
    """One anchored segment supporting a profile, with the cue family it matched."""

    segment_index: int
    start: float
    end: float
    cue_family: str


@dataclass(frozen=True)
class RankedProfile:
    profile_id: str
    score: float
    cue_families: tuple[str, ...]
    evidence: tuple[ProfileEvidence, ...]


@dataclass(frozen=True)
class ContentRoute:
    """Ranked admitted profiles, or the generic spine with an explicit reason."""

    profiles: tuple[RankedProfile, ...]
    fallback_reason: str | None = None

    @property
    def is_generic(self) -> bool:
        return not self.profiles

    @property
    def failed(self) -> bool:
        return bool(self.fallback_reason and self.fallback_reason.startswith(FALLBACK_FAILED))

    def frontmatter(self) -> dict[str, Any]:
        value: dict[str, Any] = {"profiles": [p.profile_id for p in self.profiles]}
        if self.is_generic:
            value["fallback"] = FALLBACK_FAILED if self.failed else self.fallback_reason
        return value

    def describe(self) -> str:
        if self.is_generic:
            return f"{GENERIC_PROFILE} ({self.fallback_reason})"
        return "; ".join(
            f"{p.profile_id} (score {p.score:.2f}; cues {','.join(p.cue_families)}; segments "
            f"{','.join(str(i) for i in sorted({e.segment_index for e in p.evidence}))})"
            for p in self.profiles
        )


def route_content(
    normalized: Mapping[str, Any],
    *,
    profiles: Sequence[ProfileDefinition] = INITIAL_PROFILES,
    config: RouterConfig = DEFAULT_ROUTER_CONFIG,
) -> ContentRoute:
    """Return at most two ranked, evidence-bearing profiles; otherwise generic. Never raises."""

    try:
        segments = normalized.get("segments") if isinstance(normalized, Mapping) else None
        if not isinstance(segments, list):
            segments = []
        anchorable = _anchorable_segments(segments)
        if not anchorable:
            return ContentRoute(profiles=(), fallback_reason=FALLBACK_INSUFFICIENT)
        admitted: list[RankedProfile] = []
        for profile in profiles:
            ranked = _score_profile(profile, anchorable, len(anchorable), config)
            if ranked is not None:
                admitted.append(ranked)
        admitted.sort(key=lambda p: (-p.score, p.profile_id))
        bounded = tuple(admitted[: min(config.max_profiles, MAX_PROFILES)])
        if not bounded:
            return ContentRoute(profiles=(), fallback_reason=FALLBACK_INSUFFICIENT)
        return ContentRoute(profiles=bounded)
    except Exception as exc:  # noqa: BLE001 - routing failure degrades to the generic spine
        return ContentRoute(profiles=(), fallback_reason=f"{FALLBACK_FAILED}: {type(exc).__name__}")


def _anchorable_segments(segments: list[Any]) -> tuple[tuple[int, float, float, str], ...]:
    usable: list[tuple[int, float, float, str]] = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, Mapping) or not isinstance(segment.get("text"), str):
            continue
        start, end = segment.get("start"), segment.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue
        if not validate_resolvable_anchor({"segment_index": index, "start": start, "end": end}, segments):
            continue
        usable.append((index, float(start), float(end), " ".join(segment["text"].casefold().split())))
    return tuple(usable)


def _score_profile(
    profile: ProfileDefinition,
    anchorable: Sequence[tuple[int, float, float, str]],
    total: int,
    config: RouterConfig,
) -> RankedProfile | None:
    evidence: list[ProfileEvidence] = []
    for index, start, end, text in anchorable:
        for family, patterns in profile.cue_families.items():
            if any(pattern.search(text) for pattern in patterns):
                evidence.append(ProfileEvidence(index, start, end, family))
    families = tuple(f for f in profile.cue_families if any(e.cue_family == f for e in evidence))
    segment_count = len({e.segment_index for e in evidence})
    score = segment_count / total if total else 0.0
    if (
        len(families) < config.min_cue_families
        or segment_count < config.min_evidence_segments
        or score < config.min_segment_share
    ):
        return None
    return RankedProfile(
        profile_id=profile.profile_id,
        score=score,
        cue_families=families,
        evidence=tuple(evidence),
    )


__all__ = [
    "DECISION_FRAMEWORK",
    "DEFAULT_ROUTER_CONFIG",
    "DOCUMENTARY_SCIENCE",
    "FALLBACK_FAILED",
    "FALLBACK_INSUFFICIENT",
    "GENERIC_PROFILE",
    "INITIAL_PROFILES",
    "MAX_PROFILES",
    "ContentRoute",
    "ProfileDefinition",
    "ProfileEvidence",
    "RankedProfile",
    "RouterConfig",
    "route_content",
]
