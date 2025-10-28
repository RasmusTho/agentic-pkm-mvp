from pathlib import Path
import json
import re

REQUIRED_FIELDS_INTENT = {"ts","trace_id","uuid","path","desired_state"}
REQUIRED_FIELDS_DONE   = {"ts","trace_id","uuid","from","to"}
REQUIRED_FIELDS_PENDING= {"ts","trace_id","uuid","path","reason"}
REQUIRED_FIELDS_ERROR  = {"ts","trace_id","uuid","path","err","retries"}

def test_event_shapes_contract(tmp_path: Path):
    intent = {"ts":"2025-01-01T00:00:00Z","trace_id":"t","uuid":"U","path":"vault/note.md","desired_state":"promoted"}
    done   = {"ts":"2025-01-01T00:00:01Z","trace_id":"t","uuid":"U","from":"vault/note.md","to":"vault/2_Cards/note.md"}
    pend   = {"ts":"2025-01-01T00:00:02Z","trace_id":"t","uuid":"U","path":"vault/note.md","reason":"link_update_unverified"}
    err    = {"ts":"2025-01-01T00:00:03Z","trace_id":"t","uuid":"U","path":"vault/note.md","err":"IOError","retries":1}

    assert REQUIRED_FIELDS_INTENT.issubset(intent.keys())
    assert REQUIRED_FIELDS_DONE.issubset(done.keys())
    assert REQUIRED_FIELDS_PENDING.issubset(pend.keys())
    assert REQUIRED_FIELDS_ERROR.issubset(err.keys())
