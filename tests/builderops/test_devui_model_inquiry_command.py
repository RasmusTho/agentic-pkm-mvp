"""Exact nonvisual inquiry approval tests; workflow effects are always doubled."""

from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import hashlib
import multiprocessing
import subprocess

import pytest

from app.builderops.devui_conversation_port import build_context_pack
from app.builderops import devui_sources
from app.builderops.devui_model_inquiry_command import (
    CommandContractError,
    build_command_proposal,
    canonical_hash,
    validate_command_proposal,
    approval_manifest as build_approval_manifest,
    model_inquiry_design_fixtures,
)
from app.builderops.model_inquiry import ModelInquiryService
from app.builderops.model_inquiry_operation import OperationDestination
from app.builderops.model_inquiry_workflow import SanctionedModelInquiryWorkflow
from app.builderops.model_inquiry_workflow import canonical_bytes
from app.builderops.model_inquiry_workflow import decode_object
from app.builderops import model_access_resolver, model_inquiry_runner
from app.builderops.model_inquiry_adapters import resolve_inquiry_target
from tests.builderops.inquiry_operation_fixture import InquiryGraph, REPOSITORY


NOW = datetime(2026, 9, 13, 16, 0, tzinfo=timezone.utc)


def test_command_sources_are_exact_issue_or_packaged_owner(tmp_path, monkeypatch) -> None:
    body = "## Acceptance Criteria\n- [ ] Exact result. Verify: tests/example.py\n"
    issue = {
        "number": 4697,
        "html_url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/4697",
        "updated_at": NOW.isoformat(),
        "body": body,
    }
    calls = []
    monkeypatch.setattr(
        devui_sources.cockpit_github_plane, "_run_gh", lambda args: calls.append(args) or issue
    )
    config = devui_sources.SourceConfiguration(
        REPOSITORY, None, {}, True, tmp_path, tmp_path, "1" * 40
    )
    ref = {
        "source_type": "github_issue",
        "source_id": REPOSITORY + "#4697",
        "locator": issue["html_url"],
        "content_hash": hashlib.sha256(body.encode()).hexdigest(),
    }
    pack = {
        "subject_ref": {"kind": "issue", "stable_id": "github:" + REPOSITORY + "#4697"},
        "source_states": [{"freshness": "fresh", "source_ref": ref}],
    }
    result = devui_sources.revalidate_inquiry_sources(
        config, repository=REPOSITORY, context_pack=pack
    )
    assert result["issue_number"] == 4697
    assert result["issue_body_hash"] == ref["content_hash"]
    assert calls == [["api", "repos/rasmustho/agentic-pkm-mvp/issues/4697"]]
    issue["body"] += "Changed scope.\n"
    with pytest.raises(devui_sources.SourceReadRefusal, match="changed"):
        devui_sources.revalidate_inquiry_sources(config, repository=REPOSITORY, context_pack=pack)
    pack["subject_ref"] = {"kind": "capability", "stable_id": "explicit-null-pre-ticket"}
    ref.update(source_type="capability", source_id="unadmitted-reader")
    before = len(calls)
    with pytest.raises(devui_sources.SourceReadRefusal, match="unsupported"):
        devui_sources.revalidate_inquiry_sources(config, repository=REPOSITORY, context_pack=pack)
    assert len(calls) == before


@pytest.mark.parametrize(
    "failure", ["timeout", "nonzero", "mismatched_identity", "list_state", "object_state"]
)
def test_terminal_launcher_with_failed_readback_preserves_recovery(tmp_path, monkeypatch, failure):
    graph = InquiryGraph(tmp_path, monkeypatch)
    preview = graph.preview()

    def process(argv, **kwargs):
        if "--operation-readback-stdin" in argv[-1]:
            if failure == "timeout":
                raise subprocess.TimeoutExpired(argv, 1)
            if failure == "nonzero":
                return subprocess.CompletedProcess(argv, 1, b"", b"fixture unavailable")
            captured = graph.process(argv, **kwargs)
            value = decode_object(captured.stdout)
            if failure == "list_state":
                value["state"] = []
            elif failure == "object_state":
                value["state"] = {}
            else:
                value["operation_key"] = "0" * 64
            return subprocess.CompletedProcess(argv, 0, canonical_bytes(value), b"")
        return graph.process(argv, **kwargs)

    monkeypatch.setattr(SanctionedModelInquiryWorkflow, "_process", staticmethod(process))
    response = graph.start(preview)
    assert graph.launches == 1 and len(graph.provider.calls) == 4
    assert graph.stage.exists() and graph.lock.exists()
    result = response.json()["operation"]
    assert result["state"] == "ambiguous"
    assert result["workflow_cleanup"] == "preserved_for_reconciliation"


