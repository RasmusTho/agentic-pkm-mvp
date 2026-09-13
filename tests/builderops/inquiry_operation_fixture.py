"""Real service/facade/destination/runner graph with finite host and provider fakes."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
from typing import Any

from fastapi.testclient import TestClient

from app.builderops.control_plane import service as control_service
from app.builderops.control_plane.client import (
    BuilderOpsControlPlaneClient,
    ClientConfig,
    ControlPlaneClientError,
)
from app.builderops.control_plane.models import AuthorityObjectResult, LeaseRequired
from app.builderops.devui_conversation_port import build_context_pack
from app.builderops.model_inquiry import ModelInquiryService
from app.builderops.model_inquiry_adapters import AdapterResult
from app.builderops import model_inquiry_runner
from app.builderops.model_inquiry_operation import OperationDestination
from app.builderops.model_inquiry_workflow import (
    SanctionedModelInquiryWorkflow,
    canonical_bytes,
    decode_object,
)
from tests.builderops.inquiry_intent import intent_env
from tests.builderops.test_model_inquiry_runner import _response

REPOSITORY = "rasmustho/agentic-pkm-mvp"


class ApprovalStore:
    """Database-boundary double with the existing immutable first-write rule."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict[str, Any]] = {}
        self.epoch = 1
        self.lock = threading.Lock()

    def readiness(self) -> dict[str, int]:
        return {"schema_version": 1, "authority_epoch": self.epoch}

    def commit_record(self, **kwargs: Any) -> AuthorityObjectResult:
        key = kwargs["envelope"].repository, kwargs["record_id"]
        with self.lock:
            if key in self.records:
                raise LeaseRequired("record update requires a lease")
            self.records[key] = {
                "payload": deepcopy(kwargs["payload"]),
                "state": kwargs["state"],
                "record_type": kwargs["record_type"],
                "authority_envelope": kwargs["envelope"].as_json(),
            }
        return AuthorityObjectResult(
            repository=key[0],
            object_kind="record",
            object_id=key[1],
            state=kwargs["state"],
            receipt_sequence=1,
            recovery_lsn="0/1",
        )

    def get_record(self, repository: str, record_id: str) -> dict[str, Any]:
        return deepcopy(self.records[repository, record_id])


class Provider:
    adapter_id = "configured-inquiry-fixture"
    provider = "configured-provider"
    model = "configured-model"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def execute(self, request: dict[str, Any]) -> AdapterResult:
        self.calls.append(request)
        if request["phase"] == "draft":
            return AdapterResult(_response("draft"))
        return AdapterResult(
            _response(
                "accept",
                reviewed=list(request["reviewed_artifact_refs"]),
                accepted_hash=str(request["input_artifacts"][0]["artifact_hash"]),
            )
        )


