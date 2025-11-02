import json
from pathlib import Path
import jsonschema

def test_capture_triage_contract_validates():
    schema_path = Path("schemas/capture_triage.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    bundle = {
        "capture_id": "cap-2025-10-30-20-47-33",
        "summary": "Kort sammanfattning",
        "signal_quality": "high",
        "areas": ["infra"],
        "tasks": [{
            "uuid": "cap-2025-10-30-20-47-33-task-1",
            "owner": "Rasmus",
            "text": "Sätta upp Jaeger på Demerzel",
            "deadline": "2025-10-31",
            "status": "open",
            "importance": "blocking",
            "entities": [
                {"name": "Demerzel", "entity_uuid": "ent-Demerzel"}
            ]
        }],
        "decisions": [{
            "uuid": "cap-2025-10-30-20-47-33-dec-1",
            "text": "Tracing måste vara aktiv innan v4.4 freeze.",
            "entities": [
                {"name": "Demerzel", "entity_uuid": "ent-Demerzel"}
            ]
        }],
        "entities": [{
            "name": "Demerzel",
            "entity_uuid": "ent-Demerzel",
            "entity_type": "host",
            "signal_quality": "authoritative",
            "notes": "Mac mini"
        }],
        "raw": "Mötesanteckningar här..."
    }

    # Will raise if invalid
    jsonschema.validate(instance=bundle, schema=schema)