def test_runner_consumes_the_profile_snapshot_approved_at_final_entry(tmp_path, monkeypatch):
    import yaml

    census = tmp_path / "providers.yaml"
    original = model_access_resolver._PROVIDER_CENSUS_PATH.read_text()
    census.write_text(original)
    monkeypatch.setattr(model_access_resolver, "_PROVIDER_CENSUS_PATH", census)
    graph = InquiryGraph(tmp_path, monkeypatch)
    preview = graph.preview()
    approved = resolve_inquiry_target(graph.destination.environment)[2]
    actual = []
    start = graph.service.start

    def start_then_change_profile(**kwargs):
        value = start(**kwargs)
        changed = yaml.safe_load(original)
        changed["runtime_channels"]["model_inquiry"]["dev"]["target_intent"]["reasoning_effort"] = (
            "high"
        )
        census.write_text(yaml.safe_dump(changed))
        return value

    def load_provider_boundary(environment, *, resolver=None):
        actual.append(resolve_inquiry_target(environment, resolver=resolver)[2])
        return {"synthesis": graph.provider, "verification": graph.provider}

    monkeypatch.setattr(graph.service, "start", start_then_change_profile)
    monkeypatch.setattr(model_inquiry_runner, "load_operational_adapters", load_provider_boundary)
    result = graph.start(preview).json()["operation"]
    assert result["state"] == "terminal"
    assert actual == [approved]
    assert resolve_inquiry_target(graph.destination.environment)[2] != approved


def command_material(*, now: datetime = NOW) -> dict:
    source = {
        "source_type": "owner_document",
        "source_id": "docs/BUILDEROPS_MODEL_INQUIRY/README.md",
        "content_hash": "a" * 64,
        "locator": "docs/BUILDEROPS_MODEL_INQUIRY/README.md",
    }
    pack = build_context_pack(
        pack_id="pack-inquiry",
        subject_ref={
            "kind": "capability",
            "stable_id": "model-inquiry",
            "authority_ref": source,
            "title": "Model Inquiry",
        },
        purpose="Investigate an exact pre-ticket question.",
        owner_intent_ref=source,
        source_refs=[source],
        evidence_snapshot_refs=[],
        source_states=[
            {
                "source_ref": source,
                "freshness": "fresh",
                "captured_at": now.isoformat(),
                "fresh_until": (now + timedelta(minutes=30)).isoformat(),
                "read_watermark": "source:1",
            }
        ],
        includes=["governing_sources"],
        excludes=[
            "credentials",
            "hidden_system_prompts",
            "provider_sessions",
            "broad_repository_history",
        ],
        limitations=[{"kind": "projection_only", "reason": "Not an approval."}],
        created_at=now,
        expires_at=now + timedelta(minutes=30),
    )
    return {
        "repository": "rasmustho/agentic-pkm-mvp",
        "issue_number": None,
        "issue_body_hash": None,
        "acceptance_criteria_hash": None,
        "question": "Which invariant needs independent inquiry?\n",
        "context_pack": pack,
        "workflow": {"version": "start-model-inquiry.v1", "content_hash": "b" * 64},
        "destination": {"identity": "Tailscale_macmini", "revision": "operation-reservation.v1"},
        "policy": {"ref": "inquiry-policy", "version": "1", "content_hash": "c" * 64},
        "configuration": {"ref": "inquiry-config", "version": "1", "content_hash": "d" * 64},
        "capability": {"ref": "resolved-inquiry-profile", "version": "1", "content_hash": "e" * 64},
    }


def proposal(material: dict | None = None) -> dict:
    return build_command_proposal(
        approval_id="approval-4697",
        material=material or command_material(),
        owner_principal="owner:rasmus",
        permission_ref="credential:owner",
        permission_version="1",
        authority_epoch=1,
        now=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )


def validate(value: dict, material: dict | None = None, **kwargs) -> dict:
    return validate_command_proposal(
        value,
        current_material=material or command_material(),
        owner_principal="owner:rasmus",
        permission_ref="credential:owner",
        permission_version="1",
        authority_epoch=1,
        now=kwargs.pop("now", NOW),
        **kwargs,
    )