class InquiryGraph:
    def __init__(self, tmp_path: Path, monkeypatch: Any) -> None:
        self.root = tmp_path
        self.store = ApprovalStore()
        self.calls: list[list[str]] = []
        self.launches = 0
        self.reserves = 0
        self.capability_supported = True
        self.after_attempt: Any = None
        self.after_reserve: Any = None
        self.after_entry: Any = None
        self.launch_response: Any = None
        self.manual_response: Any = None
        self.manual_question: bytes | None = None
        self.auth_purposes: list[str] = []
        self.provider = Provider()
        self.credentials = {
            "credentials": [
                self._credential("owner", ["inquiries:approve", "inquiries:read"]),
                self._credential("destination", ["inquiries:execute", "inquiries:read"]),
                self._credential("writer", ["inquiries:write", "records:write"]),
                self._credential("reader", ["inquiries:read"]),
            ]
        }
        self.manifest = tmp_path / "credentials.json"
        self.write_credentials()
        candidate = tmp_path / "candidate"
        path = candidate / "docs/BUILDEROPS_MODEL_INQUIRY/README.md"
        path.parent.mkdir(parents=True)
        path.write_text("# Model Inquiry\nExact fixture owner source.\n")
        self.source_path = path
        self.source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        (candidate / "manifest.json").write_text(
            json.dumps(
                {
                    "repository": REPOSITORY,
                    "source_sha": "1" * 40,
                    "files": {"docs/BUILDEROPS_MODEL_INQUIRY/README.md": self.source_hash},
                }
            )
        )
        monkeypatch.setenv("BUILDEROPS_CREDENTIAL_MANIFEST_FILE", str(self.manifest))
        monkeypatch.setenv("DEVUI_REPOSITORY", REPOSITORY)
        monkeypatch.setenv("DEVUI_GITHUB_ENABLED", "false")
        monkeypatch.setenv("VCS_REF", "1" * 40)
        monkeypatch.setenv("BUILDEROPS_RATE_LIMIT_PER_MINUTE", "10000")
        monkeypatch.setattr(control_service, "INQUIRY_CANDIDATE_ROOT", candidate)
        monkeypatch.setattr(control_service, "production_store", lambda _: self.store)
        monkeypatch.setattr(control_service, "database_environment", lambda _: {})
        monkeypatch.setattr(SanctionedModelInquiryWorkflow, "_process", staticmethod(self.process))
        monkeypatch.setattr(
            model_inquiry_runner,
            "load_operational_adapters",
            lambda *_args, **_kwargs: {"synthesis": self.provider, "verification": self.provider},
        )
        self.app = control_service.production_app()
        self.http = TestClient(self.app)
        vault = tmp_path / "vault"
        vault.mkdir()
        self.service = ModelInquiryService(vault)
        client = BuilderOpsControlPlaneClient(
            ClientConfig("http://testserver", "destination-fixture"),
            http_client=self.http,
            max_retries=0,
        )
        self.destination = OperationDestination(
            self.service,
            client,
            environment={**intent_env(), "BUILDEROPS_MODEL_INQUIRY_OPERATIONAL_SUBSCRIPTION": "1"},
        )
        self.lock = tmp_path / "remote-lock"
        self.stage = tmp_path / "remote-stage"

    @staticmethod
    def _credential(name: str, scopes: list[str]) -> dict[str, Any]:
        secret = name + "-fixture"
        return {
            "id": name,
            "principal": name,
            "secret_ref": "host-secret:" + name,
            "verifier_sha256": hashlib.sha256(secret.encode()).hexdigest(),
            "token_length": len(secret),
            "rotation_generation": 1,
            "scopes": scopes,
            "repositories": [REPOSITORY],
        }

    def write_credentials(self) -> None:
        self.manifest.write_text(json.dumps(self.credentials))

    @staticmethod
    def headers(name: str = "owner") -> dict[str, str]:
        return {"Authorization": "Bearer " + name + "-fixture"}

    def preview(
        self, *, approval_id: str = "approval-4697", question: str = "Exact question åäö\n\n"
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        source = {
            "source_type": "owner_document",
            "source_id": "docs/BUILDEROPS_MODEL_INQUIRY/README.md",
            "content_hash": self.source_hash,
            "locator": "docs/BUILDEROPS_MODEL_INQUIRY/README.md",
        }
        pack = build_context_pack(
            pack_id="pack-inquiry",
            subject_ref={
                "kind": "capability",
                "stable_id": "pre-ticket-model-inquiry",
                "authority_ref": source,
                "title": "Pre-ticket inquiry",
            },
            purpose="Exact pre-ticket question",
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
            limitations=[{"kind": "projection_only", "reason": "No owner acceptance."}],
            created_at=now,
            expires_at=now + timedelta(minutes=30),
        )
        response = self.http.post(
            "/v1/inquiries/command/preview",
            headers=self.headers(),
            json={
                "repository": REPOSITORY,
                "approval_id": approval_id,
                "question": question,
                "context_pack": pack,
                "expires_at": (now + timedelta(minutes=10)).isoformat(),
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    def start(
        self, preview: dict[str, Any], *, name: str = "owner", decision: str = "start"
    ) -> Any:
        return self.http.post(
            "/v1/inquiries/command/start",
            headers=self.headers(name),
            json={
                "decision": decision,
                "proposal": preview["proposal"],
                "material": preview["material"],
            },
        )

    def process(
        self, argv: list[str], *, stdin: bytes | None = None, timeout: int = 60
    ) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(argv)

        def result(
            value: dict[str, Any] | bytes = b"", code: int = 0
        ) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(
                argv, code, value if isinstance(value, bytes) else canonical_bytes(value), b""
            )

        if argv[:2] == ["/usr/bin/ssh", "-G"]:
            return result(b"user destination\nhostname fixed-host\n")
        if argv == ["/usr/bin/id", "-un"]:
            return result(b"caller\n")
        assert argv[0] == "/usr/bin/ssh", argv
        command = argv[-1]
        try:
            if command.startswith('"$HOME/.local/bin/yggdrasil-model-inquiry"'):
                if "--operation-capabilities" in command:
                    return (
                        result(self.destination.capabilities())
                        if self.capability_supported
                        else result(b"unsupported", 2)
                    )
                if command.endswith("--question-file /tmp/model-inquiry-question.md"):
                    assert stdin is None
                    self.launches += 1
                    self.manual_question = self.stage.read_bytes()
                    value = {
                        "inquiry_id": "inq_manual",
                        "final_state": "single_target_acceptance",
                        "terminal_receipt_id": "receipt_inq_manual_run_terminal",
                        "human_readable_report": "/fixture/report.md",
                    }
                    return (
                        self.manual_response(argv, value) if self.manual_response else result(value)
                    )
                envelope = decode_object(stdin or b"")
                if "--approved-operation-stdin" in command:
                    self.launches += 1
                    verb = "--approved-operation-stdin"
                elif "--operation-reserve-stdin" in command:
                    self.reserves += 1
                    verb = "--operation-reserve-stdin"
                elif "--operation-attempt-stdin" in command:
                    verb = "--operation-attempt-stdin"
                elif "--operation-readback-stdin" in command:
                    verb = "--operation-readback-stdin"
                else:
                    raise AssertionError(command)
                value = self.destination.control(
                    verb,
                    envelope,
                    question=self.stage.read_bytes()
                    if verb == "--approved-operation-stdin"
                    else None,
                )
                if verb == "--operation-attempt-stdin" and self.after_attempt:
                    self.after_attempt()
                if verb == "--operation-reserve-stdin" and self.after_reserve:
                    self.after_reserve()
                if verb == "--approved-operation-stdin" and self.launch_response:
                    return self.launch_response(argv, value)
                return result(value)
            if command.startswith("/bin/mkdir"):
                self.lock.mkdir()
                return result()
            if command.startswith("umask 077; set -C;"):
                if self.stage.exists() or self.stage.is_symlink():
                    return result(code=17)
                fd = os.open(self.stage, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(stdin or b"")
                return result()
            if command.startswith("test ! -L"):
                if self.stage.is_symlink() or self.lock.is_symlink():
                    return result(code=1)
                if "/bin/rm " in command:
                    self.stage.unlink(missing_ok=True)
                self.lock.rmdir()
                return result()
            raise AssertionError(command)
        except (ValueError, OSError, ControlPlaneClientError) as exc:
            return subprocess.CompletedProcess(argv, 1, b"", type(exc).__name__.encode())
