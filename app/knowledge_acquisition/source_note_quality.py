"""YSNV2-12 source-note quality evaluation: versioned gold set, mechanical gates, metrics.

The harness evaluates what a candidate note actually *renders*: every synthesis sentence,
source-bound claim, timestamped moment and interest-overlay ``source_says`` quote in the
proposals band.  Rendered items are resolved against the note's own durable lineage (the
frontmatter-named normalized transcript, synthesis extraction and key-moments artifacts), so
the gate catches a renderer regression instead of trusting the renderer's own anchor filter.

Mechanical criteria (recorded by name when they fail):

- ``evidence_lineage`` - the note's lineage artifacts resolve and descend from one content
  identity;
- ``anchor_validity`` - every rendered item names at least one resolvable transcript anchor;
- ``claim_entailment`` - every rendered verbatim source wording (claims, overlay quotes) is
  contained in the text of the transcript segments it cites;
- ``must_capture_recall`` - with a gold set, the share of annotated must-capture points whose
  time span overlaps a valid rendered anchor meets the gold set's declared threshold.

Selection, hierarchy, uncertainty, connections and revisit value are subjective; the report
lists them as operator-scored dimensions and never scores or accepts them automatically.

Gold sets are versioned JSON documents (``ysnv2_source_note_gold_set.v1``).  Owner annotations
are bound to the operator receipt ``ysnv2_gold_set_annotation_scope.v1`` recorded on parent
Issue #4107; this module never infers or fabricates them.  Clearly labeled synthetic fixtures
exercise the harness and can never stand in for owner evidence.

Evaluation is read-only and no-egress: it parses note text, reads the ObjectStore, and returns
a report.  It performs no network, model, vault, or ObjectStore write.
"""

from __future__ import annotations

import ast
import hashlib
import html
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

import yaml

from app.knowledge_acquisition.evidence_synthesis import validate_resolvable_anchor
from app.knowledge_acquisition.extraction_persistence import (
    ExtractionPersistenceError,
    NORMALIZED_ARTIFACT_KIND,
    load_extraction_artifact,
)
from app.knowledge_acquisition.key_moments import KEY_MOMENTS_ARTIFACT_KIND
from app.knowledge_acquisition.note_renderer import EVIDENCE_HEADING, PROPOSALS_HEADING
from app.knowledge_acquisition.raw_record import RawRecordIntegrityError, get_raw_record
from app.objects import ObjectStore

GOLD_SET_SCHEMA = "ysnv2_source_note_gold_set.v1"
QUALITY_REPORT_SCHEMA = "ysnv2_source_note_quality_report.v1"
EVALUATOR_VERSION = 1
ANNOTATION_SCOPE_RECEIPT = "ysnv2_gold_set_annotation_scope.v1"
ANNOTATION_SCOPE_RECEIPT_URL = (
    "https://github.com/RasmusTho/agentic-pkm-mvp/issues/4107#issuecomment-5933623949"
)
# Receipt scope: 3 owner-watched videos.  A larger owner set requires a new scope receipt.
ANNOTATION_SCOPE_MAX_VIDEOS = 3
# Versioned data slot for the owner's real annotations; absent until the owner supplies them.
OWNER_GOLD_SET_PATH = Path("data/golden/youtube_source_note_v2/owner_gold_set.v1.json")

SYNTHETIC_FIXTURE = "synthetic_fixture"
OWNER_ANNOTATION = "owner_annotation"
_PROVENANCE_KINDS = frozenset({SYNTHETIC_FIXTURE, OWNER_ANNOTATION})

CRITERION_EVIDENCE_LINEAGE = "evidence_lineage"
CRITERION_ANCHOR_VALIDITY = "anchor_validity"
CRITERION_CLAIM_ENTAILMENT = "claim_entailment"
CRITERION_MUST_CAPTURE_RECALL = "must_capture_recall"
OPERATOR_SCORED_DIMENSIONS = ("selection", "hierarchy", "uncertainty", "connections", "revisit_value")

