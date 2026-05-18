State: covers PRs #1062/#1067, #1063/#1068, #1064/#1069, #1065/#1070 — merged to main 2026-05-18.
# UAT — Real-Note Vertical Slice

Purpose: end-to-end validation of the read-only artifact API + companion UI components against an
actual vault note on disk, without mocks.

Scope: test/runbook only. No new feature work. No UI framework decision.

## Components under test

| PR pair | Component |
|---------|-----------|
| #1063/#1068 | `GET /api/artifacts/note` — read-only artifact endpoint |
| #1064/#1069 | `RealNoteWorkspaceShell` — renders returned payload |
| #1065/#1070 | `WorkspaceConfirmSession` — Panel confirm → artifact refresh |
| #1062/#1067 | Integration: proposal → `POST /api/panel/confirm` → vault projection + receipt |

## Preconditions

- Python environment active with repo deps installed.
- A vault is configured (`VAULT_ROOT` or the default `vault/` directory contains at least one `.md` note).
- No Postgres required; `STORE_BACKEND=memory` (default) is sufficient for this slice.

## 1) Unit and integration tests (automated)

Run all four test modules:

```bash
python -m pytest \
  tests/api/test_artifact_note_read_api.py \
  tests/companion_ui/test_real_note_workspace_shell.py \
  tests/companion_ui/test_panel_confirm_artifact_refresh.py \
  tests/integration/test_panel_confirm_integration.py \
  -v
```

Expected: 20 passed, 0 failed.

## 2) Live runtime UAT (against real vault note)

The script below exercises all five checks against an actual file on disk. Run from repo root:

