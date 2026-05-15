from pathlib import Path
import json

from app.promotion.queue import enqueue, run_once


def _setup(monkeypatch, tmp_path: Path):
    import app.promotion.queue as q

    qpath = tmp_path / "queue.jsonl"
    log = tmp_path / "log.jsonl"
    settings = tmp_path / "settings.yaml"
    monkeypatch.setattr(q, "QUEUE", qpath)
    monkeypatch.setattr(q, "LOG", log)
    monkeypatch.setattr(q, "SETTINGS", settings)
    return qpath, log, settings


def test_enqueue_writes_single_jsonl_line(tmp_path: Path, monkeypatch):
    qpath, log, settings = _setup(monkeypatch, tmp_path)
    settings.write_text(
        "promotion:\n  cooldown_seconds: 999\n  require_idle_seconds: 0\n  max_retries: 1\n  move_policy:\n    enabled: false\n    default_target: 2_Cards/Concepts\n",
        encoding="utf-8",
    )
    p = tmp_path / "vault" / "note.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\nreview_state: inbox\n---\nBody\n", encoding="utf-8")
    enqueue(p, uuid="00000000-0000-0000-0000-000000000001", desired_state="promoted")
    lines = qpath.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["uuid"] == "00000000-0000-0000-0000-000000000001"
    assert obj["path"].endswith("note.md")
    assert obj["desired_state"] == "promoted"


def test_run_once_requeues_before_cooldown(tmp_path: Path, monkeypatch):
    qpath, log, settings = _setup(monkeypatch, tmp_path)
    settings.write_text(
        "promotion:\n  cooldown_seconds: 10\n  require_idle_seconds: 0\n  max_retries: 1\n  move_policy:\n    enabled: false\n    default_target: 2_Cards/Concepts\n",
        encoding="utf-8",
    )
    p = tmp_path / "vault" / "note.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\nreview_state: inbox\n---\nX\n", encoding="utf-8")
    enqueue(p, uuid="00000000-0000-0000-0000-000000000002", desired_state="promoted")
    processed = run_once()
    assert processed == 0
    assert qpath.exists() and len(qpath.read_text(encoding="utf-8").splitlines()) == 1


def test_run_once_skips_orphan_without_override(tmp_path: Path, monkeypatch):
    qpath, log, settings = _setup(monkeypatch, tmp_path)
    settings.write_text(
        "promotion:\n  cooldown_seconds: 0\n  require_idle_seconds: 0\n  max_retries: 1\n  move_policy:\n    enabled: false\n    default_target: 2_Cards/Concepts\n",
        encoding="utf-8",
    )
    p = tmp_path / "vault" / "note.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\nreview_state: inbox\n---\nBody\n", encoding="utf-8")
    enqueue(p, uuid="00000000-0000-0000-0000-000000000003", desired_state="promoted")
    processed = run_once()
    assert processed == 0
    log_lines = log.read_text(encoding="utf-8").splitlines()
    assert any("promote.skip.orphan" in ln for ln in log_lines)


def test_run_once_override_with_reason(tmp_path: Path, monkeypatch):
    qpath, log, settings = _setup(monkeypatch, tmp_path)
    settings.write_text(
        "promotion:\n  cooldown_seconds: 0\n  require_idle_seconds: 0\n  max_retries: 1\n  move_policy:\n    enabled: false\n    default_target: 2_Cards/Concepts\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PROMOTION_ALLOW_ORPHANS", "1")
    monkeypatch.setenv("PROMOTION_ORPHAN_OVERRIDE_REASON", "tests")
    p = tmp_path / "vault" / "note.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\nreview_state: inbox\n---\nBody\n", encoding="utf-8")
    enqueue(p, uuid="00000000-0000-0000-0000-000000000004", desired_state="promoted")
    processed = run_once()
    assert processed == 1
    log_lines = log.read_text(encoding="utf-8").splitlines()
    assert any("promote.orphan.override" in ln for ln in log_lines)


def test_run_once_writes_note_via_knowledge_port(tmp_path: Path, monkeypatch):
    import app.promotion.queue as q

    qpath, log, settings = _setup(monkeypatch, tmp_path)
    settings.write_text(
        "promotion:\n  cooldown_seconds: 0\n  require_idle_seconds: 0\n  max_retries: 1\n  move_policy:\n    enabled: false\n    default_target: 2_Cards/Concepts\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(q, "VAULT", tmp_path / "vault")
    monkeypatch.setattr(q, "prepare_relations_for_promotion", lambda *a, **k: None)
    monkeypatch.setattr(q, "ensure_object_has_relations", lambda *a, **k: None)
    monkeypatch.setenv("PROMOTION_ALLOW_ORPHANS", "1")

    p = tmp_path / "vault" / "note.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\nreview_state: inbox\n---\nBody\n", encoding="utf-8")
    enqueue(p, uuid="00000000-0000-0000-0000-000000000005", desired_state="promoted")

    calls: list[tuple[str, str]] = []

    def _fake_write(path: Path, content: str, *, vault_root: Path | None = None):  # type: ignore[no-untyped-def]
        resolved_root = (vault_root or (tmp_path / "vault")).resolve()
        rel = Path(path).resolve().relative_to(resolved_root).as_posix()
        calls.append((rel, content))
        return None

    monkeypatch.setattr(q, "write_note_from_absolute", _fake_write)
    processed = run_once()
    assert processed == 1
    assert calls and calls[0][0] == "note.md"
    assert "review_state: promoted" in calls[0][1]


# --- security: trace_id uses SHA-256, not SHA-1 ---

def test_enqueue_trace_id_is_sha256_derived(tmp_path: Path, monkeypatch):
    import hashlib

    qpath, log, settings = _setup(monkeypatch, tmp_path)
    settings.write_text(
        "promotion:\n  cooldown_seconds: 999\n  require_idle_seconds: 0\n  max_retries: 1\n"
        "  move_policy:\n    enabled: false\n    default_target: 2_Cards/Concepts\n",
        encoding="utf-8",
    )
    p = tmp_path / "vault" / "sha256_note.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\nreview_state: inbox\n---\nBody\n", encoding="utf-8")
    uuid = "aaaaaaaa-0000-0000-0000-000000000001"

    monkeypatch.setattr("app.promotion.queue.current_trace_id", lambda: None)

    enqueue(p, uuid=uuid, desired_state="promoted")
    obj = json.loads(qpath.read_text(encoding="utf-8").splitlines()[0])
    tid = obj["trace_id"]
    expected = hashlib.sha256(f"{uuid}{p}".encode()).hexdigest()[:12]
    assert tid == expected, f"trace_id {tid!r} was not derived from SHA-256"
