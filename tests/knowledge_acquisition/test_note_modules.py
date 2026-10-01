"""Contract tests for the initial content modules (YSNV2-07, #4114).

Every enforcement test drives the production path: a raw record through ``assemble_candidate``
(normalize -> route -> compose modules) and ``render_candidate_note`` / ``write_candidate_note``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from app.knowledge_acquisition import note_modules
from app.knowledge_acquisition.candidate_writeback import (
    assemble_candidate,
    render_candidate_note,
    write_candidate_note,
)
from app.knowledge_acquisition.evidence_synthesis import validate_generated_language
from app.knowledge_acquisition.extraction_registry import ExtractionResult
from app.knowledge_acquisition.note_renderer import (
    EVIDENCE_HEADING,
    OWNER_NOTES_HEADING,
    PROPOSALS_HEADING,
)
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard

# Options + decision rules, but no criteria/trade-off cue: the criteria section must be omitted.
DECISION_LINES = (
    "There are two options on the table today.",
    "The first alternative is to rent, the other is to buy.",
    "Here is the framework I use to decide.",
    "My rule of thumb is to decide within a week.",
    "Thanks for watching.",
)
SCIENCE_LINES = (
    "A new study followed ten thousand people.",
    "The researchers measured sleep with wrist sensors.",
    "The data from the control group looked different.",
    "They found that short sleep raised risk.",
    "The results show a clear pattern, but the hypothesis is still uncertain.",
)
SWEDISH_DECISION_LINES = (
    "Det finns två alternativ att välja mellan.",
    "Mina kriterier är kostnad och risk.",
    "Avvägningen handlar om trygghet mot frihet.",
    "Här är ramverket jag använder för mitt beslut.",
)
GENERIC_LINES = (
    "Welcome back to the channel.",
    "Today we cook pasta with tomatoes.",
    "Enjoy your meal.",
)


def _vtt(lines: tuple[str, ...]) -> str:
    cues = [
        f"00:00:{2 * i:02d}.000 --> 00:00:{2 * i + 2:02d}.000\n{line}\n"
        for i, line in enumerate(lines)
    ]
    return "WEBVTT\n\n" + "\n".join(cues)


def _raw(lines: tuple[str, ...], *, language: str = "en", identity: str = "sha256:modules") -> dict:
    return {
        "source_kind": "youtube_url",
        "item_ref": "modules-video",
        "url": "https://youtube.com/watch?v=modules-video",
        "content_identity": identity,
        "acquisition_method": "captions_manual",
        "caption_language": language,
        "caption_body": _vtt(lines),
        "metadata": {"title": "Modules fixture", "channel": "Fixture", "publish_date": "20260101", "chapters": []},
        "provenance": {"source_kind": "youtube_url", "url": "https://youtube.com/watch?v=modules-video"},
    }


def _required_evidence(identity: str, *, sentence: str, wording: str, paraphrase: str) -> tuple[ExtractionResult, ...]:
    anchor = {"segment_index": 0, "start": 0.0, "end": 2.0}
    lineage = {"provider": "fixture", "model": "fixture"}
    return (
        ExtractionResult(
            extractor_id="synthesis",
            extractor_version=1,
            source_content_identity=identity,
            output={"synthesis_sentences": [{"text": sentence, "anchors": [anchor]}], "model_confidence": 0.8},
            model_identity=lineage,
            artifact_id="ext-synthesis",
        ),
        ExtractionResult(
            extractor_id="claims",
            extractor_version=1,
            source_content_identity=identity,
            output={"claims": [{"source_wording": wording, "system_paraphrase": paraphrase, "anchors": [anchor]}]},
            model_identity=lineage,
            artifact_id="ext-claims",
        ),
    )


def _english_candidate(lines: tuple[str, ...], identity: str):
    return assemble_candidate(
        _raw(lines, identity=identity),
        extraction_results=_required_evidence(
            identity,
            sentence="The video compares options before choosing.",
            wording=lines[0],
            paraphrase="The speaker introduces the choice being compared.",
        ),
    )


def _band(note: str) -> str:
    return note.split(PROPOSALS_HEADING, 1)[1].split(EVIDENCE_HEADING, 1)[0]


def _frontmatter(note: str) -> dict:
    return yaml.safe_load(note.split("---\n", 2)[1])


def _vault(root: Path) -> VaultContext:
    root.mkdir(parents=True, exist_ok=True)
    return VaultContext(status="selected", active_vault_id="vault-test", active_vault_name="Vault Test", active_vault_path=str(root))


def test_initial_modules_compose_under_shared_proposal_wrapper() -> None:
    for lines, module_title, present, absent in (
        (
            DECISION_LINES,
            "Decision framework",
            ("Options considered", "Decision rules"),
            ("Criteria and trade-offs",),
        ),
        (
            SCIENCE_LINES,
            "Documentary science",
            ("Evidence presented", "Methods and measurement", "Findings and uncertainty"),
            (),
        ),
    ):
        candidate = _english_candidate(lines, f"sha256:{module_title}")
        note = render_candidate_note(candidate)
        band = _band(note)

        # Exactly one shared wrapper; modules never create a sibling band or a second note shape.
        assert note.count(PROPOSALS_HEADING) == 1 and note.count(OWNER_NOTES_HEADING) == 1
        assert note.index(OWNER_NOTES_HEADING) < note.index(PROPOSALS_HEADING) < note.index(EVIDENCE_HEADING)
        owner_band = note.split(OWNER_NOTES_HEADING, 1)[1].split(PROPOSALS_HEADING, 1)[0]
        assert module_title not in owner_band

        # The universal spine is retained and precedes every module section.
        spine = band.index("### Evidence-anchored synthesis")
        assert band.index("### Evidence-anchored claims") > spine
        for section in present:
            heading = f"### {module_title} — {section}"
            assert heading in band
            assert band.index(heading) > band.index("### Evidence-anchored claims")
        # Absent evidence -> absent section; no filler heading.
        for section in absent:
            assert section not in note

        # Module content stays blockquoted inside the wrapper and every item is anchored.
        module_body = band[band.index(f"### {module_title}") :]
        for line in module_body.splitlines():
            assert line == "" or line.startswith("### ") or line.startswith(">")
        assert "`[seg 0 · 00:00:00–00:00:02]`" in module_body

    # Generic routing renders the spine only, with no module headings at all.
    generic_note = render_candidate_note(_english_candidate(GENERIC_LINES, "sha256:generic"))
    assert "### Evidence-anchored synthesis" in generic_note
    assert "Decision framework" not in generic_note and "Documentary science" not in generic_note


def test_optional_module_failure_preserves_required_evidence_note(monkeypatch, tmp_path: Path) -> None:
    # A mixed source routes to both profiles; one module crashes, the other must still render.
    lines = SCIENCE_LINES + DECISION_LINES[:4]
    original = note_modules._build_module_sections

    def _flaky(module, route_profile, normalized):
        if module.module_id == "decision_framework":
            raise RuntimeError("module template exploded")
        return original(module, route_profile, normalized)

    monkeypatch.setattr(note_modules, "_build_module_sections", _flaky)
    identity = "sha256:module-failure"
    candidate = _english_candidate(lines, identity)
    assert {p.profile_id for p in candidate.content_route.profiles} == {"decision_framework", "documentary_science"}
    assert [f.module_id for f in candidate.note_modules.failures] == ["decision_framework"]

    vault_root = tmp_path / "vault"
    result = write_candidate_note(
        candidate, vault_context=_vault(vault_root), write_guard=WriteGuard(lambda: {"state": "healthy"})
    )
    assert result.status == "written"
    note = (vault_root / result.artifact_path).read_text(encoding="utf-8")
    band = _band(note)

    # Required evidence that already materialized is untouched by the module failure.
    assert "### Evidence-anchored synthesis" in band
    assert "The video compares options before choosing." in band
    assert "### Evidence-anchored claims" in band
    assert "The speaker introduces the choice being compared." in band
    # The healthy module still renders; the failed one is absent and visibly reported.
    assert "### Documentary science — Evidence presented" in band
    assert "### Decision framework" not in band
    assert "### Degraded content modules" in band
    assert "decision_framework" in band
    frontmatter = _frontmatter(note)
    assert frontmatter["degraded"] is True
    assert frontmatter["unavailable_note_modules"] == ["decision_framework"]
    assert "content module failures: decision_framework" in note

    # A source line that trips the renderer's authority lint drops that one item, not the note.
    monkeypatch.undo()
    risky = ("You decide which option fits you.",) + DECISION_LINES[1:]
    risky_identity = "sha256:module-lint"
    risky_candidate = assemble_candidate(
        _raw(risky, identity=risky_identity),
        extraction_results=_required_evidence(
            risky_identity,
            sentence="The video compares options before choosing.",
            wording=risky[1],
            paraphrase="The speaker names the two alternatives.",
        ),
    )
    risky_note = render_candidate_note(risky_candidate)
    assert "### Evidence-anchored synthesis" in risky_note
    assert "You decide which option" not in risky_note
    assert "### Decision framework — Options considered" in risky_note
    assert risky_candidate.note_modules.omitted_items >= 1
    # The omission is visible, not silent.
    assert _frontmatter(risky_note)["omitted_module_items"] == risky_candidate.note_modules.omitted_items
    assert "### Omitted module excerpts" in _band(risky_note)
    assert not risky_candidate.note_modules.failures


def test_module_prose_follows_source_language_policy() -> None:
    # Swedish-original source: module prose in Swedish; quotations verbatim Swedish.
    identity = "sha256:swedish-modules"
    swedish = assemble_candidate(
        _raw(SWEDISH_DECISION_LINES, language="sv", identity=identity),
        extraction_results=_required_evidence(
            identity,
            sentence="Videon jämför två alternativ innan ett beslut fattas.",
            wording=SWEDISH_DECISION_LINES[0],
            paraphrase="Talaren beskriver valet som ska göras.",
        ),
    )
    assert swedish.note_modules.system_language == "sv"
    sv_note = render_candidate_note(swedish)
    sv_band = _band(sv_note)
    assert "### Beslutsramverk — Alternativ som övervägs" in sv_band
    assert "### Beslutsramverk — Kriterier och avvägningar" in sv_band
    assert "Decision framework" not in sv_note and "Options considered" not in sv_note
    for line in SWEDISH_DECISION_LINES:
        assert f"“{line}”" in sv_band
    assert validate_generated_language(note_modules.lead_text("sv", "sv"), "sv")

    # English source: English module prose, quotations verbatim English.
    english = _english_candidate(DECISION_LINES, "sha256:english-modules")
    assert english.note_modules.system_language == "en"
    en_band = _band(render_candidate_note(english))
    assert "### Decision framework — Options considered" in en_band
    assert "Beslutsramverk" not in en_band
    assert f"“{DECISION_LINES[0]}”" in en_band
    assert validate_generated_language(note_modules.lead_text("en", "en"), "en")

    # A non-Swedish, non-English source still gets English system prose while the quotation keeps
    # the source's own wording and language tag (no translation is presented as a quotation).
    foreign = assemble_candidate(_raw(DECISION_LINES, language="de", identity="sha256:german-tag"), extraction_results=())
    assert foreign.note_modules.system_language == "en"
    de_band = _band(render_candidate_note(foreign))
    assert "### Decision framework — Options considered" in de_band
    assert f"“{DECISION_LINES[0]}”" in de_band
    assert "source language: de" in de_band