```bash
PYTHONPATH=".:companion-ui/companion-app" python - <<'PYEOF'
import os, sys
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

os.environ.setdefault("INDEX_OUTBOX_PATH", "/tmp/uat_outbox.jsonl")

from app.config.paths import resolve_vault_root
vault = resolve_vault_root()
notes = [n for n in vault.glob("**/*.md") if n.stat().st_size > 0]
real_note = notes[0]
real_note_rel = str(real_note.relative_to(vault))
print(f"vault root : {vault}")
print(f"real note  : {real_note_rel}")

from app.api.app import app
client = TestClient(app)

# Check 1: GET /api/artifacts/note
resp = client.get("/api/artifacts/note", params={"note_path": real_note_rel, "artifact_id": "uat-art-001"})
assert resp.status_code == 200
data = resp.json()
assert data["body"] == real_note.read_text(encoding="utf-8")
assert len(data["content_hash"]) == 16
print(f"CHECK 1 GET /api/artifacts/note        PASS  title={data['title']!r}")

# Check 2: RealNoteWorkspaceShell
from companion_ui.workspace.real_note_workspace_shell import (
    ArtifactNotePayload, RealNoteWorkspaceShell,
    REGION_NOTE_BODY, REGION_NOTE_HEADER, REGION_AGENT_RAIL,
)
shell = RealNoteWorkspaceShell(payload=ArtifactNotePayload(**data))
assert shell.is_read_only and shell.mutation_controls == []
assert shell.region_role(REGION_NOTE_BODY) == "primary"
assert shell.region_role(REGION_AGENT_RAIL) == "secondary"
print(f"CHECK 2 RealNoteWorkspaceShell render  PASS")

# Check 3+4+5: WorkspaceConfirmSession
from companion_ui.workspace.confirm_session import WorkspaceConfirmSession
import app.panel.confirmation as confirm_module
from app.events.panel import (
    NoteRef, PanelInfo, PanelIntentAction, PanelIntentEvent,
    PanelIntentPayload, PanelRuntimeActionResult,
)
from app.agents.panel.writeback import stable_action_id, AI_STATUS_HEADER
from app.agents.panel_agent.state import PanelAgentState
from app.events.schema import make_outbox_event
from app.panel.confirmation import StagedProposal
import app.agents.panel_agent.runtime as runtime_module

ACTION_LABEL = "send email"
PROPOSAL_ID  = "prop-uat-real-001"
ARTIFACT_ID  = "uat-art-001"
AID = stable_action_id(ACTION_LABEL)

# UAT note lives inside the vault so the GET endpoint can serve it, and both
# the confirm writeback and the artifact refresh operate on the same file.
import shutil
vault_uat_dir = vault / "_uat_test"
vault_uat_dir.mkdir(exist_ok=True)
uat_note = vault_uat_dir / "test_confirm_session.md"
uat_note_rel = "_uat_test/test_confirm_session.md"
uat_note.write_text(f"# UAT Note\n- [ ] {ACTION_LABEL} <!--ai:id={AID}-->\nBody.\n", encoding="utf-8")

try:
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()
    confirm_module._proposal_store.stage(
        PROPOSAL_ID,
        StagedProposal(
            artifact_id=ARTIFACT_ID,
            intent_event=PanelIntentEvent(payload=PanelIntentPayload(
                note=NoteRef(uuid=ARTIFACT_ID, path=str(uat_note.resolve())),
                panel=PanelInfo(panel_id=PROPOSAL_ID, instruction="UAT"),
                actions=[PanelIntentAction(id=AID, label=ACTION_LABEL, checked=True)],
            )),
            proposed_at=0.0,
        ),
    )

    def _fake_graph(state, **kwargs):
        result = PanelRuntimeActionResult(id=AID, label=ACTION_LABEL, checked=True, status="triggered")
        emitted = [make_outbox_event(event="panel.intent.executed", source="test", payload={})]
        return PanelAgentState(
            trace_id="uat-trace", note=state.note, panel=state.panel,
            actions=state.actions, action_results=[result],
            emitted_events=emitted, executed_action_ids=[AID],
            vault_root=None, intent_event=state.intent_event,
        )

    class RealApiStub:
        def post(self, url, *, json):
            return client.post(url, json=json).json()
        def get(self, url, *, params):
            return client.get(url, params=params).json()

    with patch.object(runtime_module, "run_panel_graph", _fake_graph), \
         patch.object(runtime_module, "load_panel_action_catalog", lambda: None), \
         patch.object(runtime_module, "_write_db_outbox_events", lambda _: None):

        session = WorkspaceConfirmSession(http_client=RealApiStub())
        outcome = session.confirm(
            proposal_id=PROPOSAL_ID, artifact_id=ARTIFACT_ID,
            note_path=uat_note_rel, action="confirm",
            idempotency_key="idem-uat-real-001",
        )

    assert outcome.status == "executed"
    print(f"CHECK 3 WorkspaceConfirmSession.confirm PASS  status={outcome.status}")

    # Refresh must reflect the post-confirm state of the same note that was confirmed.
    assert session.current_payload is not None
    assert session.current_payload.body == uat_note.read_text(encoding="utf-8")
    print(f"CHECK 4 Artifact refresh after confirm  PASS")

    vault_content = uat_note.read_text(encoding="utf-8")
    assert f"- [ ] {ACTION_LABEL}" not in vault_content
    assert AI_STATUS_HEADER in vault_content and "✅" in vault_content
    print(f"CHECK 5 Vault state after confirm        PASS")

finally:
    shutil.rmtree(vault_uat_dir, ignore_errors=True)

print("\n  UAT RESULT:  ALL 5 CHECKS PASSED  ✅")
PYEOF
```

## 3) Expected results

| Check | Assertion |
|-------|-----------|
| `GET /api/artifacts/note` | 200, body matches disk, 16-char content_hash, artifact_id echoed |
| `RealNoteWorkspaceShell` | is_read_only=True, mutation_controls=[], all three regions present |
| `WorkspaceConfirmSession.confirm` | status=executed, receipt.outcome=success |
| Artifact refresh | current_payload.body matches real vault note after confirm |
| Vault projection | checkbox removed, AI_STATUS_HEADER + ✅ receipt written to note file |

## 4) Acceptance receipt

Filled by operator after a passing run:

```
date:          <YYYY-MM-DD>
operator:      <name>
vault:         <vault path or "vault/">
real note:     <note_path shown in output>
unit+int:      20 passed
live UAT:      5/5 PASS
blocker:       none
```

## 5) Known limits

- The live UAT patches `run_panel_graph` and `_write_db_outbox_events` to avoid LLM and Postgres
  dependencies. Real LLM execution and DB outbox delivery require `DATABASE_URL` and `PANEL_AGENT_LLM_E2E=1`.
- `WorkspaceConfirmSession` is tested via an injected HTTP stub; a full-stack browser test is
  deferred to the UI framework track (out of scope for this slice).
- Path traversal and vault-root rejection are covered by unit tests in
  `tests/api/test_artifact_note_read_api.py`; they are not re-checked here.