ItemKind = Literal["synthesis_sentence", "claim", "moment", "overlay_source_says", "module_excerpt"]

_SAFE_ITEM_REF = re.compile(r"[A-Za-z0-9_-]{1,128}")
_SECTION = re.compile(r"^### (.+)$", re.MULTILINE)
_CLAIM_WORDING = re.compile(r"^- \*\*Source wording:\*\* (.*)$")
_CLAIM_ANCHORS = re.compile(r"^\s+\*\*Anchors:\*\* (.*)$")
_CLAIM_FIELD = re.compile(r"^\s+\*\*(?:System paraphrase|Anchors):\*\*")
_MOMENT_ANCHORS = re.compile(r"^\s+\*\*Transcript anchors:\*\* (.*)$")
_MOMENT_LINE = re.compile(r"^- \[[0-9:]+\]\(")
_MODULE_EXCERPT = re.compile(r"^- `\[seg (\d+) · [0-9:]+–[0-9:]+\]` “(.*)”$")
_OVERLAY_SOURCE = re.compile(r"^- \*\*(?:Source says|Källan säger)\*\* \(([^)]*)\): “(.*)”$")
_MARKDOWN_UNESCAPE = re.compile(r"\\(.)")
_CLOCK = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")


class GoldSetError(ValueError):
    """A gold-set document is malformed or misrepresents its annotation provenance."""


# --- gold set ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class MustCapturePoint:
    point_id: str
    description: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class GoldSetEntry:
    item_ref: str
    content_identity: str
    points: tuple[MustCapturePoint, ...]


@dataclass(frozen=True)
class GoldSet:
    gold_set_id: str
    version: int
    provenance_kind: str
    annotation_scope_receipt: str | None
    recall_threshold: float
    entries: tuple[GoldSetEntry, ...]
    digest: str

    @property
    def is_owner_evidence(self) -> bool:
        return self.provenance_kind == OWNER_ANNOTATION

    def entry_for(self, *, item_ref: str | None, content_identity: str | None) -> GoldSetEntry | None:
        for entry in self.entries:
            if entry.item_ref == item_ref and entry.content_identity == content_identity:
                return entry
        return None

    def lineage(self) -> dict[str, Any]:
        return {
            "schema": GOLD_SET_SCHEMA,
            "gold_set_id": self.gold_set_id,
            "version": self.version,
            "digest": self.digest,
            "provenance_kind": self.provenance_kind,
            "annotation_scope_receipt": self.annotation_scope_receipt,
            "owner_evidence": self.is_owner_evidence,
        }


