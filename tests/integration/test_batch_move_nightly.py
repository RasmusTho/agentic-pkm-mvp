from pathlib import Path
from textwrap import dedent

from app.promotion.queue import enqueue, run_once
from scripts.yaml_roundtrip import load_frontmatter


SETTINGS_YAML = dedent("""
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
    """)


def _setup(monkeypatch, tmp_path: Path, *, note_moves_enabled: bool, settings_yaml: str = SETTINGS_YAML) -> tuple[Path, Path, Path]:
    qpath = tmp_path / "queue.jsonl"
    log = tmp_path / "log.jsonl"
    settings = tmp_path / "settings.yaml"
    vault = tmp_path / "vault"

    import app.promotion.queue as q

    monkeypatch.setattr(q, "QUEUE", qpath)
    monkeypatch.setattr(q, "LOG", log)
    monkeypatch.setattr(q, "SETTINGS", settings)
    monkeypatch.setattr(q, "VAULT", vault)
    monkeypatch.setattr(q, "_NOTE_MOVES_ENABLED", note_moves_enabled)

    settings.write_text(settings_yaml, encoding="utf-8")
    monkeypatch.setenv("PROMOTION_ALLOW_ORPHANS", "1")
    monkeypatch.setenv("PROMOTION_ORPHAN_OVERRIDE_REASON", "tests")
    return qpath, log, vault


def test_nightly_batch_moves_when_enabled(tmp_path: Path, monkeypatch):
    qpath, log, vault = _setup(monkeypatch, tmp_path, note_moves_enabled=True)
    src = vault / "Workbench" / "concept.md"
    dst_dir = vault / "2_Cards" / "Concepts"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(dedent("""        ---
        uuid: 00000000-0000-0000-0000-000000000005
        review_state: inbox
        kind: card
        category: concept
        ---
        - [x] Promote
    """), encoding="utf-8")

    enqueue(src, uuid="00000000-0000-0000-0000-000000000005", desired_state="promoted")
    processed = run_once()

    assert processed == 1
    assert (dst_dir / "concept.md").exists()
    log_lines = log.read_text(encoding="utf-8").splitlines()
    assert any("promote.done" in line for line in log_lines)


def test_batch_move_skipped_when_note_moves_disabled(tmp_path: Path, monkeypatch):
    qpath, log, vault = _setup(monkeypatch, tmp_path, note_moves_enabled=False)
    src = vault / "Workbench" / "concept.md"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(dedent("""        ---
        uuid: 00000000-0000-0000-0000-000000000006
        review_state: inbox
        kind: card
        category: concept
        ---
        - [x] Promote
    """), encoding="utf-8")

    enqueue(src, uuid="00000000-0000-0000-0000-000000000006", desired_state="promoted")
    processed = run_once()

    assert processed == 1
    assert src.exists()
    log_lines = log.read_text(encoding="utf-8").splitlines()
    assert any("promote.skip.move" in line for line in log_lines)


def test_move_updates_review_state_and_preserves_frontmatter(tmp_path: Path, monkeypatch):
    qpath, log, vault = _setup(monkeypatch, tmp_path, note_moves_enabled=True)
    src = vault / "Workbench" / "note.md"
    dst_dir = vault / "2_Cards" / "Concepts"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(dedent("""        ---
        uuid: 00000000-0000-0000-0000-000000000007
        title: Sample Note
        review_state: inbox
        kind: card
        category: concept
        tags:
          - alpha
        ---
        Body text
        - [x] Promote
    """), encoding="utf-8")

    enqueue(src, uuid="00000000-0000-0000-0000-000000000007", desired_state="promoted")
    processed = run_once()

    assert processed == 1
    moved = dst_dir / "note.md"
    assert moved.exists()
    frontmatter, body = load_frontmatter(moved.read_text(encoding="utf-8"))
    assert frontmatter["uuid"] == "00000000-0000-0000-0000-000000000007"
    assert frontmatter["title"] == "Sample Note"
    assert frontmatter["review_state"] == "promoted"
    assert "Promote" not in body


def test_move_handles_name_collision_with_suffix(tmp_path: Path, monkeypatch):
    qpath, log, vault = _setup(monkeypatch, tmp_path, note_moves_enabled=True)
    src1 = vault / "Workbench" / "concept.md"
    src2 = vault / "Inbox" / "concept.md"
    dst_dir = vault / "2_Cards" / "Concepts"
    src1.parent.mkdir(parents=True, exist_ok=True)
    src2.parent.mkdir(parents=True, exist_ok=True)
    src1.write_text(dedent("""        ---
        uuid: 00000000-0000-0000-0000-000000000008
        review_state: inbox
        kind: card
        category: concept
        ---
        - [x] Promote
    """), encoding="utf-8")
    src2.write_text(dedent("""        ---
        uuid: 00000000-0000-0000-0000-000000000009
        review_state: inbox
        kind: card
        category: concept
        ---
        - [x] Promote
    """), encoding="utf-8")

    enqueue(src1, uuid="00000000-0000-0000-0000-000000000008", desired_state="promoted")
    enqueue(src2, uuid="00000000-0000-0000-0000-000000000009", desired_state="promoted")
    processed = run_once()

    assert processed == 2
    assert (dst_dir / "concept.md").exists()
    assert (dst_dir / "concept-1.md").exists()
    assert not src1.exists()
    assert not src2.exists()
    log_lines = log.read_text(encoding="utf-8").splitlines()
    assert sum(1 for line in log_lines if "promote.done" in line) >= 2


def test_move_respects_target_rules_when_enabled(tmp_path: Path, monkeypatch):
    settings_yaml = dedent("""
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
          - when: {category: archive}
            path: 3_Archive/Notes
        default_target: 1_Triage
    """)
    qpath, log, vault = _setup(monkeypatch, tmp_path, note_moves_enabled=True, settings_yaml=settings_yaml)
    src = vault / "Workbench" / "archived.md"
    target = vault / "3_Archive" / "Notes"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(dedent("""        ---
        uuid: 00000000-0000-0000-0000-000000000010
        review_state: inbox
        kind: note
        category: archive
        ---
        - [x] Promote
    """), encoding="utf-8")

    enqueue(src, uuid="00000000-0000-0000-0000-000000000010", desired_state="promoted")
    processed = run_once()

    assert processed == 1
    assert (target / "archived.md").exists()
    log_lines = log.read_text(encoding="utf-8").splitlines()
    assert any("promote.done" in line for line in log_lines)


def test_move_handles_multiple_collisions(tmp_path: Path, monkeypatch):
    qpath, log, vault = _setup(monkeypatch, tmp_path, note_moves_enabled=True)
    dst_dir = vault / "2_Cards" / "Concepts"
    sources = []
    for idx in range(3):
        src = vault / f"Workbench{idx}" / "concept.md"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(dedent(f"""            ---
            uuid: 00000000-0000-0000-0000-00000000002{idx}
            review_state: inbox
            kind: card
            category: concept
            ---
            - [x] Promote
        """), encoding="utf-8")
        sources.append(src)
        enqueue(src, uuid=f"00000000-0000-0000-0000-00000000002{idx}", desired_state="promoted")

    processed = run_once()

    assert processed == 3
    assert (dst_dir / "concept.md").exists()
    assert (dst_dir / "concept-1.md").exists()
    assert (dst_dir / "concept-2.md").exists()
    for src in sources:
        assert not src.exists()
    log_lines = log.read_text(encoding="utf-8").splitlines()
    assert sum(1 for line in log_lines if "promote.done" in line) >= 3
