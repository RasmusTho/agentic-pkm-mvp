from pathlib import Path
from textwrap import dedent
from app.promotion.queue import enqueue, run_once

def test_nightly_batch_moves_when_enabled(tmp_path: Path, monkeypatch):
    qpath = tmp_path / "queue.jsonl"
    log   = tmp_path / "log.jsonl"
    settings = tmp_path / "settings.yaml"
    vault = tmp_path / "vault"
    src = vault / "@Desk" / "concept.md"
    dst_dir = vault / "2_Cards" / "Concepts"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(dedent("""\
        ---
        uuid: 00000000-0000-0000-0000-000000000005
    review_state: inbox
    kind: card
    category: concept
    ---
    - [x] Promote
    """), encoding="utf-8")

    settings.write_text(dedent("""\
    promotion:
      cooldown_seconds: 0
      require_idle_seconds: 0
      max_retries: 1
      move_policy:
        enabled: true
        update_internal_links: verify
        targets:
          - when: {kind: card, category: concept}
            path: 2_Cards/Concepts
        default_target: 2_Cards/Concepts
    """), encoding="utf-8")

    import app.promotion.queue as q
    monkeypatch.setattr(q, "QUEUE", qpath)
    monkeypatch.setattr(q, "LOG", log)
    monkeypatch.setattr(q, "SETTINGS", settings)
    monkeypatch.setattr(q, "VAULT", vault)
    monkeypatch.setenv("PROMOTION_ALLOW_ORPHANS", "1")
    monkeypatch.setenv("PROMOTION_ORPHAN_OVERRIDE_REASON", "tests")

    enqueue(src, uuid="00000000-0000-0000-0000-000000000005", desired_state="promoted")
    processed = run_once()
    assert processed == 1
    assert (dst_dir / "concept.md").exists()
