"""Opt-in all-PASS gate for parent #3347.

The native qualification owner supplies a private manifest.  Absence is a
normal skip outside that explicitly scheduled operation; once supplied, every
required scenario must pass and the attributable receipt is retained.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.journaling.live_journaling_acceptance import (
    load_manifest,
    run_qualified_journey,
    write_receipt,
)


@pytest.mark.not_pg
def test_conversational_journaling_live_acceptance() -> None:
    raw_manifest = os.environ.get("JOURNALING_ACCEPTANCE_MANIFEST", "").strip()
    if not raw_manifest:
        pytest.skip("JOURNALING_ACCEPTANCE_MANIFEST is not configured")

    manifest = load_manifest(Path(raw_manifest))
    report = run_qualified_journey(manifest)
    receipt = write_receipt(report, output_dir=manifest.output_dir)

    assert report.feature_acceptance == "PASS", (
        f"qualified journaling acceptance {report.feature_acceptance}: "
        f"{report.limitation}; receipt={receipt}"
    )
