"""Deterministic contracts for the live journey's actual runner and guards."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from tests.companion_ui.live_core_flow import (
    Blocked,
    CoreFlow,
    _PROBE,
    load_manifest,
    native_probe,
    validate_ask,
    validate_native_gateway,
)


def _manifest(tmp_path: Path) -> dict[str, Any]:
    return {
        "channel": "dev",
        "ui_url": "http://127.0.0.1:8111/",
        "api_url": "http://127.0.0.1:18001/",
        "expected_sha": "a" * 40,
        "run_id": "contract-test",
        "output_dir": str(tmp_path / "evidence"),
        "vault_id": "vault-fixture",
        "vault_path": "/approved/dev-fixture",
        "known_note_path": "Inbox/inbox.md",
        "capture_note_path": "Inbox/inbox.md",
        "known_note_uuid": "11111111-1111-4111-8111-111111111111",
        "capture_note_uuid": "11111111-1111-4111-8111-111111111111",
        "known_excerpt": "synthetic fixture",
        "vault_binding_id": "fixture-binding",
        "embedding_identity": {
            "provider": "fixture",
            "model": "fixture",
            "dim": 768,
            "normalize": True,
        },
        "allow_capture": True,
        "allow_ask": True,
        "navigation_ms": 30000,
        "request_ms": 35000,
        "index_seconds": 1,
    }


class _Trace:
    def start(self, **kwargs: Any) -> None:
        pass

    def stop(self, *, path: str) -> None:
        Path(path).write_bytes(b"unit fixture, not a browser trace")


class _Locator:
    def __init__(self, selector: str, d: dict[str, Any]) -> None:
        self.selector, self.d = selector, d

    def count(self) -> int:
        return int(self.selector.startswith("meta["))

    def get_attribute(self, name: str) -> str:
        return self.d["channel"] if "channel" in self.selector else self.d["expected_sha"]


class _Page:
    def __init__(self, d: dict[str, Any], *, wrong_sha: bool = False) -> None:
        self.d, self.wrong_sha, self.url = d, wrong_sha, d["ui_url"]
        self.request = self
        self.navigations: list[str] = []

    def set_default_navigation_timeout(self, value: int) -> None:
        pass

    def set_default_timeout(self, value: int) -> None:
        pass

    def get(self, url: str, **kwargs: Any) -> Any:
        if url.endswith("/version"):
            payload = {"git_sha": "b" * 40 if self.wrong_sha else self.d["expected_sha"]}
        elif url.endswith("/api/operator/health"):
            payload = {
                "environment": self.d["channel"],
                "ok": False,
                "checks": {"llm_access": {"required": True, "ok": False}},
            }
        else:
            payload = {
                "status": "selected",
                "active_vault_id": self.d["vault_id"],
                "active_vault_path": self.d["vault_path"],
            }
            if url.endswith("/api/companion/vault/settings"):
                payload = {"context": payload}
        return SimpleNamespace(ok=True, status=200, url=url, json=lambda: payload)

    def goto(self, url: str, **kwargs: Any) -> Any:
        self.navigations.append(url)
        self.url = url
        return SimpleNamespace(ok=True)

    def locator(self, selector: str) -> _Locator:
        return _Locator(selector, self.d)

    def get_by_test_id(self, value: str) -> _Locator:
        return _Locator(value, self.d)

    def screenshot(self, *, path: str) -> None:
        Path(path).write_bytes(b"unit screenshot fixture")


class _Browser:
    def __init__(self, d: dict[str, Any], *, wrong_sha: bool = False) -> None:
        self.page = _Page(d, wrong_sha=wrong_sha)

    def new_context(self) -> Any:
        return SimpleNamespace(
            new_page=lambda: self.page,
            tracing=_Trace(),
            route=lambda *args: None,
            close=lambda: None,
        )


def _runner(tmp_path: Path, *, wrong_sha: bool = False) -> CoreFlow:
    d = _manifest(tmp_path)
    return CoreFlow(
        d,
        _Browser(d, wrong_sha=wrong_sha),
        probe=lambda *_: {
            "binding_verified": True,
            "source_has_marker": False,
            "first_contact_navigation_safe": True,
            "gateway_upstream_verified": True,
        },
    )


def _independent_steps(
    runner: CoreFlow, monkeypatch: pytest.MonkeyPatch, visits: list[str]
) -> None:
    for name in (
        "open_known_note",
        "capture_acknowledged_once",
        "capture_survives_new_browser_context",
        "fresh_capture_is_indexed_and_retrievable",
        "ask_uses_this_runs_source",
        "capture_unavailable_preserves_draft",
        "ask_failure_is_visible_and_retryable",
    ):

        def action(step: str = name) -> None:
            runner._need_identity()
            visits.append(step)

        monkeypatch.setattr(runner, name, action)


def test_health_failure_does_not_hide_independent_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)
    visits: list[str] = []
    _independent_steps(runner, monkeypatch, visits)
    report = runner.run()
    assert report["steps"][0]["status"] == "failed"
    assert report["steps"][0]["reason"] == "required_health_failed:llm_access"
    assert len(visits) == 7 and all(x["status"] == "passed" for x in report["steps"][1:])
    assert not report["passed"]


def test_identity_mismatch_blocks_capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _runner(tmp_path, wrong_sha=True)
    visits: list[str] = []
    _independent_steps(runner, monkeypatch, visits)
    report = runner.run()
    assert not visits and report["capture_posts"] == 0
    assert report["steps"][0]["reason"] == "backend_revision_mismatch"
    assert all(x["status"] == "blocked" for x in report["steps"][1:])


def test_wrong_fixture_refuses_before_any_gateway_navigation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)
    monkeypatch.setattr(
        runner,
        "_binding",
        lambda: (_ for _ in ()).throw(AssertionError("active_fixture_binding_mismatch")),
    )
    with pytest.raises(AssertionError, match="active_fixture_binding_mismatch"):
        runner.channel_gateway_and_health()
    assert not runner.page.navigations and not runner.identity_ok


def test_wrong_gateway_upstream_refuses_before_navigation_or_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)
    runner.probe = lambda *_: {"gateway_upstream_verified": False}
    monkeypatch.setattr(
        runner.page, "get", lambda *a, **k: pytest.fail("HTTP before native admission")
    )
    report = runner.run()
    assert report["steps"][0]["reason"] == "native_gateway_upstream_not_verified"
    assert not runner.page.navigations and not runner.identity_ok
    assert report["capture_posts"] == report["real_ask_actions"] == 0
    assert all(step["status"] == "blocked" for step in report["steps"][1:])


def _native_rows(d: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    def row(service: str, ip: str, inner: str, outer: str) -> dict[str, Any]:
        return {
            "State": {"Running": True},
            "Config": {
                "Labels": {
                    "com.docker.compose.project": "pkm-dev",
                    "com.docker.compose.service": service,
                    "org.opencontainers.image.revision": d["expected_sha"],
                },
                "Env": ["COMPANION_API_BASE_URL=http://api:8000", "PORT=8111"],
                "Entrypoint": None,
                "Cmd": [
                    "/bin/bash",
                    "-c",
                    'python -m "${COMPANION_UI_SERVE_MODULE:-companion_ui.workspace.serve_dev_page}"',
                ],
            },
            "NetworkSettings": {
                "Ports": {inner + "/tcp": [{"HostIp": "127.0.0.1", "HostPort": outer}]},
                "Networks": {"pkm-dev_default": {"Aliases": [service], "IPAddress": ip}},
            },
        }

    return row("api", "172.18.0.5", "8000", "18001"), row(
        "companion-ui", "172.18.0.6", "8111", "8111"
    )


@pytest.mark.parametrize("fault", [None, "backend", "dns", "port", "revision", "module"])
def test_native_gateway_binds_actual_origin_to_selected_api(
    tmp_path: Path, fault: str | None
) -> None:
    d = _manifest(tmp_path)
    api, ui = _native_rows(d)
    resolved = ["172.18.0.5"]
    if fault == "backend":
        ui["Config"]["Env"][0] = "COMPANION_API_BASE_URL=http://other:8000"
    if fault == "dns":
        resolved = ["172.18.0.9"]
    if fault == "port":
        ui["NetworkSettings"]["Ports"]["8111/tcp"][0]["HostPort"] = "8112"
    if fault == "revision":
        ui["Config"]["Labels"]["org.opencontainers.image.revision"] = "b" * 40
    if fault == "module":
        ui["Config"]["Env"].append("COMPANION_UI_SERVE_MODULE=other")
    if fault is None:
        validate_native_gateway(d, api, ui, resolved)
    else:
        with pytest.raises(Blocked):
            validate_native_gateway(d, api, ui, resolved)


def test_actual_native_probe_refuses_wrong_upstream_before_http_or_source_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tests.companion_ui.live_core_flow as module

    d = _manifest(tmp_path)
    api, ui = _native_rows(d)

    def command(argv: list[str], **kwargs: Any) -> Any:
        if argv[1] == "ps":
            text = ("b" if "label=com.docker.compose.service=companion-ui" in argv else "a") * 12
        elif argv[1] == "inspect":
            text = json.dumps([api if argv[2] == "a" * 12 else ui])
        else:
            assert argv[1:3] == ["exec", "b" * 12], "Source probe ran before gateway refusal"
            text = json.dumps(["172.18.0.9"])
        return SimpleNamespace(returncode=0, stdout=text)

    monkeypatch.setattr(module.subprocess, "run", command)
    runner = CoreFlow(d, _Browser(d), probe=native_probe)
    monkeypatch.setattr(
        runner.page, "get", lambda *a, **k: pytest.fail("HTTP before native refusal")
    )
    report = runner.run()
    assert report["steps"][0]["reason"] == "native_gateway_resolves_another_backend"
    assert not runner.page.navigations and report["capture_posts"] == 0


def test_missing_briefing_refuses_before_initial_and_fresh_context_navigation(
    tmp_path: Path,
) -> None:
    runner = _runner(tmp_path)
    runner.probe = lambda *_: {
        "binding_verified": True,
        "first_contact_navigation_safe": False,
        "gateway_upstream_verified": True,
    }
    for action in (
        runner.channel_gateway_and_health,
        lambda: runner._open_note(runner.page, runner.d["known_note_path"]),
    ):
        with pytest.raises(Blocked, match="first_contact_would_generate_unbudgeted_briefing"):
            action()
    assert not runner.page.navigations and not runner.identity_ok


def test_missing_manifest_is_not_a_live_pass(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_manifest(tmp_path / "absent.json")


@pytest.mark.parametrize(
    "change",
    [
        {"channel": "prod"},
        {"api_url": "http://127.0.0.1:18002/"},
        {"api_url": "http://other-host:18001/"},
        {"capture_note_path": "../personal.md"},
        {"allow_capture": "yes"},
        {"allow_capture": True, "vault_id": None},
        {"ui_url": "http://remote-host:8111/", "api_url": "http://remote-host:18001/"},
        {"embedding_identity": {"dim": 768}},
        {"capture_note_path": "Inbox/./inbox.md"},
        {"output_dir": "/tmp/../approved/dev-fixture/evidence"},
    ],
)
def test_invalid_manifest_refuses_before_browser(tmp_path: Path, change: dict[str, Any]) -> None:
    d = _manifest(tmp_path)
    d.update(change)
    p = tmp_path / "input.json"
    p.write_text(json.dumps(d))
    os.chmod(p, 0o600)
    with pytest.raises(ValueError):
        load_manifest(p)


def test_public_or_symlinked_manifest_is_refused(tmp_path: Path) -> None:
    p = tmp_path / "input.json"
    p.write_text(json.dumps(_manifest(tmp_path)))
    os.chmod(p, 0o644)
    with pytest.raises(ValueError):
        load_manifest(p)
    os.chmod(p, 0o600)
    link = tmp_path / "link.json"
    link.symlink_to(p)
    with pytest.raises(OSError):
        load_manifest(link)


@pytest.mark.parametrize("allow_capture", [True, False])
def test_evidence_containment_uses_canonical_vault_path(
    tmp_path: Path, allow_capture: bool
) -> None:
    d = _manifest(tmp_path)
    d["allow_capture"] = allow_capture
    vault = tmp_path / "vault"
    vault.mkdir()
    d["vault_path"] = str(tmp_path / "unused" / ".." / "vault")
    d["output_dir"] = str(vault / "evidence")
    path = tmp_path / "input.json"
    path.write_text(json.dumps(d))
    path.chmod(0o600)
    with pytest.raises(ValueError, match="evidence_must_be_outside_the_vault"):
        load_manifest(path)


def test_written_capture_survives_later_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)
    visits: list[str] = []
    _independent_steps(runner, monkeypatch, visits)

    def capture() -> None:
        runner._need_identity()
        runner.capture_written = True
        runner.capture_posts = 1
        runner.ack = {"outcome": "written", "trace_id": "fixture-trace"}
        raise AssertionError("later_ui_assertion_failed")

    monkeypatch.setattr(runner, "capture_acknowledged_once", capture)
    report = runner.run()
    assert report["capture_posts"] == 1 and report["capture_acknowledgement"] == runner.ack
    assert report["steps"][2]["status"] == "failed"
    saved = json.loads((runner.output / "report.json").read_text())
    assert saved["capture_acknowledgement"]["trace_id"] == "fixture-trace"


def test_ask_fallback_cannot_pass_grounded_answer() -> None:
    source = "11111111-1111-4111-8111-111111111111"
    response = {"answer": "Person1 booking 999 at Place1", "sources": [{"uuid": source}]}
    response["llm_route"] = {"provider": "fixture-real", "model": "fixture-real"}
    with pytest.raises(AssertionError, match="admitted_grounded_synthesis"):
        validate_ask(response, source, ["Person1", "999", "Place1"])
    response.update(synthesis_receipt_id="receipt", synthesis_source_ids=[source])
    validate_ask(response, source, ["Person1", "999", "Place1"])
    with pytest.raises(AssertionError, match="current_run_facts"):
        validate_ask(response, source, ["NewPerson"])


def test_request_guard_limits_mutations_to_one_armed_action(tmp_path: Path) -> None:
    runner = _runner(tmp_path)

    def route(url: str) -> tuple[Any, list[str]]:
        calls: list[str] = []
        r = SimpleNamespace(
            request=SimpleNamespace(method="POST", url=url),
            continue_=lambda: calls.append("forward"),
            abort=lambda *_: calls.append("abort"),
        )
        return r, calls

    r, calls = route("http://127.0.0.1:8111/api/companion/capture")
    runner.capture_armed = True
    runner._guard_request(r)
    assert calls == ["abort"] and runner.capture_posts == 0
    runner.identity_ok = True
    calls.clear()
    runner._guard_request(r)
    assert calls == ["forward"] and runner.capture_posts == 1
    calls.clear()
    runner.capture_armed = True
    runner._guard_request(r)
    assert calls == ["abort"] and runner.capture_posts == 1
    r, calls = route("http://different-host:8111/api/operator/ask")
    runner.ask_armed = True
    runner._guard_request(r)
    assert calls == ["abort"] and runner.ask_posts == 0


def test_existing_evidence_directory_is_not_overwritten(tmp_path: Path) -> None:
    (tmp_path / "evidence").mkdir()
    with pytest.raises(FileExistsError):
        _runner(tmp_path)


def test_report_consumes_capture_slot_before_forwarding(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    runner.identity_ok = runner.capture_armed = True
    observations: list[int] = []
    route = SimpleNamespace(
        request=SimpleNamespace(method="POST", url="http://127.0.0.1:8111/api/companion/capture"),
        continue_=lambda: observations.append(
            json.loads((runner.output / "report.json").read_text())["capture_posts"]
        ),
        abort=lambda *_: None,
    )
    runner._guard_request(route)
    assert observations == [1]


def test_report_failure_preserves_previous_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)
    runner._write_report()
    previous = (runner.output / "report.json").read_bytes()

    def failed_replace(*args: Any) -> None:
        raise OSError("injected report publication failure")

    monkeypatch.setattr(os, "replace", failed_replace)
    runner.capture_posts = 1
    with pytest.raises(OSError):
        runner._write_report()
    assert (runner.output / "report.json").read_bytes() == previous


@pytest.mark.parametrize(
    "route,answer",
    [
        ({"provider": "mock", "model": "mock"}, "Person1 999 Place1"),
        (
            {"provider": "fixture-real", "model": "fixture-real"},
            "MOCK_ASK_ANSWER: Person1 999 Place1",
        ),
        (
            {"provider": "fixture-real", "model": "fixture-real", "backend": "mock"},
            "Person1 999 Place1",
        ),
        (None, "Person1 999 Place1"),
    ],
)
def test_mock_or_unproven_generation_cannot_pass(route: Any, answer: str) -> None:
    source = "11111111-1111-4111-8111-111111111111"
    response = {
        "answer": answer,
        "sources": [{"uuid": source}],
        "llm_route": route,
        "synthesis_receipt_id": "receipt",
        "synthesis_source_ids": [source],
    }
    with pytest.raises(AssertionError):
        validate_ask(response, source, ["Person1", "999", "Place1"])


def test_invalid_ack_blocks_actual_dependent_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)
    runner.identity_ok = True
    runner.capture_posts = 1
    monkeypatch.setattr(
        runner.page,
        "get_by_test_id",
        lambda *_: SimpleNamespace(click=lambda: None, fill=lambda *_: None),
    )
    response = SimpleNamespace(
        ok=True,
        url="http://127.0.0.1:8111/api/companion/capture",
        json=lambda: {
            "outcome": "written",
            "note_path": "Other/inbox.md",
            "trace_id": "trace",
            "governed_write": {"receipt": "receipt"},
        },
    )
    monkeypatch.setattr(
        runner.page,
        "expect_response",
        lambda *args, **kwargs: nullcontext(SimpleNamespace(value=response)),
        raising=False,
    )
    with pytest.raises(AssertionError, match="capture_acknowledgement_invalid"):
        runner.capture_acknowledged_once()
    assert runner.capture_written and not runner.capture_verified
    for action in (
        runner.capture_survives_new_browser_context,
        runner.fresh_capture_is_indexed_and_retrievable,
    ):
        with pytest.raises(Blocked, match="no_verified_capture"):
            action()
    saved = json.loads((runner.output / "report.json").read_text())
    assert saved["capture_write_observed"] and not saved["capture_verified"]


def _probe_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", "Inbox/inbox.md")
    monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
    monkeypatch.delenv("INSTANCE_VAULT_REGISTRY_PATH", raising=False)
    monkeypatch.delenv("INSTANCE_OWNERSHIP_ROOT", raising=False)
    app_path = tmp_path / "app-local.md"
    monkeypatch.setenv("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", str(app_path))
    app_path.write_text(
        "---\n"
        + json.dumps(
            {
                "schema": "app-local.settings.v1",
                "appInstallId": "app-fixture",
                "lastActiveVaultRef": "fixture",
                "knownVaults": {
                    "fixture": {"path": str(tmp_path), "vaultId": "vault-fixture"},
                },
            }
        )
        + "\n---\n"
    )
    settings = tmp_path / "settings"
    settings.mkdir()
    for name in ("vault", "local", "paths", "workflow", "design-handoff", "companion-ui"):
        fields = {"schema": f"design-handoff.{name}.v1"}
        if name == "vault":
            fields["vaultId"] = "vault-fixture"
        if name == "local":
            fields["localInstanceId"] = "local-fixture"
        (settings / (name + ".md")).write_text("---\n" + json.dumps(fields) + "\n---\n")
    return {
        "channel": "dev",
        "vault_id": "vault-fixture",
        "vault_path": str(tmp_path),
        "capture_note_path": "Inbox/inbox.md",
        "capture_note_uuid": "11111111-1111-4111-8111-111111111111",
        "vault_binding_id": "legacy-compatibility-binding",
        "marker": "PW-probe-marker",
    }


def test_native_probe_refuses_wrong_capture_producer_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _probe_input(tmp_path, monkeypatch)
    data["capture_note_path"] = "Approved/different.md"
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(data)))
    with pytest.raises(AssertionError, match="capture_producer_target_mismatch"):
        exec(_PROBE, {})


@pytest.mark.parametrize("fault", ["local_identity", "last_active"])
def test_native_restore_admission_refuses_before_identity_healing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    data = _probe_input(tmp_path, monkeypatch)
    if fault == "local_identity":
        (tmp_path / "settings/local.md").write_text("---\nschema: design-handoff.local.v1\n---\n")
    else:
        data["vault_path"] = str(tmp_path)
        p = tmp_path / "app-local.md"
        p.write_text(p.read_text().replace(str(tmp_path), str(tmp_path / "unapproved")))
        (tmp_path / "unapproved").mkdir()
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.md")}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(data)))
    with pytest.raises(AssertionError, match="fixture_restore_(identity_missing|target_mismatch)"):
        exec(_PROBE, {})
    assert {p: p.read_bytes() for p in tmp_path.rglob("*.md")} == before


@pytest.mark.parametrize("enabled,present", [(True, False), (True, True), (False, False)])
def test_native_probe_reads_before_any_provider_initialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    enabled: bool,
    present: bool,
) -> None:
    from app.index.artifact_metadata import compute_payload_content_hash
    import app.stores
    import app.stores.pg
    import app.briefing.trigger
    from app.briefing.compose import briefing_note_path
    from app.vault.manager import VaultContext

    data = _probe_input(tmp_path, monkeypatch)
    local_now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    monkeypatch.setattr(app.briefing.trigger, "BRIEFING_ENABLED", enabled)
    monkeypatch.setattr(app.briefing.trigger, "_local_now", lambda _: local_now)
    if present:
        briefing = briefing_note_path(
            vault_context=VaultContext(status="selected", active_vault_path=str(tmp_path)),
            for_date=local_now.date(),
        )
        briefing.parent.mkdir(parents=True)
        briefing.write_text("existing dated artifact, not generated by the probe")
    monkeypatch.setattr(
        app.briefing.trigger,
        "first_contact_briefing",
        lambda **_: pytest.fail("native inspection invoked a writing trigger"),
    )
    target = tmp_path / data["capture_note_path"]
    target.parent.mkdir()
    target.write_text("---\nuuid: " + data["capture_note_uuid"] + "\n---\n" + data["marker"])
    payload = {"text": data["marker"]}
    calls: list[str] = []

    class Connection:
        read_only = False
        info = SimpleNamespace(dbname="app_dev")

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def cursor(self) -> Any:
            def execute(sql: str, parameters: Any) -> None:
                assert self.read_only and sql.startswith("SELECT ")
                assert parameters[0] == data["vault_binding_id"]
                calls.append("readonly_select")

            row = {
                "object_payload": payload,
                "vector_payload": {
                    "provenance": {"content_hash": compute_payload_content_hash(payload)}
                },
            }
            return nullcontext(SimpleNamespace(execute=execute, fetchone=lambda: row))

    monkeypatch.setattr(app.stores.pg, "_connect", Connection)

    def forbidden_provider() -> None:
        raise AssertionError("a provider constructor was invoked")

    monkeypatch.setattr(app.stores, "get_object_store", forbidden_provider)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(data)))
    exec(_PROBE, {})
    result = json.loads(capsys.readouterr().out)
    assert calls == ["readonly_select"]
    assert result["object_has_marker"] and result["source_has_marker"]
    assert result["object_hash"] == result["vector_hash"]
    assert result["first_contact_navigation_safe"] is (not enabled or present)


@pytest.mark.browser_runtime
@pytest.mark.skipif(
    os.environ.get("COMPANION_UI_BROWSER_TESTS") != "1",
    reason="Set COMPANION_UI_BROWSER_TESTS=1 for the offline actual-UI navigation proof.",
)
@pytest.mark.parametrize("landing", ["cold_start", "document"])
def test_open_note_uses_visible_real_browser(tmp_path: Path, landing: str) -> None:
    from playwright.sync_api import sync_playwright
    from companion_ui.workspace.serve_dev_page import render_index_html, vendor_static_assets
    from tests.companion_ui.browser_runtime_harness import install_offline_esm_routes
    from tests.companion_ui.test_entry_state_machine import _orientation_payload, _workspace_fields

    d = _manifest(tmp_path)
    notes = [{"note_path": d["known_note_path"], "title": "Synthetic inbox"}]
    browser_fields = {
        "vault_browser_notes": notes,
        "vault_browser_identity_available": True,
        "vault_browser_total_notes": 1,
        "vault_browser_filtered_notes": 1,
        "vault_browser_state": "ready",
    }
    fields = _workspace_fields() | browser_fields
    note_html = render_index_html(
        api_base_url=d["api_url"], note_path=d["known_note_path"], fields=fields
    )
    root_html = (
        render_index_html(
            api_base_url=d["api_url"],
            orientation=_orientation_payload(leave_status="absent"),
            orientation_vault_browser={
                "notes": notes,
                "identity_available": True,
                "total_notes": 1,
                "filtered_notes": 1,
                "state": "ready",
            },
        )
        if landing == "cold_start"
        else render_index_html(api_base_url=d["api_url"], note_path="Notes/other.md", fields=fields)
    )
    admissions: list[bool] = []
    assets = vendor_static_assets()
    with sync_playwright() as playwright:
        launch = {"channel": "chrome"} if Path("/Applications/Google Chrome.app").exists() else {}
        browser = playwright.chromium.launch(**launch)
        try:
            context = browser.new_context()
            install_offline_esm_routes(context)

            def intercepted(route: Any) -> None:
                request = route.request
                target = urlparse(request.url)
                if request.method != "GET":
                    route.abort()
                elif target.scheme == "http":
                    if target.path in assets:
                        content_type, body = assets[target.path]
                    elif request.resource_type == "document":
                        content_type = "text/html"
                        body = note_html if parse_qs(target.query).get("note_path") else root_html
                    else:
                        content_type, body = "application/json", "{}"
                    route.fulfill(status=200, content_type=content_type, body=body)
                else:
                    route.fallback()

            context.route("**/*", intercepted)
            page = context.new_page()
            page.set_default_timeout(5000)
            runner = CoreFlow.__new__(CoreFlow)
            runner.d = d
            runner._admit_navigation = lambda: admissions.append(True) or {}
            runner._open_note(page, d["known_note_path"])
            assert parse_qs(urlparse(page.url).query)["note_path"] == [d["known_note_path"]]
            assert page.get_by_test_id("workspace-note-rendered").is_visible()
            assert len(admissions) == 2
        finally:
            browser.close()
