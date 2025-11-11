from __future__ import annotations

import json
import sys

from .metrics import qas003_hybrid_latency, qas010_outbox_to_index_latency


def main() -> None:
    qas003 = qas003_hybrid_latency()
    qas010 = qas010_outbox_to_index_latency()
    payload = {
        "QAS-003": qas003,
        "QAS-010": qas010,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    if qas003["p95"] > qas003["threshold"] or qas010["p95"] > qas010["threshold"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
