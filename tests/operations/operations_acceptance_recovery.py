"""Fixed refusal/recovery corpus; Product remains the execution authority."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

import httpx

from app.ops.operations_acceptance import OperationsAcceptanceRefusal, digest


def _batch(journey, roles, identity):
    commands = [journey.command(role, suffix=":" + identity) for role in roles]
    first = commands[0]
    return {"batch_id": "acceptance:" + journey.native.operation_id + ":" + identity,
        "operation_id": "artifact.update", "active_context_ref": first["active_context_ref"],
        "vault_generation": first["vault_generation"], "target_binding_id": first["target_binding_id"],
        "limit": len(commands), "partial_success_policy": "independent",
        "items": [{"request_id": row["request_id"], "artifact_id": row["targets"][0]["artifact_id"],
                   "arguments": row["arguments"], "expected_version": row["expected_version"]} for row in commands]}


@contextmanager
def drop_one_acknowledgement(upstream, expected_command):
    observed = {"post_count": 0, "original_response": None}
    with httpx.Client(base_url=upstream, timeout=60, follow_redirects=False, trust_env=False) as client:
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _forward(self):
                payload = self.rfile.read(int(self.headers.get("content-length", "0"))) if self.command == "POST" else None
                headers = {name: value for name, value in self.headers.items()
                    if name.lower() in {"content-type", "x-active-context-session", "x-active-context-override"}}
                if self.command == "POST":
                    if self.path != "/api/operations" or json.loads(payload) != expected_command or observed["post_count"]:
                        self.send_error(409)
                        return
                    observed["post_count"] += 1
                response = client.request(self.command, self.path, content=payload, headers=headers)
                if self.command == "POST":
                    observed["original_response"] = response.json()
                    self.close_connection = True
                    return
                self.send_response(response.status_code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(response.content)

            do_GET = _forward
            do_POST = _forward

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", observed
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)


def run_recovery_and_refusals(journey):
    original = journey.observe()
    source_hashes = {key: row["source_sha256"] for key, row in original["sources"].items()}
    native = journey.request("GET", "/api/operations/acceptance/authority-probe")
    if native.status_code != 200:
        raise OperationsAcceptanceRefusal("native_authority_refusal_probe_unavailable")
    cases = dict(native.json()["cases"])
    command = journey.command("lost-ack")
    for name, headers in (
        ("missing", {}), ("unknown", {"X-Active-Context-Session": "unissued-acceptance-selection"}),
        ("expired", {"X-Active-Context-Session": journey.expired_bearer}),
        ("read_only_snapshot", {"X-Active-Context-Session": command["active_context_ref"]}),
        ("empty_override", {"X-Active-Context-Session": journey.bearer, "X-Active-Context-Override": ""}),
        ("stale_override", {"X-Active-Context-Session": journey.bearer, "X-Active-Context-Override": "unissued-override"}),
        ("forged_identity_headers", {"X-Active-Context-Session": "unissued-acceptance-selection", "Principal": "forged",
             "X-API-Key": "unissued-acceptance-key", "X-Forwarded-For": "203.0.113.7"}),
    ):
        response = journey.request("POST", "/api/operations", payload=command, headers=headers)
        if response.status_code not in {401, 403}:
            raise OperationsAcceptanceRefusal("unauthorized_effect_not_refused")
        cases[name] = {"status": "refused", "http_status": response.status_code}
    if not journey.expired_bearer or not journey.expired_selection:
        raise OperationsAcceptanceRefusal("actual_expired_selection_not_observed")
    cases["expired"].update(journey.expired_selection)
    scratch = journey.http.post("/api/companion/active-context/selection",
                               json={"vault_binding_ids": [journey.binding["binding_id"]]}).json()
    scratch_header = {"X-Active-Context-Session": scratch["context_selection_id"]}
    replaced = journey.http.put("/api/companion/active-context/selection", headers=scratch_header,
                               json={"vault_binding_ids": [journey.binding["binding_id"]]})
    stale = dict(command, active_context_ref=scratch["context"]["context_id"],
                 vault_generation=str(scratch["context"]["generation"]))
    response = journey.request("POST", "/api/operations", payload=stale, headers=scratch_header)
    if replaced.status_code != 200 or response.status_code != 200 or response.json()["status"] != "conflicted":
        raise OperationsAcceptanceRefusal("replaced_selection_not_refused")
    cases["replaced"] = {"status": "refused", "outcome": response.json()}
    forged = {**command, "arguments": {**command["arguments"], "delegation": {"authority_class": "governed_effect"}}}
    response = journey.request("POST", "/api/operations", payload=forged)
    if response.status_code == 200 and response.json().get("status") in {"succeeded", "convergence_pending"}:
        raise OperationsAcceptanceRefusal("forged_delegation_enlarged_authority")
    cases["forged_delegation"] = {"status": "refused", "http_status": response.status_code}
    python = journey.binding["identity"]["sidecar"]["runtime"]["executable"]
    with journey.sdk_factory(journey.api_url, journey.bearer, python) as client:
        derived = client.payload("mimer.v2.operation.discovery")
        client.meta = {}
        if not client.call("mimer.v2.operation.discovery").isError:
            raise OperationsAcceptanceRefusal("request_metadata_reused")
        cases["no_metadata_followup"] = {"status": "refused", "preceding_host_context": derived["context"]}
    after = journey.observe()
    if source_hashes != {key: row["source_sha256"] for key, row in after["sources"].items()}:
        raise OperationsAcceptanceRefusal("authority_refusal_changed_source")
    journey._record("authority_refusals", {"cases": cases, "native": native.json(), "source_hashes": source_hashes,
                                           "after_source_hashes": source_hashes})

    refusals = {}
    for name, destination in (("traversal", "../../outside.md"), ("absolute", "/outside.md"),
                              ("protected", "settings/vault.md"), ("collision", journey.binding["source_inventory"]["collision"]["path"])):
        malicious = journey.command("move", suffix=":" + name)
        malicious.pop("expected_version")
        malicious["arguments"] = {"destination": destination}
        response = journey.request("POST", "/api/operations/preconditions", payload=malicious)
        if response.status_code not in {409, 422}:
            raise OperationsAcceptanceRefusal("hostile_or_colliding_path_not_refused")
        refusals[name] = {"http_status": response.status_code}
    stale = journey.command("edit", suffix=":stale")
    response = journey.request("POST", "/api/operations", payload=stale)
    if response.status_code != 200 or response.json()["status"] != "conflicted":
        raise OperationsAcceptanceRefusal("stale_cas_not_refused")
    refusals["stale_cas"] = response.json()
    journey._record("hostile_collision_cas", {"cases": refusals, "source_hashes": source_hashes,
        "after_source_hashes": {key: row["source_sha256"] for key, row in journey.observe()["sources"].items()}})

    successful_preview = journey.request("POST", "/api/operations/batches/preview", payload=_batch(journey, ("batch-a", "batch-b"), "complete")).json()
    successful_reference = {"batch_id": successful_preview["batch_id"], "expected_digest": successful_preview["digest"]}
    with journey.sdk_factory(journey.api_url, journey.bearer, python) as client:
        successful = client.payload("mimer.v2.batch.execute", successful_reference)
        if successful.get("counts", {}).get("completed") != 2:
            raise OperationsAcceptanceRefusal("sdk_successful_batch_not_complete")
        successful_parity = {item["request_id"]: journey.parity(client, {"request_id": item["request_id"]}, item["outcome"])
                             for item in successful["items"]}

    preview_command = _batch(journey, ("partial-a", "partial-b"), "partial")
    preview = journey.request("POST", "/api/operations/batches/preview", payload=preview_command).json()
    if preview.get("status") != "pending" or preview.get("cardinality") != 2:
        raise OperationsAcceptanceRefusal("finite_native_batch_preview_failed")
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda index: journey.request("POST", "/api/operations",
            payload=journey.command("partial-b", suffix=":race" + str(index))).json(), (0, 1)))
    if sum(row.get("convergence", {}).get("source_effect") == "committed" for row in results) != 1:
        raise OperationsAcceptanceRefusal("concurrent_effect_count_not_one")
    journey._record("concurrent_refusal", {"outcomes": results, "committed_count": 1})
    reference = {"batch_id": preview["batch_id"], "expected_digest": preview["digest"]}
    with journey.sdk_factory(journey.api_url, journey.bearer, python) as client:
        partial = client.payload("mimer.v2.batch.execute", reference)
        retained = client.payload("mimer.v2.batch.inspect", reference)
        cancelled = client.payload("mimer.v2.batch.cancel", reference)
    if (partial.get("status") != "partial" or partial.get("counts", {}).get("completed") != 1
        or [row.get("outcome") for row in retained["items"]] != [row.get("outcome") for row in partial["items"]]
        or [row.get("outcome") for row in cancelled["items"]] != [row.get("outcome") for row in partial["items"]]):
        raise OperationsAcceptanceRefusal("partial_cancel_changed_original_receipts")
    journey._record("partial_batch", {"preview": preview, "partial": partial, "retained": retained, "cancelled": cancelled,
                                      "successful_batch": successful, "successful_parity": successful_parity})

    command = journey.command("lost-ack")
    before = journey.observe()["sources"]["lost-ack"]["source_sha256"]
    with drop_one_acknowledgement(journey.api_url, command) as (proxy_url, dropped):
        with journey.sdk_factory(proxy_url, journey.bearer, python) as client:
            result = client.call("mimer.v2.artifact.update", command)
            if not result.isError:
                raise OperationsAcceptanceRefusal("acknowledgement_was_not_dropped")
    # A completely new MCP client reads the old original receipt. No source
    # command is retried, even if the adapter could not observe its outcome.
    with journey.sdk_factory(journey.api_url, journey.bearer, python) as restarted:
        receipt = restarted.payload("mimer.v2.operation.receipt", {"request_id": command["request_id"]})
        parity = journey.parity(restarted, command, receipt)
    after = journey.observe()["sources"]["lost-ack"]["source_sha256"]
    if dropped["post_count"] != 1 or dropped["original_response"] != receipt or before == after:
        raise OperationsAcceptanceRefusal("lost_ack_original_effect_not_preserved")
    proof = {"original": receipt, "parity": parity, "source_posts": dropped["post_count"],
             "source_replays": 0, "pre_sha256": before, "post_sha256": after}
    journey._record("dropped_acknowledgement", proof)
    journey._record("client_restart", proof)
    lag = journey.observe()
    pending = [row for row in lag["sources"].values() if not row["store_index_match"] or not row["source_store_match"]]
    journey._record("projection_lag", {"source_receipt": receipt, "separate_projections": lag["sources"],
        "lagged_count": len(pending)}, status="passed" if pending else "blocked")
    # There is no restart/deployment authority in this automation. The
    # separately owned native restart must supply its actual observation;
    # restarting this SDK client is never substituted for that scenario.
    before_restart = journey.observe()
    observer = getattr(journey.native, "observe_restart", None)
    restart = observer() if observer is not None else {"status": "blocked", "separate_native_authority": False,
        "reason": "separately_authorized_native_backend_wsp_restart_required"}
    if restart.get("status") != "observed" or restart.get("separate_native_authority") is not True:
        journey._record("backend_wsp_restart", {**restart, "owner": "Platform and Operations native channel owner",
            "original_receipt_hashes": {key: digest(value) for key, value in before_restart["receipts"].items()}}, status="blocked")
        return
    journey.readonly_recovery = True
    old = journey.http.get("/api/operations/capabilities", headers={"X-Active-Context-Session": journey.bearer})
    if old.status_code != 401:
        raise OperationsAcceptanceRefusal("pre_restart_selection_still_resolved")
    issued = journey.http.post("/api/companion/active-context/selection",
                              json={"vault_binding_ids": [journey.binding["binding_id"]]})
    if issued.status_code != 201 or issued.json()["context"]["principal_id"] != journey.binding["principal_id"]:
        raise OperationsAcceptanceRefusal("native_recovery_read_selection_refused")
    journey.bearer = issued.json()["context_selection_id"]
    current = journey.request("GET", "/api/operations/acceptance/recovery")
    if (current.status_code != 200 or current.json()["current_wsp_epoch"] == current.json()["original_wsp_epoch"]
        or current.json()["original_wsp_epoch"] != journey.binding["api_process_epoch"]):
        raise OperationsAcceptanceRefusal("actual_native_wsp_restart_not_observed")
    with journey.sdk_factory(journey.api_url, journey.bearer, python) as recovered:
        for request_id, original_receipt in before_restart["receipts"].items():
            if recovered.payload("mimer.v2.operation.receipt", {"request_id": request_id}) != original_receipt:
                raise OperationsAcceptanceRefusal("restart_changed_original_native_receipt")
    after_restart = journey.observe()
    if ({key: (row["artifact_id"], row["path"], row["source_sha256"]) for key, row in before_restart["sources"].items()}
        != {key: (row["artifact_id"], row["path"], row["source_sha256"]) for key, row in after_restart["sources"].items()}
        or before_restart["receipts"] != after_restart["receipts"]):
        raise OperationsAcceptanceRefusal("restart_replayed_or_changed_original_effect")
    journey._record("backend_wsp_restart", {**restart, "wsp": current.json(), "old_selection_http_status": old.status_code,
        "original_receipt_hashes": {key: digest(value) for key, value in before_restart["receipts"].items()},
        "retained_receipt_hashes": {key: digest(value) for key, value in after_restart["receipts"].items()}, "source_replays": 0})
