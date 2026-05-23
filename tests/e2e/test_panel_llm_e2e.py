from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

from app.agents.panel_agent import execute_panel_intent, run_panel_intent_for_note

pytestmark = pytest.mark.panel_llm_e2e


def _skip_if_no_llm() -> None:
    if os.getenv("PANEL_AGENT_LLM_E2E") != "1":
        pytest.skip("PANEL_AGENT_LLM_E2E!=1; skipping panel LLM E2E.")


def _skip_if_live_llm_unavailable() -> None:
    script = """
import json
from _pytest.monkeypatch import MonkeyPatch
from app.services.llm import _deterministic_llm_response, call_llm
from tests.e2e.test_panel_llm_e2e import _enable_live_llm

mp = MonkeyPatch()
_enable_live_llm(mp)
raw = None
for _ in range(3):
    candidate = call_llm(
        "panel_agent.decider.probe",
        {
            "system": "Return JSON with an actions array using the provided id.",
            "user": "Choose promote.evergreen if live LLM routing is available.",
        },
        agent="panel_agent",
        kind="panel.decider",
        trace_id="panel-llm-probe",
    )
    raw = candidate
    if candidate.strip() != _deterministic_llm_response().strip():
        break
print(json.dumps({"live": raw is not None and raw.strip() != _deterministic_llm_response().strip(), "raw": raw}))
mp.undo()
"""
    env = {key: value for key, value in os.environ.items() if not key.startswith("PYTEST_")}
    env["STORE_BACKEND"] = "memory"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    if not payload.get("live"):
        pytest.skip("live panel LLM unavailable; decider probe fell back to deterministic response")


def _enable_live_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import llm as llm_config

    monkeypatch.setenv("LLM_PROVIDER", os.getenv("LLM_PROVIDER") or "ollama")
    monkeypatch.setenv("OLLAMA_URL", os.getenv("OLLAMA_URL") or "http://127.0.0.1:11434")
    monkeypatch.setenv("LLM_MODEL", os.getenv("LLM_MODEL") or "llama3.1:8b")
    monkeypatch.setenv("LLM_TIMEOUT", os.getenv("LLM_TIMEOUT") or "30")
    monkeypatch.setattr(llm_config, "_ACTIVE_PROVIDER", None)


def _panel_actions_file(tmp_path: Path, *, variant: str) -> Path:
    path = tmp_path / f"panel-actions-{variant}.md"
    if variant == "promote_only":
        path.write_text(
            """---
mappings:
  - id: "promote.evergreen"
    kind: "promotion"
    labels:
      - "Make this note evergreen"
      - "Promote to evergreen"
    description: "Promote the note to evergreen maturity."
    llm_hint: "Choose this when the instruction explicitly asks to promote or make the note evergreen."
    intent_type: "promotion"
    downstream_event: "review.promote.evergreen"
    params:
      maturity: "evergreen"
---
""",
            encoding="utf-8",
        )
        return path
    if variant == "reply_only":
        path.write_text(
            """---
mappings:
  - id: "panel.reply"
    kind: "chat"
    labels:
      - "Reply in panel"
      - "Reflect only, no promotion"
    description: "Leave a brief reply in the panel log."
    llm_hint: "Choose this when the instruction asks for reflection or a reply without promotion."
    intent_type: "chat"
    downstream_event: "panel.reply.created"
---
""",
            encoding="utf-8",
        )
        return path
    if variant == "proposal_only":
        # #982: minimal proposal-only cognitive capabilities (non-governance-bearing).
        path.write_text(
            """---
mappings:
  - id: "proposal.next_actions"
    kind: "proposal"
    labels:
      - "Suggest next actions"
    description: "Propose a small, bounded set of next-step suggestions."
    llm_hint: "Choose this when the instruction asks what to do next or for next steps."
    intent_type: "proposal"
    downstream_event: "panel.proposal.next_actions"
    capability_class: "proposal"
    authority_class: "proposal"
    requires_human_gate: false
  - id: "retrieval.related_notes"
    kind: "retrieval"
    labels:
      - "Show related notes"
    description: "Return a bounded list of candidate related notes."
    llm_hint: "Choose this when the instruction asks for related material."
    intent_type: "retrieval"
    downstream_event: "panel.retrieval.related_notes"
    capability_class: "retrieval"
    authority_class: "read-only"
    requires_human_gate: false
---
""",
            encoding="utf-8",
        )
        return path
    raise ValueError(f"unknown panel action catalog variant: {variant}")


def _note_markdown(instruction: str, action_label: str) -> str:
    return f"""%% AI:Start %%
## AI-instruktion
{instruction}
## AI-åtgärder
- [x] {action_label}
%% AI:End %%
"""