def parse_gold_set(document: Mapping[str, Any]) -> GoldSet:
    """Validate one versioned gold-set document; refuse provenance misrepresentation."""

    if not isinstance(document, Mapping) or document.get("schema") != GOLD_SET_SCHEMA:
        raise GoldSetError(f"gold set must declare schema {GOLD_SET_SCHEMA!r}")
    gold_set_id = document.get("gold_set_id")
    version = document.get("version")
    if not isinstance(gold_set_id, str) or not gold_set_id.strip():
        raise GoldSetError("gold set requires a non-blank gold_set_id")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise GoldSetError("gold set version must be a positive integer")
    provenance = document.get("provenance")
    if not isinstance(provenance, Mapping) or provenance.get("kind") not in _PROVENANCE_KINDS:
        raise GoldSetError(f"gold set provenance.kind must be one of {sorted(_PROVENANCE_KINDS)}")
    kind = str(provenance["kind"])
    receipt = provenance.get("annotation_scope_receipt")
    annotated_by = provenance.get("annotated_by")
    videos = document.get("videos")
    if not isinstance(videos, list) or not videos:
        raise GoldSetError("gold set requires at least one video entry")
    if kind == OWNER_ANNOTATION:
        if receipt != ANNOTATION_SCOPE_RECEIPT:
            raise GoldSetError(f"owner annotations must bind operator receipt {ANNOTATION_SCOPE_RECEIPT!r}")
        if annotated_by != "owner" or not isinstance(provenance.get("annotated_at"), str):
            raise GoldSetError("owner annotations require annotated_by: owner and annotated_at")
        if len(videos) > ANNOTATION_SCOPE_MAX_VIDEOS:
            raise GoldSetError(
                f"owner gold set exceeds the receipt scope of {ANNOTATION_SCOPE_MAX_VIDEOS} videos; "
                "a larger scope requires a new operator receipt"
            )
    elif str(annotated_by or "").strip().casefold() == "owner" or receipt is not None:
        raise GoldSetError("a synthetic fixture must not claim owner annotation or the owner scope receipt")
    threshold = document.get("must_capture_recall_threshold")
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(float(threshold))
        or not 0.0 <= float(threshold) <= 1.0
    ):
        raise GoldSetError("must_capture_recall_threshold must be a number in [0, 1]")

    entries: list[GoldSetEntry] = []
    seen_entries: set[tuple[str, str]] = set()
    for video in videos:
        entries.append(_parse_entry(video))
        key = (entries[-1].item_ref, entries[-1].content_identity)
        if key in seen_entries:
            raise GoldSetError(f"duplicate gold-set entry for {key}")
        seen_entries.add(key)
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return GoldSet(
        gold_set_id=gold_set_id,
        version=version,
        provenance_kind=kind,
        annotation_scope_receipt=receipt if isinstance(receipt, str) else None,
        recall_threshold=float(threshold),
        entries=tuple(entries),
        digest="sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def _parse_entry(video: object) -> GoldSetEntry:
    if not isinstance(video, Mapping):
        raise GoldSetError("gold-set video entries must be objects")
    item_ref = video.get("item_ref")
    content_identity = video.get("content_identity")
    if not isinstance(item_ref, str) or not _SAFE_ITEM_REF.fullmatch(item_ref):
        raise GoldSetError("gold-set entry requires a safe item_ref")
    if not isinstance(content_identity, str) or not content_identity.startswith("sha256:"):
        raise GoldSetError("gold-set entry requires the annotated content_identity")
    raw_points = video.get("must_capture")
    if not isinstance(raw_points, list) or not raw_points:
        raise GoldSetError(f"gold-set entry {item_ref} requires must_capture points")
    points: list[MustCapturePoint] = []
    for raw in raw_points:
        if not isinstance(raw, Mapping):
            raise GoldSetError("must_capture points must be objects")
        point_id, description = raw.get("point_id"), raw.get("description")
        start, end = raw.get("start_seconds"), raw.get("end_seconds")
        if not isinstance(point_id, str) or not point_id.strip():
            raise GoldSetError("must_capture point requires a point_id")
        if not isinstance(description, str) or not description.strip():
            raise GoldSetError(f"must_capture point {point_id} requires a description")
        if (
            any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (start, end))
            or not math.isfinite(float(start))  # type: ignore[arg-type]
            or not math.isfinite(float(end))  # type: ignore[arg-type]
            or not 0 <= float(start) <= float(end)  # type: ignore[arg-type]
        ):
            raise GoldSetError(f"must_capture point {point_id} requires a finite ordered time span")
        if any(point.point_id == point_id for point in points):
            raise GoldSetError(f"duplicate must_capture point_id {point_id!r}")
        points.append(MustCapturePoint(point_id, description, float(start), float(end)))  # type: ignore[arg-type]
    return GoldSetEntry(item_ref=item_ref, content_identity=content_identity, points=tuple(points))


def load_gold_set(path: Path) -> GoldSet:
    return parse_gold_set(json.loads(Path(path).read_text(encoding="utf-8")))


def load_owner_gold_set(repo_root: Path) -> GoldSet | None:
    """Return the owner's annotated gold set, or ``None`` while the owner input is pending."""

    path = Path(repo_root) / OWNER_GOLD_SET_PATH
    if not path.exists():
        return None
    gold_set = load_gold_set(path)
    if not gold_set.is_owner_evidence:
        raise GoldSetError(f"{OWNER_GOLD_SET_PATH} must hold owner annotations, not a synthetic fixture")
    return gold_set


