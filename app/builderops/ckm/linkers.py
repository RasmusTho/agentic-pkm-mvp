"""Deterministic evidence linkers for the Capability Evidence Graph."""

from __future__ import annotations

import ast
import hashlib
import json
import posixpath
import re
from pathlib import Path

from app.builderops.ckm.models import CkmArtifact, CkmCapability
from app.builderops.ckm.store import CkmStore

_PATH_RE = re.compile(r"(?:\.\./)*(?:app|docs|tests|schemas)/[A-Za-z0-9_./-]+(?:\.md|\.py|\.json)?")
_LINK_RE = re.compile(r"\]\(([^)#]+(?:\.md|\.py|\.json))\)")
_ISSUE_RE = re.compile(r"(?<![\w/])#(\d+)\b")
_ADR_RE = re.compile(r"\bADR-(\d{4})\b")
_BOUNDARY_RE = re.compile(r"\b(HIX|WSP|HKA|SIP|GOV|EBF|PDM|DRI|RCA|MEM|CAO|EXE|SFC|OEF|CES)\b")
_PARENT_RE = re.compile(r"^parent_capability:\s*(.+?)\s*$", re.MULTILINE)
_LINKER_BASIS_PREFIXES = (
    "matrix:",
    "spec-directory:",
    "spec-source:",
    "adr-reference:",
    "test-code:",
    "github-spec-ref:",
    "github-ref:",
)


def _provenance(artifact: CkmArtifact) -> dict[str, object]:
    try:
        value = json.loads(artifact.provenance)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _seed_source(capability: CkmCapability) -> tuple[str, str | None] | None:
    marker = "seeded:"
    if not capability.existence_provenance.startswith(marker):
        return None
    source = capability.existence_provenance[len(marker) :]
    path, separator, anchor = source.partition("::")
    normalized_path = path.strip()
    if not normalized_path:
        return None
    normalized_anchor = anchor.strip() if separator and anchor.strip() else None
    return normalized_path, normalized_anchor


def _seed_path(capability: CkmCapability) -> str | None:
    source = _seed_source(capability)
    return source[0] if source is not None else None


