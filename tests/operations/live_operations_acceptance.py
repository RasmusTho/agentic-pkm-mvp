"""Fixed external-SDK/HTTP acceptance journey for qualified running channels.

Run in the separately installed MCP/browser runtime, never the core image.
Native facts and normal Product responses are observed, not replaced. A
required unavailable scenario is retained as blocked, never omitted or PASS.
"""
from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import Future
import json
from pathlib import Path
from queue import Queue
import sys
from threading import Thread
from time import sleep, time
from typing import Any
from urllib.parse import quote

import httpx

from app.ops.native_operations_acceptance_runner import NativeChannel, SDK_PYTHON
from app.ops.operations_acceptance import (
    FAMILIES, MAX_SECONDS, OperationsAcceptanceRefusal, digest, file_hash, inventory,
    produce_receipt, read_original_test_receipt, read_private, require_identity, write_private,
)

V1_TOOLS = ("mimer.ask", "mimer.capture", "mimer.retrieve", "mimer.read_note", "mimer.health")
EVIDENCE_DIRECTORY = Path("/var/lib/yggdrasil/bws-deploy/operations-acceptance-results")


class OfficialClient:
    """One official SDK task owns one actual stdio sidecar lifetime."""
    def __init__(self, url: str, bearer: str, python: str, *, profile: str = "v2") -> None:
        self.url, self.python, self.profile = url, python, profile
        self.meta = {"mimer/active-context-session": bearer}
        self.queue: Queue[Any] = Queue()
        self.ready: Future[Any] = Future()
        self.failure: BaseException | None = None

    async def _run(self) -> None:
        try:
            from mcp import ClientSession, types
            from mcp.client.stdio import StdioServerParameters, stdio_client
            parameters = StdioServerParameters(command=self.python,
                args=["-I", "-m", "mimer_mcp_sidecar", "--base-url", self.url, "--profile", self.profile])
            async with stdio_client(parameters) as (reader, writer), ClientSession(reader, writer) as client:
                self.ready.set_result(await client.initialize())
                while True:
                    item = await asyncio.to_thread(self.queue.get)
                    if item is None:
                        break
                    kind, name, arguments, meta, future = item
                    try:
                        result = (await client.list_tools(params=types.PaginatedRequestParams(_meta=meta))
                                  if kind == "tools" else await client.call_tool(name, arguments, meta=meta))
                        future.set_result(result)
                    except Exception as exc:
                        future.set_exception(exc)
        except BaseException as exc:
            if not self.ready.done():
                self.ready.set_exception(exc)
            else:
                self.failure = exc

    def __enter__(self) -> OfficialClient:
        self.thread = Thread(target=lambda: asyncio.run(self._run()), daemon=True)
        self.thread.start()
        self.ready.result(30)
        return self

    def _request(self, kind: str, name: str = "", arguments: dict[str, Any] | None = None) -> Any:
        future: Future[Any] = Future()
        self.queue.put((kind, name, arguments or {}, dict(self.meta), future))
        return future.result(180)

    def tools(self) -> list[Any]:
        return self._request("tools").tools

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        return self._request("call", name, arguments)

    def payload(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.call(name, arguments)
        if result.isError or not isinstance(result.structuredContent, dict):
            raise OperationsAcceptanceRefusal("original_sdk_outcome_unavailable")
        return result.structuredContent

    def __exit__(self, *_: Any) -> None:
        self.queue.put(None)
        self.thread.join(15)
        if self.thread.is_alive() or self.failure is not None:
            raise OperationsAcceptanceRefusal("external_sdk_shutdown_unconfirmed")


class OperationsJourney:
    """Real orchestration. Tests may substitute only its external effect ports."""
    def __init__(self, native: NativeChannel, directory: Path, *, client: Any = None,
                 sdk: Any = OfficialClient, browser: Any = None) -> None:
        self.native, self.directory, self.sdk_factory, self.browser = native, directory, sdk, browser
        self.channel = native.channel
        api_port, ui_port = ((18001, 8111) if self.channel == "dev" else (18002, 8112))
        self.api_url, self.ui_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{ui_port}"
        self.http = client or httpx.Client(base_url=self.api_url, timeout=180, follow_redirects=False)
        self.observations: dict[str, dict[str, Any]] = {}
        self.bearer = ""
        self.expired_bearer = ""
        self.expired_selection: dict[str, Any] = {}
        self.binding: dict[str, Any] = {}
        self.outcomes: dict[str, dict[str, Any]] = {}
        self.retained = False
        self.readonly_recovery = False

    def _record(self, name: str, proof: dict[str, Any], *, status: str = "passed") -> None:
        if name not in inventory(self.channel) or name in self.observations:
            raise OperationsAcceptanceRefusal("original_inventory_duplicate_or_unknown")
        # Carriers live only in client memory. No request headers, cookies,
        # SDK metadata or selection-creation body are evidence artifacts.
        raw = json.dumps(proof, sort_keys=True)
        if self.bearer and self.bearer in raw:
            raise OperationsAcceptanceRefusal("carrier_in_evidence")
        path = self.directory / (name + ".json")
        write_private(path, proof, create=True)
        self.observations[name] = {"id": name, "status": status, "producer": "original_observer",
            "binding_sha256": digest(self.binding), "proof": proof, "observed_at": time(),
            "artifacts": {path.name: file_hash(path)}}
        write_private(self.directory / (name + ".observation.json"), self.observations[name], create=True)

    def observe(self) -> dict[str, Any]:
        observed = self.native.observe()
        if self.binding and observed["binding"] != self.binding:
            raise OperationsAcceptanceRefusal("native_binding_changed")
        return observed

    def request(self, method: str, path: str, *, payload: dict[str, Any] | None = None,
                headers: dict[str, str] | None = None) -> Any:
        if self.readonly_recovery and method != "GET":
            raise OperationsAcceptanceRefusal("restart_recovery_is_observation_only")
        self.observe()
        response = self.http.request(method, path, json=payload,
            headers=headers if headers is not None else {"X-Active-Context-Session": self.bearer})
        return response

    def admit(self, *, test_receipt: dict[str, Any] | None = None) -> None:
        initial = self.native.admit()
        require_identity(initial["identity"], channel=self.channel)
        if initial.get("selection") is not None:
            self.binding = initial
            self.retained = True
            return
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        initial_probe = self.native.observe()
        if initial_probe["binding"] != initial:
            raise OperationsAcceptanceRefusal("original_native_admission_changed")
        for probe in ("native_doctor", "native_invariants", "source_store_index_links"):
            if initial_probe.get(probe, {}).get("status") != "healthy" or initial_probe[probe].get("checked") is not True:
                raise OperationsAcceptanceRefusal("native_preflight_probe_unavailable")
        if self.channel == "dev":
            prior = (test_receipt or {}).get("binding", {}).get("identity", {})
            expected_status = "PASS" if initial["identity"]["execution_kind"] == "deployed" else "PREMERGE_PASS"
            if ((test_receipt or {}).get("status") != expected_status or prior.get("channel") != "test"
                or any(prior.get(key) != initial["identity"][key] for key in
                       ("source_sha", "image_digest", "resource_tree", "resource_hashes", "producer_hashes", "sidecar", "execution_kind"))):
                raise OperationsAcceptanceRefusal("same_candidate_test_receipt_required")
        if self.channel == "test":
            # Exercise a genuinely expired native selection without changing
            # the server clock, TTL or authority. This bounded read-only wait
            # precedes freezing the fresh effect selection and source versions.
            old = self.http.post("/api/companion/active-context/selection",
                                 json={"vault_binding_ids": [initial["binding_id"]]})
            if old.status_code != 201:
                raise OperationsAcceptanceRefusal("expiry_selection_producer_refused")
            old_selection = old.json()
            expires = old_selection["context"]["expires_at"]
            if not time() < expires < time() + MAX_SECONDS / 2 + 5:
                raise OperationsAcceptanceRefusal("native_selection_ttl_outside_fixed_budget")
            while time() <= expires:
                sleep(min(30, max(0.01, expires - time() + 0.01)))
            self.expired_bearer = old_selection["context_selection_id"]
            self.expired_selection = {"expires_at": expires, "observed_at": time()}
        self.native.observe()
        selection = self.http.post("/api/companion/active-context/selection",
                                   json={"vault_binding_ids": [initial["binding_id"]]})
        if selection.status_code != 201:
            raise OperationsAcceptanceRefusal("native_selection_producer_refused")
        issued = selection.json()
        selected = issued["context"]
        if (selected["principal_id"] != initial["principal_id"] or selected["instance_identity"] != initial["instance_identity"]
            or selected["vault_binding_ids"] != [initial["binding_id"]]):
            raise OperationsAcceptanceRefusal("actual_native_selection_mismatch")
        self.bearer = issued["context_selection_id"]
        frozen = self.http.post("/api/operations/acceptance/admission", json={},
                                headers={"X-Active-Context-Session": self.bearer})
        if frozen.status_code != 200:
            raise OperationsAcceptanceRefusal("native_operations_freeze_refused")
        self.binding = frozen.json()
        require_identity(self.binding["identity"], channel=self.channel)
        if (self.binding["identity"] != initial["identity"] or self.binding["fixture_sha256"] != initial["fixture_sha256"]
            or not self.binding.get("slots") or not self.binding.get("selection")):
            raise OperationsAcceptanceRefusal("native_frozen_inventory_incomplete")
        self.observe()
        self._record("native_admission", {"native": self.binding, "preflight": initial_probe})

    def command(self, slot_id: str, *, suffix: str = "") -> dict[str, Any]:
        slot = next(slot for slot in self.binding["slots"] if slot["id"] == slot_id)
        selected = self.binding["selection"]
        return {**slot["intent"], "request_id": "acceptance:" + self.native.operation_id + ":" + slot_id + suffix,
            "active_context_ref": selected["context_id"], "vault_generation": str(selected["generation"]),
            "target_binding_id": self.binding["binding_id"]}

    def read_command(self, operation_id: str, *, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        selected = self.binding["selection"]
        return {"operation_id": operation_id, "request_id": "acceptance-read:" + operation_id,
            "active_context_ref": selected["context_id"], "vault_generation": str(selected["generation"]),
            "target_binding_id": self.binding["binding_id"], "arguments": arguments or {},
            "targets": [{"artifact_id": self.binding["source_inventory"]["read"]["artifact_id"]}]
                       if operation_id in {"artifact.read", "artifact.related"} else []}

    def parity(self, client: Any, command: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        if result.get("status") not in {"succeeded", "convergence_pending"} or result.get("receipt", {}).get("status") != "committed":
            raise OperationsAcceptanceRefusal("successful_native_operation_receipt_missing")
        reference = {"request_id": command["request_id"]}
        sdk = client.payload("mimer.v2.operation.receipt", reference)
        http = self.request("GET", "/api/operations/receipts/" + quote(command["request_id"], safe="")).json()
        native = self.observe()["receipts"].get(command["request_id"])
        if sdk != result or http != result or native != result:
            raise OperationsAcceptanceRefusal("original_native_receipt_parity_failed")
        self.outcomes[command["request_id"]] = result
        return {"sdk": sdk, "http": http, "native": native}

    def profiles_and_operations(self) -> None:
        python = self.binding["identity"]["sidecar"]["runtime"]["executable"]
        with self.sdk_factory(self.api_url, self.bearer, python, profile="v1") as v1:
            tools = v1.tools()
            if tuple(tool.name for tool in tools) != V1_TOOLS:
                raise OperationsAcceptanceRefusal("v1_profile_changed")
            v1_descriptors = [tool.model_dump(exclude_none=True) for tool in tools]
            if v1_descriptors != self.binding["identity"]["sidecar"]["v1_contract"]:
                raise OperationsAcceptanceRefusal("v1_descriptor_contract_changed")
            health = v1.call("mimer.health")
            if health.isError:
                raise OperationsAcceptanceRefusal("v1_native_health_unavailable")
            v1_health = json.loads(health.content[0].text)
            if not v1.call("mimer.v2.operation.receipt", {"request_id": "excluded"}).isError:
                raise OperationsAcceptanceRefusal("v1_receipt_exclusion_changed")
        with self.sdk_factory(self.api_url, self.bearer, python) as v2:
            discovery = v2.payload("mimer.v2.operation.discovery")
            capabilities = {row["resource_id"]: row["payload"] for row in discovery["items"]}
            tools = {tool.name: tool for tool in v2.tools()}
            for kind, capability in capabilities.items():
                if kind in {"operation.discovery", "operation.batch"}:
                    continue
                if capability["support"] == "supported":
                    tool = tools.get("mimer.v2." + kind)
                    if (tool is None or tool.inputSchema != capability["input_schema"]
                        or tool.outputSchema != capability["output_schema"]
                        or any(tool.meta[key] != capability[key] for key in
                               ("operation_version", "authority_class", "side_effect_class", "preview_support", "maturity"))):
                        raise OperationsAcceptanceRefusal("runtime_derived_schema_mismatch")
                elif "mimer.v2." + kind in tools:
                    raise OperationsAcceptanceRefusal("unsupported_family_advertised_as_executable")
            self._record("sdk_profiles", {"v1": v1_descriptors, "v1_health": v1_health, "v2": discovery,
                "tools": [tool.model_dump(exclude_none=True) for tool in tools.values()]})
            families = {}
            for kind in FAMILIES:
                cap = capabilities[kind]
                if kind in {"artifact.list", "artifact.read", "artifact.search", "artifact.related"}:
                    command = self.read_command(kind, arguments={"query": "Synthetic operations acceptance"} if kind == "artifact.search" else {})
                    result = v2.payload("mimer.v2." + kind, command)
                    if result["status"] != "succeeded":
                        raise OperationsAcceptanceRefusal("qualified_read_not_successful")
                    families[kind] = {"support": "supported", "status": "succeeded", "outcome": result}
                elif cap["support"] != "supported":
                    response = self.request("POST", "/api/operations", payload=self.read_command(kind))
                    if response.status_code != 200 or response.json()["status"] != "not_supported" or not cap.get("reason"):
                        raise OperationsAcceptanceRefusal("unsupported_disposition_not_native")
                    families[kind] = {"support": cap["support"], "status": "not_supported", "native_reason": cap["reason"],
                                      "outcome": response.json()}
            if self.channel == "dev":
                self._record("qualified_reads", {"families": families})
                command = self.command("dev-smoke")
                self.observe()
                result = v2.payload("mimer.v2.artifact.update", command)
                self._record("dev_operation_receipt", self.parity(v2, command, result))
                return
            receipts = {}
            for slot_id in ("capture", "edit", "move", "rename", "archive", "restore"):
                command = self.command(slot_id)
                self.observe()
                result = v2.payload("mimer.v2." + command["operation_id"], command)
                receipts[slot_id] = self.parity(v2, command, result)
                families[command["operation_id"]] = {"support": "supported", "status": "succeeded", "outcome": result}
            if set(families) != set(FAMILIES):
                raise OperationsAcceptanceRefusal("supported_family_missing_qualified_fixture_or_journey")
            self._record("qualified_families", {"families": families})
            self._record("operation_receipt_parity", {"receipts": receipts})

    def finish(self, *, started_at: float, test_receipt: dict[str, Any] | None = None) -> dict[str, Any]:
        probe = self.observe()
        for name in ("native_doctor", "native_invariants", "source_store_index_links"):
            self._record(name, probe[name], status="passed" if probe[name].get("status") == "healthy" else "blocked")
        for name in inventory(self.channel):
            if name not in self.observations:
                self._record(name, {"reason": "required_observation_unavailable", "owner": "native-operations-acceptance"}, status="blocked")
        observations = [self.observations[name] for name in inventory(self.channel)]
        try:
            result = produce_receipt(self.binding, observations, self.directory,
                started_at=started_at, finished_at=time(), test_receipt=test_receipt)
        except OperationsAcceptanceRefusal as exc:
            result = {"schema": "yggdrasil-autonomous-operations-acceptance.v1", "status": "BLOCKED",
                "execution_kind": self.binding["identity"]["execution_kind"], "binding": self.binding,
                "required_scenarios": list(inventory(self.channel)), "observations": observations,
                "reason": exc.reason, "started_at": started_at, "finished_at": time()}
        write_private(self.directory / "receipt.json", result, create=True)
        return result

    def run(self, *, test_receipt_path: Path | None = None) -> dict[str, Any]:
        started = time()
        try:
            test_receipt = read_original_test_receipt(test_receipt_path) if test_receipt_path is not None else None
            self.admit(test_receipt=test_receipt)
            if self.retained:
                return self.recover_retained(test_receipt=test_receipt)
            self.profiles_and_operations()
            if self.channel == "test":
                if self.browser is None:
                    from tests.companion_ui.live_operations_acceptance import browser_journeys
                    self.browser = browser_journeys
                self.browser(self)
                self.recovery_and_refusals()
            if time() > started + MAX_SECONDS:
                raise OperationsAcceptanceRefusal("fixed_run_deadline_exceeded")
            return self.finish(started_at=started, test_receipt=test_receipt)
        finally:
            # Do not clear/recreate a selection or delete native context on an
            # ambiguous outcome. Original native recovery owns that state.
            self.http.close()

    def recover_retained(self, *, test_receipt: dict[str, Any] | None = None) -> dict[str, Any]:
        """Read original private observations and native receipts; zero replay."""
        probe = self.observe()
        receipt_path = self.directory / "receipt.json"
        rows = []
        for name in inventory(self.channel):
            path = self.directory / (name + ".observation.json")
            if path.exists():
                row = read_private(path)
                if row.get("id") != name or row.get("binding_sha256") != digest(self.binding):
                    raise OperationsAcceptanceRefusal("foreign_retained_observation")
                rows.append(row)
        if receipt_path.exists():
            original = read_private(receipt_path)
            if original.get("binding") != self.binding:
                raise OperationsAcceptanceRefusal("foreign_original_receipt")
            if original.get("status") in {"PASS", "PREMERGE_PASS"}:
                verified = produce_receipt(self.binding, rows, self.directory,
                    started_at=original["started_at"], finished_at=original["finished_at"], test_receipt=test_receipt)
                if verified != original:
                    raise OperationsAcceptanceRefusal("original_receipt_changed")
            return original
        result = {"schema": "yggdrasil-autonomous-operations-acceptance.v1", "status": "BLOCKED",
            "execution_kind": self.binding["identity"]["execution_kind"], "binding": self.binding,
            "reason": "interrupted_original_inventory_requires_reconciliation_without_replay",
            "required_scenarios": list(inventory(self.channel)), "observations": rows,
            "original_native_receipt_hashes": {key: digest(value) for key, value in probe["receipts"].items()},
            "source_replays": 0}
        write_private(receipt_path, result, create=True)
        return result

    def recovery_and_refusals(self) -> None:
        # Fixed methods are below so the assembled caller has no configurable
        # profile, command, scenario list or Product provider implementation.
        from tests.operations.operations_acceptance_recovery import run_recovery_and_refusals
        run_recovery_and_refusals(self)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("channel", choices=("test", "dev"))
    parser.add_argument("operation_id")
    parser.add_argument("--test-receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        if Path(sys.executable).resolve() != SDK_PYTHON.resolve():
            raise OperationsAcceptanceRefusal("qualified_external_runtime_required")
        if (args.channel == "dev") != (args.test_receipt is not None):
            raise OperationsAcceptanceRefusal("dev_requires_original_test_receipt")
        native = NativeChannel(args.channel, args.operation_id)
        directory = EVIDENCE_DIRECTORY
        directory.mkdir(mode=0o700, exist_ok=True)
        result = OperationsJourney(native, directory / (args.channel + "-" + args.operation_id)).run(test_receipt_path=args.test_receipt)
        print(json.dumps({"schema": result["schema"], "status": result["status"],
                          "channel": args.channel, "operation_id": args.operation_id,
                          "receipt_sha256": digest(result)}))
        return 0 if result["status"] == "PASS" else 1
    except Exception as exc:
        reason = exc.reason if isinstance(exc, OperationsAcceptanceRefusal) else "native_prerequisite_unavailable"
        print(json.dumps({"status": "BLOCKED", "reason": reason, "action": "restore-environment"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