# --- rendered subject -------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceItem:
    """One rendered proposal item and the transcript anchors it cites."""

    kind: ItemKind
    text: str
    anchors: tuple[Mapping[str, Any], ...]
    verbatim: str | None = None
    """Source wording that must be contained in the cited segments (claims, overlay quotes)."""


@dataclass(frozen=True)
class EvaluationSubject:
    item_ref: str | None
    content_identity: str | None
    segments: tuple[Mapping[str, Any], ...]
    items: tuple[EvidenceItem, ...]
    lineage: Mapping[str, Any]
    lineage_failures: tuple[str, ...] = ()
    unparsed_items: tuple[str, ...] = ()
    """Rendered evidence bullets the harness could not recognize; they fail anchor validity."""
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


def load_rendered_subject(note_text: str) -> EvaluationSubject:
    """Parse a rendered candidate note and resolve its durable lineage read-only."""

    frontmatter = _frontmatter(note_text)
    failures: list[str] = []
    provenance = frontmatter.get("provenance")
    if not isinstance(provenance, Mapping):
        provenance = {}
    # Candidate notes carry identity under ``provenance``; D5 proposal companions at top level.
    content_identity = provenance.get("content_identity") or frontmatter.get("content_identity")
    item_ref = _item_ref_from_url(str(provenance.get("url") or ""))
    raw_record_id = frontmatter.get("raw_record_id")
    normalized_id = frontmatter.get("normalized_artifact_id")
    raw_extraction_ids = frontmatter.get("extraction_artifact_ids") or []
    if not isinstance(raw_extraction_ids, list):
        failures.append("extraction_artifact_ids_malformed")
        raw_extraction_ids = []
    extraction_ids = [str(v) for v in raw_extraction_ids]
    moments_id = frontmatter.get("key_moments_artifact_id")

    segments: list[Mapping[str, Any]] = []
    transcript = _get_object(normalized_id)
    if transcript is None or transcript.kind != NORMALIZED_ARTIFACT_KIND:
        failures.append("normalized_transcript_unresolvable")
    else:
        ext = dict(transcript.payload).get("extensions") or {}
        if ext.get("content_identity") != content_identity or ext.get("raw_record_id") != raw_record_id:
            failures.append("normalized_transcript_wrong_ancestor")
        segments = [seg for seg in ext.get("segments") or () if isinstance(seg, Mapping)]

    synthesis_anchors: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for extraction_id in extraction_ids:
        try:
            extraction = load_extraction_artifact(extraction_id)
        except (ExtractionPersistenceError, ValueError, TypeError):
            extraction = None
        if extraction is None:
            failures.append(f"extraction_unresolvable:{extraction_id}")
            continue
        if extraction.result.source_content_identity != content_identity:
            failures.append(f"extraction_wrong_content_identity:{extraction_id}")
        if extraction.result.extractor_id == "synthesis":
            for sentence in extraction.result.output.get("synthesis_sentences") or ():
                if isinstance(sentence, Mapping) and isinstance(sentence.get("text"), str):
                    anchors = sentence.get("anchors")
                    synthesis_anchors.setdefault(
                        sentence["text"].strip(), tuple(anchors) if isinstance(anchors, list) else ()
                    )

    diagnostics: dict[str, Any] = {"content_route": frontmatter.get("content_route")}
    if moments_id:
        moments = _get_object(moments_id)
        moments_ext = (dict(moments.payload).get("extensions") or {}) if moments is not None else {}
        if moments is None or moments.kind != KEY_MOMENTS_ARTIFACT_KIND:
            failures.append("key_moments_unresolvable")
        elif moments_ext.get("content_identity") != content_identity:
            failures.append("key_moments_wrong_content_identity")
        else:
            budget = moments_ext.get("budget") or {}
            diagnostics["moment_budget_duration_seconds"] = budget.get("duration_seconds")
    if raw_record_id:
        try:
            raw = get_raw_record(str(raw_record_id))
        except (RawRecordIntegrityError, ValueError, TypeError):
            raw = None
        if raw is None or raw.get("content_identity") != content_identity:
            failures.append("raw_record_unresolvable")
        elif item_ref is not None and raw.get("item_ref") != item_ref:
            failures.append("raw_record_wrong_item_ref")
        else:
            item_ref = str(raw.get("item_ref"))
            metadata = raw.get("metadata")
            diagnostics["source_duration_seconds"] = (
                metadata.get("duration") if isinstance(metadata, Mapping) else None
            )
    else:
        failures.append("raw_record_unresolvable")

    items, unparsed = _rendered_items(note_text, segments=segments, synthesis_anchors=synthesis_anchors)
    return EvaluationSubject(
        item_ref=item_ref,
        content_identity=content_identity if isinstance(content_identity, str) else None,
        segments=tuple(segments),
        items=tuple(items),
        lineage={
            "raw_record_id": raw_record_id,
            "normalized_artifact_id": normalized_id,
            "extraction_artifact_ids": extraction_ids,
            "key_moments_artifact_id": moments_id,
            "note_digest": "sha256:" + hashlib.sha256(note_text.encode("utf-8")).hexdigest(),
        },
        lineage_failures=tuple(failures),
        unparsed_items=tuple(unparsed),
        diagnostics=diagnostics,
    )


