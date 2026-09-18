"""FCA-06: real admission/read/launch; only external I/O is substituted.

Temporary Git, PostgreSQL and credential fixtures are not a live host installer,
consumer grant, candidate producer or an owner acceptance receipt.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.builderops.control_plane.client import ControlPlaneClientError
from app.builderops.devui_focus_inputs import read_focus_inputs
from app.builderops.devui_overview_inputs import derive_overview_inputs
from app.builderops.devui_sources import _task
from app.builderops.epic_dispatch import dispatch_issue_sessions
from app.builderops.issue_delivery_readback import admit_issue_delivery_task
from app.builderops.second_consumer import validate_pilot_plan
from tests.builderops.test_issue_delivery_operation import _production_adapter
from tests.builderops.test_issue_delivery_readback import BODY, _issue, _provider

HUB = "rasmustho/agentic-pkm-mvp"
CONSUMER = "rasmustho/bifrost"
ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs/BUILDER_FACTORY_ACCEPTANCE/second_consumer_pilot_plan.json"


def _admit_and_read(h):
    approval = h.approval
    number = approval["issue"]["number"]
    source = {
        **_issue(), **approval["issue"], "body": BODY,
        "labels": [{"name": "agent:ready"}],
        "html_url": approval["issue"]["url"],
        "url": f"https://api.github.com/repos/{HUB}/issues/{number}",
        "repository_url": f"https://api.github.com/repos/{HUB}",
    }
    reads = []

    def issue_reader(repository, issue_number):
        reads.append((repository, int(issue_number)))
        assert (repository, int(issue_number)) == (HUB, number)
        return deepcopy(source)

    task = admit_issue_delivery_task(
        client=h.host, repository=approval["repository"],
        approval_id=approval["approval_id"], issue_reader=issue_reader,
        observed_at=datetime.now(timezone.utc).isoformat(),
    )
    item = _task(task, repository=approval["repository"])
    assert item is not None
    overview = derive_overview_inputs(work_provider=_provider(item))
    focus = read_focus_inputs(
        f"github:{HUB}#{number}", repository=HUB, issue_reader=issue_reader,
    )
    assert overview["now"] and focus["evidence"]
    assert set(reads) == {(HUB, number)}
    return task


def _launch(h):
    approval = h.approval
    return dispatch_issue_sessions(
        approval["context"]["dispatch_plan"], _production_adapter(h),
        expected_plan_hash=approval["context"]["expected_plan_hash"],
    )


@pytest.mark.pg
def test_composed_path_is_repo_scoped_without_hub_fallback(issue_delivery_production_harness):
    observed = []
    for bifrost in (False, True):
        h = issue_delivery_production_harness(bifrost=bifrost, issue_body=BODY)
        task = _admit_and_read(h)
        approval = h.approval
        assert task["repository"] == (CONSUMER if bifrost else HUB)
        if bifrost:
            policies = approval["target_policies"]
            assert set(policies) == {HUB, CONSUMER}
            assert policies[HUB] != policies[CONSUMER]
            assert h.workflow_root != h.checkout
            assert not (h.checkout / "scripts/issue_pickup_claim.sh").exists()
            assert task["payload"]["issue_delivery"]["delivery_sources"]["issue_repository"] == HUB
            consumer = h.credentials.resolve(repository=CONSUMER, credential_id="consumer-effect", rotation_generation=1)
            hub = h.credentials.resolve(repository=HUB, credential_id="hub-effect", rotation_generation=1)
            assert consumer != hub
            for repository, credential in ((CONSUMER, "hub-effect"), (HUB, "consumer-effect")):
                with pytest.raises(ValueError, match="unavailable"):
                    h.credentials.resolve(repository=repository, credential_id=credential, rotation_generation=1)
        result = _launch(h)
        assert result["stopped_reason"] == "worker-handoff", result
        assert h.worker_transport.calls == h.transport.apply_calls == 1
        observed.append(approval["repository"])
        # Exercise actual authenticated preview, not only RepoRef parsing.
        for repository in ("rasmustho/unconfigured-consumer", ""):
            unsupported = deepcopy(dict(approval))
            unsupported["repository"] = repository
            with pytest.raises(ControlPlaneClientError):
                h.owner.issue_delivery_preview(manifest=unsupported)
        assert h.worker_transport.calls == h.transport.apply_calls == 1
    assert observed == [HUB, CONSUMER]


@pytest.mark.pg
@pytest.mark.parametrize("drift", ["missing_policy", "borrowed_policy", "borrowed_credential", "workflow_reference", "source_unavailable"])
def test_composed_consumer_refuses_borrowing_before_entry(issue_delivery_production_harness, drift):
    h = issue_delivery_production_harness(bifrost=True, issue_body=BODY)
    _admit_and_read(h)
    state = h.source_state
    if drift == "missing_policy":
        del state["documents"][CONSUMER]
    elif drift == "borrowed_policy":
        state["documents"][CONSUMER] = deepcopy(state["documents"][HUB])
    elif drift == "borrowed_credential":
        state["documents"][CONSUMER]["github_credential"]["credential_id"] = "hub-effect"
    elif drift == "workflow_reference":
        subprocess.run(["git", "-C", str(h.workflow_root), "remote", "set-url", "origin", f"https://github.com/{CONSUMER}.git"], check=True)
    else:
        state["unavailable"] = True
    result = _launch(h)
    assert result["stopped_reason"] == "session-launch-failed", result
    assert h.worker_transport.calls == h.transport.apply_calls == 0


@pytest.mark.pg
def test_consumer_has_no_product_or_owner_client_runtime_dependency(issue_delivery_production_harness, monkeypatch):
    # Boot a clean interpreter without Product configuration or services.
    env = dict(os.environ)
    for key in ("DATABASE_URL", "POSTGRES_URL", "VAULT_ROOT", "BUILDEROPS_DATABASE_URL", "BUILDEROPS_DATABASE_URL_FILE", "BUILDEROPS_CREDENTIAL_MANIFEST_FILE"):
        env.pop(key, None)
        monkeypatch.delenv(key, raising=False)
    env["PYTHONPATH"] = str(ROOT)
    boot = subprocess.run([sys.executable, "-c", """