def _freeform_note_markdown(instruction: str) -> str:
    """Panel with instruction only — no checkbox actions (freeform discovery path)."""
    return f"""%% AI:Start %%
## AI-instruktion
{instruction}
%% AI:End %%
"""


def _read_outbox(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _seed_note(note_uuid: str, markdown: str) -> None:
    from datetime import datetime, timezone
    from app.objects import DomainObject, ObjectStore

    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload={"raw_text": markdown, "origin": "vault"},
        source_ref="vault/Test.md",
        created_at=datetime.now(timezone.utc),
    )
    ObjectStore().save_object(obj, emit_outbox=False, trace_id="panel-llm-e2e")


def _run_panel(note_uuid: str) -> list[dict]:
    events = run_panel_intent_for_note(note_uuid, trace_id="panel-llm-e2e")
    assert len(events) == 1
    res = execute_panel_intent(events[0])
    return res.emitted_events


def _run_live_panel_case_subprocess(
    tmp_path: Path,
    *,
    instruction: str,
    action_label: str,
    actions_variant: str,
) -> tuple[str, list[str], list[dict]]:
    outbox_path = tmp_path / f"index-outbox-{uuid4()}.jsonl"
    actions_path = _panel_actions_file(tmp_path, variant=actions_variant)
    script = f"""
import json
import os
from pathlib import Path
from uuid import uuid4

from _pytest.monkeypatch import MonkeyPatch

from tests.e2e.test_panel_llm_e2e import _enable_live_llm, _note_markdown, _read_outbox, _seed_note
from app.agents.panel_agent.agent import run_panel_intent_for_note
from app.agents.panel_agent.runtime import execute_panel_intent

mp = MonkeyPatch()
_enable_live_llm(mp)
reset_store_backends()
note_uuid = str(uuid4())
mp.setenv("INDEX_OUTBOX_PATH", {str(outbox_path)!r})
mp.setenv("PANEL_AGENT_DECIDER", "llm")
mp.setenv("PANEL_ACTIONS_PATH", {str(actions_path)!r})
mp.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", Path({str(outbox_path)!r}), raising=False)
_seed_note(note_uuid, _note_markdown({instruction!r}, {action_label!r}))
events = run_panel_intent_for_note(note_uuid, trace_id="panel-llm-e2e")
assert len(events) == 1
result = execute_panel_intent(events[0])
payload = {{
    "note_uuid": note_uuid,
    "topics": [getattr(event, "event", None) or event.get("event") for event in result.emitted_events],
    "outbox_events": _read_outbox(Path({str(outbox_path)!r})),
}}
print(json.dumps(payload))
mp.undo()
"""
    env = {key: value for key, value in os.environ.items() if not key.startswith("PYTEST_")}
    env["STORE_BACKEND"] = "memory"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    return str(payload["note_uuid"]), list(payload["topics"]), list(payload["outbox_events"])


def _run_live_panel_freeform_subprocess(
    tmp_path: Path,
    *,
    instruction: str,
    actions_variant: str,
) -> tuple[str, list[str], list[dict]]:
    """Run a freeform panel (no checkboxes) via live LLM in an isolated subprocess."""
    outbox_path = tmp_path / f"index-outbox-freeform-{uuid4()}.jsonl"
    actions_path = _panel_actions_file(tmp_path, variant=actions_variant)
    script = f"""
import json
import os
from pathlib import Path
from uuid import uuid4

from _pytest.monkeypatch import MonkeyPatch

from tests.e2e.test_panel_llm_e2e import _enable_live_llm, _freeform_note_markdown, _read_outbox, _seed_note
from app.agents.panel_agent.agent import run_panel_intent_for_note
from app.agents.panel_agent.runtime import execute_panel_intent

mp = MonkeyPatch()
_enable_live_llm(mp)
reset_store_backends()
note_uuid = str(uuid4())
mp.setenv("INDEX_OUTBOX_PATH", {str(outbox_path)!r})
mp.setenv("PANEL_AGENT_DECIDER", "llm")
mp.setenv("PANEL_ACTIONS_PATH", {str(actions_path)!r})
mp.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", Path({str(outbox_path)!r}), raising=False)
_seed_note(note_uuid, _freeform_note_markdown({instruction!r}))
events = run_panel_intent_for_note(note_uuid, trace_id="panel-llm-freeform-e2e")
assert len(events) == 1
result = execute_panel_intent(events[0])
payload = {{
    "note_uuid": note_uuid,
    "topics": [getattr(event, "event", None) or event.get("event") for event in result.emitted_events],
    "outbox_events": _read_outbox(Path({str(outbox_path)!r})),
}}
print(json.dumps(payload))
mp.undo()
"""
    env = {key: value for key, value in os.environ.items() if not key.startswith("PYTEST_")}
    env["STORE_BACKEND"] = "memory"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    return str(payload["note_uuid"]), list(payload["topics"]), list(payload["outbox_events"])


