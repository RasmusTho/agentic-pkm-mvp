#!/usr/bin/env python3
"""Print a BuilderOps-only preparation plan. This program never installs anything."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.ops.builderops_probe import ProbeConfig  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-engine-id", required=True)
    parser.add_argument("--expected-epoch", type=int, required=True)
    parser.add_argument("--expected-schema-version", type=int, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", args.expected_engine_id) or not all(
        0 < value <= 2**63 - 1 for value in (args.expected_epoch, args.expected_schema_version)
    ):
        parser.error("qualified engine and positive epoch/schema identity required")
    config = ProbeConfig(
        target_hostname="builder-system",
        engine_socket="unix:///run/docker-builderops.sock",
        expected_engine_id=args.expected_engine_id,
        project="builderops-control-plane",
        api_url="http://127.0.0.1:18100",
        expected_epoch=args.expected_epoch,
        expected_schema_version=args.expected_schema_version,
        probe_token_file="/opt/builderops/secrets/probe-token",
        alert_runtime_file="/run/yggdrasil-builderops-probe/alerts.env",
        state_file="/var/lib/yggdrasil-builderops-probe/alert.json",
        max_outbox_age_seconds=300,
    )
    from dataclasses import asdict

    print(
        json.dumps(
            {
                "schema": "builderops_probe_preparation.v1",
                "target": "bob-1",
                "configuration": asdict(config),
                "host_mutations": [],
                "activation_ready": False,
                "artifacts": [
                    "app/__init__.py",
                    "app/ops/__init__.py",
                    "app/ops/builderops_probe.py",
                    "app/ops/builderops_probe_secret.py",
                    "ops/host-setup/mac-mini/notification_channels.py",
                    "config/systemd/yggdrasil-builderops-probe.service",
                    "config/systemd/yggdrasil-builderops-probe.timer",
                ],
                "prerequisites": [
                    "exact reviewed source/interpreter and qualified bob-1 identity",
                    "host-owned mode-0600 configuration with qualified engine/epoch/schema",
                    "existing health:read probe-token custody and private loopback reachability",
                    "separately admitted bob-1 Heimdal alert consumer with secure runtime handoff",
                    "operator authorization for installation and outage/recovery drill",
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
