from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_REQUIREMENTS = REPO_ROOT / "requirements.txt"
APP_REQUIREMENTS = REPO_ROOT / "app" / "requirements.txt"
DOCKERFILE = REPO_ROOT / "Dockerfile"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
PY312_SMOKE = REPO_ROOT / "scripts" / "py312_smoke_test.sh"

PINNED_RUNTIME_PACKAGES = ("numpy", "langgraph")
REQUIREMENTS_REF_RE = re.compile(r"-r\s+(?P<path>['\"]?[^'\"\s\\]*requirements\.txt['\"]?)")


@dataclass(frozen=True)
class RequirementEntry:
    requirement: Requirement
    source: Path


@dataclass(frozen=True)
class InstallSource:
    owner: Path
    location: str
    requirements_ref: str


def _strip_comment(line: str) -> str:
    return line.split("#", 1)[0].strip()


def _parse_requirements(path: Path, seen: frozenset[Path] = frozenset()) -> dict[str, RequirementEntry]:
    path = path.resolve()
    if path in seen:
        raise AssertionError(f"Cyclic requirements include detected at {path}")
    if not path.exists():
        raise AssertionError(f"Missing requirements file: {path.relative_to(REPO_ROOT)}")

    entries: dict[str, RequirementEntry] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = _strip_comment(raw_line)
        if not line:
            continue
        if line.startswith(("-r ", "--requirement ")):
            include = line.split(maxsplit=1)[1]
            include_path = (path.parent / include).resolve()
            entries.update(_parse_requirements(include_path, seen | {path}))
            continue
        if line.startswith(("-", "git+", "http://", "https://")):
            continue

        requirement = Requirement(line)
        entries[canonicalize_name(requirement.name)] = RequirementEntry(
            requirement=requirement,
            source=path,
        )
    return entries


def _major_version(entry: RequirementEntry) -> int | None:
    exact_versions = [
        spec.version
        for spec in entry.requirement.specifier
        if spec.operator in {"==", "==="} and not spec.version.endswith(".*")
    ]
    versions = exact_versions or [
        spec.version
        for spec in entry.requirement.specifier
        if spec.operator in {">=", ">", "~="}
    ]
    if not versions:
        return None

    try:
        return max(Version(version).major for version in versions)
    except InvalidVersion as exc:
        raise AssertionError(
            f"Unable to parse version in {entry.source.relative_to(REPO_ROOT)}: "
            f"{entry.requirement}"
        ) from exc


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _runtime_requirement_refs(command_text: str) -> list[str]:
    refs: list[str] = []
    for match in REQUIREMENTS_REF_RE.finditer(command_text):
        ref = match.group("path").strip("'\"")
        if PurePosixPath(ref).name == "dev-requirements.txt":
            continue
        refs.append(ref)
    return refs


def _workflow_run_blocks() -> list[tuple[Path, str, str]]:
    blocks: list[tuple[Path, str, str]] = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        jobs = data.get("jobs") or {}
        for job_name, job in jobs.items():
            for step_index, step in enumerate(job.get("steps") or []):
                run = step.get("run")
                if isinstance(run, str):
                    blocks.append((path, f"jobs.{job_name}.steps[{step_index}]", run))
    return blocks


def _install_sources() -> list[InstallSource]:
    sources = [
        InstallSource(DOCKERFILE, "Dockerfile", ref)
        for ref in _runtime_requirement_refs(DOCKERFILE.read_text(encoding="utf-8"))
    ]
    for path, location, run in _workflow_run_blocks():
        sources.extend(
            InstallSource(path, location, ref) for ref in _runtime_requirement_refs(run)
        )
    sources.extend(
        InstallSource(PY312_SMOKE, "script", ref)
        for ref in _runtime_requirement_refs(PY312_SMOKE.read_text(encoding="utf-8"))
    )
    return sources


def _manifest_for_ref(source: InstallSource) -> Path:
    ref = PurePosixPath(source.requirements_ref)
    if ref.is_absolute():
        raise AssertionError(
            f"Requirements install source must be repo-relative in {_relative(source.owner)} "
            f"{source.location}: {source.requirements_ref}"
        )
    return (REPO_ROOT / Path(ref.as_posix())).resolve()


def test_shared_pins_do_not_diverge() -> None:
    root_requirements = _parse_requirements(ROOT_REQUIREMENTS)
    app_requirements = _parse_requirements(APP_REQUIREMENTS)
    shared_names = sorted(set(root_requirements) & set(app_requirements))

    divergences: list[str] = []
    for name in shared_names:
        root_major = _major_version(root_requirements[name])
        app_major = _major_version(app_requirements[name])
        if root_major is None or app_major is None:
            continue
        if root_major != app_major:
            divergences.append(
                f"{name}: requirements.txt major {root_major} != "
                f"app/requirements.txt major {app_major}"
            )

    assert not divergences, "Shared requirement majors diverged:\n" + "\n".join(divergences)


def test_docker_and_ci_install_same_numpy_major() -> None:
    sources = _install_sources()
    assert sources, "No Docker/CI requirements install sources found"

    docker_sources = [source for source in sources if source.owner == DOCKERFILE]
    ci_sources = [source for source in sources if source.owner != DOCKERFILE]
    assert docker_sources, "Dockerfile does not install a runtime requirements manifest"
    assert ci_sources, "No CI or smoke-test runtime requirements installs found"

    app_refs = [
        f"{_relative(source.owner)} {source.location}: {source.requirements_ref}"
        for source in ci_sources
        if source.requirements_ref == "app/requirements.txt"
    ]
    assert not app_refs, "CI/smoke jobs must install root requirements.txt directly:\n" + "\n".join(
        app_refs
    )

    docker_major_sets = {
        tuple(
            _major_version(_parse_requirements(_manifest_for_ref(source))[package])
            for package in PINNED_RUNTIME_PACKAGES
        )
        for source in docker_sources
    }
    assert len(docker_major_sets) == 1
    expected_majors = docker_major_sets.pop()

    mismatches: list[str] = []
    for source in ci_sources:
        manifest = _manifest_for_ref(source)
        requirements = _parse_requirements(manifest)
        actual_majors = tuple(
            _major_version(requirements[package]) for package in PINNED_RUNTIME_PACKAGES
        )
        if actual_majors != expected_majors:
            mismatches.append(
                f"{_relative(source.owner)} {source.location} installs "
                f"{source.requirements_ref} with {PINNED_RUNTIME_PACKAGES} majors "
                f"{actual_majors}, expected {expected_majors}"
            )

    assert not mismatches, "Docker and CI runtime dependency majors diverged:\n" + "\n".join(
        mismatches
    )
