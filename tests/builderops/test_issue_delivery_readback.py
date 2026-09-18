"""FCA-ID-C production readback contracts for Issue delivery (#5552)."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

import pytest
from tests.builderops.test_owner_fact_producers import bifrost_writer as bifrost_writer

from app.builderops import cockpit_github_plane
from app.builderops.devui_focus_inputs import read_focus_inputs
from app.builderops.devui_focus import compose_focus_view
from app.builderops.devui_overview import compose_overview_view
from app.builderops.devui_overview_inputs import derive_overview_inputs
from app.builderops.devui_sources import SourceReadRefusal, _task
from app.builderops.issue_delivery_readback import (
    IssueDeliveryReadbackRefused,
    admit_issue_delivery_task,
    compose_issue_delivery_readback,
)


REPOSITORY = "rasmustho/agentic-pkm-mvp"


@pytest.mark.pg
@pytest.mark.parametrize("phase", ["candidate_ready", "missing_ref", "unknown", "missing_task", "expired_lease"])
def test_candidate_reference_restart_is_not_delivery(issue_delivery_production_harness, monkeypatch, phase):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from tests.builderops.test_issue_delivery_operation import _production_adapter, _cross_issue_approval, _recovered_candidate_adapter
    from app.builderops.issue_delivery_operation import observe_issue_delivery_operation, IssueDeliveryOperationError
    from app.builderops.issue_delivery_readback import read_issue_delivery_projection
    from app.builderops.control_plane.client import ControlPlaneClientError
    harness = issue_delivery_production_harness(bifrost=True, host_candidate=True)
    approval = harness.approval
    successors = [_production_adapter(harness, approval=_cross_issue_approval(harness, issue_number=number, suffix=str(number)))
                  for number in (5561, 5562)]
    adapter = _production_adapter(harness)
    context = approval["context"]["dispatch_plan"]["context_packs"][0]
    transition = harness.host.transition_task
    lost = False
    def lose_append(**kwargs):
        nonlocal lost
        if phase == "missing_ref" and kwargs["request"].get("continuation") and not lost:
            lost = True
            raise ControlPlaneClientError("injected lost native reference append")
        return transition(**kwargs)
    monkeypatch.setattr(harness.host, "transition_task", lose_append)
    applicator = harness.executor.candidate_applicator
    write = applicator.write_object
    writes = []
    def write_object(kind, data):
        result = write(kind, data)
        writes.append(kind)
        if phase == "unknown":
            raise OSError("injected partial object write")
        return result
    monkeypatch.setattr(applicator, "write_object", write_object)
    try:
        result = adapter.launch(context)
    except IssueDeliveryOperationError:
        assert phase == "missing_ref"
        result = {"candidate_state": "unknown"}
    assert result["candidate_state"] == ("unknown" if phase in {"unknown", "missing_ref"} else "candidate_ready")
    terminal = adapter._read("terminal")
    terminal_hash = terminal["payload"]["receipt_hash"]
    task_id = f"issue-delivery-{approval['approval_id']}"
    if phase == "missing_task":
        with harness.store._connect() as conn:
            conn.execute("DELETE FROM builderops_tasks WHERE repository=%s AND task_id=%s", (approval["repository"], task_id))
    elif phase == "expired_lease":
        with harness.store._connect() as conn:
            conn.execute("UPDATE builderops_leases SET expires_at=clock_timestamp()-interval '1 second' WHERE repository=%s AND resource_id=%s",
                         (approval["repository"], task_id))
    checked = []
    store_class = type(harness.store)
    reuse = store_class._issue_delivery_terminal_is_reusable
    def observed_reuse(conn, **kwargs):
        verdict = reuse(conn, **kwargs)
        checked.append((kwargs["operation_key"], verdict))
        return verdict
    monkeypatch.setattr(store_class, "_issue_delivery_terminal_is_reusable", staticmethod(observed_reuse))
    barrier = threading.Barrier(2)
    def reserve(other):
        barrier.wait(timeout=10)
        try:
            other.reserve()
        except IssueDeliveryOperationError:
            return "refused"
        return "reserved"
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reserve, other) for other in successors]
        assert [future.result(timeout=30) for future in futures] == ["refused", "refused"]
    assert checked and all(key == approval["operation_key"] and verdict is False for key, verdict in checked)
    observed = observe_issue_delivery_operation(approval, client=harness.host,
        plan=approval["context"]["dispatch_plan"], expected_plan_hash=approval["context"]["expected_plan_hash"],
        repo_root=harness.worktree)
    assert observed.state == "terminal"
    original_writes = tuple(writes)
    if phase != "missing_task":
        if phase == "missing_ref":
            # Competing repair callers share the native fence and expected-version CAS.
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(_recovered_candidate_adapter(harness).launch, context) for _ in range(2)]
                replays = []
                for future in futures:
                    try:
                        replays.append(future.result(timeout=30))
                    except (ControlPlaneClientError, IssueDeliveryOperationError):
                        pass
            assert replays and any(item["candidate_state"] == "candidate_ready" for item in replays)
        else:
            assert _recovered_candidate_adapter(harness).launch(context)["fresh_session"] is False
        task = harness.host.get_task(repository=approval["repository"], task_id=task_id)
        refs = task["payload"]["continuation"]["host_effect_refs"]
        assert len(refs) == 2
        candidate = harness.ledger.status(refs[-1]["operation_key"])
        assert candidate["status"] == ("unknown" if phase == "unknown" else "succeeded")
        projection = read_issue_delivery_projection(client=harness.host, task=task,
            github_reader=lambda *args, **kwargs: pytest.fail("candidate readback must not guess remote delivery"))
        assert projection["state"] == ("unknown" if phase == "unknown" else "candidate_ready")
        assert projection["delivery_facts"] == {}
        assert projection["candidate"]["ready_to_try"] is False
        if phase != "unknown":
            request = adapter._build_effect_request({"effect_kind": "candidate_prepare",
                "target": terminal["payload"]["candidate_binding"]["target"]})
            assert harness.executor.execute(request).outcome == "applied"
            changed = request.model_copy(update={"target": request.target.model_copy(update={"timestamp": request.target.timestamp + 1})})
            assert changed.effect_slot_sha256 == request.effect_slot_sha256
            with pytest.raises(ValueError, match="foreign or changed"):
                harness.executor.execute(changed)
    assert tuple(writes) == original_writes
    assert adapter._read("terminal")["payload"]["receipt_hash"] == terminal_hash
    assert harness.worker_transport.calls == 1


@pytest.mark.pg
def test_native_admission_refuses_withdrawal_during_readback(issue_delivery_production_harness) -> None:
    harness = issue_delivery_production_harness(bifrost=True, issue_body=BODY)
    approval = harness.approval
    number = approval["issue"]["number"]
    issue = {**_issue(), "number": number, "node_id": approval["issue"]["node_id"],
             "title": approval["issue"]["title"], "html_url": approval["issue"]["url"],
             "url": f"https://api.github.com/repos/{REPOSITORY}/issues/{number}"}
    def issue_reader(repo, issue_number):
        assert (repo, issue_number) == (REPOSITORY, number)
        document = json.loads(harness.registry.manifest_path.read_text())
        for credential in document["credentials"]:
            if credential["id"] == "owner":
                credential["revoked"] = True
        harness.registry.manifest_path.write_text(json.dumps(document))
        return deepcopy(issue)
    with pytest.raises(IssueDeliveryReadbackRefused, match="admission readback"):
        admit_issue_delivery_task(client=harness.host, repository=approval["repository"],
            approval_id=approval["approval_id"], issue_reader=issue_reader,
            observed_at="2026-09-17T17:00:00Z")
    assert harness.host.issue_delivery_readback(repository=approval["repository"],
        approval_id=approval["approval_id"])["state"] == "invalidated"
    assert harness.transport.apply_calls == harness.worker_transport.calls == 0


@pytest.mark.pg
def test_bifrost_delivery_projection_preserves_source_pair(issue_delivery_production_harness) -> None:
    from app.builderops.epic_dispatch import dispatch_issue_sessions
    from app.builderops.issue_delivery_readback import read_issue_delivery_projection
    from tests.builderops.test_issue_delivery_operation import _production_adapter
    from tests.builderops.test_issue_delivery_effect_executor import _bifrost_candidate_request
    from app.builderops.control_plane.issue_delivery import delivery_source_pair

    harness = issue_delivery_production_harness(bifrost=True, issue_body=BODY)
    approval = harness.approval
    repository = approval["repository"]
    number = approval["issue"]["number"]
    source = {**_issue(), "number": number, "node_id": approval["issue"]["node_id"],
              "title": approval["issue"]["title"],
              "html_url": approval["issue"]["url"],
              "url": f"https://api.github.com/repos/{REPOSITORY}/issues/{number}"}
    harness.source_state["issue"] = source
    reads = []
    def issue_reader(repo, issue_number):
        reads.append((repo, issue_number))
        assert (repo, issue_number) == (REPOSITORY, number)
        return deepcopy(source)
    task = admit_issue_delivery_task(client=harness.host, repository=repository, approval_id=approval["approval_id"],
                                    issue_reader=issue_reader, observed_at="2026-09-17T17:00:00Z")
    assert reads == [(REPOSITORY, number)] * 2
    assert task["payload"]["issue_delivery"]["delivery_sources"] == delivery_source_pair(approval)
    item = _task(task, repository=repository)
    assert item is not None
    assert item["issue_delivery"]["delivery_sources"] == delivery_source_pair(approval)
    for field, value in (("contract_version", "fca-issue-delivery.v1"),
                         ("repository", REPOSITORY), ("issue_repository", repository),
                         ("workflow_repository", repository), ("source_revision", "0" * 40),
                         ("workflow_source_revision", "main")):
        corrupted = deepcopy(task)
        corrupted["payload"]["issue_delivery"]["delivery_sources"][field] = value
        with pytest.raises(SourceReadRefusal, match="binding_invalid"):
            _task(corrupted, repository=repository)
    missing = deepcopy(task)
    del missing["payload"]["issue_delivery"]["delivery_sources"]
    with pytest.raises(SourceReadRefusal, match="scope_mismatch"):
        _task(missing, repository=repository)
    proposed = {}
    def worker_content():
        request = _bifrost_candidate_request(harness, "publication")
        publication = request.target.model_dump(mode="json")
        merge = {key: val for key, val in publication.items() if key not in {"title_sha256", "body_sha256", "expected_remote_ref_state"}}
        merge.update(kind="merge", pr_number=6000)
        proposed.update(publication=publication, merge=merge, closure={"kind": "closure", "issue_number": number,
                        "pr_number": 6000, "merge_commit_sha": "3" * 40, "expected_issue_state": "open"})
        harness.worker_transport.effect_targets = proposed
    harness.worker_transport.effect_kind = "delivery"
    harness.worker_transport.pre_entry_check = worker_content
    harness.transport.readbacks = ["applied"] * 4
    result = dispatch_issue_sessions(approval["context"]["dispatch_plan"], _production_adapter(harness),
                                    expected_plan_hash=approval["context"]["expected_plan_hash"])
    assert result["stopped_reason"] == "worker-handoff", result
    assert harness.transport.apply_calls == 4
    github = _github()
    github.update(repository=repository, issue_repository=REPOSITORY)
    github["issue"].update(number=number, node_id=approval["issue"]["node_id"], html_url=approval["issue"]["url"])
    head = proposed["publication"]["head_sha"]
    github["pull_request"].update(number=6000, governing_issue=number, governing_issue_repository=REPOSITORY,
        head_sha=head, head_ref=approval["destination"]["branch"], base_sha=approval["destination"]["base_sha"],
        merge_commit_sha="3" * 40, title_sha256="1" * 64, body_sha256="2" * 64)
    github["required_gates"]["head_sha"] = head
    github["reviews"]["head_sha"] = head
    def github_reader(repo, issue_number, **kwargs):
        assert (repo, issue_number, kwargs["issue_repository"]) == (repository, number, REPOSITORY)
        assert kwargs["verification_checks"] == ("documentation",)
        return deepcopy(github)
    projection = read_issue_delivery_projection(client=harness.host, task=task, github_reader=github_reader,
                                                owner_binding_reader=lambda *args, **kwargs: None)
    assert projection["state"] == "delivered"
    assert projection["delivery_sources"] == delivery_source_pair(approval)
    assert projection["subject_ref"] == f"github:{REPOSITORY}#{number}"
    assert projection["candidate"]["ready_to_try"] is False
    item["issue_delivery_readback"] = projection
    overview = derive_overview_inputs(work_provider=_provider(item))
    assert overview["now"][0]["delivery_facts"]["delivery"]["state"] == "evidenced"
    github["issue_repository"] = repository
    with pytest.raises(IssueDeliveryReadbackRefused, match="repository"):
        read_issue_delivery_projection(client=harness.host, task=task, github_reader=github_reader,
                                       owner_binding_reader=lambda *args, **kwargs: None)
ISSUE = 5552
BODY = """## Context
Bounded FCA-ID-C slice.

