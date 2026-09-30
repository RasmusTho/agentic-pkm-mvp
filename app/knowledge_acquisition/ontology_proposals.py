"""Deterministic ontology relevance gate and proposal validation (YSNV2-08).

Ontology-shaped output carries high authority pressure, so this module keeps it narrowly
proposal-class:

- ``evaluate_ontology_gate`` is a deterministic, model-free check over normalized transcript
  segments. It passes only when at least ``min_distinct_families`` qualifying signal families
  each occur in at least ``min_anchored_repetitions`` distinct, time-bounded segments. A failed
  gate means the ontology section is omitted entirely; no low-confidence filler is produced.
- ``validate_ontology_element`` accepts one model-produced element only when every anchor
  resolves, any ``source_definition`` is present verbatim in the anchored source text (so it
  stays in the original language and is never a translation), and ``system_paraphrase`` follows
  D6. Accepted elements are stamped ``status: proposed`` with explicit wording classes.
- ``render_ontology_proposals`` re-applies the gate and element validation at the rendering
  boundary, so a stale or tampered extraction output cannot acquire standing in a note.

This module performs no persistence, vault, concept, relation, or review-state writes. Nothing
here can promote a proposal; promotion into SIP ontology is out of scope for this capability.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Mapping

from app.knowledge_acquisition.evidence_synthesis import (
    caption_quality_confidence_cap,
    system_language_for,
    validate_generated_language,
    validate_resolvable_anchor,
)

ARTIFACT_CLASS = "ontology_proposal"
PROPOSAL_STATUS = "proposed"
WORDING_CLASS_SOURCE_DEFINITION = "source_definition"
WORDING_CLASS_SYSTEM_PARAPHRASE = "system_paraphrase"
ELEMENT_KINDS: tuple[str, ...] = (
    "concept",
    "relation",
    "distinction",
    "mapping",
    "alternative_interpretation",
    "competency_question",
)


def _patterns(*phrases: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)") for phrase in phrases)


# Closed, reviewable lexical cue sets (English and Swedish, the two D6 languages). Matching is
# case-insensitive on whole phrases; the gate never consults a model.
SIGNAL_FAMILIES: Mapping[str, tuple[re.Pattern[str], ...]] = {
    "definition": _patterns(
        "is defined as", "are defined as", "we define", "definition of", "refers to",
        "is called", "are called", "what we call",
        "definieras som", "definitionen av", "syftar på", "avser", "kallas för", "kallas",
    ),
    "taxonomy": _patterns(
        "is a type of", "is a kind of", "types of", "kinds of", "is a category of",
        "subcategory", "subtype", "is an instance of",
        "är en typ av", "typer av", "sorters", "är en kategori av", "underkategori",
    ),
    "relation": _patterns(
        "is part of", "consists of", "is composed of", "depends on", "leads to",
        "is caused by", "belongs to",
        "är en del av", "består av", "beror på", "leder till", "orsakas av", "tillhör",
    ),
    "distinction": _patterns(
        "differs from", "is different from", "distinguish between", "the difference between",
        "as opposed to", "in contrast to", "not to be confused with",
        "skiljer sig från", "skillnaden mellan", "till skillnad från", "i motsats till",
        "inte att förväxla med",
    ),
}


@dataclass(frozen=True)
class OntologyGateConfig:
    min_distinct_families: int = 2
    min_anchored_repetitions: int = 2


DEFAULT_GATE_CONFIG = OntologyGateConfig()


@dataclass(frozen=True)
class OntologyGateResult:
    passed: bool
    family_segments: Mapping[str, tuple[int, ...]]
    qualifying_families: tuple[str, ...]
    config: OntologyGateConfig

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "family_segments": {k: list(v) for k, v in sorted(self.family_segments.items())},
            "qualifying_families": list(self.qualifying_families),
            "min_distinct_families": self.config.min_distinct_families,
            "min_anchored_repetitions": self.config.min_anchored_repetitions,
        }


@dataclass(frozen=True)
class RenderedOntology:
    """Validated, render-safe ontology proposals plus visible omissions."""

    gate: OntologyGateResult
    elements: tuple[Mapping[str, Any], ...]
    dropped: tuple[str, ...]


def evaluate_ontology_gate(
    normalized: Mapping[str, Any], *, config: OntologyGateConfig = DEFAULT_GATE_CONFIG
) -> OntologyGateResult:
    """Count each signal family once per distinct, time-bounded (anchorable) segment."""

    segments = normalized.get("segments")
    if not isinstance(segments, list):
        segments = []
    hits: dict[str, list[int]] = {family: [] for family in SIGNAL_FAMILIES}
    for index, segment in enumerate(segments):
        if not isinstance(segment, Mapping) or not isinstance(segment.get("text"), str):
            continue
        start, end = segment.get("start"), segment.get("end")
        if not validate_resolvable_anchor(
            {"segment_index": index, "start": start, "end": end}, segments
        ):
            continue
        text = " ".join(segment["text"].casefold().split())
        for family, patterns in SIGNAL_FAMILIES.items():
            if any(pattern.search(text) for pattern in patterns):
                hits[family].append(index)
    qualifying = tuple(
        family
        for family in SIGNAL_FAMILIES
        if len(hits[family]) >= max(1, config.min_anchored_repetitions)
    )
    passed = len(qualifying) >= max(1, config.min_distinct_families)
    return OntologyGateResult(
        passed=passed,
        family_segments={family: tuple(indices) for family, indices in hits.items() if indices},
        qualifying_families=qualifying,
        config=config,
    )


def validate_ontology_element(
    element: Mapping[str, Any], normalized: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(proposal, None)`` for an acceptable element or ``(None, reason)``.

    Accepts either the model's raw element shape or an already-stamped proposal, so the same
    checks run at extraction and again at rendering.
    """

    if not isinstance(element, Mapping):
        return None, "element is not an object"
    kind = element.get("kind")
    if kind not in ELEMENT_KINDS:
        return None, "unknown element kind"
    if "status" in element and element.get("status") != PROPOSAL_STATUS:
        return None, "element status is not proposed"
    segments = normalized.get("segments")
    if not isinstance(segments, list):
        segments = []
    anchors = element.get("anchors")
    if not isinstance(anchors, list) or not anchors:
        return None, "element has no anchors"
    if not all(isinstance(a, Mapping) and validate_resolvable_anchor(a, segments) for a in anchors):
        return None, "element anchor is not resolvable"

    definition_ok, source_definition = _wording_text(
        element.get("source_definition"), WORDING_CLASS_SOURCE_DEFINITION
    )
    paraphrase_ok, paraphrase = _wording_text(
        element.get("system_paraphrase"), WORDING_CLASS_SYSTEM_PARAPHRASE
    )
    if not definition_ok or not paraphrase_ok:
        return None, "element wording class is invalid"
    if not isinstance(paraphrase, str) or not paraphrase.strip():
        return None, "system_paraphrase is required"
    if source_definition is not None:
        # Verbatim means a case-preserving span of one anchored segment, not a span stitched
        # across segments and not a re-cased or translated rendering.
        wording = _squash_space(source_definition)
        if not wording or not any(
            wording in _squash_space(str(segments[a["segment_index"]].get("text", "")))
            for a in anchors
        ):
            return None, "source_definition is not verbatim anchored source wording"
        if _squash(source_definition) == _squash(paraphrase):
            return None, "source_definition and system_paraphrase must remain distinct"
    system_language = system_language_for(normalized.get("language"))
    if not validate_generated_language(paraphrase, system_language):
        return None, "system_paraphrase language is not allowed by D6"
    confidence = element.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence):
        return None, "confidence must be a finite number"
    bounded = min(max(0.0, float(confidence)), caption_quality_confidence_cap(normalized.get("acquisition_method")))

    source_language = str(normalized.get("language") or "und")
    return {
        "kind": kind,
        "status": PROPOSAL_STATUS,
        "source_definition": (
            None
            if source_definition is None
            else {
                "wording_class": WORDING_CLASS_SOURCE_DEFINITION,
                "text": source_definition,
                "language": source_language,
            }
        ),
        "system_paraphrase": {
            "wording_class": WORDING_CLASS_SYSTEM_PARAPHRASE,
            "text": paraphrase,
            "language": system_language,
        },
        "confidence": bounded,
        "anchors": [
            {
                "segment_index": int(anchor["segment_index"]),
                "start": float(anchor["start"]),
                "end": float(anchor["end"]),
            }
            for anchor in anchors
        ],
    }, None


