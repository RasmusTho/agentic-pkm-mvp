"""Opt-in browser journey against an existing dev/test gateway.

All application mutations originate in the browser. The Docker probe is a
bounded read of the approved note and its existing object/vector rows.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import time
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urljoin, urlparse
from uuid import UUID

from tests.companion_ui.live_smoke_contract import (
    assert_gateway_identity,
    assert_operator_channel,
)


class Blocked(RuntimeError):
    """A prerequisite could not be established; this is not a passing test."""


def _origin(url: str) -> tuple[str, str | None, int | None]:
    p = urlparse(url)
    return p.scheme, p.hostname, p.port


def _relative(value: str) -> bool:
    p = PurePosixPath(value)
    return (
        bool(value)
        and not p.is_absolute()
        and not any(x in {"", "..", "."} for x in value.split("/"))
    )


def load_manifest(path: Path) -> dict[str, Any]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid()
        ):
            raise ValueError("manifest_requires_private_regular_file")
        raw = os.read(fd, 32769)
    finally:
        os.close(fd)
    if len(raw) > 32768:
        raise ValueError("manifest_too_large")
    d = json.loads(raw)
    required = {"channel", "ui_url", "api_url", "expected_sha", "run_id", "output_dir"}
    optional = {
        "vault_id",
        "vault_path",
        "known_note_path",
        "known_note_uuid",
        "known_excerpt",
        "capture_note_path",
        "capture_note_uuid",
        "vault_binding_id",
        "embedding_identity",
        "allow_capture",
        "allow_ask",
        "navigation_ms",
        "index_seconds",
        "request_ms",
    }
    if not isinstance(d, dict) or not required <= d.keys() or d.keys() - required - optional:
        raise ValueError("manifest_fields_invalid")
    if d["channel"] not in {"dev", "test"}:
        raise ValueError("only_dev_and_test_are_supported")
    if any(not isinstance(d[k], str) or "\x00" in d[k] or len(d[k]) > 4096 for k in required):
        raise ValueError("manifest_string_invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", d["expected_sha"]):
        raise ValueError("expected_sha_invalid")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", d["run_id"]):
        raise ValueError("run_id_invalid")
    ports = {"dev": (8111, 18001), "test": (8112, 18002)}[d["channel"]]
    for key, port in zip(("ui_url", "api_url"), ports):
        p = urlparse(d[key])
        if (
            p.scheme != "http"
            or p.port != port
            or not p.hostname
            or p.username
            or p.password
            or p.query
            or p.fragment
            or p.path not in {"", "/"}
        ):
            raise ValueError("channel_origin_invalid")
        try:
            loopback = ipaddress.ip_address(p.hostname).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise ValueError("native_probe_requires_guest_loopback_origins")
    if urlparse(d["ui_url"]).hostname != urlparse(d["api_url"]).hostname:
        raise ValueError("gateway_backend_host_mismatch")
    out = Path(d["output_dir"])
    if not out.is_absolute() or out.is_symlink() or any(p.is_symlink() for p in out.parents):
        raise ValueError("output_directory_invalid")
    for key in ("allow_capture", "allow_ask"):
        if type(d.get(key, False)) is not bool:
            raise ValueError("effect_permission_invalid")
        d.setdefault(key, False)
    for key in ("known_note_path", "capture_note_path"):
        if d.get(key) and not _relative(d[key]):
            raise ValueError("fixture_path_invalid")
    for key in ("known_note_uuid", "capture_note_uuid"):
        if d.get(key):
            UUID(d[key])
    if d["allow_capture"]:
        for key in (
            "vault_id",
            "vault_path",
            "known_note_path",
            "known_note_uuid",
            "known_excerpt",
            "capture_note_path",
            "capture_note_uuid",
            "vault_binding_id",
            "embedding_identity",
        ):
            if not d.get(key):
                raise ValueError("approved_capture_fixture_missing")
        if not Path(d["vault_path"]).is_absolute():
            raise ValueError("approved_vault_path_invalid")
        if out.is_relative_to(Path(d["vault_path"])):
            raise ValueError("evidence_must_be_outside_the_vault")
        identity = d["embedding_identity"]
        if (
            not isinstance(identity, dict)
            or set(identity) != {"provider", "model", "dim", "normalize"}
            or not isinstance(identity["provider"], str)
            or not identity["provider"]
            or not isinstance(identity["model"], str)
            or not identity["model"]
            or type(identity["dim"]) is not int
            or not 1 <= identity["dim"] <= 8192
            or type(identity["normalize"]) is not bool
        ):
            raise ValueError("embedding_identity_invalid")
    for key, default, maximum in (
        ("navigation_ms", 30000, 60000),
        ("request_ms", 35000, 60000),
        ("index_seconds", 120, 180),
    ):
        d.setdefault(key, default)
        if type(d[key]) is not int or not 1 <= d[key] <= maximum:
            raise ValueError("test_budget_invalid")
    return d


# Runs inside the already-running, exact-channel API container. Its input is
# stdin; note content and credentials never become command arguments/output.
_PROBE = r"""
import hashlib,json,os,pathlib,sys
from uuid import UUID
p=json.load(sys.stdin)
assert os.environ.get('PKM_ENVIRONMENT')==p['channel']
root=pathlib.Path(os.environ['VAULT_ROOT']).resolve(strict=True)
assert str(root)==p['vault_path']
from app.vault.paths import get_vault_capture_note_rel
assert get_vault_capture_note_rel(root)==p['capture_note_path'],'capture_producer_target_mismatch'
# GET / and /workspace trigger first-contact on the server. Admit navigation
# only when its actual producer is disabled or its dated idempotency file is
# already present. Do not invoke the trigger, compose a note or construct a
# vault manager merely to inspect this precondition.
from app.briefing.trigger import BRIEFING_ENABLED,_local_now
from app.briefing.compose import briefing_note_path
from app.vault.manager import VaultContext
briefing_safe=not BRIEFING_ENABLED
if BRIEFING_ENABLED:
 target=briefing_note_path(vault_context=VaultContext(status='selected',active_vault_path=str(root)),for_date=_local_now(None).date())
 briefing_safe=not target.is_symlink() and target.is_file() and target.resolve(strict=True).is_relative_to(root)
