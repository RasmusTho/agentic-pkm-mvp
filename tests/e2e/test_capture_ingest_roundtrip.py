from pathlib import Path
from app.cli.capture_ingest import ingest_capture

def test_ingest_capture_creates_inbox_file(tmp_path, monkeypatch):
    # flytta cwd så vi inte skriver i din riktiga vault vid test
    monkeypatch.chdir(tmp_path)

    raw = """Möte med Dante om OPNsense failover.
- [ ] Köp extra WAN-modem
Beslut: Vi kör dual-WAN med failover.
"""

    src = tmp_path / "raw.txt"
    src.write_text(raw, encoding="utf-8")

    out_path = ingest_capture(src)

    assert out_path.exists()
    text = out_path.read_text(encoding="utf-8")

    # basic expectations
    assert text.startswith("---\n")
    assert "review_state: inbox" in text
    assert "## Tasks" in text
    assert "Köp extra WAN-modem" in text
    assert "[[OPNsense]]" in text or "OPNsense" in text
