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

import pytest

from tests.companion_ui.live_core_flow import Blocked, CoreFlow, _PROBE, load_manifest, validate_ask


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


def test_missing_briefing_refuses_before_initial_and_fresh_context_navigation(
    tmp_path: Path,
) -> None:
    runner = _runner(tmp_path)
    runner.probe = lambda *_: {
        "binding_verified": True,
        "first_contact_navigation_safe": False,
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
    return {
        "channel": "dev",
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
