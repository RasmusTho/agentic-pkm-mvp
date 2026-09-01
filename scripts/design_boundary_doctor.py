#!/usr/bin/env python3
"""Render the read-only design-boundary drift report."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from app.governance.design_boundary_doctor import (
    DEFAULT_EFFECTS_PATH,
    DesignBoundaryDoctorRefusal,
    run_design_boundary_doctor,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--effects", type=Path, default=DEFAULT_EFFECTS_PATH)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        report = run_design_boundary_doctor(
            args.repo_root,
            effects_path=args.effects,
            packet_path=args.packet,
        )
    except (DesignBoundaryDoctorRefusal, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"design-boundary-doctor: refusal: {exc}", file=sys.stderr)
        return 2
    if args.as_json:
        print(report.canonical_json())
    else:
        print(f"status: {report.status}")
        for finding in report.findings:
            print(f"{finding.state}: {finding.subject}: {finding.detail}")
        print("authority: advisory evidence only; no acceptance or repair authority")
    return 0 if report.status == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
