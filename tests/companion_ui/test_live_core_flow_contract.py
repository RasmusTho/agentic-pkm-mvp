"""Deterministic contracts for the live journey's actual runner and guards."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.companion_ui.live_core_flow import CoreFlow, load_manifest, validate_ask


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
        "embedding_identity": {"dim": 768},
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
        probe=lambda *_: {"binding_verified": True, "source_has_marker": False},
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
