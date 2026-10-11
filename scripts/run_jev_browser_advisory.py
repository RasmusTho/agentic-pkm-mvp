#!/usr/bin/env python3
"""Run exact offline browser checks and retain a separately advisory Jev report."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
import xml.etree.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import ygg_jev  # noqa: E402
from tests.companion_ui.jev_advisory import (  # noqa: E402
    FIXTURE_VERSION, MIN_CONFIDENCE, RUBRIC_VERSION, InvalidObservation,
    assessed_answers, build_judgment_request, load_observations, request_fingerprint,
)

TEST_MODULE = "tests/companion_ui/test_vault_browser_state_runtime.py"
HELPER = Path.home() / ".local/bin/jev-direct"

ORDINARY_NAMES = {
    f"{method}[{viewport}-{case}]"
    for viewport in ("desktop", "narrow-pane")
    for method, cases in (
        ("test_vault_browser_failure_state_matrix", ("populated-bound", "populated-unbound", "empty-bound", "empty-unbound", "partial-bound", "error-bound")),
        ("test_read_only_note_link_navigates_with_exact_path", ("populated", "partial")),
    )
    for case in cases
}
KNOWN_NAMES = {f"test_known_combined_identity_notice_omission[{viewport}-{case}]"
               for viewport in ("desktop", "narrow-pane") for case in ("partial", "error")}


def _fsync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _durable_mkdir(directory: Path) -> None:
    missing = []
    cursor = directory
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    for path in reversed(missing):
        try:
            path.mkdir()
        except FileExistsError:
            pass
        _fsync_directory(path.parent)


def _persist(path: Path, report: dict[str, Any], *, exclusive: bool = False) -> None:
    if exclusive:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2); handle.flush(); os.fsync(handle.fileno())
    else:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as handle:
            temporary = Path(handle.name)
            json.dump(report, handle, indent=2); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    _fsync_directory(path.parent)


def _browser_inventory(junit: Path) -> dict[str, int]:
    cases = ET.parse(junit).getroot().findall(".//testcase")
    names = [case.get("name") for case in cases]
    if len(names) != 20 or set(names) != ORDINARY_NAMES | KNOWN_NAMES:
        raise InvalidObservation()
    passed = known = 0
    for case in cases:
        if case.get("classname") != "tests.companion_ui.test_vault_browser_state_runtime" or case.find("failure") is not None or case.find("error") is not None:
            raise InvalidObservation()
        if len(case.findall("skipped")) > 1:
            raise InvalidObservation()
        skipped = case.find("skipped")
        if skipped is not None:
            if case.get("name") not in KNOWN_NAMES or skipped.get("type") != "pytest.xfail" or "KD-87DEE784B97A" not in skipped.get("message", ""):
                raise InvalidObservation()
            known += 1
        else:
            passed += 1
    if passed + known != 20 or known > 4:
        raise InvalidObservation()
    return {"passed": passed, "known_defect_xfails": known}


def _run_browser(directory: Path, source_sha: str) -> int:
    env = os.environ.copy()
    env.update({"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "COMPANION_UI_BROWSER_TESTS": "1",
                "COMPANION_UI_STATE_EVIDENCE_DIR": str(directory / "browser"),
                "COMPANION_UI_JEV_OBSERVATIONS_DIR": str(directory / "observations"),
                "COMPANION_UI_JEV_SOURCE_SHA": source_sha})
    # The exact suite remains the gate. Provider failure cannot replace this result.
    with (directory / "pytest.log").open("wb") as log:
        return subprocess.run([sys.executable, "-m", "pytest", "-q", f"--junitxml={directory / 'junit.xml'}", TEST_MODULE],
                              cwd=REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=False).returncode


def _helper_status() -> str | None:
    try:
        if not HELPER.is_file():
            return "helper_unavailable"
        if hashlib.sha256(HELPER.read_bytes()).digest() != hashlib.sha256((REPO_ROOT / "scripts/ygg_jev.py").read_bytes()).digest():
            return "helper_out_of_date"
    except OSError:
        return "helper_unavailable"
    return None


def _judge_once(request: dict[str, Any]) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [sys.executable, "-I", str(HELPER)], input=json.dumps(request).encode(),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={"HOME": str(Path.home()), "PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath, "LANG": "C"},
            timeout=45, check=False,
        )
        if result.returncode != 0:
            return {"status": "unassessed", "reason": "helper_failed", "results": {}}
        answers = assessed_answers(result.stdout, request)
        return {"status": "completed", "reason": None, **answers}
    except (OSError, subprocess.TimeoutExpired, ygg_jev.InvalidResponse):
        return {"status": "unassessed", "reason": "indeterminate_or_invalid_response", "results": {}}


def run(output_root: Path, *, live_jev: bool = False) -> int:
    source_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True)
    if dirty:
        print("Run from an isolated clean checkout so evidence has one source SHA.", file=sys.stderr)
        return 2
    directory = output_root.resolve() / f"{source_sha}-{RUBRIC_VERSION}"
    _durable_mkdir(directory)
    path = directory / "report.json"
    report: dict[str, Any] = {
        "schema": "jev-browser-advisory.v1", "source_sha": source_sha,
        "fixture_version": FIXTURE_VERSION, "rubric_version": RUBRIC_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(), "advisory_only": True,
        "confidence_threshold": MIN_CONFIDENCE, "deterministic": {"status": "pending", "exit_code": 2},
        "jev": {"status": "unassessed", "reason": "not_started", "origin": "not-run", "results": {}},
    }
    try:
        _persist(path, report, exclusive=True)
    except FileExistsError:
        # Existing intent, including interrupted or unassessed attempts, is never replayed.
        print(f"Existing advisory report retained; no replay: {path}")
        try:
            prior = json.loads(path.read_text())
            return int(prior["deterministic"]["exit_code"])
        except (OSError, ValueError, KeyError, TypeError):
            return 2
    code = _run_browser(directory, source_sha)
    report["deterministic"] = {"status": "passed" if code == 0 else "failed", "exit_code": code}
    if code:
        report["jev"]["reason"] = "deterministic_failed"
    else:
        try:
            report["deterministic"].update(_browser_inventory(directory / "junit.xml"))
            observations = load_observations(directory / "observations", source_sha)
            request = build_judgment_request(observations)
            report["observations"] = observations
            report["request_sha256"] = request_fingerprint(request)
        except (InvalidObservation, ygg_jev.InvalidRequest, OSError, ET.ParseError):
            report["deterministic"] = {"status": "incomplete_evidence", "exit_code": 2}
            report["jev"]["reason"] = "incomplete_evidence"
            code = 2
        else:
            reason = "live_disabled" if not live_jev else _helper_status()
            if reason:
                report["jev"]["reason"] = reason
            else:
                report["jev"].update({"reason": "attempt_started", "origin": "live"})
                _persist(path, report)  # Durable intent BEFORE any possible dispatch.
                report["jev"].update(_judge_once(request))
    _persist(path, report)
    print(f"Advisory report: {path}")
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="Retained evidence root; existing source/rubric attempts are never replayed.")
    parser.add_argument("--live-jev", action="store_true", help="One synthetic advisory batch through the existing reviewed local helper.")
    args = parser.parse_args()
    return run(args.output_dir, live_jev=args.live_jev)


if __name__ == "__main__":
    raise SystemExit(main())