def render_ontology_proposals(
    output: Mapping[str, Any] | None,
    normalized: Mapping[str, Any],
    *,
    config: OntologyGateConfig = DEFAULT_GATE_CONFIG,
) -> RenderedOntology | None:
    """Return render-safe proposals, or ``None`` when the section must be omitted."""

    if output is None:
        return None
    gate = evaluate_ontology_gate(normalized, config=config)
    if not gate.passed or output.get("artifact_class") != ARTIFACT_CLASS:
        return None
    elements: list[Mapping[str, Any]] = []
    dropped: list[str] = []
    proposals = output.get("proposals")
    for element in proposals if isinstance(proposals, list) else ():
        proposal, reason = validate_ontology_element(element, normalized)
        if proposal is None:
            dropped.append(str(reason))
        else:
            elements.append(proposal)
    if not elements:
        return None
    return RenderedOntology(gate=gate, elements=tuple(elements), dropped=tuple(dropped))


def ontology_section_content(rendered: RenderedOntology) -> str:
    families = ", ".join(
        f"{family}×{len(rendered.gate.family_segments[family])}"
        for family in rendered.gate.qualifying_families
    )
    lines = [
        "**Standing:** every item below is `proposed` ontology material for review. It is not "
        "canonical, and no concept, relation, or review state was created or changed.",
        f"**Relevance gate:** passed ({families}).",
    ]
    for element in rendered.elements:
        definition = element["source_definition"]
        paraphrase = element["system_paraphrase"]
        lines.append(
            f"- **{element['kind']}** · status `{element['status']}` · confidence {element['confidence']:g}"
        )
        if definition is not None:
            lines.append(
                f"  **Source definition** (`{definition['wording_class']}`, {definition['language']}): "
                f"{definition['text']}"
            )
        lines.append(
            f"  **System paraphrase** (`{paraphrase['wording_class']}`, {paraphrase['language']}): "
            f"{paraphrase['text']}"
        )
        lines.append(f"  **Anchors:** {element['anchors']}")
    if rendered.dropped:
        lines.append(
            "**Omitted unsupported ontology items:** " + "; ".join(rendered.dropped)
        )
    return "\n".join(lines)


def _wording_text(value: object, wording_class: str) -> tuple[bool, str | None]:
    """Return ``(valid, text)``; ``text`` is ``None`` when the field is absent."""

    if value is None:
        return True, None
    if isinstance(value, str):
        return True, value
    if isinstance(value, Mapping):
        text = value.get("text")
        if value.get("wording_class") == wording_class and isinstance(text, str):
            return True, text
    return False, None


def _squash(text: str) -> str:
    return " ".join(text.casefold().split())


def _squash_space(text: str) -> str:
    return " ".join(text.split())


__all__ = [
    "ARTIFACT_CLASS",
    "DEFAULT_GATE_CONFIG",
    "ELEMENT_KINDS",
    "OntologyGateConfig",
    "OntologyGateResult",
    "PROPOSAL_STATUS",
    "RenderedOntology",
    "SIGNAL_FAMILIES",
    "evaluate_ontology_gate",
    "ontology_section_content",
    "render_ontology_proposals",
    "validate_ontology_element",
]
