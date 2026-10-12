#!/usr/bin/env python3
"""Load the channel's host BWS identity and launch the fixed probe consumer."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_CONFIG_ROOT = Path("/etc/yggdrasil/bws-deploy")
CHANNEL_PROJECT = {"test": "non-prod", "prod": "prod"}

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


def _read_deploy_identifiers(channel: str, config_root: Path = DEPLOY_CONFIG_ROOT) -> tuple[str, str]:
    if channel not in CHANNEL_PROJECT:
        raise ValueError("probe channel is invalid")
    path = config_root / f"{channel}.json"
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise ValueError("BWS channel configuration is unavailable") from None
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_uid != 0:
            raise ValueError("BWS channel configuration is unavailable")
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=True) as handle:
            descriptor = -1
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("BWS channel configuration is unavailable") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(payload, dict):
        raise ValueError("BWS channel configuration is unavailable")
    project_id = payload.get("project_id")
    organization_id = payload.get("organization_id")
    if not isinstance(project_id, str) or not isinstance(organization_id, str):
        raise ValueError("BWS channel configuration is unavailable")
    return project_id, organization_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", choices=tuple(CHANNEL_PROJECT), required=True)
    args = parser.parse_args(argv)
    try:
        project_id, organization_id = _read_deploy_identifiers(args.channel)
        os.environ["BWS_READER_PROJECT"] = CHANNEL_PROJECT[args.channel]
        os.environ["BWS_PROJECT_ID"] = project_id
        os.environ["BWS_ORGANIZATION_ID"] = organization_id
        from app.ops.host_secret_bootstrap import main as bootstrap_main

        return bootstrap_main(
            [
                "--provider",
                "bws",
                "--channel",
                args.channel,
                "--consumer",
                "heimdal-external-alerts",
                "--run-probe",
            ]
        )
    except ValueError as exc:
        print(f"{exc}; probe launch refused", file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
