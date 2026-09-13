"""Finite operation protocol for the operator-owned Model Inquiry wrapper.

The live wrapper must explicitly delegate to this entrypoint after operator
activation. This module never installs it or substitutes a provider launcher.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import os
from pathlib import Path
import sys
from typing import Any, Mapping

from app.builderops.control_plane.client import BuilderOpsControlPlaneClient, ClientConfig
from app.builderops.devui_model_inquiry_command import (
    OPERATION_VERBS,
    OPERATION_VERSION,
    canonical_hash,
    validate_approval_identity,
)
from app.builderops.model_inquiry import ModelInquiryService
from app.builderops.model_inquiry_adapters import (
    operational_subscription_requested,
    resolve_inquiry_target,
)
from app.builderops.model_inquiry_runner import ModelInquiryRunner
from app.builderops.model_inquiry_workflow import (
    DESTINATION,
    LOCK,
    STAGE,
    canonical_bytes,
    decode_object,
    workflow_binding,
)


class OperationRefused(ValueError):
    """No operation effect is authorized by the exact current service binding."""


class OperationDestination:
    def __init__(
        self,
        service: ModelInquiryService,
        client: BuilderOpsControlPlaneClient,
        *,
        environment: Mapping[str, str],
    ) -> None:
        self.service = service
        self.client = client
        self.environment = environment

    @classmethod
    def from_env(cls) -> "OperationDestination":
        return cls(
            ModelInquiryService.from_env(),
            BuilderOpsControlPlaneClient(ClientConfig.from_env(), max_retries=0),
            environment=os.environ,
        )

    def current_bindings(self) -> dict[str, Any]:
        if not operational_subscription_requested(self.environment):
            raise OperationRefused("operational subscription workflow is not configured")
        resolver, intent, resolution = resolve_inquiry_target(self.environment)
        profile = resolver.model_inquiry_profile(intent.channel)
        return {
            "workflow": workflow_binding(),
            "destination": {"identity": DESTINATION, "revision": OPERATION_VERSION},
            "policy": {
                "ref": "builder-model-access:model-inquiry",
                "version": "1",
                "content_hash": canonical_hash(profile.model_dump(mode="json")),
            },
            "configuration": {
                "ref": "model-inquiry-role-intent",
                "version": "1",
                "content_hash": canonical_hash(asdict(intent)),
            },
            "capability": {
                "ref": "resolved-model-inquiry-profile",
                "version": "1",
                "content_hash": canonical_hash(resolution.model_dump(mode="json")),
            },
        }

    def capabilities(self) -> dict[str, Any]:
        return {
            "schema": "builderops.model-inquiry-operation-capabilities.v1",
            "version": OPERATION_VERSION,
            "verbs": OPERATION_VERBS.copy(),
            "bindings": self.current_bindings(),
            "stop_support": "unsupported",
        }

    def _authorize(self, approval: dict[str, Any], purpose: str) -> dict[str, Any]:
        reply = self.client.inquiry_command_authority(approval=approval, purpose=purpose)
        if (
            reply.get("approval") != approval
            or reply.get("purpose") != purpose
            or type(reply.get("authority_epoch")) is not int
            or not reply.get("observed_at")
        ):
            raise OperationRefused("service approval binding is unavailable")
        if purpose != "readback":
            if reply["authority_epoch"] != approval["proposal"]["approval_rule"]["authority_epoch"]:
                raise OperationRefused("authority epoch changed")
            if any(
                approval["material"][name] != value
                for name, value in self.current_bindings().items()
            ):
                raise OperationRefused("current workflow/profile differs from approval")
        return reply

    def _readback(self, approval: dict[str, Any], authority: dict[str, Any]) -> dict[str, Any]:
        value = self.service.command_operation_readback(approval)
        value["source_epoch"] = authority["authority_epoch"]
        value["observed_at"] = authority["observed_at"]
        return value

    def control(
        self, verb: str, envelope: dict[str, Any], *, question: bytes | None = None
    ) -> dict[str, Any]:
        if (
            verb not in OPERATION_VERBS
            or verb == "--operation-capabilities"
            or set(envelope)
            != {"approval", "reservation_receipt_hash", "launch_attempt_receipt_hash"}
        ):
            raise OperationRefused("unsupported exact operation envelope")
        approval = validate_approval_identity(envelope["approval"])
        purpose = {
            "--operation-reserve-stdin": "reserve",
            "--operation-attempt-stdin": "attempt",
            "--approved-operation-stdin": "execute",
            "--operation-readback-stdin": "readback",
        }[verb]
        authority = self._authorize(approval, purpose)
        reservation_hash, attempt_hash = (
            envelope["reservation_receipt_hash"],
            envelope["launch_attempt_receipt_hash"],
        )
        if purpose == "reserve":
            if reservation_hash is not None or attempt_hash is not None:
                raise OperationRefused("reservation must precede attempt")
            _, created = self.service.reserve_command_operation(approval)
            return {"created": created, "readback": self._readback(approval, authority)}
        readback = self._readback(approval, authority)
        for name in ("reservation_receipt_hash", "launch_attempt_receipt_hash"):
            if envelope[name] is not None and envelope[name] != readback[name]:
                raise OperationRefused("operation receipt hash changed")
        if purpose == "readback":
            return readback
        if reservation_hash is None:
            raise OperationRefused("exact reservation receipt required")
        if purpose == "attempt":
            if attempt_hash is not None:
                raise OperationRefused("new attempt must not change receipt identity")
            _, created = self.service.record_command_launch_attempt(approval)
            return {"created": created, "readback": self._readback(approval, authority)}
        if attempt_hash is None or question != approval["proposal"]["exact_inputs"][0][
            "text"
        ].encode("utf-8"):
            raise OperationRefused("exact staged question and attempt required")
        _, entered = self.service.enter_command_invocation(
            approval, reservation_hash=reservation_hash, attempt_hash=attempt_hash
        )
        if not entered:
            # Never ask the runner to resume/retry an operation entry. Its own
            # legacy resume support is not a second operation authorization.
            raise OperationRefused("operation invocation already consumed")
        # Queue time, atomic entry, or an in-flight credential/source change
        # cannot reuse the earlier authorization. Failure now stays ambiguous.
        self._authorize(approval, "execute")
        inquiry_id = approval["inquiry_id"]
        self.service.start(
            question=question.decode("utf-8"),
            workflow="model_inquiry",
            acceptance_mode="single_target",
            source_refs=[
                {"ref_type": "builderops_approval", "ref": approval["approval_receipt_ref"]}
            ],
            created_by=approval["owner_principal"],
            inquiry_id=inquiry_id,
        )
        result = ModelInquiryRunner(
            self.service, env=self.environment, allow_operational_fallback=False
        ).run(inquiry_id)
        terminal = {
            "inquiry_id": inquiry_id,
            "final_state": result["outcome"],
            "terminal_receipt_id": result["terminal_receipt_id"],
            "human_readable_report": result["human_readable_report"],
        }
        self.service.record_command_response(
            approval, returncode=0, stdout=canonical_bytes(terminal).decode("utf-8")
        )
        return terminal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    for verb in OPERATION_VERBS:
        group.add_argument(verb, action="store_true")
    parser.add_argument("--question-file", choices=[STAGE])
    args = parser.parse_args(argv)
    verb = next(verb for verb in OPERATION_VERBS if getattr(args, verb[2:].replace("-", "_")))
    destination: OperationDestination | None = None
    try:
        if bool(args.question_file) != (verb == "--approved-operation-stdin"):
            raise OperationRefused("only approved invocation reads the fixed staged question")
        destination = OperationDestination.from_env()
        if verb == "--operation-capabilities":
            result = destination.capabilities()
        else:
            raw = sys.stdin.buffer.read(262145)
            envelope = decode_object(raw)
            if canonical_bytes(envelope) != raw:
                raise OperationRefused("canonical operation JSON required")
            question = None
            if args.question_file:
                path = Path(STAGE)
                lock = Path(LOCK)
                if (
                    lock.is_symlink()
                    or not lock.is_dir()
                    or lock.stat().st_uid != os.getuid()
                    or path.is_symlink()
                    or not path.is_file()
                    or path.stat().st_uid != os.getuid()
                ):
                    raise OperationRefused("staged question is not owned")
                question = path.read_bytes()
                if len(question) > 16384:
                    raise OperationRefused("bounded staged question required")
            result = destination.control(verb, envelope, question=question)
        sys.stdout.buffer.write(canonical_bytes(result) + b"\n")
        return 0
    except Exception:
        # No process/credential/provider exception text crosses this boundary.
        sys.stderr.write("model inquiry operation refused or unavailable\n")
        return 1
    finally:
        if destination is not None:
            destination.client.close()


if __name__ == "__main__":
    raise SystemExit(main())