note=root/p['capture_note_path']
assert not note.is_symlink() and note.resolve(strict=True).is_relative_to(root)
raw=note.read_bytes();assert len(raw)<=2*1024*1024
from app.rebuildability.product_total_loss import parse_bounded_frontmatter
fm,body,error=parse_bounded_frontmatter(raw.decode());assert error is None
assert str(fm.get('uuid') or fm.get('id') or '')==p['capture_note_uuid']
assert os.environ.get('STORE_SCHEMA_AUTOCREATE','').lower() not in {'1','true','yes'}
from app.stores.pg import _connect
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
assert p['vault_binding_id']==COMPATIBILITY_BINDING_ID,'unsupported_scoped_capture_probe'
from app.index.artifact_metadata import canonicalize_indexable_text,compute_payload_content_hash
with _connect() as conn:
 conn.read_only=True
 assert conn.info.dbname=={'dev':'app_dev','test':'app_test'}[p['channel']]
 with conn.cursor() as cur:
  cur.execute('SELECT o.payload AS object_payload,v.payload AS vector_payload FROM store_objects o LEFT JOIN store_vector_index v ON o.vault_binding_id=v.vault_binding_id AND o.object_id=v.object_id WHERE o.vault_binding_id=%s AND o.object_id=%s LIMIT 1',(p['vault_binding_id'],UUID(p['capture_note_uuid'])))
  row=cur.fetchone()
