"""FCA-07 composed proof; external transports are doubles, authorities are real."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from app.builderops.owner_acceptance import read_owner_acceptance


def test_disconnected_client_has_no_read_or_effect():
    def unavailable(*args, **kwargs):
        raise OSError("source disconnected")

    result = read_owner_acceptance(
        client=None,
        task={},
        github_reader=unavailable,
        outcome_reader=unavailable,
        connected=False,
        now=lambda: datetime.now(timezone.utc),
    )
    assert result["status"] == "incomplete"
    assert result["platform_acceptance"] == "incomplete"
    assert result["missing"] == ["owner_client_disconnected"]


@pytest.fixture
def composed_case(
    issue_delivery_production_harness,
    tmp_path,
    monkeypatch,
):
    from app.builderops.epic_dispatch import dispatch_issue_sessions
    from app.builderops.issue_delivery_readback import admit_issue_delivery_task
    from tests.builderops.test_issue_delivery_operation import _production_adapter
    from tests.builderops import test_owner_fact_producers as owner_fixtures
    from tests.ops.test_devui_vm102_runtime_receipts import _bundle
    from tests.builderops.test_issue_delivery_readback import BODY
    from app.builderops.devui_focus_inputs import read_focus_inputs
    from app.builderops.devui_owner_synthesis import synthesize_owner_overview
    from tests.builderops.test_devui_owner_synthesis import Adapter, _response

    # One composition makes many authenticated reads. This finite matrix uses
    # the service's existing configuration so a 429 cannot mask a refusal case;
    # the real limiter remains installed and production defaults are unchanged.
    monkeypatch.setenv("BUILDEROPS_RATE_LIMIT_PER_MINUTE", "10000")
    explained = []

    def explain_preview(preview):
        manifest = preview["manifest"]
        repo = manifest["repository"]
        number = manifest["issue"]["number"]
        subject = f"github:{repo}#{number}"
        focus = read_focus_inputs(
            subject,
            repository=repo,
            issue_reader=lambda *_: {
                "number": number,
                "title": "Composed owner scenario",
                "body": BODY,
                "state": "open",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "labels": [{"name": "agent:ready"}],
                "html_url": f"https://github.com/{repo}/issues/{number}",
            },
        )
        snapshot = {
            "repo": repo,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "evidence": [
                {
                    "evidence_id": subject,
                    "source_ref": {
                        "source_type": "github_issue",
                        "source_id": subject,
                        "content_hash": manifest["issue"]["body_hash"],
                        "locator": f"https://github.com/{repo}/issues/{number}",
                    },
                    "kind": "issue",
                    "summary": "Exact owner approval pending",
                    "state": "observed",
                }
            ],
            "limitations": ["Delivery and owner acceptance remain unproved."],
        }
        synthesis = synthesize_owner_overview(
            snapshot,
            adapter=Adapter(
                _response(
                    content="Already delivered and accepted; start it again.",
                    reviewed_artifact_refs=[subject],
                )
            ),
        )
        assert synthesis["authority"] == "projection_only"
        assert synthesis["canonical_status"] == "unavailable"
        assert all(p["authority"] == "proposal_only" for p in synthesis["proposals"])
        unavailable = Adapter(_response())
        unavailable.execute = lambda _: (_ for _ in ()).throw(RuntimeError("model unavailable"))
        failed = synthesize_owner_overview(snapshot, adapter=unavailable)
        assert failed["model"]["status"] == "unavailable"
        assert failed["source_snapshot"] == snapshot and failed["proposals"] == []
        assert focus["evidence"]
        explained.append((subject, manifest["issue"]["body_hash"]))

    h = issue_delivery_production_harness(
        effect_kind="delivery", issue_body=BODY, preview_observer=explain_preview
    )
    h.transport.readbacks = ["applied"] * 4
    approval = h.approval
    repo = approval["repository"]
    number = approval["issue"]["number"]
    subject = f"github:{repo}#{number}"
    assert explained == [(subject, approval["issue"]["body_hash"])]
    monkeypatch.setattr(owner_fixtures, "REPO", repo)
    monkeypatch.setattr(owner_fixtures, "SUBJECT", subject)
    monkeypatch.setattr(owner_fixtures, "_bundle", lambda: _bundle(source_sha="f" * 40))
    w = owner_fixtures.OwnerWriter(tmp_path / "outcomes", h.store, monkeypatch)
    issue = {
        **approval["issue"],
        "title": "Composed owner scenario",
        "body": BODY,
        "labels": [{"name": "agent:ready"}],
        "html_url": f"https://github.com/{repo}/issues/{number}",
        "url": f"https://api.github.com/repos/{repo}/issues/{number}",
        "repository_url": f"https://api.github.com/repos/{repo}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    task = admit_issue_delivery_task(
        client=h.host,
        repository=repo,
        approval_id=approval["approval_id"],
        issue_reader=lambda *_: issue,
        observed_at=issue["updated_at"],
    )
    dispatched = dispatch_issue_sessions(
        approval["context"]["dispatch_plan"],
        _production_adapter(h),
        expected_plan_hash=approval["context"]["expected_plan_hash"],
    )
    assert dispatched["stopped_reason"] == "worker-handoff"
    assert h.transport.apply_calls == 4
    assert h.worker_transport.calls == 1
    assert len(dispatched["sessions"][0]["host_effect_refs"]) == 4
    stamp = datetime.now(timezone.utc).isoformat()
    github = {
        "repository": repo,
        "observed_at": stamp,
        "issue": {
            **issue,
            "state": "closed",
            "closed_at": stamp,
            "closed_by": {"login": "fixture"},
        },
        "pull_request": {
            "number": 6000,
            "node_id": "PR_fixture",
            "state": "closed",
            "merged": True,
            "merged_at": stamp,
            "title_sha256": "1" * 64,
            "body_sha256": "2" * 64,
            "governing_issue": number,
            "head_ref": approval["destination"]["branch"],
            "head_sha": "f" * 40,
            "base_ref": "main",
            "base_sha": approval["destination"]["base_sha"],
            "merge_commit_sha": "3" * 40,
        },
        "required_gates": {
            "state": "success",
            "head_sha": "f" * 40,
            "policy_sha256": "7" * 64,
            "observed_at": stamp,
        },
        "reviews": {"state": "approved", "head_sha": "f" * 40, "observed_at": stamp},
    }

    def read(**changes):
        args = dict(
            client=h.host,
            task=task,
            github_reader=lambda *a, **kw: deepcopy(github),
            outcome_reader=lambda: w.read().json(),
            connected=True,
            now=lambda: datetime.now(timezone.utc),
        )
        args.update(changes)
        return read_owner_acceptance(**args)

    return h, w, read, github, task


def confirm_outcomes(w):
    trial_response = w.submit(w.request(), "composed-trial")
    assert trial_response.status_code == 200, trial_response.text
    trial = trial_response.json()["receipt"]
    response = w.submit(
        w.request("owner_acceptance", "accepted", trial_receipt_ref=trial["id"]),
        "composed-decision",
    )
    assert response.status_code == 200, response.text
    return trial, response.json()["receipt"]


@pytest.mark.pg
def test_composed_owner_flow_preserves_real_effect_and_trial_evidence(composed_case):
    h, w, read, github, task = composed_case
    before = read()
    assert before["status"] == "incomplete", before
    assert "owner_trial_missing" in before["missing"], before
    trial_response = w.submit(w.request(), "composed-trial")
    assert trial_response.status_code == 200, trial_response.text
    trial = trial_response.json()["receipt"]
    assert read()["status"] == "incomplete"
    decision_response = w.submit(
        w.request("owner_acceptance", "accepted", trial_receipt_ref=trial["id"]),
        "composed-decision",
    )
    assert decision_response.status_code == 200, decision_response.text
    decision = decision_response.json()["receipt"]
    result = read()
    assert result["status"] == "evidence_complete", result
    assert result["platform_acceptance"] == "incomplete"
    assert result["owner_trial_ref"] == trial["id"]
    assert result["owner_acceptance_ref"] == decision["id"]
    assert result["delivery"]["head_sha"] == "f" * 40
    from app.builderops.devui_sources import _task
    from app.builderops.devui_overview_inputs import derive_overview_inputs
    from app.builderops.devui_owner_facts import owner_fact_candidates, append_focus_owner_facts
    from app.builderops.devui_focus_inputs import read_focus_inputs
    from tests.builderops.test_issue_delivery_readback import _provider

    item = _task(task, repository=h.approval["repository"])
    item["issue_delivery_readback"] = result["delivery"]
    overview = derive_overview_inputs(work_provider=_provider(item))
    assert overview["now"][0]["delivery_facts"]["delivery"]["state"] == "evidenced"
    provider = {
        "status": "available",
        "owner_outcomes_status": "available",
        "subjects": [w.read().json()],
        "owner_asks": [],
    }
    candidates = owner_fact_candidates(provider)
    assert candidates["ready_to_try"], candidates
    subject = w.profile["subject_ref"]
    focus = append_focus_owner_facts(
        read_focus_inputs(
            subject,
            repository=h.approval["repository"],
            issue_reader=lambda *_: github["issue"],
            issue_delivery_reader=lambda _: result["delivery"],
        ),
        provider,
    )
    assert any(decision["hash"] == row["source_ref"].get("version") for row in focus["evidence"])
    assert read(connected=False)["status"] == "incomplete"
    assert h.transport.apply_calls == 4  # readback never repeats an effect
    rejected = w.submit(
        w.request(
            "owner_acceptance",
            "rejected",
            trial_receipt_ref=trial["id"],
            expected_previous_receipt_id=decision["id"],
            supersedes_receipt_id=decision["id"],
            correction_reason="owner_correction",
        ),
        "composed-correction",
    )
    assert rejected.status_code == 200, rejected.text
    assert "owner_acceptance_rejected" in read()["missing"]
    w.profile["version"] = "2"
    w.write_sources()
    changed_profile = read()
    assert changed_profile["status"] == "incomplete"
    assert changed_profile["owner_trial_ref"] is None
    assert changed_profile["owner_acceptance_ref"] is None


@pytest.mark.pg
@pytest.mark.parametrize("slow_read", ["owner", "status"])
def test_final_read_cannot_outlive_evidence_window(composed_case, monkeypatch, slow_read):
    h, w, read, github, task = composed_case
    confirm_outcomes(w)
    assert read()["status"] == "evidence_complete"
    elapsed = 0
    reads = 0

    def now():
        return datetime.now(timezone.utc) + timedelta(seconds=elapsed)

    def owner_reader():
        nonlocal elapsed, reads
        value = w.read().json()  # actual authenticated producer read
        reads += 1
        if slow_read == "owner" and reads == 2:
            elapsed = 301
            # A slow final read can itself be fresh while earlier evidence has
            # expired. Only its transport observation time is advanced.
            value["observed_at"] = now().isoformat()
        return value

    real_status = h.host.status

    def status_reader():
        nonlocal elapsed
        value = real_status()  # retain the real authenticated epoch read
        if slow_read == "status":
            elapsed = 301
        return value

    with monkeypatch.context() as patch:
        patch.setattr(h.host, "status", status_reader)
        result = read(outcome_reader=owner_reader, now=now)
    assert reads == 2
    assert result["status"] == "incomplete", result
    assert result["missing"] == ["evidence_expired_during_read"]
    assert result["delivery"] is None
    assert result["owner_trial_ref"] is None
    assert result["owner_acceptance_ref"] is None
    assert read()["status"] == "evidence_complete"
    assert h.transport.apply_calls == 4


@pytest.mark.pg
def test_incomplete_or_stale_evidence_cannot_pass_acceptance(composed_case):
    h, w, read, github, task = composed_case
    confirm_outcomes(w)
    assert read()["status"] == "evidence_complete"
    original = w.read().json()
    mutations = [
        ("owner_trial_missing", lambda v: v["facts"].update(owner_trial=None)),
        ("owner_acceptance_missing", lambda v: v["facts"].update(owner_acceptance=None)),
        ("source_readback_unavailable", lambda v: v["facts"].update(ready_to_try=None)),
        (
            "source_readback_unavailable",
            lambda v: v["binding"]["candidate_ref"].update(source_sha="0" * 40),
        ),
        (
            "source_readback_unavailable",
            lambda v: v["binding"]["authorization_ref"].update(authority_epoch=999),
        ),
        (
            "source_readback_unavailable",
            lambda v: v["binding"].update(owner_grant_status="unavailable"),
        ),
        (
            "source_readback_unavailable",
            lambda v: v.update(observed_at="2020-01-01T00:00:00+00:00"),
        ),
        ("owner_trial_invalid", lambda v: v.update(history=[])),
        (
            "owner_acceptance_invalid",
            lambda v: v["facts"]["owner_acceptance"]["receipt_body"]["request"].update(
                trial_receipt_ref="other-trial"
            ),
        ),
    ]
    for reason, mutate in mutations:
        changed = deepcopy(original)
        mutate(changed)
        changed.update(component_pass_count=999, closed_issue_count=999, model_claim="accepted")
        result = read(outcome_reader=lambda: changed)
        assert result["status"] == "incomplete", result
        assert result["platform_acceptance"] == "incomplete"
        assert reason in result["missing"], result
        assert read()["status"] == "evidence_complete"
    for key in ("issue", "pull_request", "required_gates", "reviews"):
        changed = deepcopy(github)
        changed.pop(key)
        assert read(github_reader=lambda *a, **kw: changed)["status"] == "incomplete"
        assert read()["status"] == "evidence_complete"
    changed = deepcopy(github)
    changed["pull_request"]["head_sha"] = "0" * 40
    assert read(github_reader=lambda *a, **kw: changed)["status"] == "incomplete"
    changed = deepcopy(github)
    changed["observed_at"] = "2020-01-01T00:00:00+00:00"
    assert read(github_reader=lambda *a, **kw: changed)["status"] == "incomplete"

    def disconnected():
        raise OSError("owner client disconnected")

    assert read(outcome_reader=disconnected)["status"] == "incomplete"
    reads = iter(
        [original, {**deepcopy(original), "facts": {**original["facts"], "owner_acceptance": None}}]
    )
    assert read(outcome_reader=lambda: next(reads))["missing"] == ["owner_lineage_changed"]
    assert read()["status"] == "evidence_complete"
    # Corrupt the actual durable effect status, not a replacement service or
    # launcher: all prior human receipts remain, yet delivery is now unknown.
    with h.store._connect() as conn:
        conn.execute(
            "UPDATE builderops_outbox SET status='unknown' WHERE repository=%s",
            (h.approval["repository"],),
        )
    assert read()["missing"] == ["delivery_evidence_incomplete"]
    assert h.transport.apply_calls == 4


@pytest.mark.pg
@pytest.mark.parametrize(
    "scenario", ["technical_wait", "revoked", "ambiguous_start", "unknown_effect"]
)
def test_selected_workflow_stop_and_recovery_proof(issue_delivery_production_harness, scenario):
    from app.builderops.epic_dispatch import dispatch_issue_sessions
    from app.builderops.issue_delivery_operation import observe_issue_delivery_operation
    from tests.builderops.test_issue_delivery_operation import _production_adapter

    h = issue_delivery_production_harness(
        effect_kind="publication",
        revoke_before_effect=scenario == "revoked",
        lose_response_after_entry=scenario == "ambiguous_start",
    )
    if scenario == "unknown_effect":
        h.transport.readbacks = ["applied", "unknown"]
    approval = h.approval
    plan = approval["context"]["dispatch_plan"]
    adapter = _production_adapter(h)
    if scenario == "technical_wait":
        adapter.reserve()
    else:
        dispatch_issue_sessions(
            plan, adapter, expected_plan_hash=approval["context"]["expected_plan_hash"]
        )
    before = (h.worker_transport.calls, h.transport.apply_calls)
    observation = observe_issue_delivery_operation(
        approval,
        client=h.client,
        plan=plan,
        expected_plan_hash=approval["context"]["expected_plan_hash"],
        repo_root=h.worktree,
    )
    assert (h.worker_transport.calls, h.transport.apply_calls) == before
    if scenario == "technical_wait":
        assert observation.state == "reserved"
        assert before == (0, 0)
    elif scenario == "ambiguous_start":
        assert observation.state == "launch_unknown"
        assert before == (1, 1)
    elif scenario == "revoked":
        assert before == (1, 1)
        assert observation.state != "terminal"
    else:
        assert before == (1, 2)
        assert any(
            h.ledger.status(ref["operation_key"])["status"] != "succeeded"
            for ref in observation.host_effect_refs
        )
    # Reconnection means observe the same durable operation. It is not a new
    # approval, and replay must not repeat the worker or an external effect.
    if scenario != "technical_wait":
        dispatch_issue_sessions(
            plan,
            _production_adapter(h),
            expected_plan_hash=approval["context"]["expected_plan_hash"],
        )
        assert (h.worker_transport.calls, h.transport.apply_calls) == before


def test_parent_plan_is_operator_readable_and_remains_incomplete():
    root = Path(__file__).resolve().parents[2]
    plan = json.loads(
        (root / "docs/BUILDER_FACTORY_ACCEPTANCE/owner_platform_acceptance_plan.json").read_text()
    )
    assert plan["contract"] == "builder_owner_platform_acceptance_plan.v1"
    assert plan["status"] == "incomplete"
    assert plan["qualified_repositories"] == ["rasmustho/agentic-pkm-mvp"]
    assert plan["selected_workflow"]["operation"] == "deliver_ready_issue"
    assert plan["selected_workflow"]["ddo_required"] is False
    assert all(
        item["status"] == "incomplete" and item["receipt_ref"] is None
        for item in plan["required_live_receipts"]
    )
    assert len(plan["owner_questions"]) >= 4
    assert set(plan["scenarios"]) == {
        "normal",
        "owner_decision",
        "technical_wait",
        "stale_or_contradictory",
        "model_unavailable",
        "ambiguous_start",
        "client_disconnected",
        "revoked",
    }
    assert plan["read_only_acknowledgement_is_owner_acceptance"] is False
    for reference in plan["source_contracts"]:
        assert (root / reference).is_file(), reference
