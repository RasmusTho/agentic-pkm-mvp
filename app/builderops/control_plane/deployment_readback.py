"""Fresh, credential-free projection of the selected host deployment files."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def deployment_readback() -> dict[str, Any] | None:
    """Reread both mounted files; missing, malformed or changing files refuse."""
    receipt_path = os.environ.get("BUILDEROPS_DEPLOYMENT_RECEIPT_FILE")
    pin_path = os.environ.get("BUILDEROPS_SELECTED_PIN_FILE")
    if not receipt_path or not pin_path:
        return None
    try:
        receipt_file, pin_file = Path(receipt_path), Path(pin_path)
        receipt_bytes, pin_bytes = receipt_file.read_bytes(), pin_file.read_bytes()
        raw = json.loads(receipt_bytes)
        pairs = [line.split("=", 1) for line in pin_bytes.decode().splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
        pin = dict(pairs)
        if len(pin) != len(pairs) or not isinstance(raw, dict):
            return None
        patterns = {"source_sha": r"[0-9a-f]{40}", "image_digest": r"sha256:[0-9a-f]{64}",
                    "postgres_image_digest": r"sha256:[0-9a-f]{64}", "candidate_receipt_sha": r"[0-9a-f]{64}"}
        pin_keys = {"source_sha": "BUILDEROPS_SOURCE_SHA", "image_digest": "BUILDEROPS_IMAGE_DIGEST",
                    "postgres_image_digest": "BUILDEROPS_POSTGRES_IMAGE_DIGEST",
                    "candidate_receipt_sha": "BUILDEROPS_CANDIDATE_RECEIPT_SHA"}
        selected = {key: pin.get(pin_keys[key]) for key in patterns}
        if any(not isinstance(raw.get(key), str) or re.fullmatch(pattern, raw[key]) is None
               or selected[key] != raw[key] for key, pattern in patterns.items()):
            return None
        if (raw.get("project") != "builderops-control-plane"
                or any(raw.get(key) is not True for key in ("migration_completed", "authority_fencing_required"))
                or any(type(raw.get(key)) is not int or raw[key] < 1 for key in ("schema_version", "authority_epoch"))):
            return None
        receipt = {key: raw[key] for key in (*patterns, "project", "migration_completed",
                                           "authority_fencing_required", "schema_version", "authority_epoch")}
        if receipt_file.read_bytes() != receipt_bytes or pin_file.read_bytes() != pin_bytes:
            return None
        return {"deployment_receipt": receipt, "selected_pin": selected,
                "observed_at": datetime.now(timezone.utc).isoformat()}
    except (OSError, ValueError, UnicodeError):
        return None