payload=dict(row['object_payload'] or {}) if row else {}
vector=dict(row['vector_payload'] or {}) if row else {}
print(json.dumps({'source_uuid':p['capture_note_uuid'],'source_raw_sha256':hashlib.sha256(raw).hexdigest(),'source_has_marker':p['marker'] in body,'object_has_marker':p['marker'] in canonicalize_indexable_text(payload),'object_hash':compute_payload_content_hash(payload) if row else None,'vector_hash':vector.get('provenance',{}).get('content_hash'),'embedding_identity':vector.get('embedding_identity') or vector.get('provenance',{}).get('embedding_identity'),'binding_verified':True,'first_contact_navigation_safe':briefing_safe}))
"""


def native_probe(d: dict[str, Any], marker: str) -> dict[str, Any]:
    def command(argv: list[str], **kwargs: Any) -> str:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=20, **kwargs)
        if p.returncode:
            raise Blocked("native_read_probe_unavailable")
        return p.stdout

    project = "pkm-" + d["channel"]
    ids = command(
        [
            "docker",
            "ps",
            "-q",
            "--filter",
            "label=com.docker.compose.project=" + project,
            "--filter",
            "label=com.docker.compose.service=api",
        ]
    ).split()
    if len(ids) != 1 or not re.fullmatch(r"[0-9a-f]{12,64}", ids[0]):
        raise Blocked("selected_api_container_unavailable")
    row = json.loads(command(["docker", "inspect", ids[0]]))[0]
    labels = row["Config"]["Labels"]
    if labels.get("org.opencontainers.image.revision") != d["expected_sha"]:
        raise Blocked("native_api_revision_mismatch")
    values = {
        k: d[k]
        for k in (
            "channel",
            "vault_path",
            "capture_note_path",
            "capture_note_uuid",
            "vault_binding_id",
        )
    }
    values["marker"] = marker
    return json.loads(
        command(["docker", "exec", "-i", ids[0], "python", "-c", _PROBE], input=json.dumps(values))
    )


def validate_ask(payload: dict[str, Any], source_uuid: str, facts: list[str]) -> None:
    answer = payload.get("answer")
    if not isinstance(answer, str) or not all(x.casefold() in answer.casefold() for x in facts):
        raise AssertionError("ask_did_not_answer_current_run_facts")
    route = payload.get("llm_route")
    if (
        not isinstance(route, dict)
        or not isinstance(route.get("provider"), str)
        or not route["provider"].strip()
        or not isinstance(route.get("model"), str)
        or not route["model"].strip()
    ):
        raise AssertionError("ask_generation_route_missing")
    if (
        route["provider"].strip().lower() in {"mock", "fake", "dummy"}
        or str(route.get("backend", "")).strip().lower() in {"mock", "golden"}
        or str(route.get("model", "")).strip().lower() in {"mock", "fake", "dummy"}
        or answer.lstrip().startswith("MOCK_ASK_ANSWER:")
    ):
        raise AssertionError("ask_mock_generation_is_not_live_acceptance")
    sources = payload.get("sources") or []
    if source_uuid not in {x.get("uuid") for x in sources if isinstance(x, dict)}:
        raise AssertionError("ask_did_not_cite_current_source")
    if not payload.get("synthesis_receipt_id") or source_uuid not in (
        payload.get("synthesis_source_ids") or []
    ):
        raise AssertionError("ask_has_no_admitted_grounded_synthesis")


def validate_capture_ack(ack: dict[str, Any], expected_path: str, posts: int) -> None:
    if (
        ack.get("outcome") != "written"
        or ack.get("note_path") != expected_path
        or not isinstance(ack.get("trace_id"), str)
        or not ack["trace_id"].strip()
        or not isinstance(ack.get("governed_write"), dict)
        or not ack["governed_write"]
        or posts != 1
    ):
        raise AssertionError("capture_acknowledgement_invalid")


class CoreFlow:
    """One bounded journey, with independent status for its eight steps."""

    def __init__(
        self,
        d: dict[str, Any],
        browser: Any,
        probe: Callable[[dict[str, Any], str], dict[str, Any]] = native_probe,
    ) -> None:
        self.d, self.browser, self.probe = d, browser, probe
        self.output = Path(d["output_dir"])
        self.output.mkdir(mode=0o700, parents=True, exist_ok=False)
        os.chmod(self.output, 0o700)
        self.context = browser.new_context()
        self.context.tracing.start(screenshots=True, snapshots=True)
        self.page = self.context.new_page()
        self.page.set_default_navigation_timeout(d["navigation_ms"])
        self.page.set_default_timeout(10000)
        self.identity_ok = self.capture_written = self.persisted = self.indexed = False
        self.capture_verified = False
        self.capture_posts = self.ask_posts = 0
        self.capture_armed = self.ask_armed = False
        self.ack: dict[str, Any] | None = None
        self.results: list[dict[str, Any]] = []
        self.marker = "PW-" + d["channel"] + "-" + d["run_id"]
        token = hashlib.sha256(self.marker.encode()).hexdigest()
        self.facts = ["Person" + token[:8], "Place" + token[8:16], str(int(token[16:22], 16))]
        self.text = f"{self.marker}: Testperson {self.facts[0]} has booking {self.facts[2]} at {self.facts[1]}."
        self.question = f"For {self.marker}, what is {self.facts[0]}'s booking number and place?"
        self.context.route("**/*", self._guard_request)

    def _guard_request(self, route: Any) -> None:
        request = route.request
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            route.continue_()
            return
        if not self.identity_ok or _origin(request.url) != _origin(self.d["ui_url"]):
            route.abort("blockedbyclient")
            return
        path = urlparse(request.url).path
        if (
            path == "/api/companion/capture"
            and request.method == "POST"
            and self.capture_armed
            and self.d["allow_capture"]
            and self.capture_posts == 0
        ):
            self.capture_posts += 1
            self.capture_armed = False
            self._write_report()
            route.continue_()
        elif (
            path == "/api/operator/ask"
            and request.method == "POST"
            and self.ask_armed
            and self.d["allow_ask"]
            and self.ask_posts == 0
        ):
            self.ask_posts += 1
            self.ask_armed = False
            self._write_report()
            route.continue_()
        else:
            route.abort("blockedbyclient")

    def _get(self, url: str) -> dict[str, Any]:
        try:
            response = self.page.request.get(url, timeout=self.d["request_ms"], max_redirects=0)
        except Exception as exc:
            raise Blocked("endpoint_unreachable") from exc
        if not response.ok:
            raise Blocked("endpoint_http_" + str(response.status))
        if _origin(response.url) != _origin(url):
            raise AssertionError("read_origin_changed")
        return response.json()

    def _binding(self) -> None:
        ctx = self._get(urljoin(self.d["api_url"], "/api/companion/vault/context"))
        if (
            ctx.get("status") != "selected"
            or ctx.get("active_vault_id") != self.d.get("vault_id")
            or ctx.get("active_vault_path") != self.d.get("vault_path")
        ):
            raise AssertionError("active_fixture_binding_mismatch")

    def _need_identity(self) -> None:
        if not self.identity_ok:
            raise Blocked("channel_and_fixture_identity_not_verified")
        if _origin(self.page.url) != _origin(self.d["ui_url"]):
            raise AssertionError("browser_origin_changed")
        self._binding()

    def _admit_navigation(self) -> dict[str, Any]:
        # The gateway's document GET performs an internal POST which browser
        # routing cannot intercept. Recheck its native read-only precondition
        # before every root/note navigation, including fresh contexts.
        self._binding()
        evidence = self.probe(self.d, self.marker)
        if evidence.get("binding_verified") is not True:
            raise AssertionError("fixture_not_verified")
        if evidence.get("first_contact_navigation_safe") is not True:
            raise Blocked("first_contact_would_generate_unbudgeted_briefing")
        return evidence

    def channel_gateway_and_health(self) -> None:
        version = self._get(urljoin(self.d["api_url"], "/version"))
        if version.get("git_sha") != self.d["expected_sha"]:
            raise AssertionError("backend_revision_mismatch")
        health = self._get(urljoin(self.d["ui_url"], "/api/operator/health"))
        try:
            assert_operator_channel(health, expected_channel=self.d["channel"])
        except AssertionError as exc:
            raise AssertionError("backend_channel_mismatch") from exc
        baseline = self._admit_navigation()
        if baseline.get("source_has_marker"):
            raise AssertionError("run_id_reused")
        response = self.page.goto(self.d["ui_url"], wait_until="domcontentloaded")
        if response is None or not response.ok:
            raise AssertionError("gateway_page_unavailable")
        if _origin(self.page.url) != _origin(self.d["ui_url"]):
            raise AssertionError("gateway_redirected_to_other_origin")
        channel = self.page.locator('meta[name="pkm-runtime-channel"]')
        revision = self.page.locator('meta[name="pkm-runtime-git-sha"]')
        if channel.count() != 1 or revision.count() != 1:
            raise AssertionError("gateway_identity_marker_missing")
        assert_gateway_identity(
            actual_channel=channel.get_attribute("content") or "",
            actual_git_sha=revision.get_attribute("content") or "",
            expected_channel=self.d["channel"],
            expected_git_sha=self.d["expected_sha"],
        )
        self._binding()
        self.identity_ok = True
        for name in (
            "workspace-error-state",
            "workspace-wrong-device-state",
            "workspace-vault-unreachable-state",
        ):
            if self.page.get_by_test_id(name).count():
                raise AssertionError("gateway_error_entry_state")
        if health.get("ok") is not True:
            failed = [
                k
                for k, v in health.get("checks", {}).items()
                if isinstance(v, dict) and v.get("required") is True and v.get("ok") is not True
            ]
            raise AssertionError("required_health_failed:" + ",".join(failed))

    def _open_note(self, page: Any, path: str) -> None:
        self._admit_navigation()
        page.goto(self.d["ui_url"], wait_until="domcontentloaded")
        pane = page.locator('[data-testid="workspace-vault-browser"]:visible').first
        if not pane.count():
            opened = False
            for selector in (
                '[data-testid="workspace-vault-chip"]',
                '[data-intent="vault.open"]',
                '[data-testid="vault-browse-button"]',
            ):
                controls = page.locator(selector)
                for n in range(controls.count()):
                    item = controls.nth(n)
                    if item.is_visible():
                        item.click()
                        opened = True
                        break
                if opened:
                    break
            if not opened:
                raise AssertionError("vault_browse_control_missing")
        pane.wait_for(state="visible")
        folders = path.split("/")[:-1]
        for index in range(len(folders)):
            folder = "/".join(folders[: index + 1])
            groups = pane.get_by_test_id("workspace-vault-browser-group")
            for n in range(groups.count()):
                group = groups.nth(n)
                if group.get_attribute("data-folder") == folder:
                    details = group.locator(":scope > details")
                    if details.get_attribute("open") is None:
                        details.locator(":scope > summary").click()
                    break
        links = pane.get_by_test_id("workspace-vault-browser-note-link")
        for n in range(links.count()):
            link = links.nth(n)
            if parse_qs(urlparse(link.get_attribute("href") or "").query).get("note_path") == [
                path
            ]:
                self._admit_navigation()
                link.click()
                page.get_by_test_id("workspace-note-rendered").wait_for(state="visible")
                return
        raise AssertionError("approved_note_not_reachable_in_browser")

    def open_known_note(self) -> None:
        self._need_identity()
        self._open_note(self.page, self.d["known_note_path"])
        note = self._get(
            urljoin(self.d["api_url"], "/api/companion/workspace")
            + "?note_path="
            + quote(self.d["known_note_path"])
        )
        if note["artifact"].get("artifact_id") != self.d["known_note_uuid"]:
            raise AssertionError("opened_note_identity_mismatch")
        if (
            self.d["known_excerpt"]
            not in self.page.get_by_test_id("workspace-note-rendered").inner_text()
        ):
            raise AssertionError("fixture_excerpt_not_visible")

    def capture_acknowledged_once(self) -> None:
        self._need_identity()
        if not self.d["allow_capture"]:
            raise Blocked("capture_not_authorized")
        self.page.get_by_test_id("workspace-surface-icon-capture").click()
        self.page.get_by_test_id("capture-input").fill(self.text)
        self._binding()
        self.capture_armed = True
        with self.page.expect_response(
            lambda r: urlparse(r.url).path == "/api/companion/capture"
            and r.request.method == "POST",
            timeout=self.d["request_ms"],
        ) as response:
            self.page.get_by_test_id("capture-save").click()
        result = response.value
        self.capture_armed = False
        if _origin(result.url) != _origin(self.d["ui_url"]):
            raise AssertionError("capture_response_origin_mismatch")
        if not result.ok:
            raise AssertionError("capture_http_" + str(result.status))
        self.ack = result.json()
        # Preserve a durable success acknowledgement even if a later UI/index
        # assertion fails. Re-running capture is not a recovery operation.
        self.capture_written = self.ack.get("outcome") == "written"
        self._write_report()
        validate_capture_ack(self.ack, self.d["capture_note_path"], self.capture_posts)
        self.page.locator('[data-capture-state="written"]').filter(has_text=self.marker).wait_for()
        item = self.page.locator('[data-capture-state="written"]').filter(has_text=self.marker)
        if item.get_attribute("data-ack-trace-id") != self.ack["trace_id"]:
            raise AssertionError("capture_trace_not_rendered")
        self._binding()
        if not self.probe(self.d, self.marker).get("source_has_marker"):
            raise AssertionError("capture_not_in_approved_source")
        self.capture_verified = True
        self._write_report()

    def capture_survives_new_browser_context(self) -> None:
        self._need_identity()
        if not self.capture_verified:
            raise Blocked("no_verified_capture")
        context = self.browser.new_context()
        try:
            page = context.new_page()
            page.set_default_navigation_timeout(self.d["navigation_ms"])
            page.set_default_timeout(10000)
            self._open_note(page, self.d["capture_note_path"])
            text = page.get_by_test_id("workspace-note-rendered").inner_text()
            if text.count(self.marker) != 1 or not all(x in text for x in self.facts):
                raise AssertionError("fresh_context_did_not_read_capture")
            self.persisted = True
        finally:
            context.close()

    def fresh_capture_is_indexed_and_retrievable(self) -> None:
        self._need_identity()
        if not self.capture_verified:
            raise Blocked("no_verified_capture")
        if self.ack and self.ack.get("ingest_warning"):
            raise AssertionError("capture_ack_reports_ingest_binding_warning")
        deadline = time.monotonic() + self.d["index_seconds"]
        while True:
            evidence = self.probe(self.d, self.marker)
            if (
                evidence.get("object_has_marker")
                and evidence.get("object_hash")
                and evidence["object_hash"] == evidence.get("vector_hash")
            ):
                break
            if time.monotonic() >= deadline:
                raise AssertionError("captured_source_not_fresh_in_index_before_deadline")
            time.sleep(2)
        identity = evidence.get("embedding_identity") or {}
        if any(identity.get(k) != v for k, v in self.d["embedding_identity"].items()):
            raise AssertionError("indexed_embedding_identity_mismatch")
        result = self._get(urljoin(self.d["api_url"], "/search") + "?q=" + quote(self.text))
        if self.d["capture_note_uuid"] not in {x.get("uuid") for x in result.get("results", [])}:
            raise AssertionError("fresh_capture_missing_from_retrieval")
        self.indexed = True

    def _open_operator(self, page: Any) -> None:
        controls = page.locator('[data-intent="map.open"]')
        for n in range(controls.count()):
            if controls.nth(n).is_visible():
                controls.nth(n).click()
                break
        else:
            raise AssertionError("map_control_missing")
        page.locator('[data-testid="system-map-node"][data-surface-id="operator"]').click()
        page.get_by_test_id("operator-ask-input").wait_for(state="visible")

    def ask_uses_this_runs_source(self) -> None:
        self._need_identity()
        if not self.indexed:
            raise Blocked("fresh_capture_not_index_verified")
        if not self.d["allow_ask"]:
            raise Blocked("ask_not_authorized")
        self._open_operator(self.page)
        self.page.get_by_test_id("operator-ask-input").fill(self.question)
        self._binding()
        self.ask_armed = True
        with self.page.expect_response(
            lambda r: urlparse(r.url).path == "/api/operator/ask" and r.request.method == "POST",
            timeout=self.d["request_ms"],
        ) as response:
            self.page.get_by_test_id("operator-ask-btn").click()
        self.ask_armed = False
        result = response.value
        if not result.ok or _origin(result.url) != _origin(self.d["ui_url"]):
            raise AssertionError("ask_response_failed_or_wrong_origin")
        payload = result.json()
        self.page.get_by_test_id("operator-ask-btn").wait_for(state="visible")
        self.page.wait_for_function("!document.getElementById('operator-ask-btn').disabled")
        if (
            self.page.get_by_test_id("operator-ask-answer").inner_text().strip()
            != str(payload.get("answer", "")).strip()
        ):
            raise AssertionError("ask_response_not_rendered")
        validate_ask(payload, self.d["capture_note_uuid"], self.facts)

    def capture_unavailable_preserves_draft(self) -> None:
        self._need_identity()
        context = self.browser.new_context()
        try:
            page = context.new_page()
            page.set_default_navigation_timeout(self.d["navigation_ms"])
            page.set_default_timeout(10000)
            self._open_note(page, self.d["known_note_path"])
            context.route("**/api/companion/capture", lambda route: route.abort("failed"))
            page.get_by_test_id("workspace-surface-icon-capture").click()
            draft = self.marker + "-offline-draft"
            page.get_by_test_id("capture-input").fill(draft)
            page.get_by_test_id("capture-save").click()
            item = page.locator('[data-capture-state="not_yet_written"]').filter(has_text=draft)
            item.wait_for()
            if item.get_attribute("data-ack-trace-id"):
                raise AssertionError("offline_capture_fabricated_acknowledgement")
        finally:
            context.close()

    def ask_failure_is_visible_and_retryable(self) -> None:
        self._need_identity()
        context = self.browser.new_context()
        try:
            page = context.new_page()
            page.set_default_navigation_timeout(self.d["navigation_ms"])
            page.set_default_timeout(10000)
            self._open_note(page, self.d["known_note_path"])
            self._open_operator(page)
            marker = "PW_TEST_ASK_UNAVAILABLE"
            context.route(
                "**/api/operator/ask",
                lambda route: route.fulfill(
                    status=503, content_type="application/json", body=json.dumps({"error": marker})
                ),
            )
            page.get_by_test_id("operator-ask-input").fill(self.question)
            page.get_by_test_id("operator-ask-btn").click()
            page.get_by_test_id("operator-ask-answer").filter(has_text=marker).wait_for()
            page.wait_for_function("!document.getElementById('operator-ask-btn').disabled")
            if page.get_by_test_id("operator-ask-input").input_value() != self.question:
                raise AssertionError("failed_ask_lost_question")
        finally:
            context.close()

    def run(self) -> dict[str, Any]:
        actions = [
            self.channel_gateway_and_health,
            self.open_known_note,
            self.capture_acknowledged_once,
            self.capture_survives_new_browser_context,
            self.fresh_capture_is_indexed_and_retrievable,
            self.ask_uses_this_runs_source,
            self.capture_unavailable_preserves_draft,
            self.ask_failure_is_visible_and_retryable,
        ]
        try:
            for number, action in enumerate(actions, 1):
                start = time.monotonic()
                item: dict[str, Any] = {
                    "id": f"PW-{number:02}",
                    "name": action.__name__,
                    "kind": "browser_fault_injection" if number >= 7 else "live",
                }
                try:
                    action()
                    item.update(status="passed", reason=None)
                except Blocked as exc:
                    item.update(status="blocked", reason=str(exc))
                except AssertionError as exc:
                    item.update(status="failed", reason=str(exc)[:240])
                except Exception as exc:
                    # Raw browser/SDK exceptions can contain vault bodies or
                    # credential-bearing URLs. Keep only their class here.
                    item.update(status="failed", reason=type(exc).__name__)
                item["seconds"] = round(time.monotonic() - start, 3)
                if item["status"] != "passed":
                    try:
                        path = self.output / (item["id"] + ".png")
                        self.page.screenshot(path=str(path))
                        os.chmod(path, 0o600)
                        item["screenshot"] = path.name
                    except Exception:
                        pass
                self.results.append(item)
                self._write_report()
        finally:
            try:
                path = self.output / "trace.zip"
                self.context.tracing.stop(path=str(path))
                os.chmod(path, 0o600)
            finally:
                self.context.close()
        return self._write_report()

    def _write_report(self) -> dict[str, Any]:
        report = {
            "schema": "playwright_core_flow_execution.v1",
            "channel": self.d["channel"],
            "expected_sha": self.d["expected_sha"],
            "run_id": self.d["run_id"],
            "steps": self.results,
            "capture_posts": self.capture_posts,
            "real_ask_actions": self.ask_posts,
            "capture_acknowledgement": self.ack,
            "capture_write_observed": self.capture_written,
            "capture_verified": self.capture_verified,
            "passed": len(self.results) == 8 and all(x["status"] == "passed" for x in self.results),
        }
        path = self.output / "report.json"
        temporary = self.output / "report.json.next"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
        directory = os.open(self.output, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return report


def execute_manifest(path: Path) -> dict[str, Any]:
    d = load_manifest(path)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            return CoreFlow(d, browser).run()
        finally:
            browser.close()