import sys
import app.builderops.control_plane.service
import app.builderops.issue_delivery_operation
import app.builderops.devui_focus_inputs
assert not any(k == p or k.startswith(p + '.') for k in sys.modules for p in
               ('app.api', 'app.main', 'app.instance', 'app.vault', 'app.config.llm'))
"""], env=env, cwd=ROOT, capture_output=True, text=True)
    assert boot.returncode == 0, boot.stderr
    h = issue_delivery_production_harness(bifrost=True, issue_body=BODY)
    task = _admit_and_read(h)
    approval = deepcopy(h.approval)
    # Disconnect the authenticated approving UI before the worker enters.
    h.owner._http.close()
    result = _launch(h)
    assert result["stopped_reason"] == "worker-handoff", result
    historical = h.host.issue_delivery_readback(repository=CONSUMER, approval_id=approval["approval_id"])
    assert historical["approval"] == approval
    assert task["payload"]["issue_delivery"]["operation_key"] == approval["operation_key"]
    replay = _launch(h)
    assert replay["sessions"][0]["session_id"] == result["sessions"][0]["session_id"]
    assert h.worker_transport.calls == h.transport.apply_calls == 1
    assert _production_adapter(h).stop() == {"stop_support": "unsupported", "stop_status": "unsupported"}
    plan = json.loads(PLAN.read_text())
    assert "host_runtime" in plan["prerequisites_before_start"]
    assert validate_pilot_plan(plan)["status"] == "incomplete"


def test_pilot_plan_is_incomplete_and_rejects_fixture_or_partial_completion():
    plan = json.loads(PLAN.read_text())
    result = validate_pilot_plan(plan)
    assert result["status"] == "incomplete"
    assert result["start_authorized"] is False
    assert result["missing_live_evidence"]
    for key in plan["prerequisites_before_start"]:
        changed = deepcopy(plan)
        del changed["prerequisites_before_start"][key]
        assert validate_pilot_plan(changed)["status"] == "invalid"
    for mutation in ({"status": "complete"}, {"start_authorized": True}, {"live_evidence": {"fixture": "passed"}}):
        assert validate_pilot_plan({**plan, **mutation})["status"] == "invalid"
    assert validate_pilot_plan(None)["status"] == "invalid"