def test_command_preview_requires_complete_exact_binding() -> None:
    exact = proposal()
    assert validate(exact) == exact
    assert exact["exact_inputs"][0]["text"].endswith("\n")
    assert exact["issue_number"] is None
    for field in exact:
        missing = deepcopy(exact)
        del missing[field]
        with pytest.raises(CommandContractError):
            validate(missing)
    for path in (
        ("exact_inputs", 0, "content_hash"),
        ("destination", "workflow_hash"),
        ("approval_rule", "authenticated_principal_ref"),
        ("expected_receipt", "required_fields"),
        ("freshness", "invalidation_conditions"),
    ):
        changed = deepcopy(exact)
        item = changed
        for key in path[:-1]:
            item = item[key]
        item[path[-1]] = "changed"
        with pytest.raises(CommandContractError):
            validate(changed)
    with pytest.raises(CommandContractError):
        validate({**exact, "command_type": "apply"})


def test_stale_or_changed_preview_cannot_start() -> None:
    exact = proposal()
    for field in ("question", "workflow", "destination", "policy", "configuration", "capability"):
        changed = command_material()
        if field == "question":
            changed[field] += "A new question."
        elif field == "destination":
            changed[field]["revision"] = "changed"
        else:
            changed[field]["content_hash"] = "f" * 64
        with pytest.raises(CommandContractError):
            validate(exact, changed)
    with pytest.raises(CommandContractError, match="expir"):
        validate(exact, now=NOW + timedelta(minutes=10))
    for field in (
        "proposal_hash",
        "operation_key",
        "repository",
        "source_refs",
        "explicit_non_effects",
    ):
        changed = deepcopy(exact)
        changed[field] = "tampered"
        with pytest.raises(CommandContractError):
            validate(changed)


def approval_manifest() -> dict:
    exact = proposal()
    return build_approval_manifest(exact, command_material(), approved_at=NOW)


def test_operation_key_replay_never_relaunches_inquiry(tmp_path, monkeypatch) -> None:
    manifest = approval_manifest()
    destinations = [ModelInquiryService(tmp_path), ModelInquiryService(tmp_path)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        reserved = list(
            pool.map(lambda service: service.reserve_command_operation(manifest), destinations)
        )
    assert sum(created for _binding, created in reserved) == 1
    assert reserved[0][0] == reserved[1][0]
    binding = reserved[0][0]
    assert binding["inquiry_id"]
    assert not (tmp_path / "model-inquiries" / binding["inquiry_id"] / "manifest.json").exists()
    restarted = ModelInquiryService(tmp_path)
    assert restarted.reserve_command_operation(manifest) == (binding, False)
    before_attempt = restarted.command_operation_readback(manifest)
    assert before_attempt["state"] == "reserved"
    assert before_attempt["launch_evidence"] is None
    assert before_attempt["stop_support"] == "unsupported"
    assert restarted.record_command_launch_attempt(manifest)[1] is True
    assert restarted.record_command_launch_attempt(manifest)[1] is False
    after_attempt = ModelInquiryService(tmp_path).command_operation_readback(manifest)
    assert after_attempt["state"] == "ambiguous"
    assert after_attempt["reason"] == "launch_attempt_without_terminal_response"
    changed = deepcopy(manifest)
    changed["proposal"]["exact_inputs"][0]["text"] = "Another question"
    with pytest.raises(ValueError):
        restarted.reserve_command_operation(changed)

    graph_root = tmp_path / "graph"
    graph_root.mkdir()
    graph = InquiryGraph(graph_root, monkeypatch)
    preview = graph.preview()
    calls_before_hold = len(graph.calls)
    assert graph.start(preview, decision="hold").json() == {"state": "held", "effects": []}
    assert len(graph.calls) == calls_before_hold and not graph.store.records
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: graph.start(preview), range(2)))
    assert all(response.status_code == 200 for response in responses), [
        response.text for response in responses
    ]
    assert graph.launches == 1 and len(graph.provider.calls) == 4
    graph.destination = OperationDestination(
        ModelInquiryService(graph_root / "vault"),
        graph.destination.client,
        environment=graph.destination.environment,
    )
    replay = graph.start(preview).json()["operation"]
    assert replay["state"] == "terminal" and graph.launches == 1
    assert replay["inquiry_id"] == preview["proposal"]["inquiry_id"]
    new_key = deepcopy(preview)
    new_key["proposal"]["operation_key"] = "f" * 64
    assert graph.start(new_key).status_code == 400
    assert graph.launches == 1


