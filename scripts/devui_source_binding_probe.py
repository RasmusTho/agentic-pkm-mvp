"""GET-only probe run inside the existing DevUI consumer, never as an operator API client."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

from app.builderops.control_plane.client import BuilderOpsControlPlaneClient, ClientConfig
from app.builderops.devui_runtime import load_configuration
from app.builderops.devui_sources import SourceReadRefusal, _task


def observe(repository: str, epoch: int, source_sha: str) -> dict[str, object]:
    config = load_configuration(os.environ)
    source = config.sources
    if (type(epoch) is not int or not 0 < epoch < 2**63 or
            source.repository != repository or config.source_sha != source_sha or
            not source.api_environment.get("BUILDEROPS_API_TOKEN_FILE") or
            source.api_environment.get("BUILDEROPS_API_TOKEN")):
        raise ValueError("consumer_binding_refused")
    invalid = projected = unprojected = 0
    with BuilderOpsControlPlaneClient(ClientConfig.from_env(source.api_environment), max_retries=0) as client:
        for phase in ("before", "after"):
            status = client.status()
            if type(status.get("authority_epoch")) is not int or status["authority_epoch"] != epoch or status.get("schema_version") != 5:
                raise ValueError("source_identity_refused")
            if phase == "after":
                break
            rows = client.list_tasks(repository=repository)
            if len(rows) > 200:
                raise ValueError("source_collection_refused")
            seen = set()
            for listed in rows:
                try:
                    _task(listed, repository=repository)
                except SourceReadRefusal as exc:
                    if str(exc) != "task_payload_invalid":
                        raise
                if listed["task_id"] in seen:
                    raise ValueError("source_collection_refused")
                seen.add(listed["task_id"])
                row = client.get_task(repository=repository, task_id=listed["task_id"])
                if (row.get("version") != listed.get("version") or
                        row.get("payload") != listed.get("payload") or
                        row.get("state") != listed.get("state")):
                    raise ValueError("source_snapshot_changed")
                try:
                    item = _task(row, repository=repository)
                except SourceReadRefusal as exc:
                    if str(exc) != "task_payload_invalid":
                        raise
                    invalid += 1
                else:
                    if item is None:
                        unprojected += 1
                    else:
                        projected += 1
    return {"contract": "devui_source_binding_observation.v1", "repository": repository,
            "source_sha": source_sha, "installed_epoch": source.authority_epoch,
            "target_epoch": epoch, "schema_version": 5,
            "observed_at": datetime.now(timezone.utc).isoformat(), "task_count": len(rows),
            "data_outcome": "refused" if invalid else "partial" if unprojected else "available" if projected else "unavailable",
            "data_refusal": "task_payload_invalid" if invalid else None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--epoch", required=True, type=int)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(observe(args.repository, args.epoch, args.source_sha), sort_keys=True))
    except Exception:
        # Transport errors and source payloads can contain credentials or private text.
        print(json.dumps({"refusal": "source_binding_probe_refused"}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