def _contains_phrase(text: str, phrase: str, *, case_sensitive: bool = False) -> bool:
    flags = 0 if case_sensitive else re.IGNORECASE
    return bool(re.search(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", text, flags))


def _name_selectors(
    text: str,
    capabilities: list[CkmCapability],
) -> set[str]:
    """Return capability ids explicitly named in *text* without substring bleed.

    Longer capability names reserve their matching spans first, so ``Retrieval``
    is not selected merely because the text says ``Retrieval & Context
    Assembly``. A separate occurrence of ``Retrieval`` still selects the leaf.
    """
    occupied: list[tuple[int, int]] = []
    selected: set[str] = set()
    for capability in sorted(capabilities, key=lambda item: len(item.name), reverse=True):
        matches = list(
            re.finditer(
                rf"(?<![\w-]){re.escape(capability.name)}(?![\w-])",
                text,
                re.IGNORECASE,
            )
        )
        unclaimed = [
            match for match in matches
            if not any(
                start <= match.start() and match.end() <= end
                for start, end in occupied
            )
        ]
        if not unclaimed:
            continue
        selected.add(capability.id)
        occupied.extend((match.start(), match.end()) for match in unclaimed)
    return selected


def _artifact_source_text(root: Path, artifact: CkmArtifact) -> str:
    path = root / artifact.source_ref
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""
    provenance = _provenance(artifact)
    return "\n".join(
        str(provenance.get(key, "")) for key in ("title", "payload_summary")
    )


def _matrix_selectors(
    root: Path,
    line: str,
    artifact: CkmArtifact,
    candidates: list[CkmCapability],
) -> dict[str, str | None]:
    """Resolve a boundary candidate pool to source-backed capability selectors."""
    if len(candidates) == 1:
        return {candidates[0].id: None}
    row_names = _name_selectors(line, candidates)
    source_names = _name_selectors(_artifact_source_text(root, artifact), candidates)
    selectors: dict[str, str | None] = {}
    for capability in candidates:
        seed_path = _seed_path(capability)
        if seed_path == artifact.source_ref:
            selectors[capability.id] = f"seed-source:{seed_path}"
        elif capability.id in row_names:
            selectors[capability.id] = f"row-name:{capability.name}"
        elif capability.id in source_names:
            selectors[capability.id] = f"source-name:{capability.name}"
    return selectors


def _adr_disambiguator(
    text: str,
    capability: CkmCapability,
    *,
    anchor_occurrences: dict[str, int],
) -> str | None:
    """Return capability-specific evidence for an ADR sharing a seed document.

    A document path alone cannot identify one capability when multiple seed rows
    cite it. Prefer the human-readable capability name, then the SBS boundary
    code, then an anchor only when that anchor uniquely identifies a seed row
    within the shared document.
    """
    if _contains_phrase(text, capability.name):
        return f"name:{capability.name}"
    if capability.boundary_ref and _contains_phrase(
        text, capability.boundary_ref, case_sensitive=True
    ):
        return f"boundary:{capability.boundary_ref}"
    source = _seed_source(capability)
    anchor = source[1] if source is not None else None
    if anchor and anchor_occurrences.get(anchor.casefold()) == 1 and _contains_phrase(text, anchor):
        return f"anchor:{anchor}"
    return None


def _kind(artifact: CkmArtifact) -> str:
    return {
        "document": "doc",
        "source_file": "source",
        "issue": "requirement",
    }.get(artifact.artifact_kind, artifact.artifact_kind)


def _dimension(artifact: CkmArtifact) -> str:
    return {
        "test": "test_completeness",
        "pull_request": "functional_completeness",
        "issue": "requirement_coverage",
        "adr": "architectural_stability",
        "spec": "requirement_coverage",
        "document": "documentation_quality",
    }.get(artifact.artifact_kind, "functional_completeness")


def _emit(
    store: CkmStore,
    artifact: CkmArtifact,
    capability: CkmCapability,
    *,
    rule: str,
    detail: str,
    desired_edges: set[tuple[str, str, str]],
    maturity_dimension: str | None = None,
) -> int:
    evidence_kind = _kind(artifact)
    dimension = maturity_dimension or _dimension(artifact)
    basis = f"{rule}:{detail}"
    desired_edges.add((artifact.id, capability.id, basis))
    existing = store.get_evidence_edge(
        artifact_id=artifact.id,
        capability_id=capability.id,
        evidence_kind=evidence_kind,
        maturity_dimension=dimension,
        basis=basis,
    )
    if (
        existing is not None
        and existing.evidence_kind == evidence_kind
        and existing.polarity == "supports"
        and existing.maturity_dimension == dimension
        and existing.confidence == 1.0
        and existing.extraction_method == "deterministic"
        and existing.lifecycle == "confirmed"
        and existing.source_ref == artifact.source_ref
        and existing.model is None
        and existing.provider is None
    ):
        return 0
    store.upsert_evidence_edge(
        artifact_id=artifact.id,
        capability_id=capability.id,
        evidence_kind=evidence_kind,
        polarity="supports",
        maturity_dimension=dimension,
        confidence=1.0,
        extraction_method="deterministic",
        lifecycle="confirmed",
        source_ref=artifact.source_ref,
        basis=basis,
    )
    return int(existing is None)


def _matrix_links(
    store: CkmStore,
    root: Path,
    artifacts: dict[str, CkmArtifact],
    boundaries: dict[str, list[CkmCapability]],
    desired_edges: set[tuple[str, str, str]],
) -> int:
    path = root / "docs/architecture/traceability-matrix.md"
    if not path.is_file():
        return 0
    changed = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("|") or not re.match(r"^\|\s*\d+\s*\|", line):
            continue
        row_boundaries = sorted(set(_BOUNDARY_RE.findall(line)))
        refs = {match.replace("../", "") for match in _PATH_RE.findall(line)}
        for target in _LINK_RE.findall(line):
            normalized = posixpath.normpath(posixpath.join("docs/architecture", target))
            if not normalized.startswith("../"):
                refs.add(normalized)
        refs.update(f"github:issue:{number}" for number in _ISSUE_RE.findall(line))
        for number in _ADR_RE.findall(line):
            prefix = f"docs/adr/ADR-{number}"
            refs.update(ref for ref in artifacts if ref.startswith(prefix))
        for ref in sorted(refs):
            artifact = artifacts.get(ref)
            if artifact is None:
                continue
            selected: dict[str, tuple[CkmCapability, str | None]] = {}
            for boundary in row_boundaries:
                candidates = boundaries.get(boundary, [])
                selectors = _matrix_selectors(root, line, artifact, candidates)
                for capability in candidates:
                    if capability.id in selectors:
                        selected[capability.id] = (capability, selectors[capability.id])
            for capability, selector in selected.values():
                detail = f"row:{line_number}|citation:{ref}"
                if selector is not None:
                    detail = f"{detail}|selector:{selector}"
                changed += _emit(
                    store,
                    artifact,
                    capability,
                    rule="matrix",
                    detail=detail,
                    desired_edges=desired_edges,
                )
    return changed


def _spec_links(
    store: CkmStore,
    root: Path,
    artifacts: dict[str, CkmArtifact],
    capabilities: list[CkmCapability],
    desired_edges: set[tuple[str, str, str]],
) -> int:
    by_name = {capability.name.casefold(): capability for capability in capabilities}
    by_slug = {capability.name.casefold().replace(" ", "-"): capability for capability in capabilities}
    changed = 0
    for artifact in artifacts.values():
        if artifact.artifact_kind != "spec":
            continue
        path = root / artifact.source_ref
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        match = _PARENT_RE.search(text)
        if not match:
            continue
        parent = match.group(1).strip().strip('"\'').casefold()
        capability = by_name.get(parent) or by_slug.get(parent.replace(" ", "-"))
        if capability:
            changed += _emit(
                store,
                artifact,
                capability,
                rule="spec-directory",
                detail=artifact.source_ref,
                desired_edges=desired_edges,
            )
            for source_ref in sorted(set(_PATH_RE.findall(text))):
                normalized = source_ref.replace("../", "")
                source = artifacts.get(normalized)
                if source is not None and source.artifact_kind == "source_file":
                    changed += _emit(
                        store,
                        source,
                        capability,
                        rule="spec-source",
                        detail=artifact.source_ref,
                        desired_edges=desired_edges,
                    )
    return changed


def _adr_links(
    store: CkmStore,
    root: Path,
    artifacts: dict[str, CkmArtifact],
    capabilities: list[CkmCapability],
    desired_edges: set[tuple[str, str, str]],
) -> int:
    changed = 0
    capabilities_by_seed_path: dict[str, list[CkmCapability]] = {}
    for capability in capabilities:
        seed_path = _seed_path(capability)
        if seed_path:
            capabilities_by_seed_path.setdefault(seed_path, []).append(capability)
    for artifact in artifacts.values():
        if artifact.artifact_kind != "adr":
            continue
        path = root / artifact.source_ref
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for seed_path, candidates in capabilities_by_seed_path.items():
            if seed_path not in text:
                continue
            anchors = [
                source[1].casefold()
                for capability in candidates
                if (source := _seed_source(capability)) is not None and source[1] is not None
            ]
            anchor_occurrences = {anchor: anchors.count(anchor) for anchor in set(anchors)}
            for capability in candidates:
                disambiguator = None
                if len(candidates) > 1:
                    disambiguator = _adr_disambiguator(
                        text,
                        capability,
                        anchor_occurrences=anchor_occurrences,
                    )
                    if disambiguator is None:
                        continue
                detail = seed_path
                if disambiguator is not None:
                    detail = f"{seed_path}|selector:{disambiguator}"
                changed += _emit(
                    store,
                    artifact,
                    capability,
                    rule="adr-reference",
                    detail=detail,
                    desired_edges=desired_edges,
                )
    return changed


def _imported_modules(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _test_links(
    store: CkmStore,
    root: Path,
    artifacts: dict[str, CkmArtifact],
    desired_edges: set[tuple[str, str, str]],
) -> int:
    changed = 0
    artifact_edges: dict[str, set[str]] = {}
    for edge in store.list_evidence_edges():
        linked_artifact = artifacts.get(edge.source_ref)
        if (
            edge.extraction_method == "deterministic"
            and edge.lifecycle == "confirmed"
            and linked_artifact is not None
            and linked_artifact.artifact_kind == "source_file"
            and edge.evidence_kind == "source"
        ):
            artifact_edges.setdefault(edge.artifact_id, set()).add(edge.capability_id)
    capabilities = {capability.id: capability for capability in store.list_capabilities()}
    for test in artifacts.values():
        if test.artifact_kind != "test":
            continue
        candidates: set[str] = set()
        relative = test.source_ref
        if relative.startswith("tests/"):
            tail = relative.removeprefix("tests/")
            name = Path(tail).name
            mirrored = str(Path("app") / Path(tail).parent / name.removeprefix("test_"))
            candidates.add(mirrored)
        for module in _imported_modules(root / relative):
            if module.startswith("app."):
                candidates.add(module.replace(".", "/") + ".py")
        for source_ref in sorted(candidates):
            source = artifacts.get(source_ref)
            if source is None:
                continue
            capability_ids = artifact_edges.get(source.id, set())
            for capability_id in sorted(capability_ids):
                capability = capabilities.get(capability_id)
                if capability:
                    changed += _emit(
                        store,
                        test,
                        capability,
                        rule="test-code",
                        detail=source_ref,
                        desired_edges=desired_edges,
                    )
    return changed


def _github_links(
    store: CkmStore,
    artifacts: dict[str, CkmArtifact],
    capabilities: list[CkmCapability],
    desired_edges: set[tuple[str, str, str]],
) -> int:
    changed = 0
    spec_capabilities: dict[str, CkmCapability] = {}
    capability_by_id = {capability.id: capability for capability in capabilities}
    artifact_by_id = {artifact.id: artifact for artifact in artifacts.values()}
    for edge in store.list_evidence_edges():
        linked_artifact = artifact_by_id.get(edge.artifact_id)
        linked_capability = capability_by_id.get(edge.capability_id)
        if (
            linked_artifact
            and linked_capability
            and linked_artifact.artifact_kind == "spec"
            and edge.extraction_method == "deterministic"
            and edge.lifecycle == "confirmed"
            and edge.basis.startswith("spec-directory:")
        ):
            spec_capabilities[linked_artifact.source_ref] = linked_capability
    for artifact in artifacts.values():
        if artifact.artifact_kind not in {"issue", "pull_request"}:
            continue
        provenance = _provenance(artifact)
        references = provenance.get("references", [])
        if not isinstance(references, list):
            continue
        labels = provenance.get("labels", [])
        is_closed_task = (
            artifact.artifact_kind == "issue"
            and provenance.get("state") == "closed"
            and isinstance(labels, list)
            and "type:task" in labels
        )
        is_merged_pr = (
            artifact.artifact_kind == "pull_request"
            and isinstance(provenance.get("merged_at"), str)
            and bool(provenance["merged_at"])
        )
        dimension = (
            "requirement_coverage"
            if is_closed_task
            else "functional_completeness"
            if is_merged_pr
            else "integration_completeness"
        )
        emitted: set[str] = set()
        for reference in (str(value) for value in references):
            for spec_path, capability in spec_capabilities.items():
                if reference == spec_path or reference.startswith(str(Path(spec_path).parent) + "/"):
                    changed += _emit(
                        store,
                        artifact,
                        capability,
                        rule="github-spec-ref",
                        detail=reference,
                        desired_edges=desired_edges,
                        maturity_dimension=dimension,
                    )
                    emitted.add(capability.id)
        for capability in capabilities:
            seed_path = _seed_path(capability)
            if capability.id not in emitted and seed_path and any(
                str(ref).startswith(seed_path) for ref in references
            ):
                changed += _emit(
                    store,
                    artifact,
                    capability,
                    rule="github-ref",
                    detail=seed_path,
                    desired_edges=desired_edges,
                    maturity_dimension=dimension,
                )
    return changed


def link_deterministic(store: CkmStore, root: Path) -> dict[str, int | str]:
    """Run every mechanical linker and report the honest unlinked backlog."""
    store.ensure_schema()
    root = root.resolve()
    artifacts = {artifact.source_ref: artifact for artifact in store.list_artifacts()}
    capabilities = store.list_capabilities()
    boundaries: dict[str, list[CkmCapability]] = {}
    for capability in capabilities:
        if capability.boundary_ref:
            boundaries.setdefault(capability.boundary_ref, []).append(capability)
    desired_edges: set[tuple[str, str, str]] = set()
    results = {
        "matrix": _matrix_links(store, root, artifacts, boundaries, desired_edges),
        "spec": _spec_links(store, root, artifacts, capabilities, desired_edges),
        "adr": _adr_links(store, root, artifacts, capabilities, desired_edges),
        "test_code": _test_links(store, root, artifacts, desired_edges),
        "github_ref": _github_links(store, artifacts, capabilities, desired_edges),
    }
    results["removed"] = store.delete_deterministic_edges_not_in(
        desired_edges, owned_basis_prefixes=_LINKER_BASIS_PREFIXES
    )
    linked_ids = {edge.artifact_id for edge in store.list_evidence_edges()}
    results["unlinked_artifacts"] = sum(artifact.id not in linked_ids for artifact in artifacts.values())
    watermark = hashlib.sha256(
        "\n".join(f"{item.source_ref}:{item.watermark}" for item in sorted(artifacts.values(), key=lambda value: value.source_ref)).encode()
    ).hexdigest()
    store.set_watermark("deterministic_linkers", watermark)
    return {**results, "watermark": watermark}