def test_receipt_and_ambiguous_outcomes_preserve_workflow_contract(tmp_path, monkeypatch) -> None:
    service = ModelInquiryService(tmp_path)
    manifest = approval_manifest()
    binding, _ = service.reserve_command_operation(manifest)
    service.record_command_launch_attempt(manifest)
    exact = {
        "inquiry_id": binding["inquiry_id"],
        "final_state": "single_target_acceptance",
        "terminal_receipt_id": f"receipt_{binding['inquiry_id']}_run_terminal",
        "human_readable_report": str(
            tmp_path / "model-inquiries" / binding["inquiry_id"] / "report.md"
        ),
    }
    for code, output in (
        (1, json.dumps(exact)),
        (0, ""),
        (0, "[]"),
        (0, json.dumps({**exact, "inquiry_id": "another"})),
        (0, json.dumps({**exact, "final_state": "active"})),
        (0, json.dumps({**exact, "terminal_receipt_id": ""})),
    ):
        result = service.record_command_response(manifest, returncode=code, stdout=output)
        assert result["state"] == "ambiguous"
        assert result["terminal_receipt"] is None
    # Four plausible strings without actual runner artifacts are not a receipt.
    assert (
        service.record_command_response(manifest, returncode=0, stdout=json.dumps(exact))["state"]
        == "ambiguous"
    )
    graph_root = tmp_path / "graph"
    graph_root.mkdir()
    graph = InquiryGraph(graph_root, monkeypatch)
    preview = graph.preview()
    graph.launch_response = lambda argv, value: subprocess.CompletedProcess(
        argv, 1, canonical_bytes(value), b""
    )
    initial = graph.start(preview).json()
    assert initial["operation"]["state"] == "ambiguous"
    assert graph.lock.exists() and graph.stage.exists()
    readback = graph.http.get(
        "/v1/inquiries/command/approval-4697",
        params={"repository": REPOSITORY},
        headers=graph.headers("reader"),
    ).json()
    assert readback["state"] == "terminal"
    assert readback["terminal_receipt"]["inquiry_id"] == preview["proposal"]["inquiry_id"]
    assert graph.launches == 1 and graph.lock.exists() and graph.stage.exists()
    report = graph_root / "vault/model-inquiries" / preview["proposal"]["inquiry_id"] / "report.md"
    report.write_text("tampered")
    assert SanctionedModelInquiryWorkflow().readback(initial["approval"])["state"] == "unavailable"


@pytest.mark.parametrize(
    "change", ["revoked", "rotation", "scope", "epoch", "source", "expiry", "configuration"]
)
def test_destination_final_revalidation_prevents_revoked_launch(
    tmp_path, monkeypatch, change
) -> None:
    graph = InquiryGraph(tmp_path, monkeypatch)
    preview = graph.preview()

    def change_authority():
        if change == "epoch":
            graph.store.epoch += 1
        elif change == "source":
            graph.source_path.write_text("changed current owner source")
        elif change == "configuration":
            graph.destination.environment["BUILDEROPS_MODEL_INQUIRY_OPERATIONAL_SUBSCRIPTION"] = "0"
        elif change == "expiry":
            from app.builderops.control_plane import service

            future = datetime.now(timezone.utc) + timedelta(minutes=20)

            class Future(datetime):
                @classmethod
                def now(cls, tz=None):
                    return future

            monkeypatch.setattr(service, "datetime", Future)
        else:
            owner = graph.credentials["credentials"][0]
            if change == "revoked":
                owner["revoked"] = True
            elif change == "rotation":
                owner["rotation_generation"] = 2
            else:
                owner["scopes"] = ["inquiries:read"]
            graph.write_credentials()

    # Change authority after the atomic entry, proving the last check is real.
    original = graph.service.enter_command_invocation

    def enter(*args, **kwargs):
        value = original(*args, **kwargs)
        change_authority()
        return value

    monkeypatch.setattr(graph.service, "enter_command_invocation", enter)
    result = graph.start(preview).json()
    assert result["operation"]["state"] == "ambiguous"
    assert not graph.provider.calls
    assert graph.stage.exists() and graph.lock.exists()
    directory = tmp_path / "vault/model-inquiries" / preview["proposal"]["inquiry_id"]
    assert (directory / "command-invocation-entry.json").exists()
    assert not (directory / "manifest.json").exists()


