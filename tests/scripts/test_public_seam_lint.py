"""Contract tests for the INV-EF1 public seam gate and doctor."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "public_seam_lint.py"
REGISTER = REPO_ROOT / "docs" / "architecture" / "inv-ef1-register.json"


def _write_config(root: Path, rows: list[dict[str, str]]) -> None:
    (root / "scripts").mkdir(exist_ok=True)
    (root / "docs").mkdir(exist_ok=True)
    (root / "scripts" / "patterns.json").write_text(
        json.dumps({"patterns": [{"name": "person", "category": "ii", "regex": "operator-name"}]}),
        encoding="utf-8",
    )
    (root / "docs" / "register.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")


def _row(artifact: str, *, disposition: str = "stay") -> dict[str, str]:
    return {
        "artifact": artifact,
        "category": "ii",
        "why_load_bearing": "Fixture-owned operator binding.",
        "disposition": disposition,
        "issue": "#2892",
    }


def _init_repo(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    _write_config(root, rows)
    (root / "baseline.txt").write_text("clean\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
    return root


def _run(root: Path, mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            mode,
            "--repo-root",
            str(root),
            "--base-ref",
            "HEAD~1",
            "--patterns",
            "scripts/patterns.json",
            "--register",
            "docs/register.json",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def _commit(root: Path) -> None:
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "change"], cwd=root, check=True)


def test_gate_mode_clean_on_current_tree(tmp_path: Path) -> None:
    root = _init_repo(tmp_path, [_row("changed.txt")])
    (root / "changed.txt").write_text("operator-name\n", encoding="utf-8")
    _commit(root)

    result = _run(root, "gate")

    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)["ok"] is True


def test_gate_mode_fails_on_secret_shape(tmp_path: Path) -> None:
    root = _init_repo(tmp_path, [_row("changed.txt")])
    (root / "changed.txt").write_text("ghp_" + "a" * 24 + "\n", encoding="utf-8")
    _commit(root)

    result = _run(root, "gate")

    assert result.returncode == 1
    assert json.loads(result.stdout)["secret_hits"]


def test_gate_mode_register_coverage(tmp_path: Path) -> None:
    root = _init_repo(tmp_path, [])
    (root / "changed.txt").write_text("operator-name\n", encoding="utf-8")
    _commit(root)

    uncovered = _run(root, "gate")
    assert uncovered.returncode == 1
    assert json.loads(uncovered.stdout)["uncovered_hits"]

    _write_config(root, [_row("changed.txt")])
    _commit(root)
    covered = _run(root, "gate")
    assert covered.returncode == 0, covered.stderr + covered.stdout


def test_doctor_mode_reconciliation(tmp_path: Path) -> None:
    root = _init_repo(tmp_path, [_row("stale.txt"), _row("migrate.txt", disposition="parameterize")])
    (root / "drift.txt").write_text("operator-name\n", encoding="utf-8")
    (root / "migrate.txt").write_text("operator-name\n", encoding="utf-8")
    _commit(root)

    result = _run(root, "doctor")

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["uncovered_hits"]
    assert report["stale_rows"]
    assert report["migration_pending"]


def test_verification_process_map_machine_reference_is_registered() -> None:
    rows = json.loads(REGISTER.read_text(encoding="utf-8"))["rows"]

    assert {
        "artifact": "docs/development/BUILDER_SYSTEM_PROCESS_MAP.md",
        "category": "iii",
        "why_load_bearing": (
            "The Builder System owner doc preserves the explicit machine boundary "
            "required by the verification dispatch contract."
        ),
        "disposition": "stay",
        "issue": "#3602",
    } in rows
