"""Actual served Companion controls, with only client-local response faults."""
from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path
from time import monotonic
from urllib.parse import parse_qs, urlparse

from app.ops.operations_acceptance import OperationsAcceptanceRefusal, file_hash, write_private
from app.operations.contracts import OperationStatus, ReceiptStatus, SourceEffectStatus


def browser_journeys(journey):
    from playwright.sync_api import sync_playwright
    rows = []
    errors = []
    external = []
    started = monotonic()
    primary_error = None
    with sync_playwright() as playwright:
        admitted_browser = journey.binding["identity"]["sidecar"].get("browser")
        executable = Path(admitted_browser["executable"] if admitted_browser else playwright.chromium.executable_path)
        observed_browser = {"playwright": importlib.metadata.version("playwright"), "executable": str(executable),
                            "executable_sha256": file_hash(executable, max_bytes=1024 ** 3)}
        if admitted_browser is not None and admitted_browser != observed_browser:
            raise OperationsAcceptanceRefusal("actual_browser_resource_changed")
        browser = playwright.chromium.launch(**({"executable_path": str(executable)} if admitted_browser else {}))
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.add_cookies([{"name": "companion_context_session", "value": journey.bearer,
            "url": journey.ui_url, "httpOnly": True, "sameSite": "Strict"}])
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))

        def guard(route):
            url = urlparse(route.request.url)
            if not route.request.url.startswith(journey.ui_url + "/"):
                external.append(url.scheme + "://" + str(url.netloc) + url.path)
                route.abort()
                return
            if url.path.startswith("/api/operations"):
                journey.observe()
            route.continue_()

        def observe_response(response):
            path = urlparse(response.url).path
            if path.startswith("/api/operations"):
                try:
                    body = response.json()
                except Exception as response_error:
                    reason = "original_response_body_unavailable:" + type(response_error).__name__
                    errors.append(reason)
                    body = {"observation_error": reason}
                rows.append({"method": response.request.method, "path": path,
                    "request": response.request.post_data_json if response.request.method == "POST" else None,
                    "http_status": response.status, "response": body,
                    "observed_after_seconds": monotonic() - started})

        def retain_original(path, trace):
            if journey.bearer in json.dumps(trace):
                raise OperationsAcceptanceRefusal("browser_trace_contains_selection_carrier")
            write_private(path, trace, create=True)
            # This repository is public. Only finite typed facts and the
            # private original's hash may leave the runner, never native
            # envelopes, request bodies/identities, paths or carrier material.
            allowed = {str(value) for value in OperationStatus} | {
                "observed", "pending", "partial", "not_completed", "cancelled"}
            summaries = []
            for row in trace["responses"]:
                body = row["response"]
                body = body if isinstance(body, dict) else {}
                receipt = body.get("receipt")
                convergence = body.get("convergence")
                receipt = receipt if isinstance(receipt, dict) else {}
                convergence = convergence if isinstance(convergence, dict) else {}
                status = body.get("status")
                receipt_status = receipt.get("status")
                effect = convergence.get("source_effect")
                summaries.append({"http_status": row["http_status"],
                    "native_status": status if isinstance(status, str) and status in allowed else None,
                    "receipt_present": body.get("receipt") is not None,
                    "receipt_status": receipt_status if isinstance(receipt_status, str)
                        and receipt_status in {str(value) for value in ReceiptStatus} else None,
                    "source_effect": effect if isinstance(effect, str)
                        and effect in {str(value) for value in SourceEffectStatus} else None,
                    "observed_after_seconds": row["observed_after_seconds"]})
            write_private(path.with_suffix(".public.json"), {
                "kind": "finite_browser_status_summary", "original_sha256": file_hash(path),
                "responses": summaries, "visible_runtime_statuses": trace.get("visible_runtime_statuses", []),
                "complete_original_evidence": False,
            }, create=True)

        page.route("**/*", guard)
        page.on("response", observe_response)

        def open_operations(selection=True):
            page.get_by_test_id("operations-open").click()
            if selection:
                page.locator('#operations-kind option[value="artifact.update"]:enabled').wait_for(state="attached")
                page.locator('#operations-resources input[type=checkbox]:enabled').first.wait_for()

        def choose(roles):
            for check in page.locator('#operations-resources input[type=checkbox]:checked').all():
                check.uncheck()
            for role in roles:
                identity = journey.binding["source_inventory"][role]["artifact_id"]
                page.locator(f'#operations-resources input[data-resource-id="{identity}"]').check()
            page.locator("#operations-kind").select_option("artifact.update")
            for role in roles:
                identity = journey.binding["source_inventory"][role]["artifact_id"]
                page.locator(f'[data-argument="body"][data-resource="{identity}"]').fill("Synthetic operations result " + role + ".\n")
            page.locator("#operations-preview").click()
            page.locator("#operations-confirm:enabled").wait_for()

        def reset():
            page.goto(journey.ui_url + "/", wait_until="domcontentloaded")
            open_operations()
            # Existing URL recovery may have been restored. Starting a new
            # intent uses its served control, never edits browser state.
            if page.locator("#operations-new").is_visible():
                page.locator("#operations-new").click()

        try:
            journey.observe()
            page.goto(journey.ui_url + "/", wait_until="domcontentloaded")
            open_operations()
            journey._record("browser_discovery", {"observed": list(rows), "selected_binding": page.locator("#operations-binding").input_value()})
            choose(["browser"])
            journey._record("browser_selected_preflight", {"observed": list(rows), "scope": page.locator("#operations-scope").text_content()})
            page.locator("#operations-confirm").dblclick()
            page.get_by_text("Source effect: committed", exact=False).wait_for()
            writes = [row for row in rows if row["method"] == "POST" and row["path"] == "/api/operations"
                      and row["request"]["operation_id"] == "artifact.update"]
            if len(writes) != 1:
                raise OperationsAcceptanceRefusal("browser_confirmation_replayed")
            original = writes[0]
            python = journey.binding["identity"]["sidecar"]["runtime"]["executable"]
            with journey.sdk_factory(journey.api_url, journey.bearer, python) as sdk:
                parity = journey.parity(sdk, original["request"], original["response"])
            page.reload(wait_until="domcontentloaded")
            open_operations(selection=False)
            page.get_by_text("Source effect: committed", exact=False).wait_for()
            if len([row for row in rows if row["method"] == "POST" and row["path"] == "/api/operations"
                    and row["request"]["operation_id"] == "artifact.update"]) != 1:
                raise OperationsAcceptanceRefusal("browser_restart_replayed")
            journey._record("browser_receipt_recovery", {"parity": parity, "observed": list(rows), "source_replays": 0})

            reset()
            choose(["browser-a", "browser-b"])
            scope = page.locator("#operations-scope").text_content()
            if "Cardinality: 2" not in scope or "Maximum count: 2" not in scope:
                raise OperationsAcceptanceRefusal("browser_finite_confirmation_missing")
            page.locator("#operations-confirm").click()
            page.get_by_text("Runtime status: convergence_pending", exact=True).wait_for()
            completed_batches = [row["response"] for row in rows if row["path"].endswith("/execute")
                                 and row["response"].get("counts", {}).get("completed") == 2]
            if not completed_batches:
                raise OperationsAcceptanceRefusal("browser_original_completed_batch_missing")
            batch_parity = {}
            with journey.sdk_factory(journey.api_url, journey.bearer, python) as sdk:
                for item in completed_batches[-1]["items"]:
                    batch_parity[item["request_id"]] = journey.parity(sdk, {"request_id": item["request_id"]}, item["outcome"])
            journey._record("browser_confirmation_progress", {"scope": scope,
                "progress": page.locator("#operations-progress").text_content(), "observed": list(rows), "native_parity": batch_parity})

            reset()
            # Preview uses existing finite admission too. Cancel two allowed,
            # still-unconsumed intents; later SDK recovery uses these slots.
            choose(["partial-a", "lost-ack"])
            before_cancel = journey.observe()

            def delay_only_client_submission(route):
                values = parse_qs(urlparse(page.url).query)
                identity, expected = values["operation_request"][0], values["operation_digest"][0]
                # Return the exact original native pending read, without ever
                # forwarding this client submission. Cancellation then uses
                # the ordinary served cancel control and native API.
                response = journey.request("GET", "/api/operations/batches/" + identity + "?expected_digest=" + expected)
                route.fulfill(status=response.status_code, json=response.json())

            page.route("**/api/operations/batches/*/execute", delay_only_client_submission)
            page.locator("#operations-confirm").click()
            page.locator("#operations-cancel:visible").wait_for()
            page.locator("#operations-cancel").click()
            page.get_by_text("Runtime status: cancelled", exact=True).wait_for()
            after_cancel = journey.observe()
            if (before_cancel["receipts"] != after_cancel["receipts"]
                or {role: before_cancel["sources"][role]["source_sha256"] for role in ("partial-a", "lost-ack")}
                != {role: after_cancel["sources"][role]["source_sha256"] for role in ("partial-a", "lost-ack")}):
                raise OperationsAcceptanceRefusal("browser_cancel_consumed_or_changed_source")
            journey._record("browser_cancel", {"observed": list(rows), "progress": page.locator("#operations-progress").text_content(),
                "source_replays": 0, "native_receipts_unchanged": True})
            page.unroute("**/api/operations/batches/*/execute", delay_only_client_submission)

            reset()
            choose(["concurrent"])
            command = journey.command("concurrent")
            changed = journey.request("POST", "/api/operations", payload=command)
            if changed.status_code != 200 or (changed.json().get("convergence") or {}).get("source_effect") != "committed":
                raise OperationsAcceptanceRefusal("native_browser_conflict_race_not_observed")
            before = journey.observe()["sources"]["concurrent"]["source_sha256"]
            page.locator("#operations-confirm").click()
            page.get_by_text("Runtime status: conflicted", exact=True).wait_for()
            after = journey.observe()["sources"]["concurrent"]["source_sha256"]
            if before != after:
                raise OperationsAcceptanceRefusal("browser_conflict_changed_source")
            journey._record("browser_conflict", {"observed": list(rows), "pre_sha256": before, "post_sha256": after,
                "original_native_outcome": changed.json()})
            if errors or external:
                raise OperationsAcceptanceRefusal("served_browser_runtime_failed")
            # Original action/response trace contains no headers or cookies.
            # Full network tracing would retain the raw WSP carrier and is
            # deliberately not an acceptance artifact.
            trace = {"kind": "original_served_browser_actions", "responses": rows,
                     "page_errors": errors, "external_requests": external, "browser_runtime": observed_browser}
            path = journey.directory / "browser-actions.json"
            retain_original(path, trace)
            for name in ("browser_discovery", "browser_selected_preflight", "browser_confirmation_progress",
                         "browser_cancel", "browser_receipt_recovery", "browser_conflict"):
                journey.observations[name]["artifacts"][path.name] = file_hash(path)
                write_private(journey.directory / (name + ".observation.json"), journey.observations[name])
            page.screenshot(path=str(journey.directory / "browser-final.png"))
        except BaseException as exc:
            primary_error = exc
            try:
                # Retain the original response, including a legitimate refusal
                # without a journal receipt. Never collect headers, cookies,
                # arbitrary DOM, URLs or a HAR to diagnose an ownership race.
                allowed = {str(value) for value in OperationStatus} | {
                    "pending", "partial", "not_completed", "cancelled"}
                statuses = []
                visible_error = None
                try:
                    visible = page.locator("#operations-progress > p").all_text_contents()
                    statuses = [text.removeprefix("Runtime status: ") for text in visible
                        if text.startswith("Runtime status: ")
                        and text.removeprefix("Runtime status: ") in allowed]
                except Exception as observation_error:
                    visible_error = type(observation_error).__name__
                trace = {"kind": "original_served_browser_failure", "complete": False,
                    "responses": rows, "page_errors": errors, "external_requests": external,
                    "browser_runtime": observed_browser, "visible_runtime_statuses": statuses,
                    "visible_status_observation_error": visible_error,
                    "captured_after_seconds": monotonic() - started,
                    "last_completed_scenario": next(reversed(journey.observations), None)}
                retain_original(journey.directory / "browser-actions.failure.json", trace)
                exc.add_note("Original browser failure evidence: browser-actions.failure.json")
            except BaseException as capture_error:
                exc.add_note("Original browser failure evidence unavailable: " + type(capture_error).__name__)
            raise
        finally:
            cleanup_errors = []
            for close in (context.close, browser.close):
                try:
                    close()
                except BaseException as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            if primary_error is not None:
                for cleanup_error in cleanup_errors:
                    primary_error.add_note("Browser cleanup failed: " + type(cleanup_error).__name__)
            elif cleanup_errors:
                raise cleanup_errors[0]
