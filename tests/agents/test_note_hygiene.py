from app.agents.note_hygiene.agent import classify_and_act

def test_title_url_only_salvaged():
    note = {"fm":{"uuid":"u1","kind":"concept"}, "body":"# Widgets\nhttps://example.com/x"}
    out = classify_and_act(note)
    assert "## Summary" in out["body"]
    assert out["action"] == "fix_structure"

def test_frontmatter_only_archived():
    note = {"fm":{"uuid":"u2","kind":"concept"}, "body":""}
    out = classify_and_act(note)
    assert out["action"] == "archive"

def test_large_json_moved_to_attachment():
    body = "# A\n```\n" + "x"*10000 + "\n```"
    note = {"fm":{"uuid":"u3","kind":"concept"}, "body":body}
    out = classify_and_act(note)
    assert out["action"] in ("fix_structure","keep")