## Scope
- Add independent delivery readback.

## Source Anchors
- `docs/CONCEPTS/FEATURE_CANDIDATE_ACCEPTANCE/README.md#fca-id-c`

## SBS Impact
- No SBS impact.

## Constraints
- Reuse the existing TaskRecord and Issue-delivery authorities.

## Acceptance Criteria
- [ ] Read back delivery.
  Verify: tests/builderops/test_issue_delivery_readback.py::test_production_issue_task_envelope_reaches_overview

## Out of Scope
- Deployment and owner acceptance.

## Suggested Validation
- Run the declared focused test.

## Source Docs
- `docs/CONCEPTS/FEATURE_CANDIDATE_ACCEPTANCE/README.md`
"""
BODY_HASH = hashlib.sha256(BODY.encode()).hexdigest()
AC_TEXT = (
    "- [ ] Read back delivery.\n"
    "  Verify: tests/builderops/test_issue_delivery_readback.py::"
    "test_production_issue_task_envelope_reaches_overview\n\n"
)
AC_HASH = hashlib.sha256(AC_TEXT.encode()).hexdigest()
SOURCE_SHA = "a" * 40
HEAD_SHA = "b" * 40
MERGE_SHA = "c" * 40
APPROVAL_HASH = "d" * 64
PR_TITLE = "Deliver FCA-ID-C readback"
PR_BODY = f"Fixes #{ISSUE}"
PR_TITLE_HASH = hashlib.sha256(PR_TITLE.encode()).hexdigest()
PR_BODY_HASH = hashlib.sha256(PR_BODY.encode()).hexdigest()


def _approval() -> dict:
    return {
        "contract_version": "fca-issue-delivery.v1",
        "approval_id": "approval-5552",
        "approval_manifest_hash": APPROVAL_HASH,
        "authority_epoch": 7,
        "operation_key": "operation-5552",
        "repository": REPOSITORY,
        "issue": {
            "number": ISSUE,
            "node_id": "I_5552",
            "state": "open",
            "body_hash": BODY_HASH,
            "acceptance_criteria_hash": AC_HASH,
        },
        "source": {"revision": SOURCE_SHA},
        "destination": {
            "branch": "codex/5552-issue-delivery-readback",
            "base_ref": "main",
            "base_sha": SOURCE_SHA,
        },
    }


def _approval_readback() -> dict:
    approval = _approval()
    return {
        "state": "approved",
        "approval_id": approval["approval_id"],
        "approval": approval,
        "manifest": approval,
        "operation": {
            "operation_key": approval["operation_key"],
            "repository": REPOSITORY,
            "issue_number": ISSUE,
        },
        "receipt": {"approval_manifest_hash": APPROVAL_HASH},
    }


def _issue(*, state: str = "open", updated_at: str = "2026-09-16T12:00:00Z") -> dict:
    return {
        "number": ISSUE,
        "node_id": "I_5552",
        "state": state,
        "title": "task: independently read back Issue delivery and candidate",
        "body": BODY,
        "labels": [{"name": "agent:ready"}],
        "html_url": f"https://github.com/{REPOSITORY}/issues/{ISSUE}",
        "url": f"https://api.github.com/repos/{REPOSITORY}/issues/{ISSUE}",
        "repository_url": f"https://api.github.com/repos/{REPOSITORY}",
        "created_at": "2026-09-16T10:00:00Z",
        "updated_at": updated_at,
    }


class _TaskClient:
    authority_epoch = 7

    def __init__(self) -> None:
        self.row: dict | None = None

    def issue_delivery_readback(self, *, repository: str, approval_id: str) -> dict:
        assert (repository, approval_id) == (REPOSITORY, "approval-5552")
        return deepcopy(_approval_readback())

    def transition_task(self, **request: object) -> dict:
        assert request["to_state"] == "ready"
        self.row = {
            "repository": REPOSITORY,
            "task_id": request["task_id"],
            "state": "ready",
            "version": 1,
            "updated_at": "2026-09-16T12:00:01+00:00",
            "lease": None,
            "payload": deepcopy(request["request"]),
            "authority_envelope": {
                **deepcopy(request["envelope"]),
                "actor": "builderops:test",
                "schema_version": 1,
            },
        }
        return {
            "result": {
                "repository": REPOSITORY,
                "task_id": request["task_id"],
                "state": "ready",
                "receipt_sequence": 1,
                "recovery_lsn": "0/1",
                "operation_key": None,
                "replayed": False,
            }
        }

    def get_task(self, *, repository: str, task_id: str) -> dict:
        assert repository == REPOSITORY
        assert self.row is not None and self.row["task_id"] == task_id
        return deepcopy(self.row)

    def status(self) -> dict:
        return {"authority_epoch": self.authority_epoch}


def _provider(item: dict) -> dict:
    captured = "2026-09-16T12:00:02+00:00"
    return {
        "provider": "builderops_cockpit",
        "status": "available",
        "authority": "read_time_join",
        "captured_at": captured,
        "payload": {
            "authority": "read_time_join",
            "generated_at": captured,
            "claim": {"kind": "counted", "text": "working", "as_of": captured},
            "sources": [{
                "name": "dispatcher-store", "state": "fresh", "configured": True,
                "last_successful_read": captured,
            }],
            "bands": [{"key": "working", "countable": True, "count": 1, "items": [item]}],
        },
    }


def _composition() -> dict:
    return {
        "contract_version": "devui.composition.v1",
        "authority": "projection_only",
        "captured_at": "2026-09-16T12:00:02+00:00",
        "providers": {
            "work": {
                "provider": "builderops_cockpit",
                "status": "available",
                "authority": "read_time_join",
                "captured_at": "2026-09-16T12:00:02+00:00",
                "snapshot": {"watermark": "work:5552"},
                "completeness": {"claim": {"kind": "counted"}},
            }
        },
    }


def _effects() -> list[dict]:
    return [
        {"operation_key": "1" * 64, "status": "succeeded", "payload": {
            "request_sha256": "1" * 64, "effect_slot_sha256": "4" * 64,
            "effect_kind": "publication", "target": {
            "kind": "publication", "issue_number": ISSUE, "branch": "codex/5552-issue-delivery-readback",
            "base_ref": "main", "base_sha": SOURCE_SHA, "head_sha": HEAD_SHA,
            "title_sha256": PR_TITLE_HASH, "body_sha256": PR_BODY_HASH,
        }}},
        {"operation_key": "2" * 64, "status": "succeeded", "payload": {
            "request_sha256": "2" * 64, "effect_slot_sha256": "5" * 64,
            "effect_kind": "merge", "target": {
            "kind": "merge", "issue_number": ISSUE, "pr_number": 6001,
            "branch": "codex/5552-issue-delivery-readback", "base_ref": "main",
            "base_sha": SOURCE_SHA, "head_sha": HEAD_SHA,
        }}},
        {"operation_key": "3" * 64, "status": "succeeded", "payload": {
            "request_sha256": "3" * 64, "effect_slot_sha256": "6" * 64,
            "effect_kind": "closure", "target": {
            "kind": "closure", "issue_number": ISSUE, "pr_number": 6001,
            "merge_commit_sha": MERGE_SHA, "expected_issue_state": "open",
        }}},
    ]


def _github(*, head_sha: str = HEAD_SHA, issue_state: str = "closed") -> dict:
    return {
        "repository": REPOSITORY,
        "observed_at": "2026-09-16T12:02:00+00:00",
        "issue": {
            **_issue(state=issue_state),
            "body_hash": BODY_HASH,
            "acceptance_criteria_hash": AC_HASH,
            "closed_at": "2026-09-16T12:01:00Z" if issue_state == "closed" else None,
            "closed_by": {"login": "merge-owner"} if issue_state == "closed" else None,
        },
        "pull_request": {
            "number": 6001, "node_id": "PR_6001", "state": "closed", "merged": True,
            "merged_at": "2026-09-16T12:00:30Z",
            "title_sha256": PR_TITLE_HASH, "body_sha256": PR_BODY_HASH,
            "governing_issue": ISSUE,
            "head_ref": "codex/5552-issue-delivery-readback", "head_sha": head_sha,
            "base_ref": "main", "base_sha": SOURCE_SHA, "merge_commit_sha": MERGE_SHA,
        },
        "required_gates": {
            "state": "success", "head_sha": head_sha,
            "policy_sha256": "7" * 64,
            "observed_at": "2026-09-16T12:02:00+00:00",
        },
        "reviews": {
            "state": "approved", "head_sha": head_sha,
            "observed_at": "2026-09-16T12:02:00+00:00",
        },
    }


def _operation(*, worker_receipt: dict | None = None) -> dict:
    return {
        "state": "terminal",
        "operation_key": "operation-5552",
        "worker_receipt": worker_receipt or {"claimed_success": True},
        "host_effect_refs": [
            {"operation_key": str(index) * 64, "request_sha256": str(index) * 64,
             "effect_slot_sha256": str(index + 3) * 64}
            for index in range(1, 4)
        ],
    }


def _binding(*, status: str = "current", source_sha: str = HEAD_SHA) -> dict:
    return {
        "repository": REPOSITORY,
        "subject_ref": f"github:{REPOSITORY}#{ISSUE}",
        "source_revision": source_sha,
        "readiness_status": status,
        "candidate_ref": {"source_sha": source_sha, "devui_image_digest": "sha256:" + "e" * 64,
                          "devui_config_fingerprint": "f" * 64},
        "environment_ref": {"vmid": 102, "name": "bob-1", "component_id": "devui"},
        "readiness_receipt_ref": {"id": "receipt:health", "sha256": "1" * 64,
                                  "source_owner": "builderops_deployment_owner"},
        "acceptance_profile_ref": {"id": "profile:devui-trial", "version": "1", "sha256": "2" * 64,
                                   "source_owner": "builderops_vm102_receipt_source"},
        "binding_hash": "3" * 64,
        "observed_at": "2026-09-16T12:00:03+00:00",
    }


def _projection(**changes: object) -> dict:
    values = {
        "task": None,
        "approval_readback": _approval_readback(),
        "operation": _operation(),
        "host_effects": _effects(),
        "github_evidence": _github(),
        "owner_binding": _binding(),
    }
    values.update(changes)
    return compose_issue_delivery_readback(**values)


def test_issue_delivery_admission_builds_exact_task_contract() -> None:
    client = _TaskClient()
    row = admit_issue_delivery_task(
        client=client,
        repository=REPOSITORY,
        approval_id="approval-5552",
        issue_reader=lambda _repo, _number: _issue(),
        observed_at="2026-09-16T12:00:00+00:00",
    )
    projection = _projection(task=row)
    item = _task(row, repository=REPOSITORY)
    assert item is not None
    item["issue_delivery_readback"] = projection

    overview = derive_overview_inputs(
        work_provider=_provider(item),
    )
    focus = read_focus_inputs(
        f"github:{REPOSITORY}#{ISSUE}",
        repository=REPOSITORY,
        issue_reader=lambda _repo, _number: _issue(),
        issue_delivery_reader=lambda _subject: projection,
    )

    assert row["version"] == row["payload"]["issue_delivery"]["task_record_version"] == 1
    assert overview["now"][0]["delivery_facts"]["delivery"]["state"] == "evidenced"
    assert overview["now"][0]["delivery_facts"]["ready_to_try"]["state"] == "evidenced"
    assert any(
        str(item.get("claim_id", "")).startswith("issue-delivery:")
        for item in focus["evidence"]
    )
    composed_overview = compose_overview_view(
        composition=_composition(), candidates=overview
    )
    composed_focus = compose_focus_view(
        **focus,
        now=lambda: datetime(2026, 9, 16, 12, 0, 4, tzinfo=timezone.utc),
    )
    assert composed_overview["now"]
    assert composed_focus["state"] == "focus_partial"

    generic_item = deepcopy(item)
    generic_item.pop("issue_delivery_readback")
    generic = derive_overview_inputs(work_provider=_provider(generic_item))["now"][0]
    assert "delivery_facts" not in generic
    mismatched = deepcopy(projection)
    mismatched["subject_ref"] = f"github:{REPOSITORY}#9999"
    assert derive_overview_inputs(
        work_provider=_provider(item),
        issue_delivery_provider={f"github:{REPOSITORY}#{ISSUE}": mismatched},
    ) == {"now": []}

    reads = 0
    def drifting_issue(_repo: str, _number: int) -> dict:
        nonlocal reads
        reads += 1
        value = _issue()
        if reads == 2:
            value["title"] = "changed during admission"
        return value

    with pytest.raises(IssueDeliveryReadbackRefused, match="admission readback"):
        admit_issue_delivery_task(
            client=_TaskClient(),
            repository=REPOSITORY,
            approval_id="approval-5552",
            issue_reader=drifting_issue,
            observed_at="2026-09-16T12:00:00+00:00",
        )

    class RevokedDuringAdmission(_TaskClient):
        reads = 0

        def issue_delivery_readback(self, *, repository: str, approval_id: str) -> dict:
            result = super().issue_delivery_readback(
                repository=repository, approval_id=approval_id
            )
            self.reads += 1
            if self.reads == 2:
                result["state"] = "invalidated"
            return result

    with pytest.raises(IssueDeliveryReadbackRefused, match="admission readback"):
        admit_issue_delivery_task(
            client=RevokedDuringAdmission(),
            repository=REPOSITORY,
            approval_id="approval-5552",
            issue_reader=lambda _repo, _number: _issue(),
            observed_at="2026-09-16T12:00:00+00:00",
        )


@pytest.mark.pg
def test_production_issue_task_envelope_reaches_overview(
    issue_delivery_production_harness,
) -> None:
    harness = issue_delivery_production_harness()
    approval = harness.approval
    issue = approval["issue"]
    number = int(issue["number"])
    repository = str(approval["repository"])
    task_id = f"issue-delivery-{approval['approval_id']}"
    payload = {
        "repo": repository,
        "task_id": task_id,
        "issue_number": number,
        "title": "Production Issue-delivery readback",
        "status": "ready",
        "why_now": "Issue delivery is active.",
        "created_at": "2026-09-16T12:00:00+00:00",
        "updated_at": "2026-09-16T12:00:00+00:00",
        "sync_state": {"labels": ["agent:ready"]},
        "issue_delivery": {
            "contract": "fca-issue-delivery-task.v1",
            "task_record_version": 1,
            "approval_id": approval["approval_id"],
            "approval_manifest_hash": approval["approval_manifest_hash"],
            "operation_key": approval["operation_key"],
            "authority_epoch": approval["authority_epoch"],
            "issue_node_id": issue["node_id"],
            "issue_body_hash": issue["body_hash"],
            "acceptance_criteria_hash": issue["acceptance_criteria_hash"],
            "source_revision": approval["source"]["revision"],
        },
    }
    envelope = {
        "repository": repository,
        "scope": f"issue:{number}",
        "stack": "builderops-issue-delivery",
        "source_refs": [f"builderops:issue-delivery:{approval['approval_id']}"],
    }
    harness.host.transition_task(
        envelope=envelope,
        task_id=task_id,
        to_state="ready",
        idempotency_key=f"issue-delivery-admission:{approval['approval_id']}",
        request=payload,
    )
    row = harness.host.get_task(repository=repository, task_id=task_id)
    item = _task(row, repository=repository)
    assert item is not None
    subject = f"github:{repository}#{number}"
    projection = deepcopy(_projection())
    projection.update(subject_ref=subject, issue_number=number, task_record_version=1)
    projection["evidence"][0]["evidence_id"] = f"issue-delivery:{number}:{HEAD_SHA}"
    projection["evidence"][0]["source_ref"].update(
        source_id=f"{repository}#{number}:pr-6001",
        locator=f"https://github.com/{repository}/pull/6001",
    )
    projection["delivery_facts"]["delivery"].update(
        evidence_id=projection["evidence"][0]["evidence_id"],
        source_ref=deepcopy(projection["evidence"][0]["source_ref"]),
    )
    item["issue_delivery_readback"] = projection

    overview = derive_overview_inputs(work_provider=_provider(item))
    focus_issue = _issue()
    focus_issue.update(
        number=number,
        node_id=issue["node_id"],
        html_url=f"https://github.com/{repository}/issues/{number}",
        url=f"https://api.github.com/repos/{repository}/issues/{number}",
        repository_url=f"https://api.github.com/repos/{repository}",
    )
    focus = read_focus_inputs(
        subject,
        repository=repository,
        issue_reader=lambda _repo, _number: focus_issue,
        issue_delivery_reader=lambda _subject: projection,
    )

    assert row["version"] == row["payload"]["issue_delivery"]["task_record_version"] == 1
    assert overview["now"][0]["delivery_facts"]["delivery"]["state"] == "evidenced"
    assert any(
        str(evidence.get("claim_id", "")).startswith("issue-delivery:")
        for evidence in focus["evidence"]
    )


@pytest.mark.parametrize("bifrost", [False, True])
def test_production_readback_uses_independent_github_evidence(monkeypatch: pytest.MonkeyPatch, bifrost: bool) -> None:
    repository = "rasmustho/bifrost" if bifrost else REPOSITORY
    body = f"Governing-Issue: {REPOSITORY}#{ISSUE}" if bifrost else PR_BODY
    def paged(_owner: str, _name: str, endpoint: str, **_kwargs: object) -> list[dict]:
        if endpoint == "pulls":
            return [{"number": 6001, "body": body, "head": {
                "ref": "codex/5552-issue-delivery-readback",
            }}]
        if endpoint == "pulls/6001/reviews":
            return [{
                "id": 1, "state": "APPROVED", "commit_id": HEAD_SHA,
                "submitted_at": "2026-09-16T12:01:00Z", "user": {"login": "reviewer"},
            }]
        raise AssertionError(endpoint)

    def run(args: list[str]) -> dict:
        endpoint = args[1]
        assert "/rasmustho/bifrost/issues/" not in endpoint
        if endpoint.endswith(f"issues/{ISSUE}"):
            return _github()["issue"]
        if endpoint.endswith("pulls/6001"):
            return {
                "number": 6001, "node_id": "PR_6001", "state": "closed", "merged": True,
                "merged_at": "2026-09-16T12:00:30Z",
                "title": PR_TITLE, "body": body,
                "head": {"ref": "codex/5552-issue-delivery-readback", "sha": HEAD_SHA},
                "base": {"ref": "main", "sha": SOURCE_SHA},
                "merge_commit_sha": MERGE_SHA,
            }
        if endpoint.endswith(f"commits/{HEAD_SHA}/check-runs"):
            return {"check_runs": [{
                "id": 2, "name": "documentation" if bifrost else "Unit tests (not pg)", "head_sha": HEAD_SHA,
                "status": "completed", "conclusion": "success", "app": {"id": 7},
            }]}
        if endpoint.endswith(f"commits/{HEAD_SHA}/status"):
            return {"statuses": []}
        if endpoint.endswith("branches/main/protection"):
            return {"required_status_checks": {"contexts": [], "checks": []}}
        if endpoint.endswith(repository):
            return {"default_branch": "main"}
        raise AssertionError(endpoint)

    monkeypatch.setattr(cockpit_github_plane, "_paged_rest", paged)
    monkeypatch.setattr(cockpit_github_plane, "_run_gh", run)
    parsed = cockpit_github_plane.read_issue_delivery_github(
        repository, ISSUE, branch="codex/5552-issue-delivery-readback",
        **({"issue_repository": REPOSITORY, "verification_checks": ("documentation",)} if bifrost else {}),
    )
    if bifrost:
        assert parsed["issue_repository"] == REPOSITORY
        assert parsed["pull_request"]["governing_issue_repository"] == REPOSITORY
        assert parsed["required_gates"]["state"] == "success"
        return

    delivered = _projection(
        operation=_operation(worker_receipt={"forged": "success"}),
        github_evidence=parsed,
    )
    assert delivered["state"] == "delivered"

    def neutral_required_gate(args: list[str]) -> dict:
        response = run(args)
        if args[1].endswith(f"commits/{HEAD_SHA}/check-runs"):
            response = deepcopy(response)
            response["check_runs"][0]["conclusion"] = "neutral"
        return response

    monkeypatch.setattr(cockpit_github_plane, "_run_gh", neutral_required_gate)
    incomplete = cockpit_github_plane.read_issue_delivery_github(
        REPOSITORY, ISSUE, branch="codex/5552-issue-delivery-readback"
    )
    assert incomplete["required_gates"]["state"] == "incomplete"
    with pytest.raises(IssueDeliveryReadbackRefused, match="reviewed merge"):
        _projection(github_evidence=incomplete)
    monkeypatch.setattr(cockpit_github_plane, "_run_gh", run)

    with pytest.raises(IssueDeliveryReadbackRefused, match="GitHub evidence"):
        _projection(github_evidence=None)
    with pytest.raises(IssueDeliveryReadbackRefused, match="head"):
        _projection(github_evidence=_github(head_sha="9" * 40))
    with pytest.raises(IssueDeliveryReadbackRefused, match="closure"):
        _projection(github_evidence=_github(issue_state="open"))
    with pytest.raises(IssueDeliveryReadbackRefused, match="host effect"):
        _projection(host_effects=_effects()[:-1])

    changed_head = False

    def late_head(args: list[str]) -> dict:
        nonlocal changed_head
        response = run(args)
        if args[1].endswith("pulls/6001"):
            if changed_head:
                response = deepcopy(response)
                response["head"]["sha"] = "9" * 40
            changed_head = True
        return response

    monkeypatch.setattr(cockpit_github_plane, "_run_gh", late_head)
    with pytest.raises(cockpit_github_plane.GithubReadError, match="changed during"):
        cockpit_github_plane.read_issue_delivery_github(
            REPOSITORY, ISSUE, branch="codex/5552-issue-delivery-readback"
        )

    assert _projection() == _projection()  # reconnect/readback is deterministic


@pytest.mark.pg
def test_issue_delivery_candidate_profile_linkage(bifrost_writer) -> None:  # noqa: F811
    current = _projection()
    assert current["candidate"]["ready_to_try"] is True
    assert current["candidate"]["source_revision"] == HEAD_SHA
    assert current["candidate"]["acceptance_profile_ref"]["id"] == "profile:devui-trial"
    assert "owner_outcome" not in current
    assert current["delivery_facts"]["ready_to_try"]["state"] == "evidenced"

    for binding in (
        _binding(status="withdrawn"),
        _binding(source_sha="8" * 40),
        None,
    ):
        projection = _projection(owner_binding=binding)
        assert projection["candidate"]["ready_to_try"] is False
        assert "ready_to_try" not in projection["delivery_facts"]
        assert "owner_outcome" not in projection
    from app.builderops.issue_delivery_readback import read_issue_delivery_projection
    w = bifrost_writer
    projected = read_issue_delivery_projection(client=w.harness.host, task=w.task,
        github_reader=cockpit_github_plane.read_issue_delivery_github)
    assert projected["candidate"]["ready_to_try"] is True
    assert projected["candidate"]["source_revision"] == w.merge
    assert projected["subject_ref"] == w.subject
    assert projected["candidate"]["candidate_ref"]["delivery_ref"]["approval_id"] == w.harness.approval["approval_id"]
    ready_evidence = projected["evidence"][-1]
    assert ready_evidence["source_ref"]["source_type"] == "builderops_bifrost_documentation_receipt"
    w.responses[f"git/commits/{w.merge}"]["sha"] = "0" * 40
    refused = read_issue_delivery_projection(client=w.harness.host, task=w.task,
        github_reader=cockpit_github_plane.read_issue_delivery_github)
    assert refused["candidate"]["ready_to_try"] is False
