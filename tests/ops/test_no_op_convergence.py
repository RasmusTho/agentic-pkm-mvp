from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.stores import reset_store_backends

pytestmark = pytest.mark.not_pg


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _panel_note(title: str, auto: str = "watcher") -> str:
    return f"""---
title: {title}
ai_panel_auto_run: {auto}
---
%% AI:Start %%
## AI-instruktion
Do work
## AI-åtgärder
- [x] Gör denna anteckning evergreen
%% AI:End %%
"""


def _read_outbox(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            records.append(json.loads(ln))
        except Exception:
            continue
    return records


def _vault_digest(vault_root: Path) -> str:
    """
    Digest only 'content notes' (exclude _system + hidden state files) so we can assert
    convergence after the system has processed its own writes.
    """
    h = hashlib.sha256()
    files: list[Path] = []
    for p in vault_root.rglob("*.md"):
        rel = p.relative_to(vault_root)
        if rel.parts and rel.parts[0] == "_system":
            continue
        if any(part.startswith(".") for part in rel.parts):
            continue
        files.append(p)

    for p in sorted(files, key=lambda x: str(x.relative_to(vault_root)).lower()):
        rel = str(p.relative_to(vault_root))
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def test_no_op_convergence_watcher_then_promotion_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    1. Run watcher once -> should emit promote.intent.created (via PanelAgent runtime)
    2. Enqueue those promote intents into promotion queue and run it -> modifies note
    3. Run watcher again -> may ingest the promotion write, but MUST NOT re-emit promote.intent.created
    4. Run promotion again -> MUST be a no-op
    5. Run watcher third time -> MUST be no changes; vault content stable (converged)
    """
    reset_store_backends()

    vault = tmp_path / "vault"
    note_path = vault / "Concepts" / "A.md"
    _write(note_path, _panel_note("A", auto="watcher"))

    actions_path = tmp_path / "panel-actions.yaml"
    _write(
        actions_path,
        """---
mappings:
  - id: promote.evergreen
    label: "Gör denna anteckning evergreen"
    intent_type: promotion
    downstream_event: review.promote.evergreen
    params:
      maturity: evergreen
---
""",
    )

    outbox_path = tmp_path / "index-outbox.jsonl"
    snapshot_path = tmp_path / "watcher-state.json"

    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    env = {
        "STORE_BACKEND": "memory",
        "LLM_PROVIDER": "mock",
        "LLM_MOCK_RESPONSE": "Mock response [#1]",
        "PANEL_ACTIONS_PATH": str(actions_path),
        "INDEX_OUTBOX_PATH": str(outbox_path),
    }

    runner = CliRunner()

    # --- Tick 1: watcher
    r1 = runner.invoke(
        cli,
        ["vault-watcher-run", "--vault-root", str(vault), "--snapshot-path", str(snapshot_path)],
        env=env,
    )
    assert r1.exit_code == 0, r1.output

    outbox1 = _read_outbox(outbox_path)
    promote1 = [rec for rec in outbox1 if rec.get("event") == "promote.intent.created"]
    assert promote1, "expected promote.intent.created from panel runtime on first watcher tick"
    cursor = len(outbox1)

    # --- Promotion queue setup (patch paths into tmp)
    import app.promotion.queue as q

    queue_path = tmp_path / "promote.queue.jsonl"
    log_path = tmp_path / "promote.log.jsonl"
    settings_path = tmp_path / "promotion-settings.yaml"

    _write(
        settings_path,
        """promotion:
  cooldown_seconds: 0
  require_idle_seconds: 0
  max_retries: 1
  move_policy:
    enabled: false
    default_target: 2_Cards/Concepts
""",
    )

    monkeypatch.setattr(q, "QUEUE", queue_path, raising=False)
    monkeypatch.setattr(q, "LOG", log_path, raising=False)
    monkeypatch.setattr(q, "SETTINGS", settings_path, raising=False)

    # Allow orphan promotions in tests (avoids relation-store setup)
    monkeypatch.setenv("PROMOTION_ALLOW_ORPHANS", "1")
    monkeypatch.setenv("PROMOTION_ORPHAN_OVERRIDE_REASON", "tests")

    # Enqueue everything we saw in outbox tick1
    for rec in promote1:
        payload = rec.get("payload") or {}
        note = payload.get("note") or {}
        note_uuid = str(note.get("uuid") or "").strip()
        note_path_str = str(note.get("path") or payload.get("note_path") or "").strip()
        desired_state = str(payload.get("maturity") or "promoted").strip()

        assert note_uuid, "promote intent missing note.uuid"
        assert note_path_str, "promote intent missing note.path"

        p = Path(note_path_str)
        if not p.is_absolute():
            # best-effort: treat as vault-relative
            p2 = (vault / p).resolve()
            if p2.exists():
                p = p2
        assert p.exists(), f"promote intent path does not exist: {p}"

        q.enqueue(p, uuid=note_uuid, desired_state=desired_state)

    processed1 = q.run_once()
    assert processed1 >= 1, "expected promotion queue to process at least one queued item"

    # --- Tick 2: watcher (may see promotion's write); must NOT re-emit promote intents
    r2 = runner.invoke(
        cli,
        ["vault-watcher-run", "--vault-root", str(vault), "--snapshot-path", str(snapshot_path)],
        env=env,
    )
    assert r2.exit_code == 0, r2.output

    outbox2_new = _read_outbox(outbox_path)[cursor:]
    cursor += len(outbox2_new)

    assert not any(rec.get("event") == "promote.intent.created" for rec in outbox2_new), (
        "watcher re-emitted promote.intent.created after promotion; should converge to no-op"
    )

    # Promotion tick 2 must be a no-op (queue should be empty)
    processed2 = q.run_once()
    assert processed2 == 0

    digest_after_tick2 = _vault_digest(vault)

    # --- Tick 3: watcher must be no changes now (steady state)
    r3 = runner.invoke(
        cli,
        ["vault-watcher-run", "--vault-root", str(vault), "--snapshot-path", str(snapshot_path)],
        env=env,
    )
    assert r3.exit_code == 0, r3.output
    assert "changed=0" in r3.output, r3.output

    digest_after_tick3 = _vault_digest(vault)
    assert digest_after_tick3 == digest_after_tick2, "vault content changed after convergence"
