"""Served controls and official SDK against one temporary native binding."""
from __future__ import annotations

from contextlib import contextmanager
import os
from time import sleep

import pytest

from tests.companion_ui.live_operations_acceptance import browser_journeys
from tests.companion_ui.test_operations_workspace import gateway
from tests.operations._operations_acceptance_harness import host, journey
from tests.operations._surface_harness import runtime_http

pytestmark = [pytest.mark.usefixtures("product_model_access_gateway"), pytest.mark.browser_runtime,
    pytest.mark.skipif(os.environ.get("COMPANION_UI_BROWSER_TESTS") != "1",
                       reason="Real Chromium proof executes in the blocking browser lane")]


@contextmanager
def served_journey(tmp_path, monkeypatch):
    instance = host(tmp_path, monkeypatch)
    with runtime_http(instance) as (api, calls, _), gateway(instance) as (ui, _):
        run = journey(instance, tmp_path / "served-original", api, ui)
        original_command, original_probe = run.command, run.native.observe
        conflict_phase = [False]

        def command(role, *args, **kwargs):
            if role == "concurrent":
                conflict_phase[0] = True
            return original_command(role, *args, **kwargs)

        def observe():
            # Real remote observations can exceed the UI's 1s receipt poll.
            # Keep that ordering deterministic without replacing a native
            # outcome or reducing the admitted source/effect obligations.
            if conflict_phase[0]:
                sleep(1.25)
            return original_probe()

        monkeypatch.setattr(run, "command", command)
        monkeypatch.setattr(run.native, "observe", observe)
        try:
            browser_journeys(run)
            yield instance, run, calls
        finally:
            run.http.close()


def test_served_companion_journeys_use_same_native_receipts(tmp_path, monkeypatch):
    with served_journey(tmp_path, monkeypatch) as (_, run, _):
        expected = {"browser_discovery", "browser_selected_preflight", "browser_confirmation_progress",
                    "browser_cancel", "browser_receipt_recovery", "browser_conflict"}
        assert set(run.observations) == expected
        assert all(row["status"] == "passed" for row in run.observations.values())
        parity = run.observations["browser_receipt_recovery"]["proof"]["parity"]
        assert parity["sdk"] == parity["http"] == parity["native"]
        batch = run.observations["browser_confirmation_progress"]["proof"]["native_parity"]
        assert len(batch) == 2 and all(row["sdk"] == row["http"] == row["native"] for row in batch.values())
        conflict = run.observations["browser_conflict"]["proof"]
        assert conflict["pre_sha256"] == conflict["post_sha256"]
        for path in run.directory.iterdir():
            assert run.bearer.encode() not in path.read_bytes()
