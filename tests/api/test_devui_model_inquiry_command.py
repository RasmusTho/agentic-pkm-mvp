from __future__ import annotations

from tests.builderops.inquiry_operation_fixture import InquiryGraph


def test_production_constructor_reaches_sanctioned_inquiry_protocol(tmp_path, monkeypatch) -> None:
    graph = InquiryGraph(tmp_path, monkeypatch)
    preview = graph.preview()
    response = graph.start(preview)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["operation"]["state"] == "terminal", result
    assert result["operation"]["terminal_receipt"]["final_state"] == "single_target_acceptance"
    assert result["approval"]["inquiry_id"] == preview["proposal"]["inquiry_id"]
    assert graph.launches == 1 and len(graph.provider.calls) == 4
    assert (
        graph.service.trace(result["approval"]["inquiry_id"])["question"]["content"]
        == preview["material"]["question"]
    )
    assert result["operation"]["workflow_cleanup"] == "complete"
    assert not graph.stage.exists() and not graph.lock.exists()


def test_start_requires_authenticated_action_boundary(tmp_path, monkeypatch) -> None:
    graph = InquiryGraph(tmp_path, monkeypatch)
    preview = graph.preview()
    payload = {
        "decision": "start",
        "proposal": preview["proposal"],
        "material": preview["material"],
    }
    for headers in (
        {"Host": "localhost"},
        {"Authorization": "Bearer invalid", "Host": "127.0.0.1"},
    ):
        assert (
            graph.http.post(
                "/v1/inquiries/command/start", json=payload, headers=headers
            ).status_code
            == 401
        )
    assert graph.start(preview, name="writer").status_code == 403
    assert graph.start(preview, name="reader").status_code == 403
    assert not graph.store.records and graph.launches == 0
    record = {
        "envelope": {
            "repository": "rasmustho/agentic-pkm-mvp",
            "scope": "model-inquiry-approval",
            "stack": "builderops",
            "source_refs": ["fixture"],
        },
        "record_id": "inquiry-approval:forged",
        "record_type": "ModelInquiryApproval",
        "state": "approved",
        "payload": {},
        "idempotency_key": "forged",
    }
    assert (
        graph.http.post("/v1/records", headers=graph.headers("writer"), json=record).status_code
        == 403
    )
    assert graph.start(preview, decision="hold").json() == {"state": "held", "effects": []}
    assert not graph.store.records and graph.launches == 0


def test_operation_cli_uses_canonical_envelope_and_fixed_stage(tmp_path, monkeypatch) -> None:
    import io
    from pathlib import Path
    from app.builderops import model_inquiry_operation as protocol
    from app.builderops.model_inquiry_workflow import (
        canonical_bytes,
        SanctionedModelInquiryWorkflow,
    )

    graph = InquiryGraph(tmp_path, monkeypatch)
    preview = graph.preview()
    graph.lock.mkdir()
    approved = graph.start(preview).json()["approval"]
    graph.stage.write_bytes(preview["material"]["question"].encode())
    monkeypatch.setattr(
        protocol.OperationDestination, "from_env", classmethod(lambda cls: graph.destination)
    )
    monkeypatch.setattr(
        protocol,
        "Path",
        lambda path: graph.stage
        if path == protocol.STAGE
        else graph.lock
        if path == protocol.LOCK
        else Path(path),
    )

    def invoke(args, envelope):
        output = io.BytesIO()
        stdout = io.TextIOWrapper(output, encoding="utf-8")
        with monkeypatch.context() as scoped:
            scoped.setattr(
                protocol.sys, "stdin", io.TextIOWrapper(io.BytesIO(envelope), encoding="utf-8")
            )
            scoped.setattr(protocol.sys, "stdout", stdout)
            code = protocol.main(args)
            stdout.flush()
            raw = output.getvalue()
        return code, raw

    binding = graph.service.command_operation_readback(approved)
    envelope = SanctionedModelInquiryWorkflow._envelope(approved, binding)
    assert invoke(["--operation-attempt-stdin"], canonical_bytes(envelope) + b" ")[0] == 1
    assert graph.service.command_operation_readback(approved)["launch_attempt_receipt_hash"] is None
    code, _ = invoke(["--operation-attempt-stdin"], canonical_bytes(envelope))
    assert code == 0
    envelope = SanctionedModelInquiryWorkflow._envelope(
        approved, graph.service.command_operation_readback(approved)
    )
    code, raw = invoke(
        ["--approved-operation-stdin", "--question-file", protocol.STAGE], canonical_bytes(envelope)
    )
    assert code == 0 and approved["inquiry_id"].encode() in raw
    assert len(graph.provider.calls) == 4
    assert (
        invoke(
            ["--approved-operation-stdin", "--question-file", protocol.STAGE],
            canonical_bytes(envelope),
        )[0]
        == 1
    )
    assert len(graph.provider.calls) == 4
