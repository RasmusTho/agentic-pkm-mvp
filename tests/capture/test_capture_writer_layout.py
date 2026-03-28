from app.capture.writer import generate_notes


def test_generate_notes_links_entities_and_sets_canonical_draft_review_state() -> None:
    bundle = {
        "capture_id": "cap-2025-10-30",
        "summary": "Vi behöver koppla OPNsense till Jaeger via Demerzel.",
        "signal_quality": "high",
        "areas": ["infra"],
        "tasks": [{
            "uuid": "task-1",
            "owner": "Rasmus",
            "text": "Konfigurera export till Jaeger från OPNsense på Demerzel",
            "deadline": "2025-10-31",
            "status": "open",
            "importance": "blocking",
            "entities": [
                {"name": "OPNsense", "entity_uuid": "ent-OPNsense"},
                {"name": "Jaeger", "entity_uuid": "ent-Jaeger"},
                {"name": "Demerzel", "entity_uuid": "ent-Demerzel"}
            ]
        }],
        "decisions": [{
            "uuid": "dec-1",
            "text": "Tracing måste vara aktiv innan v4.4 freeze.",
            "entities": [
                {"name": "Demerzel", "entity_uuid": "ent-Demerzel"}
            ]
        }],
        "entities": [
            {"name": "OPNsense", "entity_uuid": "ent-OPNsense", "entity_type": "firewall", "signal_quality": "authoritative", "notes": ""},
            {"name": "Jaeger", "entity_uuid": "ent-Jaeger", "entity_type": "observability", "signal_quality": "authoritative", "notes": ""},
            {"name": "Demerzel", "entity_uuid": "ent-Demerzel", "entity_type": "host", "signal_quality": "authoritative", "notes": "Mac mini"}
        ],
        "raw": "Råtext här..."
    }

    notes = generate_notes(bundle)
    cap_note = notes["capture"]

    fm = cap_note["frontmatter"]
    assert fm["uuid"] == "cap-2025-10-30"
    assert fm["kind"] == "capture"
    assert fm["review_state"] == "draft"
    assert "infra" in fm["areas"]
    assert fm["signal_quality"] == "high"

    body = cap_note["body"]
    assert "[[OPNsense]]" in body
    assert "[[Jaeger]]" in body
    assert "[[Demerzel]]" in body
    assert "## Raw" in body
    assert "Råtext här..." in body