def _get_object(object_id: object) -> Any:
    """Read one durable object; a malformed id is an unresolvable reference, not a crash."""

    if not object_id:
        return None
    try:
        return ObjectStore().get_object(str(object_id))
    except (ValueError, TypeError):
        return None


def _frontmatter(note_text: str) -> Mapping[str, Any]:
    if not note_text.startswith("---\n"):
        return {}
    try:
        loaded = yaml.safe_load(note_text.split("---\n", 2)[1])
    except (IndexError, yaml.YAMLError):
        return {}
    return loaded if isinstance(loaded, Mapping) else {}


def _item_ref_from_url(url: str) -> str | None:
    match = re.search(r"[?&]v=([A-Za-z0-9_-]{1,128})", url)
    return match.group(1) if match else None


def _proposal_sections(note_text: str) -> dict[str, list[str]]:
    """Split the proposals band into its ``### `` sections.

    Band and section headings are matched as whole lines: generated content is blockquoted
    (``> `` prefixed), so a heading-like string inside source text can never end the band early.
    """

    lines = note_text.splitlines()
    try:
        start = lines.index(PROPOSALS_HEADING)
    except ValueError:
        return {}
    end = next((i for i in range(start + 1, len(lines)) if lines[i] == EVIDENCE_HEADING), len(lines))
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in lines[start + 1 : end]:
        heading = _SECTION.match(line)
        if heading is not None:
            current = sections.setdefault(html.unescape(heading.group(1).strip()), [])
            continue
        if current is not None:
            current.append(html.unescape(line[2:] if line.startswith("> ") else line.lstrip(">")))
    return sections


