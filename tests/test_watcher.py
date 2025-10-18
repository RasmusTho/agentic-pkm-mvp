from app.ingest import watcher
from app.settings import settings


def test_watcher_processes_text_file(monkeypatch, tmp_path):
    watch_dir = tmp_path / "incoming"
    vault_dir = tmp_path / "vault"
    inbox_dir = vault_dir / "Inbox"
    processed_dir = watch_dir / "processed"

    watch_dir.mkdir(parents=True)
    (watch_dir / "note.txt").write_text("alpha beta gamma", encoding="utf-8")

    monkeypatch.setattr(settings, "watch_dir", str(watch_dir), raising=False)
    monkeypatch.setattr(settings, "vault_dir", str(vault_dir), raising=False)
    monkeypatch.setattr(settings, "inbox_subdir", "Inbox", raising=False)
    monkeypatch.setattr(settings, "processed_dir", "processed", raising=False)
    monkeypatch.setattr(settings, "chunk_size", 4, raising=False)
    monkeypatch.setattr(settings, "chunk_overlap", 1, raising=False)

    processed = watcher.process_once()
    assert processed == 1

    md_files = list(inbox_dir.glob("*.md"))
    assert len(md_files) == 1
    content = md_files[0].read_text(encoding="utf-8")
    assert "alpha beta" in content
    assert (processed_dir / "note.txt").exists()
