"""Read-only, deterministic report of design-boundary metadata drift."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.governance import design_packet_resolver as resolver


DOCTOR_CONTRACT = "design_boundary_doctor.v1"
EFFECT_CONTRACT = "owned_effect_boundaries.v1"
DEFAULT_EFFECTS_PATH = Path("docs/architecture/owned-effect-boundaries.json")
FITNESS_PATH = Path("docs/architecture/SBS_FITNESS_RULES.md")
INVARIANT_PATH = Path("docs/testing/invariant-tests.md")
DoctorState = Literal[
    "healthy",
    "stale-reference",
    "duplicate-authority",
    "packet-drift",
    "unclassified-effect",
]

_STATE_ORDER = {
    "stale-reference": 0,
    "duplicate-authority": 1,
    "packet-drift": 2,
    "unclassified-effect": 3,
    "healthy": 4,
}
_EFFECT_CLASSES = {
    "authority-bearing durable",
    "mechanical durable",
    "derived/rebuildable",
    "external",
    "none",
}
_REFERENCE_PATTERN = re.compile(r"^[^\s].+ :: [^\s].+$")


@dataclass(frozen=True)
class DoctorFinding:
    state: DoctorState
    code: str
    subject: str
    detail: str
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "detail": self.detail,
            "evidence": list(self.evidence),
            "state": self.state,
            "subject": self.subject,
        }


@dataclass(frozen=True)
class DesignBoundaryReport:
    repository_head: str
    status: DoctorState
    findings: tuple[DoctorFinding, ...]
    evidence: tuple[str, ...]
    uncertainty: tuple[str, ...]
    contract: str = DOCTOR_CONTRACT
    authority: str = "advisory_evidence_only_no_acceptance_or_repair_authority"

    def to_dict(self) -> dict[str, object]:
        return {
            "authority": self.authority,
            "contract": self.contract,
            "evidence": list(self.evidence),
            "findings": [finding.to_dict() for finding in self.findings],
            "repository_head": self.repository_head,
            "status": self.status,
            "uncertainty": list(self.uncertainty),
        }

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class DesignBoundaryDoctorRefusal(ValueError):
    """Invalid authority metadata prevents a partial report."""


def run_design_boundary_doctor(
    repository_root: Path,
    *,
    packet_path: Path | None = None,
    effects_path: Path = DEFAULT_EFFECTS_PATH,
    repository_head: str | None = None,
) -> DesignBoundaryReport:
    """Inspect committed design metadata without writing any repository or external state."""

    root = repository_root.resolve()
    head = repository_head or _git_head(root)
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise DesignBoundaryDoctorRefusal("repository_head must be a lowercase 40-character Git object id")
    findings: list[DoctorFinding] = []
    evidence = [
        _evidence(root, resolver._KERNEL_PATH),
        _evidence(root, FITNESS_PATH),
        _evidence(root, INVARIANT_PATH),
    ]
    findings.extend(_inspect_kernel(root, head, evidence))
    findings.extend(_inspect_fitness(root, evidence))
    findings.extend(_inspect_effects(root, head, effects_path, evidence))
    if packet_path is not None:
        findings.extend(_inspect_packet(root, head, packet_path, evidence))

    findings.sort(key=lambda item: (_STATE_ORDER[item.state], item.code, item.subject, item.detail))
    status: DoctorState = findings[0].state if findings else "healthy"
    uncertainty = (
        "This report is advisory evidence only; it does not accept, repair, close, merge, or promote anything.",
        "The report checks the named repository snapshot and cannot prove live GitHub, BuilderOps, runtime, or owner state.",
    )
    return DesignBoundaryReport(
        repository_head=head,
        status=status,
        findings=tuple(findings),
        evidence=tuple(sorted(set(evidence))),
        uncertainty=uncertainty,
    )


def _inspect_kernel(root: Path, head: str, evidence: list[str]) -> list[DoctorFinding]:
    try:
        entries = resolver._load_kernel(root, head)
        resolver._assert_kernel_references(root, head, entries)
    except resolver._Refusal as exc:
        state: DoctorState = "duplicate-authority" if exc.code == "ambiguous_authority" else "stale-reference"
        return [
            DoctorFinding(
                state=state,
                code=exc.code,
                subject="docs/DESIGN_PRINCIPLES.md",
                detail=exc.detail,
                evidence=("docs/DESIGN_PRINCIPLES.md",),
            )
        ]
    by_applicability: dict[str, list[str]] = {}
    for entry in entries:
        by_applicability.setdefault(entry.applicability, []).append(entry.principle_id)
    for applicability, ids in sorted(by_applicability.items()):
        if len(ids) > 1:
            return [
                DoctorFinding(
                    state="duplicate-authority",
                    code="duplicate_applicability_owner",
                    subject=applicability,
                    detail="one applicability has multiple principle owners",
                    evidence=("docs/DESIGN_PRINCIPLES.md",),
                )
            ]
    return []


def _inspect_fitness(root: Path, evidence: list[str]) -> list[DoctorFinding]:
    for path in (FITNESS_PATH, INVARIANT_PATH):
        try:
            text = (root / path).read_text(encoding="utf-8")
        except OSError as exc:
            return [
                DoctorFinding(
                    state="stale-reference",
                    code="fitness_metadata_unavailable",
                    subject=path.as_posix(),
                    detail=f"fitness metadata cannot be read: {exc}",
                    evidence=(path.as_posix(),),
                )
            ]
        if path == FITNESS_PATH and "Effectful capabilities declare an owned boundary." not in text:
            return [
                DoctorFinding(
                    state="stale-reference",
                    code="fitness_rule_missing",
                    subject=path.as_posix(),
                    detail="owned-effect fitness rule is not registered",
                    evidence=(path.as_posix(),),
                )
            ]
        if path == INVARIANT_PATH and "### owned_effect_boundaries" not in text:
            return [
                DoctorFinding(
                    state="stale-reference",
                    code="invariant_metadata_missing",
                    subject=path.as_posix(),
                    detail="owned-effect invariant is not registered",
                    evidence=(path.as_posix(),),
                )
            ]
    return []


def _inspect_effects(root: Path, head: str, path: Path, evidence: list[str]) -> list[DoctorFinding]:
    relative = _relative_path(root, path)
    evidence.append(_evidence(root, relative))
    try:
        payload = json.loads((root / relative).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DesignBoundaryDoctorRefusal(f"effect metadata is invalid: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("contract") != EFFECT_CONTRACT:
        raise DesignBoundaryDoctorRefusal("effect metadata has an unknown contract")
    declarations = payload.get("declarations")
    if not isinstance(declarations, list):
        raise DesignBoundaryDoctorRefusal("effect metadata declarations must be a list")
    findings: list[DoctorFinding] = []
    names: set[str] = set()
    for index, raw in enumerate(declarations):
        subject = f"{relative.as_posix()}[{index}]"
        if not isinstance(raw, dict):
            findings.append(_effect_finding(subject, "declaration must be an object", relative))
            continue
        name = raw.get("name")
        effect_class = raw.get("effect_class")
        owner_contract = raw.get("owner_contract")
        port = raw.get("port")
        direct_effects = raw.get("direct_effects", [])
        if isinstance(name, str) and name in names:
            findings.append(
                DoctorFinding(
                    state="duplicate-authority",
                    code="duplicate_effect_declaration",
                    subject=name,
                    detail="effect declaration name is owned more than once",
                    evidence=(relative.as_posix(),),
                )
            )
        if isinstance(name, str):
            names.add(name)
            subject = name
        if effect_class not in _EFFECT_CLASSES:
            findings.append(_effect_finding(subject, "effect class is missing or unknown", relative))
            continue
        effectful = effect_class != "none"
        if effectful and (not _nonempty(owner_contract) or not _nonempty(port)):
            findings.append(_effect_finding(subject, "effectful declaration lacks owner contract or port", relative))
        if effect_class == "none" and (_nonempty(owner_contract) or _nonempty(port) or direct_effects):
            findings.append(_effect_finding(subject, "pure declaration carries an owned effect", relative))
        if not isinstance(direct_effects, list) or any(not isinstance(item, str) or not item.strip() for item in direct_effects):
            findings.append(_effect_finding(subject, "direct effects are not a valid string list", relative))
        elif direct_effects:
            findings.append(_effect_finding(subject, "direct effects bypass the named owner port", relative))
        if effectful:
            if not isinstance(owner_contract, str) or _REFERENCE_PATTERN.fullmatch(owner_contract) is None:
                findings.append(_effect_finding(subject, "owner contract must name an exact document section", relative))
            else:
                try:
                    resolver._assert_reference(root, head, owner_contract)
                except resolver._Refusal as exc:
                    findings.append(_effect_finding(subject, f"owner contract does not resolve: {exc.detail}", relative))
    return findings


def _inspect_packet(root: Path, head: str, path: Path, evidence: list[str]) -> list[DoctorFinding]:
    relative = _relative_path(root, path)
    evidence.append(_evidence(root, relative))
    try:
        payload = json.loads((root / relative).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DesignBoundaryDoctorRefusal(f"packet metadata is invalid: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("contract") != resolver.PACKET_CONTRACT:
        raise DesignBoundaryDoctorRefusal("packet metadata has an unknown contract")
    facts = payload.get("normalized_change_facts")
    if not isinstance(facts, dict):
        raise DesignBoundaryDoctorRefusal("packet facts are missing")
    try:
        change_facts = resolver.ChangeFacts(
            changed_paths=tuple(facts["changed_paths"]),
            system_classification=facts["system_classification"],
            write_class=facts["write_class"],
            persistence_class=facts["persistence_class"],
            external_effects=tuple(facts["external_effects"]),
            risk_triggers=tuple(facts["risk_triggers"]),
            expected_principle_ids=tuple(facts["expected_principle_ids"]),
        )
        expected = resolver.resolve_design_packet(change_facts, repository_root=root, repository_head=head)
    except (KeyError, TypeError, ValueError) as exc:
        raise DesignBoundaryDoctorRefusal(f"packet facts are invalid: {exc}") from exc
    if not isinstance(expected, resolver.DesignPacket) or expected.to_dict() != payload:
        return [
            DoctorFinding(
                state="packet-drift",
                code="packet_does_not_match_snapshot",
                subject=relative.as_posix(),
                detail="persisted packet differs from the current canonical resolver projection",
                evidence=(relative.as_posix(), "docs/DESIGN_PRINCIPLES.md"),
            )
        ]
    return []


def _effect_finding(subject: str, detail: str, path: Path) -> DoctorFinding:
    return DoctorFinding(
        state="unclassified-effect",
        code="effect_declaration_invalid",
        subject=subject,
        detail=detail,
        evidence=(path.as_posix(),),
    )


def _git_head(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip().lower()


def _relative_path(root: Path, path: Path) -> Path:
    candidate = path if path.is_absolute() else root / path
    try:
        return candidate.resolve().relative_to(root)
    except ValueError as exc:
        raise DesignBoundaryDoctorRefusal("metadata paths must remain inside repository_root") from exc


def _evidence(root: Path, path: Path) -> str:
    target = root / path
    try:
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
    except OSError:
        return f"{path.as_posix()}#unreadable"
    return f"{path.as_posix()}#sha256:{digest}"


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


__all__ = [
    "DOCTOR_CONTRACT",
    "DEFAULT_EFFECTS_PATH",
    "DesignBoundaryDoctorRefusal",
    "DesignBoundaryReport",
    "DoctorFinding",
    "run_design_boundary_doctor",
]