def test_operation_protocol_authenticates_every_control_verb(tmp_path, monkeypatch) -> None:
    from app.builderops.control_plane.client import ClientConfig, ControlPlaneClientError

    graph = InquiryGraph(tmp_path, monkeypatch)
    preview = graph.preview()
    graph.lock.mkdir()  # Only reservation is admitted; no launch may start.
    approved = graph.start(preview).json()["approval"]
    binding = graph.service.command_operation_readback(approved)
    envelope = SanctionedModelInquiryWorkflow._envelope(approved, binding)
    for verb in (
        "--operation-reserve-stdin",
        "--operation-attempt-stdin",
        "--approved-operation-stdin",
        "--operation-readback-stdin",
    ):
        graph.destination.client._config = ClientConfig("http://testserver", "writer-fixture")
        with pytest.raises(ControlPlaneClientError):
            graph.destination.control(verb, envelope)
        graph.destination.client._config = ClientConfig("http://testserver", "destination-fixture")
        forged = deepcopy(approved)
        forged["approved_at"] = NOW.isoformat()
        forged["approval_manifest_hash"] = canonical_hash(
            {k: v for k, v in forged.items() if k != "approval_manifest_hash"}
        )
        with pytest.raises(ControlPlaneClientError):
            graph.destination.control(verb, {**envelope, "approval": forged})
    graph.destination.client._config = ClientConfig("http://testserver", "reader-fixture")
    assert graph.destination.control("--operation-readback-stdin", envelope)["state"] == "reserved"
    with pytest.raises(ControlPlaneClientError):
        graph.destination.control("--operation-attempt-stdin", envelope)
    assert not graph.provider.calls and graph.launches == 0


def _process_entry(path, manifest, reservation_hash, attempt_hash, queue):
    from pathlib import Path

    result = ModelInquiryService(Path(path)).enter_command_invocation(
        manifest, reservation_hash=reservation_hash, attempt_hash=attempt_hash
    )
    queue.put(result[1])


def test_operation_entry_is_consumed_once(tmp_path) -> None:
    manifest = approval_manifest()
    service = ModelInquiryService(tmp_path)
    reservation, _ = service.reserve_command_operation(manifest)
    attempt, _ = service.record_command_launch_attempt(manifest)
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    children = [
        context.Process(
            target=_process_entry,
            args=(
                str(tmp_path),
                manifest,
                reservation["artifact_hash"],
                attempt["artifact_hash"],
                queue,
            ),
        )
        for _ in range(2)
    ]
    for child in children:
        child.start()
    results = [queue.get(timeout=20) for _ in children]
    for child in children:
        child.join(20)
        assert child.exitcode == 0
    assert sorted(results) == [False, True]
    assert service.command_operation_readback(manifest)["state"] == "ambiguous"
    assert not (tmp_path / "model-inquiries" / manifest["inquiry_id"] / "manifest.json").exists()


@pytest.mark.parametrize("boundary", ["reservation", "attempt", "question_artifact"])
def test_partial_destination_writes_never_authorize_restart(
    tmp_path, monkeypatch, boundary
) -> None:
    graph = InquiryGraph(tmp_path, monkeypatch)
    preview = graph.preview()

    def lost_response():
        raise subprocess.TimeoutExpired("fixed-host-fixture", 1)

    if boundary == "reservation":
        graph.after_reserve = lost_response
    elif boundary == "attempt":
        graph.after_attempt = lost_response
    else:
        original = graph.service._write_immutable

        def partial(path, *args, **kwargs):
            if path.name == "manifest.json":
                raise ValueError("fixture crash after immutable question")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(graph.service, "_write_immutable", partial)
    first = graph.start(preview).json()
    assert not graph.provider.calls
    launches = graph.launches
    graph.after_reserve = graph.after_attempt = None
    again = graph.start(preview).json()
    assert again["approval"] == first["approval"]
    assert again["operation"]["state"] == ("reserved" if boundary == "reservation" else "ambiguous")
    assert graph.launches == launches and not graph.provider.calls
    if boundary != "reservation":
        assert graph.lock.exists() and graph.stage.exists()


def test_unsupported_operation_capabilities_refuse_before_reservation(
    tmp_path, monkeypatch
) -> None:
    graph = InquiryGraph(tmp_path, monkeypatch)
    preview = graph.preview()
    graph.capability_supported = False
    response = graph.start(preview)
    assert response.status_code in {400, 503}
    assert not graph.store.records and graph.reserves == 0 and graph.launches == 0
    assert not graph.lock.exists() and not graph.stage.exists()


def test_model_inquiry_emits_design_handoff_fixtures() -> None:
    exact = proposal()
    fixtures = model_inquiry_design_fixtures(exact)
    assert set(fixtures) == {
        "exact_preview",
        "start",
        "hold",
        "stale",
        "terminal",
        "ambiguous",
        "workflow_unavailable",
    }
    assert fixtures["exact_preview"]["proposal"] == exact
    assert fixtures["hold"]["effects"] == []
    assert fixtures["ambiguous"]["automatic_relaunch"] is False
    assert fixtures["stale"]["start_available"] is False
    assert all(
        item["visual_geometry"] == "unspecified" and item["owner_acceptance"] is False
        for item in fixtures.values()
    )
