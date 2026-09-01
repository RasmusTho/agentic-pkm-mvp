"""Deterministic, read-only projection of the canonical design-principle kernel.

The resolver owns selection mechanics only. Principle prose and local owner semantics remain in
their referenced documents; a returned packet is never acceptance, ranking, or mutation authority.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TypeAlias


PACKET_CONTRACT = "design_packet.v1"
REFUSAL_CONTRACT = "design_packet_refusal.v1"
KERNEL_VERSION = "design-principle-kernel.v1"
PACKET_AUTHORITY = "projection_only_no_mutation_acceptance_or_ranking_authority"

_KERNEL_PATH = Path("docs/DESIGN_PRINCIPLES.md")
_ALLOWED_SYSTEM_CLASSIFICATIONS = {"product", "builder", "platform-ops", "boundary"}
_ALLOWED_WRITE_CLASSES = {
    "none",
    "read-only",
    "governance-docs-process",
    "derived",
    "mechanical",
    "authority-bearing",
    "durable",
    "external-effect",
}
_ALLOWED_PERSISTENCE_CLASSES = {"none", "derived-rebuildable", "durable", "authority"}
_ALLOWED_ENFORCEMENT = {"blocking", "advisory", "manual-review"}
_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
_PRINCIPLE_ID_PATTERN = re.compile(r"DP-[0-9A-Z]+")
_SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_PRINCIPLE_HEADING = re.compile(r"^### (?P<title>.+)$", re.MULTILINE)
_KERNEL_SECTION_HEADING = re.compile(r"^## System Design Principles$", re.MULTILINE)
_LEVEL_TWO_HEADING = re.compile(r"^## .+$", re.MULTILINE)
_MARKDOWN_HEADING = re.compile(r"^#{1,6} (?P<title>[^\r\n]+)$", re.MULTILINE)
_ROUTING_LINE = re.compile(
    r"^\*\*Routing metadata:\*\* "
    r"ID `(?P<id>DP-[0-9A-Z]+)`; "
    r"applicability `(?P<applicability>[a-z0-9-]+)`; "
    r"owner `(?P<owner>[^`]+)`; "
    r"required reading `(?P<required_reading>[^`]+)`; "
    r"enforcement `(?P<enforcement>[a-z-]+)`\.$",
    re.MULTILINE,
)
# Fail-closed identity projection only; routing metadata and prose remain authoritative in the blob.
_CANONICAL_KERNEL = (
    ("1. Boundary-First Design", "DP-01"),
    ("2. Capability-Based Composition", "DP-02"),
    ("2A. Interaction-First Architecture", "DP-02A"),
    ("2B. Foundation Before Agency", "DP-02B"),
    ("3. Separation of System Layers", "DP-03"),
    ("4. Explicit Mutation Authority", "DP-04"),
    ("5. Governance Before Autonomy", "DP-05"),
    ("6. Contracts Over Implementations", "DP-06"),
    ("7. Modularity With Replaceability", "DP-07"),
    ("8. Flexibility Without Semantic Drift", "DP-08"),
    ("9. Volatility Isolation", "DP-09"),
    ("10. Single-Operator Scale", "DP-10"),
    ("11. Shared Visual Language", "DP-11"),
)


@dataclass(frozen=True)
class ChangeFacts:
    """Declared change facts before validation and canonical normalization."""

    changed_paths: tuple[str, ...]
    system_classification: str
    write_class: str
    persistence_class: str
    external_effects: tuple[str, ...] = ()
    risk_triggers: tuple[str, ...] = ()
    expected_principle_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class NormalizedChangeFacts:
    changed_paths: tuple[str, ...]
    system_classification: str
    write_class: str
    persistence_class: str
    external_effects: tuple[str, ...]
    risk_triggers: tuple[str, ...]
    expected_principle_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "changed_paths": list(self.changed_paths),
            "expected_principle_ids": list(self.expected_principle_ids),
            "external_effects": list(self.external_effects),
            "persistence_class": self.persistence_class,
            "risk_triggers": list(self.risk_triggers),
            "system_classification": self.system_classification,
            "write_class": self.write_class,
        }


@dataclass(frozen=True)
class PrincipleSelection:
    principle_id: str
    applicability: str
    owner: str
    required_reading: str
    enforcement: str

    def to_dict(self) -> dict[str, str]:
        return {
            "applicability": self.applicability,
            "enforcement": self.enforcement,
            "owner": self.owner,
            "principle_id": self.principle_id,
            "required_reading": self.required_reading,
        }


@dataclass(frozen=True)
class DesignPacket:
    repository_head: str
    kernel_sha256: str
    normalized_change_facts: NormalizedChangeFacts
    principles: tuple[PrincipleSelection, ...]
    contract: str = PACKET_CONTRACT
    kernel_version: str = KERNEL_VERSION
    authority: str = PACKET_AUTHORITY

    def to_dict(self) -> dict[str, object]:
        return {
            "authority": self.authority,
            "contract": self.contract,
            "kernel_sha256": self.kernel_sha256,
            "kernel_version": self.kernel_version,
            "normalized_change_facts": self.normalized_change_facts.to_dict(),
            "principles": [principle.to_dict() for principle in self.principles],
            "repository_head": self.repository_head,
        }

    def canonical_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True)
class DesignPacketRefusal:
    code: str
    detail: str
    repository_head: str
    contract: str = REFUSAL_CONTRACT

    def to_dict(self) -> dict[str, str]:
        return {
            "contract": self.contract,
            "code": self.code,
            "detail": self.detail,
            "repository_head": self.repository_head,
        }

    def canonical_json(self) -> str:
        return _canonical_json(self.to_dict())


DesignPacketOutcome: TypeAlias = DesignPacket | DesignPacketRefusal


@dataclass(frozen=True)
class _KernelEntry:
    title: str
    principle_id: str
    applicability: str
    owner: str
    required_reading: str
    enforcement: str

    def selection(self) -> PrincipleSelection:
        return PrincipleSelection(
            principle_id=self.principle_id,
            applicability=self.applicability,
            owner=self.owner,
            required_reading=self.required_reading,
            enforcement=self.enforcement,
        )

    def digest_payload(self) -> dict[str, str]:
        return {
            "applicability": self.applicability,
            "enforcement": self.enforcement,
            "owner": self.owner,
            "principle_id": self.principle_id,
            "required_reading": self.required_reading,
            "title": self.title,
        }


class _Refusal(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def resolve_design_packet(
    facts: ChangeFacts,
    *,
    repository_root: Path,
    repository_head: str,
) -> DesignPacketOutcome:
    """Resolve the smallest canonical packet, or one typed refusal with no partial result."""

    normalized_head = repository_head.strip().lower() if isinstance(repository_head, str) else ""
    if _SHA_PATTERN.fullmatch(normalized_head) is None:
        return DesignPacketRefusal(
            code="invalid_repository_head",
            detail="repository_head must be one lowercase 40-character Git object id",
            repository_head=normalized_head,
        )

    try:
        normalized = _normalize_facts(facts)
        _assert_commit(repository_root, normalized_head)
        entries = _load_kernel(repository_root, normalized_head)
        _assert_kernel_references(repository_root, normalized_head, entries)
        _assert_expected_kernel(normalized.expected_principle_ids, entries)
        selected = _select_entries(normalized, entries)
    except _Refusal as refusal:
        return DesignPacketRefusal(
            code=refusal.code,
            detail=refusal.detail,
            repository_head=normalized_head,
        )

    kernel_sha256 = hashlib.sha256(
        _canonical_json([entry.digest_payload() for entry in entries]).encode("utf-8")
    ).hexdigest()
    return DesignPacket(
        repository_head=normalized_head,
        kernel_sha256=kernel_sha256,
        normalized_change_facts=normalized,
        principles=tuple(entry.selection() for entry in selected),
    )


def _normalize_facts(facts: ChangeFacts) -> NormalizedChangeFacts:
    if not isinstance(facts, ChangeFacts):
        raise _Refusal("invalid_change_facts", "facts must use the ChangeFacts contract")

    changed_paths = _normalized_paths(facts.changed_paths)
    external_effects = _normalized_slugs(facts.external_effects, field="external_effects")
    risk_triggers = _normalized_slugs(facts.risk_triggers, field="risk_triggers")
    expected_ids = _normalized_ids(facts.expected_principle_ids)
    system_classification = _normalized_scalar(facts.system_classification)
    write_class = _normalized_scalar(facts.write_class)
    persistence_class = _normalized_scalar(facts.persistence_class)

    if system_classification not in _ALLOWED_SYSTEM_CLASSIFICATIONS:
        raise _Refusal("invalid_change_facts", "system_classification is not recognized")
    if write_class not in _ALLOWED_WRITE_CLASSES:
        raise _Refusal("invalid_change_facts", "write_class is not recognized")
    if persistence_class not in _ALLOWED_PERSISTENCE_CLASSES:
        raise _Refusal("invalid_change_facts", "persistence_class is not recognized")
    if not changed_paths:
        raise _Refusal("invalid_change_facts", "changed_paths must not be empty")

    if external_effects and write_class in {"none", "read-only"}:
        raise _Refusal(
            "contradictory_classification",
            "external effects contradict a none or read-only write class",
        )
    if write_class == "none" and persistence_class != "none":
        raise _Refusal(
            "contradictory_classification",
            "non-empty persistence contradicts a none write class",
        )
    if write_class in {"read-only", "derived"} and persistence_class in {"durable", "authority"}:
        raise _Refusal(
            "contradictory_classification",
            "durable or authority persistence contradicts the declared write class",
        )
    if write_class == "durable" and persistence_class not in {"durable", "authority"}:
        raise _Refusal(
            "contradictory_classification",
            "a durable write requires durable or authority persistence",
        )

    return NormalizedChangeFacts(
        changed_paths=changed_paths,
        system_classification=system_classification,
        write_class=write_class,
        persistence_class=persistence_class,
        external_effects=external_effects,
        risk_triggers=risk_triggers,
        expected_principle_ids=expected_ids,
    )


def _normalized_scalar(value: object) -> str:
    if not isinstance(value, str):
        raise _Refusal("invalid_change_facts", "classification values must be strings")
    return value.strip().lower()


def _normalized_paths(values: object) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in _normalized_text_items(values, field="changed_paths"):
        if "\\" in value:
            raise _Refusal("invalid_change_facts", "changed_paths must use repository separators")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise _Refusal("invalid_change_facts", "changed_paths must be relative repository paths")
        normalized.append(path.as_posix())
    return tuple(sorted(set(normalized)))


def _normalized_slugs(values: object, *, field: str) -> tuple[str, ...]:
    normalized = tuple(value.lower() for value in _normalized_text_items(values, field=field))
    if any(_SLUG_PATTERN.fullmatch(value) is None for value in normalized):
        raise _Refusal("invalid_change_facts", f"{field} must contain lowercase slugs")
    return tuple(sorted(set(normalized)))


def _normalized_ids(values: object) -> tuple[str, ...]:
    normalized = _normalized_text_items(values, field="expected_principle_ids", sort=False)
    if any(_PRINCIPLE_ID_PATTERN.fullmatch(value) is None for value in normalized):
        raise _Refusal("invalid_change_facts", "expected_principle_ids contains an invalid ID")
    if len(set(normalized)) != len(normalized):
        raise _Refusal("invalid_change_facts", "expected_principle_ids contains duplicates")
    return normalized


def _normalized_text_items(values: object, *, field: str, sort: bool = True) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)) or any(not isinstance(item, str) for item in values):
        raise _Refusal("invalid_change_facts", f"{field} must be a string sequence")
    normalized = tuple(item.strip() for item in values)
    if any(not item for item in normalized):
        raise _Refusal("invalid_change_facts", f"{field} contains an empty value")
    return tuple(sorted(set(normalized))) if sort else normalized


def _load_kernel(repository_root: Path, repository_head: str) -> tuple[_KernelEntry, ...]:
    if not isinstance(repository_root, Path):
        raise _Refusal("kernel_unavailable", "repository_root must be a Path")
    text = _git_object_text(repository_root, repository_head, _KERNEL_PATH.as_posix())
    if text is None:
        raise _Refusal("kernel_unavailable", "the canonical principle kernel is unavailable") from None

    boundaries = list(_KERNEL_SECTION_HEADING.finditer(text))
    if len(boundaries) != 1:
        raise _Refusal(
            "stale_kernel_ids",
            "the canonical principle section boundary must occur exactly once",
        )
    boundary = boundaries[0]
    next_section = _LEVEL_TWO_HEADING.search(text, boundary.end())
    section = text[boundary.start() : len(text) if next_section is None else next_section.start()]
    headings = list(_PRINCIPLE_HEADING.finditer(section))
    if not headings:
        raise _Refusal("stale_kernel_ids", "the canonical principle kernel is empty")

    metadata_candidates = [
        line
        for line in section.splitlines()
        if "Routing metadata" in line or re.search(r"\bDP-[0-9A-Z]+\b", line) is not None
    ]
    if len(metadata_candidates) != len(headings) or any(
        _ROUTING_LINE.fullmatch(line) is None for line in metadata_candidates
    ):
        raise _Refusal(
            "stale_kernel_ids",
            "routing metadata must form one complete canonical line per principle block",
        )

    entries: list[_KernelEntry] = []
    for index, heading in enumerate(headings):
        block_end = headings[index + 1].start() if index + 1 < len(headings) else len(section)
        matches = list(_ROUTING_LINE.finditer(section, heading.end(), block_end))
        if len(matches) != 1:
            raise _Refusal(
                "stale_kernel_ids",
                "each canonical principle must carry exactly one routing metadata line",
            )
        match = matches[0]
        enforcement = match.group("enforcement")
        if enforcement not in _ALLOWED_ENFORCEMENT:
            raise _Refusal("stale_kernel_ids", "the kernel contains an unknown enforcement posture")
        entries.append(
            _KernelEntry(
                title=heading.group("title"),
                principle_id=match.group("id"),
                applicability=match.group("applicability"),
                owner=match.group("owner"),
                required_reading=match.group("required_reading"),
                enforcement=enforcement,
            )
        )

    identity = tuple(
        (
            entry.title,
            entry.principle_id,
            entry.owner,
        )
        for entry in entries
    )
    expected_identity = tuple(
        (
            title,
            principle_id,
            f"docs/DESIGN_PRINCIPLES.md :: {title}",
        )
        for title, principle_id in _CANONICAL_KERNEL
    )
    if identity != expected_identity:
        raise _Refusal(
            "stale_kernel_ids",
            "the kernel heading, ID, and canonical-owner registry drifted",
        )
    return tuple(entries)


def _assert_expected_kernel(expected: tuple[str, ...], entries: tuple[_KernelEntry, ...]) -> None:
    actual = tuple(entry.principle_id for entry in entries)
    if expected and expected != actual:
        raise _Refusal("stale_kernel_ids", "the caller's expected principle IDs are stale")


def _select_entries(
    facts: NormalizedChangeFacts,
    entries: tuple[_KernelEntry, ...],
) -> tuple[_KernelEntry, ...]:
    applicability = set(facts.risk_triggers)
    if facts.system_classification == "boundary":
        applicability.add("architecture-boundary-change")
    if (
        facts.external_effects
        or facts.write_class in {"authority-bearing", "durable", "external-effect"}
        or facts.persistence_class in {"durable", "authority"}
    ):
        applicability.add("durable-or-external-mutation-change")
    if facts.write_class == "governance-docs-process":
        applicability.add("cognition-automation-or-governance-change")
    if not applicability:
        raise _Refusal("ambiguous_authority", "the change facts select no principle applicability")

    by_applicability: dict[str, list[_KernelEntry]] = {}
    for entry in entries:
        by_applicability.setdefault(entry.applicability, []).append(entry)
    for trigger in applicability:
        matches = by_applicability.get(trigger, [])
        if not matches:
            raise _Refusal("stale_kernel_ids", "a selected applicability is absent from the kernel")
        if len(matches) != 1:
            raise _Refusal("ambiguous_authority", "a selected applicability has multiple owners")

    selected_ids = {
        by_applicability[trigger][0].principle_id for trigger in sorted(applicability)
    }
    return tuple(entry for entry in entries if entry.principle_id in selected_ids)


def _assert_kernel_references(
    repository_root: Path,
    repository_head: str,
    entries: tuple[_KernelEntry, ...],
) -> None:
    for entry in entries:
        for reference in (entry.owner, entry.required_reading):
            _assert_reference(repository_root, repository_head, reference)


def _assert_commit(repository_root: Path, repository_head: str) -> None:
    completed = _git_command(repository_root, "cat-file", "-t", repository_head)
    if completed is None or completed.returncode != 0 or completed.stdout.strip() != b"commit":
        raise _Refusal(
            "invalid_repository_head",
            "repository_head is not a commit in repository_root",
        )


def _assert_reference(repository_root: Path, repository_head: str, reference: str) -> None:
    path_text, separator, section = reference.partition(" :: ")
    if not separator or not section or section != section.strip():
        raise _Refusal(
            "missing_owner_section",
            "a kernel reference must name one exact nonempty section",
        )
    relative = PurePosixPath(path_text)
    if (
        not path_text
        or "\\" in path_text
        or relative.is_absolute()
        or ".." in relative.parts
        or relative.as_posix() != path_text
    ):
        raise _Refusal(
            "missing_owner_section",
            "a kernel reference must use one canonical repository-relative path",
        )
    text = _git_object_text(repository_root, repository_head, relative.as_posix())
    if text is None:
        raise _Refusal("missing_owner_section", "a referenced owner document is unavailable")
    matches = [
        match.group("title")
        for match in _MARKDOWN_HEADING.finditer(text)
        if match.group("title") == section
    ]
    if not matches:
        raise _Refusal("missing_owner_section", "a kernel reference section does not resolve")
    if len(matches) != 1:
        raise _Refusal("ambiguous_authority", "a kernel reference section is ambiguous")


def _git_object_text(repository_root: Path, repository_head: str, path: str) -> str | None:
    completed = _git_command(repository_root, "show", f"{repository_head}:{path}")
    if completed is None or completed.returncode != 0:
        return None
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeError:
        return None


def _git_command(
    repository_root: Path,
    *args: str,
) -> subprocess.CompletedProcess[bytes] | None:
    if not isinstance(repository_root, Path):
        return None
    try:
        return subprocess.run(
            ["git", "-C", str(repository_root), *args],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


__all__ = [
    "ChangeFacts",
    "DesignPacket",
    "DesignPacketOutcome",
    "DesignPacketRefusal",
    "NormalizedChangeFacts",
    "PrincipleSelection",
    "resolve_design_packet",
]
