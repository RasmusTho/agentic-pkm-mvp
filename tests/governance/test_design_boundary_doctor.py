from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from app.governance.design_packet_resolver import ChangeFacts, resolve_design_packet


REPO_ROOT = Path(__file__).resolve().parents[2]
DESIGN_PRINCIPLES = REPO_ROOT / "docs/DESIGN_PRINCIPLES.md"
EFFECTS = "docs/architecture/owned-effect-boundaries.json"
REFERENCE_PAIR = re.compile(r"owner `(?P<owner>[^`]+)`; required reading `(?P<reading>[^`]+)`;")


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "fixture"
    for relative in (
        "docs/DESIGN_PRINCIPLES.md",
        "docs/architecture/SBS_FITNESS_RULES.md",
        "docs/testing/invariant-tests.md",
        EFFECTS,
        "docs/contracts/STORE_PORT.md",
        "docs/contracts/EXECUTION_REQUEST.md",
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)

    kernel = DESIGN_PRINCIPLES.read_text(encoding="utf-8")
    references = {
        reference
        for match in REFERENCE_PAIR.finditer(kernel)
        for reference in (match.group("owner"), match.group("reading"))
    }
    for reference in references:
        path_text, separator, _section = reference.partition(" :: ")
        if not separator or path_text == "docs/DESIGN_PRINCIPLES.md":
            continue
        source = REPO_ROOT / path_text
        if source.is_file():
            target = root / path_text
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Design Boundary Test")
    _git(root, "config", "user.email", "design-boundary@example.invalid")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")
    return root


def _doctor(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/design_boundary_doctor.py"),
            "--repo-root",
            str(root),
            "--json",
            *extra,
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )


def _status(result: subprocess.CompletedProcess[str]) -> str:
    assert result.stdout, result.stderr
    return json.loads(result.stdout)["status"]


def _commit_change(root: Path, relative: str, transform) -> None:
    path = root / relative
    path.write_text(transform(path.read_text(encoding="utf-8")), encoding="utf-8")
    _git(root, "add", relative)
    _git(root, "commit", "-qm", "fixture drift")


def _packet_file(root: Path, path: Path) -> None:
    head = _git(root, "rev-parse", "HEAD")
    facts = ChangeFacts(
        changed_paths=("app/example.py",),
        system_classification="boundary",
        write_class="read-only",
        persistence_class="none",
        risk_triggers=(),
    )
    packet = resolve_design_packet(facts, repository_root=root, repository_head=head)
    path.write_text(packet.canonical_json(), encoding="utf-8")  # type: ignore[union-attr]


def test_doctor_reports_typed_boundary_drift(tmp_path: Path) -> None:
    healthy = _fixture(tmp_path / "healthy")
    assert _status(_doctor(healthy)) == "healthy"

    stale = _fixture(tmp_path / "stale")
    _commit_change(
        stale,
        "docs/DESIGN_PRINCIPLES.md",
        lambda text: text.replace(
            "required reading `docs/ARCHITECTURE.md :: Boundary Enforcement`",
            "required reading `docs/MISSING.md :: Boundary Enforcement`",
            1,
        ),
    )
    assert _status(_doctor(stale)) == "stale-reference"

    duplicate = _fixture(tmp_path / "duplicate")
    _commit_change(
        duplicate,
        "docs/DESIGN_PRINCIPLES.md",
        lambda text: text.replace(
            "ID `DP-02`; applicability `capability-or-orchestration-change`",
            "ID `DP-02`; applicability `architecture-boundary-change`",
            1,
        ),
    )
    assert _status(_doctor(duplicate)) == "duplicate-authority"

    packet_drift = _fixture(tmp_path / "packet")
    packet = packet_drift / "packet.json"
    _packet_file(packet_drift, packet)
    _commit_change(
        packet_drift,
        "docs/DESIGN_PRINCIPLES.md",
        lambda text: text.replace("# Design Principles", "# Design Principles\n\nFixture revision.", 1),
    )
    assert _status(_doctor(packet_drift, "--packet", str(packet))) == "packet-drift"

    effect_drift = _fixture(tmp_path / "effect")
    _commit_change(
        effect_drift,
        EFFECTS,
        lambda text: text.replace('"effect_class": "external"', '"effect_class": "unknown"', 1),
    )
    assert _status(_doctor(effect_drift)) == "unclassified-effect"

    invalid = _fixture(tmp_path / "invalid")
    _commit_change(invalid, EFFECTS, lambda text: text.replace("owned_effect_boundaries.v1", "unknown.v1", 1))
    refused = _doctor(invalid)
    assert refused.returncode == 2
    assert "refusal" in refused.stderr


def test_doctor_is_read_only(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    before = _git(fixture, "status", "--porcelain")
    first = _doctor(fixture)
    after = _git(fixture, "status", "--porcelain")
    second = _doctor(fixture)

    assert first.returncode == 0
    assert before == after == ""
    assert first.stdout == second.stdout


def test_doctor_output_is_evidence_not_authority(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    result = _doctor(fixture)
    payload = json.loads(result.stdout)

    assert payload["contract"] == "design_boundary_doctor.v1"
    assert payload["authority"] == "advisory_evidence_only_no_acceptance_or_repair_authority"
    assert payload["uncertainty"]
    assert any(item.startswith("docs/DESIGN_PRINCIPLES.md#sha256:") for item in payload["evidence"])
    assert "accept" not in payload["status"]
    assert "repair" not in payload["status"]
