"""Initial content-sensitive note modules for YouTube source notes (YSNV2-07).

A module is an optional, evidence-bearing addition beneath the shared proposals wrapper. It never
replaces the universal spine (synthesis, claims, evidence and lineage) and never creates a second
note shape: it only yields ``ProposalSection`` values that ``render_review_required_note``
blockquotes inside the one non-authoritative proposal band.

Rules this module enforces:

- a module renders only for a profile the content router admitted, and only the sections that
  have anchored source evidence; absent sections are omitted, never filled;
- each item is a verbatim, anchored source excerpt in its original language, presented as a
  quotation; system-generated prose (titles and lead line) follows D6 — English unless the source
  is Swedish-original, then Swedish;
- an item the renderer's authority lint would refuse is dropped and counted, not rendered;
- any other module failure is captured as a ``ModuleFailure`` so the note renders generically and
  visibly degraded; required evidence already rendered by the spine is never removed.

This module performs no persistence, vault, or model calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.knowledge_acquisition.content_router import ContentRoute, RankedProfile
from app.knowledge_acquisition.evidence_synthesis import system_language_for
from app.knowledge_acquisition.note_renderer import (
    NoteRenderError,
    ProposalSection,
    validate_proposal_section,
)

MAX_ITEMS_PER_SECTION = 5


@dataclass(frozen=True)
class ModuleSectionDefinition:
    cue_family: str
    titles: Mapping[str, str]


@dataclass(frozen=True)
class ModuleDefinition:
    module_id: str
    profile_id: str
    titles: Mapping[str, str]
    sections: tuple[ModuleSectionDefinition, ...]


DECISION_FRAMEWORK_MODULE = ModuleDefinition(
    module_id="decision_framework",
    profile_id="decision_framework",
    titles={"en": "Decision framework", "sv": "Beslutsramverk"},
    sections=(
        ModuleSectionDefinition("options", {"en": "Options considered", "sv": "Alternativ som övervägs"}),
        ModuleSectionDefinition(
            "criteria", {"en": "Criteria and trade-offs", "sv": "Kriterier och avvägningar"}
        ),
        ModuleSectionDefinition("decision", {"en": "Decision rules", "sv": "Beslutsregler"}),
    ),
)
DOCUMENTARY_SCIENCE_MODULE = ModuleDefinition(
    module_id="documentary_science",
    profile_id="documentary_science",
    titles={"en": "Documentary science", "sv": "Dokumentär vetenskap"},
    sections=(
        ModuleSectionDefinition("evidence", {"en": "Evidence presented", "sv": "Presenterade belägg"}),
        ModuleSectionDefinition("method", {"en": "Methods and measurement", "sv": "Metod och mätning"}),
        ModuleSectionDefinition(
            "findings", {"en": "Findings and uncertainty", "sv": "Resultat och osäkerhet"}
        ),
    ),
)
INITIAL_MODULES: tuple[ModuleDefinition, ...] = (DECISION_FRAMEWORK_MODULE, DOCUMENTARY_SCIENCE_MODULE)

_LEAD = {
    "en": (
        "Source excerpts matched by the conservative content router. Quotations keep the "
        "original source wording and are not translated (source language: {language})."
    ),
    "sv": (
        "Utdrag ur källan som matchats av den försiktiga innehållsroutern. Citaten behåller "
        "källans ursprungliga ordalydelse och översätts inte (källspråk: {language})."
    ),
}
_DEGRADED_TITLE = {"en": "Degraded content modules", "sv": "Degraderade innehållsmoduler"}
_DEGRADED_ITEM = {
    "en": "Content module `{module_id}` could not be rendered and was omitted; the generic note remains intact.",
    "sv": "Innehållsmodulen `{module_id}` kunde inte renderas och utelämnades; den generiska anteckningen är intakt.",
}
_ROUTING_FAILED_TITLE = {"en": "Content routing failed", "sv": "Innehållsroutningen misslyckades"}
_ROUTING_FAILED_BODY = {
    "en": "Content routing failed ({reason}); this note uses the generic layout without content modules.",
    "sv": "Innehållsroutningen misslyckades ({reason}); anteckningen använder den generiska layouten utan innehållsmoduler.",
}


@dataclass(frozen=True)
class ModuleFailure:
    module_id: str
    reason: str


@dataclass(frozen=True)
class RenderedModules:
    """Composed module sections plus visible degradation details."""

    sections: tuple[ProposalSection, ...]
    failures: tuple[ModuleFailure, ...]
    omitted_items: int
    system_language: str


def lead_text(system_language: str, source_language: str) -> str:
    return _LEAD[_d6(system_language)].format(language=source_language)


def compose_note_modules(route: ContentRoute | None, normalized: Mapping[str, Any]) -> RenderedModules:
    """Compose modules for routed profiles; a failing module is reported, never raised."""

    system_language = system_language_for(normalized.get("language"))
    sections: list[ProposalSection] = []
    failures: list[ModuleFailure] = []
    omitted = 0
    for ranked in route.profiles if route is not None else ():
        module = next((m for m in INITIAL_MODULES if m.profile_id == ranked.profile_id), None)
        if module is None:
            continue
        try:
            built, dropped = _build_module_sections(module, ranked, normalized)
        except Exception as exc:  # noqa: BLE001 - optional module failure degrades visibly
            failures.append(ModuleFailure(module.module_id, f"{type(exc).__name__}: {exc}"))
            continue
        sections.extend(built)
        omitted += dropped
    return RenderedModules(
        sections=tuple(sections),
        failures=tuple(failures),
        omitted_items=omitted,
        system_language=system_language,
    )


def degradation_sections(route: ContentRoute | None, modules: RenderedModules | None) -> tuple[ProposalSection, ...]:
    """Visible, D6-language markers for routing or module failure."""

    language = modules.system_language if modules is not None else "en"
    sections: list[ProposalSection] = []
    if route is not None and route.failed:
        sections.append(
            ProposalSection(
                module_id="content-routing-failed",
                title=_ROUTING_FAILED_TITLE[language],
                content=_ROUTING_FAILED_BODY[language].format(reason=route.fallback_reason),
            )
        )
    if modules is not None and modules.failures:
        sections.append(
            ProposalSection(
                module_id="content-module-gaps",
                title=_DEGRADED_TITLE[language],
                content="\n".join(
                    "- " + _DEGRADED_ITEM[language].format(module_id=failure.module_id)
                    for failure in modules.failures
                ),
            )
        )
    return tuple(sections)


def _build_module_sections(
    module: ModuleDefinition, ranked: RankedProfile, normalized: Mapping[str, Any]
) -> tuple[tuple[ProposalSection, ...], int]:
    language = system_language_for(normalized.get("language"))
    source_language = str(normalized.get("language") or "und")
    segments = normalized.get("segments")
    if not isinstance(segments, list):
        raise ValueError("normalized segments are required for module rendering")
    built: list[ProposalSection] = []
    omitted = 0
    for definition in module.sections:
        module_id = f"module.{module.module_id}.{definition.cue_family}"
        title = f"{module.titles[language]} — {definition.titles[language]}"
        items: list[str] = []
        seen: set[int] = set()
        for evidence in ranked.evidence:
            if evidence.cue_family != definition.cue_family or evidence.segment_index in seen:
                continue
            seen.add(evidence.segment_index)
            text = " ".join(str(segments[evidence.segment_index].get("text", "")).split())
            item = f"- `[{_timestamp(evidence.start)}–{_timestamp(evidence.end)}]` “{text}”"
            try:
                validate_proposal_section(ProposalSection(module_id=module_id, title=title, content=item))
            except NoteRenderError:
                omitted += 1
                continue
            items.append(item)
            if len(items) >= MAX_ITEMS_PER_SECTION:
                break
        if not items:
            continue
        section = ProposalSection(
            module_id=module_id,
            title=title,
            # The lead line is stated once per module, on its first rendered section.
            content=("" if built else lead_text(language, source_language) + "\n\n")
            + "\n".join(items),
        )
        validate_proposal_section(section)
        built.append(section)
    return tuple(built), omitted


def _timestamp(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def _d6(language: str) -> str:
    return "sv" if language == "sv" else "en"


__all__ = [
    "DECISION_FRAMEWORK_MODULE",
    "DOCUMENTARY_SCIENCE_MODULE",
    "INITIAL_MODULES",
    "MAX_ITEMS_PER_SECTION",
    "ModuleDefinition",
    "ModuleFailure",
    "ModuleSectionDefinition",
    "RenderedModules",
    "compose_note_modules",
    "degradation_sections",
    "lead_text",
]