def _rendered_items(
    note_text: str,
    *,
    segments: Sequence[Mapping[str, Any]],
    synthesis_anchors: Mapping[str, tuple[Mapping[str, Any], ...]],
) -> tuple[list[EvidenceItem], list[str]]:
    """Return every recognized rendered evidence item plus any unrecognized evidence bullet."""

    sections = _proposal_sections(note_text)
    items: list[EvidenceItem] = []
    unparsed: list[str] = []
    for line in sections.get("Evidence-anchored synthesis", ()):
        if line.startswith("- "):
            text = line[2:].strip()
            items.append(EvidenceItem("synthesis_sentence", text, synthesis_anchors.get(text, ())))

    claim_lines = sections.get("Evidence-anchored claims", [])
    for index, line in enumerate(claim_lines):
        wording = _CLAIM_WORDING.match(line)
        if wording is None:
            if line.startswith("- "):
                unparsed.append(f"Evidence-anchored claims: {line[:80]}")
            continue
        anchors: tuple[Mapping[str, Any], ...] = ()
        # A multi-line source wording continues until its paraphrase/anchors field; every
        # continuation line is part of the verbatim text that must be entailed.
        wording_lines = [wording.group(1)]
        in_wording = True
        for follow in claim_lines[index + 1 :]:
            if follow.startswith("- "):
                break
            matched = _CLAIM_ANCHORS.match(follow)
            if matched is not None:
                anchors = _literal_anchors(matched.group(1))
                break
            if _CLAIM_FIELD.match(follow):
                in_wording = False
            elif in_wording:
                wording_lines.append(follow)
        text = " ".join(" ".join(wording_lines).split())
        items.append(EvidenceItem("claim", text, anchors, verbatim=text))

    by_anchor = {str(seg.get("anchor")): (i, seg) for i, seg in enumerate(segments) if seg.get("anchor")}
    moment_lines = sections.get("Timestamped moments", [])
    for index, line in enumerate(moment_lines):
        if not _MOMENT_LINE.match(line):
            if line.startswith("- "):
                unparsed.append(f"Timestamped moments: {line[:80]}")
            continue
        anchors = ()
        for follow in moment_lines[index + 1 : index + 2]:
            matched = _MOMENT_ANCHORS.match(follow)
            if matched is not None:
                anchors = tuple(
                    _segment_anchor(by_anchor[name.strip()])
                    if name.strip() in by_anchor
                    else {"anchor": name.strip()}
                    for name in matched.group(1).split(",")
                    if name.strip()
                )
        items.append(EvidenceItem("moment", line, anchors))

    for title, lines in sections.items():
        overlay = title in {"Interest overlay", "Intresseöverlägg"}
        # A content-module section is any section rendering at least one module excerpt; every
        # other bullet in it is unrecognized evidence and fails rather than being ignored.
        module_section = any(_MODULE_EXCERPT.match(line) for line in lines)
        for line in lines:
            if module_section and line.startswith("- ") and not _MODULE_EXCERPT.match(line):
                unparsed.append(f"{title}: {line[:80]}")
                continue
            excerpt = _MODULE_EXCERPT.match(line)
            if excerpt is not None:
                # Content-module excerpts are anchored verbatim transcript quotes.
                index = int(excerpt.group(1))
                quote = excerpt.group(2)
                excerpt_anchors: tuple[Mapping[str, Any], ...] = (
                    (_segment_anchor((index, segments[index])),)
                    if 0 <= index < len(segments)
                    else ({"segment_index": index},)
                )
                items.append(EvidenceItem("module_excerpt", quote, excerpt_anchors, verbatim=quote))
                continue
            if not overlay:
                continue
            matched = _OVERLAY_SOURCE.match(line)
            if matched is None:
                if line.startswith("- "):
                    unparsed.append(f"{title}: {line[:80]}")
                continue
            quote = _MARKDOWN_UNESCAPE.sub(r"\1", matched.group(2))
            overlay_anchors = tuple(_overlay_anchors(matched.group(1), quote, segments))
            items.append(EvidenceItem("overlay_source_says", quote, overlay_anchors, verbatim=quote))
    return items, unparsed


def _literal_anchors(value: str) -> tuple[Mapping[str, Any], ...]:
    try:
        parsed = ast.literal_eval(value.strip())
    except (ValueError, SyntaxError):
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(anchor for anchor in parsed if isinstance(anchor, Mapping))


def _segment_anchor(indexed: tuple[int, Mapping[str, Any]]) -> Mapping[str, Any]:
    index, segment = indexed
    return {"segment_index": index, "start": segment.get("start"), "end": segment.get("end")}