def test_panel_llm_promotes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _skip_if_no_llm()
    _skip_if_live_llm_unavailable()
    last_topics: list[str] = []
    last_outbox_events: list[dict] = []
    for _ in range(3):
        note_uuid, topics, outbox_events = _run_live_panel_case_subprocess(
            tmp_path,
            instruction="Make this note evergreen. Do not summarize; just promote it.",
            action_label="Make this note evergreen",
            actions_variant="promote_only",
        )
        assert "panel.intent.executed" in topics
        assert "panel.log.created" in topics
        assert any(ev.get("event") == "panel.intent.created" for ev in outbox_events)
        if "promote.intent.created" in topics and any(
            ev.get("event") == "promote.intent.created" and ev.get("payload", {}).get("note", {}).get("uuid") == note_uuid
            for ev in outbox_events
        ):
            break
        last_topics = topics
        last_outbox_events = outbox_events
    else:
        pytest.fail(
            "expected promote.intent.created from live panel LLM run after 3 isolated attempts; "
            f"last topics={last_topics} outbox_events={[ev.get('event') for ev in last_outbox_events]}"
        )


def test_panel_llm_no_promotion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _skip_if_no_llm()
    _skip_if_live_llm_unavailable()
    _, topics, outbox_events = _run_live_panel_case_subprocess(
        tmp_path,
        instruction="Give me a short reflection on this note but do not promote it.",
        action_label="Reflect only, no promotion",
        actions_variant="reply_only",
    )
    assert "panel.intent.executed" in topics
    assert "panel.log.created" in topics
    assert "promote.intent.created" not in topics
    assert any(ev.get("event") == "panel.intent.created" for ev in outbox_events)
    assert not any(ev.get("event") == "promote.intent.created" for ev in outbox_events)


def test_panel_llm_freeform_promotes_without_checkboxes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Freeform path: instruction alone (no checkboxes) drives catalog discovery via live LLM."""
    _skip_if_no_llm()
    _skip_if_live_llm_unavailable()
    last_topics: list[str] = []
    last_outbox_events: list[dict] = []
    for _ in range(3):
        note_uuid, topics, outbox_events = _run_live_panel_freeform_subprocess(
            tmp_path,
            instruction="Make this note evergreen. No summary needed, just promote it.",
            actions_variant="promote_only",
        )
        assert "panel.intent.executed" in topics
        assert "panel.log.created" in topics
        assert any(ev.get("event") == "panel.intent.created" for ev in outbox_events)
        if "promote.intent.created" in topics and any(
            ev.get("event") == "promote.intent.created" and ev.get("payload", {}).get("note", {}).get("uuid") == note_uuid
            for ev in outbox_events
        ):
            break
        last_topics = topics
        last_outbox_events = outbox_events
    else:
        pytest.fail(
            "expected promote.intent.created from freeform panel LLM run (no checkboxes) after 3 attempts; "
            f"last topics={last_topics} outbox_events={[ev.get('event') for ev in last_outbox_events]}"
        )


def test_panel_generates_bounded_proposals_from_freeform_instruction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#982 AC: PanelAgent can generate at least one bounded suggestion from a
    freeform orientation request using the proposal-only capability set.

    Live-LLM smoke: with no checkbox actions and a proposal-only catalog, the
    panel must surface at least one bounded proposal-only action via the
    freeform path. The downstream surface remains observational (no
    governance-bearing event fires).
    """
    _skip_if_no_llm()
    _skip_if_live_llm_unavailable()
    last_topics: list[str] = []
    last_outbox_events: list[dict] = []
    for _ in range(3):
        _, topics, outbox_events = _run_live_panel_freeform_subprocess(
            tmp_path,
            instruction="I am not sure what to do with this note. What would you suggest next?",
            actions_variant="proposal_only",
        )
        assert "panel.intent.executed" in topics
        assert "panel.log.created" in topics
        # No governance-bearing effect from proposal-only capabilities.
        assert "promote.intent.created" not in topics
        assert not any(ev.get("event") == "promote.intent.created" for ev in outbox_events)
        # The bounded suggestion surface is the panel.action.logged receipt.
        if "panel.action.logged" in topics:
            break
        last_topics = topics
        last_outbox_events = outbox_events
    else:
        pytest.fail(
            "expected at least one bounded proposal-only suggestion (panel.action.logged) "
            "from a freeform orientation request after 3 attempts; "
            f"last topics={last_topics} outbox_events={[ev.get('event') for ev in last_outbox_events]}"
        )