def _overlay_anchors(stamps: str, quote: str, segments: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Resolve rendered ``(mm:ss)`` stamps to the segments that start at them and hold the quote."""

    anchors: list[Mapping[str, Any]] = []
    for stamp in stamps.split(","):
        clock = _CLOCK.match(stamp.strip())
        if clock is None:
            anchors.append({"unresolved_stamp": stamp.strip()})
            continue
        seconds = int(clock.group(1) or 0) * 3600 + int(clock.group(2)) * 60 + int(clock.group(3))
        starting = [
            (i, seg)
            for i, seg in enumerate(segments)
            if isinstance(seg.get("start"), (int, float)) and math.floor(float(seg["start"])) == seconds
        ]
        holding = [pair for pair in starting if _normalize(quote) in _normalize(str(pair[1].get("text") or ""))]
        chosen = (holding or starting)[:1]
        if chosen:
            anchors.append(_segment_anchor(chosen[0]))
        else:
            anchors.append({"unresolved_stamp": stamp.strip()})
    return anchors


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


# --- evaluation -------------------------------------------------------------------------------


@dataclass(frozen=True)
class QualityReport:
    schema: str
    evaluator_version: int
    passed: bool
    failed_criteria: tuple[str, ...]
    metrics: Mapping[str, Any]
    failures: Mapping[str, tuple[str, ...]]
    subject_lineage: Mapping[str, Any]
    gold_set_lineage: Mapping[str, Any] | None
    diagnostics: Mapping[str, Any]
    operator_scored_dimensions: tuple[str, ...] = OPERATOR_SCORED_DIMENSIONS

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "evaluator_version": self.evaluator_version,
            "passed": self.passed,
            "failed_criteria": list(self.failed_criteria),
            "metrics": dict(self.metrics),
            "failures": {key: list(value) for key, value in self.failures.items()},
            "subject_lineage": dict(self.subject_lineage),
            "gold_set_lineage": dict(self.gold_set_lineage) if self.gold_set_lineage else None,
            "diagnostics": dict(self.diagnostics),
            "operator_scored_dimensions": {name: "pending_operator" for name in self.operator_scored_dimensions},
            # A mechanical pass is never capability or note acceptance.
            "evaluation_scope": "mechanical_only",
        }


def evaluate_subject(subject: EvaluationSubject, *, gold_set: GoldSet | None = None) -> QualityReport:
    """Score one rendered subject; every failing mechanical criterion is named in the report."""

    failures: dict[str, list[str]] = {
        CRITERION_EVIDENCE_LINEAGE: list(subject.lineage_failures),
        CRITERION_ANCHOR_VALIDITY: [],
        CRITERION_CLAIM_ENTAILMENT: [],
        CRITERION_MUST_CAPTURE_RECALL: [],
    }
    valid_items: list[EvidenceItem] = []
    supported_items: list[EvidenceItem] = []
    entailed = 0
    failures[CRITERION_ANCHOR_VALIDITY].extend(f"unparsed rendered item: {line}" for line in subject.unparsed_items)
    for position, item in enumerate(subject.items):
        label = f"{item.kind}[{position}]: {item.text[:80]}"
        if not item.anchors or not all(validate_resolvable_anchor(a, subject.segments) for a in item.anchors):
            failures[CRITERION_ANCHOR_VALIDITY].append(label)
            continue
        valid_items.append(item)
        if item.verbatim is not None:
            cited = " ".join(str(subject.segments[int(a["segment_index"])].get("text") or "") for a in item.anchors)
            if not item.verbatim.strip() or _normalize(item.verbatim) not in _normalize(cited):
                failures[CRITERION_CLAIM_ENTAILMENT].append(label)
                continue
            entailed += 1
        supported_items.append(item)

    total = len(subject.items)
    verbatim_total = sum(1 for item in subject.items if item.verbatim is not None)
    metrics: dict[str, Any] = {
        "rendered_items": total,
        "rendered_items_by_kind": _count_by_kind(subject.items),
        "anchor_validity": (len(valid_items) / total) if total else None,
        "claim_entailment": (entailed / verbatim_total) if verbatim_total else None,
    }
    if total == 0:
        failures[CRITERION_ANCHOR_VALIDITY].append("no rendered evidence items")

    gold_lineage: dict[str, Any] | None = None
    metrics["must_capture_recall"] = "not_evaluated"
    if gold_set is not None:
        gold_lineage = gold_set.lineage()
        entry = gold_set.entry_for(item_ref=subject.item_ref, content_identity=subject.content_identity)
        if entry is None:
            failures[CRITERION_MUST_CAPTURE_RECALL].append(
                "no gold-set entry annotates this item_ref at this content_identity"
            )
            metrics["must_capture_recall"] = None
        else:
            # Only anchored AND entailed items can capture a point; a fabricated quote cannot.
            captured, missed = _must_capture(entry, supported_items)
            recall = len(captured) / len(entry.points)
            metrics["must_capture_recall"] = recall
            metrics["must_capture_threshold"] = gold_set.recall_threshold
            metrics["must_capture_captured"] = captured
            metrics["must_capture_missed"] = missed
            gold_lineage["entry"] = {"item_ref": entry.item_ref, "content_identity": entry.content_identity}
            if recall < gold_set.recall_threshold:
                failures[CRITERION_MUST_CAPTURE_RECALL].append(
                    f"recall {recall:.3f} below threshold {gold_set.recall_threshold:.3f}; missed {missed}"
                )

    failed = tuple(name for name, found in failures.items() if found)
    return QualityReport(
        schema=QUALITY_REPORT_SCHEMA,
        evaluator_version=EVALUATOR_VERSION,
        passed=not failed,
        failed_criteria=failed,
        metrics=metrics,
        failures={name: tuple(found) for name, found in failures.items() if found},
        subject_lineage={
            "item_ref": subject.item_ref,
            "content_identity": subject.content_identity,
            **dict(subject.lineage),
        },
        gold_set_lineage=gold_lineage,
        diagnostics=dict(subject.diagnostics),
    )


def evaluate_source_note(note_text: str, *, gold_set: GoldSet | None = None) -> QualityReport:
    """Evaluate one rendered candidate note against its durable lineage (read-only, no egress)."""

    return evaluate_subject(load_rendered_subject(note_text), gold_set=gold_set)


def _count_by_kind(items: Sequence[EvidenceItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    return counts


def _must_capture(entry: GoldSetEntry, items: Sequence[EvidenceItem]) -> tuple[list[str], list[str]]:
    spans = [
        (float(anchor["start"]), float(anchor["end"]))
        for item in items
        for anchor in item.anchors
    ]
    captured: list[str] = []
    missed: list[str] = []
    for point in entry.points:
        if point.start_seconds == point.end_seconds:
            hit = any(start <= point.start_seconds <= end for start, end in spans)
        else:  # positive overlap; spans that merely touch a boundary do not capture the point
            hit = any(start < point.end_seconds and point.start_seconds < end for start, end in spans)
        (captured if hit else missed).append(point.point_id)
    return captured, missed


__all__ = [
    "ANNOTATION_SCOPE_RECEIPT",
    "ANNOTATION_SCOPE_RECEIPT_URL",
    "CRITERION_ANCHOR_VALIDITY",
    "CRITERION_CLAIM_ENTAILMENT",
    "CRITERION_EVIDENCE_LINEAGE",
    "CRITERION_MUST_CAPTURE_RECALL",
    "EVALUATOR_VERSION",
    "GOLD_SET_SCHEMA",
    "OPERATOR_SCORED_DIMENSIONS",
    "OWNER_ANNOTATION",
    "OWNER_GOLD_SET_PATH",
    "QUALITY_REPORT_SCHEMA",
    "SYNTHETIC_FIXTURE",
    "EvaluationSubject",
    "EvidenceItem",
    "GoldSet",
    "GoldSetEntry",
    "GoldSetError",
    "MustCapturePoint",
    "QualityReport",
    "evaluate_source_note",
    "evaluate_subject",
    "load_gold_set",
    "load_owner_gold_set",
    "load_rendered_subject",
    "parse_gold_set",
]
