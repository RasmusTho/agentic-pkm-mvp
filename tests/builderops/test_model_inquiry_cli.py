from __future__ import annotations

import json
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from queue import Empty
from threading import Barrier, Event
from typing import Any, Mapping

import pytest
from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_root
from app.builderops.model_inquiry import ModelInquiryService
from app.builderops.model_inquiry_adapters import AdapterResult, INQUIRY_INTENT_CONFIG_ENV
from app.builderops.model_inquiry_contract import RESPONSE_SCHEMA_VERSION
from app.builderops.model_inquiry_promotion import ModelInquiryPromotionGateway
from app.builderops.model_inquiry_runner import ModelInquiryRunner
from app.builderops.models import BuilderOpsConflictError, BuilderOpsValidationError


def _commit_turn_in_process(env: dict[str, str], messages) -> None:
    messages.put("started")
    service = ModelInquiryService.from_env(env)
    service.commit_turn(
        "inq_test_process_lock",
        turn_id="turn-a",
        sequence=0,
        role="reviewer",
        content="Process-safe turn",
        input_artifact_refs=["question"],
        source_refs=[{"ref_type": "github_issue", "ref": "#3290"}],
    )
    messages.put("committed")


def _env(tmp_path: Path) -> dict[str, str]:
    vault = tmp_path / "shared-vault"
    vault.mkdir()
    return {
        "BUILDEROPS_VAULT_ROOT": str(vault),
        "BUILDEROPS_DB_PATH": str(tmp_path / "local" / "builderops.sqlite3"),
    }


def _response(
    stance: str,
    *,
    reviewed: list[str] | None = None,
    accepted_hash: str | None = None,
    content: str | None = None,
) -> str:
    return json.dumps(
        {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "stance": stance,
            "content": content or f"{stance} answer",
            "claims": [f"{stance} claim"],
            "risks": [f"{stance} risk"],
            "blocking_questions": [],
            "reviewed_artifact_refs": reviewed or [],
            "accepted_artifact_hash": accepted_hash,
        }
    )


@dataclass
class _ConsensusAdapter:
    adapter_id: str
    provider: str
    model: str
    content: str = ""

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        if request["phase"] == "draft":
            return AdapterResult(_response("draft", content=self.content or None))
        return AdapterResult(
            _response(
                "accept",
                reviewed=list(request["reviewed_artifact_refs"]),
                accepted_hash=request["input_artifacts"][0]["artifact_hash"],
                content=self.content or None,
            )
        )


def test_terminal_run_writes_human_readable_markdown_report(tmp_path: Path) -> None:
    env = _env(tmp_path)
    service = ModelInquiryService.from_env(env)
    service.start(
        question="Which boundary should own durable human knowledge?",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_markdown_report",
        source_refs=[{"ref_type": "github_issue", "ref": "#3540"}],
    )
    adapters = {
        role: _ConsensusAdapter(f"{role}-adapter", role, f"{role}-model")
        for role in ("fable", "gpt_codex")
    }

    result = ModelInquiryRunner(service, adapters).run("inq_test_markdown_report", max_rounds=1)

    report = Path(result["human_readable_report"])
    assert report.is_file()
    rendered = report.read_text(encoding="utf-8")
    assert "# Model inquiry — inq_test_markdown_report" in rendered
    assert "Which boundary should own durable human knowledge?" in rendered
    assert "### 0. fable — draft" in rendered
    assert "### 3. gpt_codex — review" in rendered
    assert "## Shared synthesis" in rendered
    assert "## Run result" in rendered
    assert "Outcome: **consensus**" in rendered

    ModelInquiryPromotionGateway(service).evaluate("inq_test_markdown_report")
    service.write_human_readable_report("inq_test_markdown_report")
    rendered = report.read_text(encoding="utf-8")
    assert "## Readiness" in rendered
    assert "Outcome: **needs_input**" in rendered


def test_markdown_report_is_deterministic_and_derived(tmp_path: Path) -> None:
    env = _env(tmp_path)
    service = ModelInquiryService.from_env(env)
    service.start(
        question="Render this safely.",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_markdown_deterministic",
        source_refs=[{"ref_type": "github_issue", "ref": "#3540"}],
    )
    adapters = {
        role: _ConsensusAdapter(f"{role}-adapter", role, f"{role}-model")
        for role in ("fable", "gpt_codex")
    }
    result = ModelInquiryRunner(service, adapters).run(
        "inq_test_markdown_deterministic", max_rounds=1
    )
    report = Path(result["human_readable_report"])
    json_before = {
        path.relative_to(report.parent): path.read_bytes()
        for path in report.parent.rglob("*.json")
    }

    service.write_human_readable_report("inq_test_markdown_deterministic")

    assert report.read_text(encoding="utf-8") == service.write_human_readable_report(
        "inq_test_markdown_deterministic"
    ).read_text(encoding="utf-8")
    assert {
        path.relative_to(report.parent): path.read_bytes()
        for path in report.parent.rglob("*.json")
    } == json_before


def test_markdown_report_fences_untrusted_question_and_model_text(tmp_path: Path) -> None:
    env = _env(tmp_path)
    service = ModelInquiryService.from_env(env)
    service.start(
        question="# Question\n\n<script>alert('x')</script>\n```",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_markdown_untrusted",
        source_refs=[{"ref_type": "github_issue", "ref": "#3540"}],
    )
    response = json.dumps(
        {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "stance": "draft",
            "content": "# Model heading\n\n<script>bad</script>\n```",
            "claims": ["# Claim", "<b>claim</b>"],
            "risks": ["```"],
            "blocking_questions": ["<img src=x>"],
            "reviewed_artifact_refs": [],
            "accepted_artifact_hash": None,
        }
    )
    service.commit_turn(
        "inq_test_markdown_untrusted",
        turn_id="draft-fable",
        sequence=0,
        role="fable",
        content=response,
        input_artifact_refs=["question"],
        source_refs=[{"ref_type": "github_issue", "ref": "#3540"}],
    )
    report = service.write_human_readable_report("inq_test_markdown_untrusted")

    rendered = report.read_text(encoding="utf-8")
    assert "````" in rendered
    assert "<script>alert('x')</script>" in rendered
    assert "<script>bad</script>" in rendered
    assert "<img src=x>" in rendered


def test_markdown_report_fences_untrusted_synthesis_and_readiness(tmp_path: Path) -> None:
    env = _env(tmp_path)
    service = ModelInquiryService.from_env(env)
    service.start(
        question="Safe question",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_markdown_synthesis_untrusted",
        source_refs=[{"ref_type": "github_issue", "ref": "#3540"}],
    )
    content = "# Synthesis heading\n\n<script>bad</script>\n```"
    adapters = {
        role: _ConsensusAdapter(f"{role}-adapter", role, f"{role}-model", content)
        for role in ("fable", "gpt_codex")
    }

    result = ModelInquiryRunner(service, adapters).run(
        "inq_test_markdown_synthesis_untrusted", max_rounds=1
    )
    ModelInquiryPromotionGateway(service).evaluate("inq_test_markdown_synthesis_untrusted")
    report = service.write_human_readable_report("inq_test_markdown_synthesis_untrusted")

    rendered = report.read_text(encoding="utf-8")
    assert result["outcome"] == "consensus"
    assert "## Shared synthesis" in rendered
    assert "````" in rendered
    assert "# Synthesis heading" in rendered
    assert "<script>bad</script>" in rendered


def test_start_persists_question_before_provider_call(tmp_path: Path) -> None:
    env = _env(tmp_path)
    question_file = tmp_path / "question.md"
    question_file.write_text("# Question\n\nHow should the boundary work?\n", encoding="utf-8")

    result = CliRunner().invoke(
        builderops_root,
        [
            "builderops",
            "inquiry",
            "start",
            "--question-file",
            str(question_file),
            "--workflow",
            "fable-gpt-architecture",
            "--inquiry-id",
            "inq_test_start",
            "--json",
        ],
        env=env,
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["inquiry"]["inquiry_id"] == "inq_test_start"
    assert payload["question"]["content"].startswith("# Question")
    assert payload["turns"] == []
    assert payload["receipts"][0]["event_type"] == "inquiry_started"

    observed: list[dict[str, object]] = []

    def successor_hook(inquiry_id: str) -> None:
        reopened = ModelInquiryService.from_env(env)
        trace = reopened.trace(inquiry_id)
        assert trace["question"]["content_hash"]
        assert trace["receipts"][0]["event_type"] == "inquiry_started"
        observed.append(trace)

    service = ModelInquiryService.from_env(env)
    service.start(
        question="A second durable question",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_callback",
        source_refs=[{"ref_type": "file", "ref": str(question_file)}],
        after_persist=successor_hook,
    )

    assert len(observed) == 1
    assert observed[0]["turns"] == []


def test_start_and_resume_inquiry(tmp_path: Path) -> None:
    env = _env(tmp_path)
    question_file = tmp_path / "question.md"
    question_file.write_text("# Question\n\nHow should the boundary work?\n", encoding="utf-8")

    start = CliRunner().invoke(
        builderops_root,
        [
            "builderops",
            "inquiry",
            "start",
            "--question-file",
            str(question_file),
            "--workflow",
            "fable-gpt-architecture",
            "--inquiry-id",
            "inq_test_start_resume",
            "--json",
        ],
        env=env,
        catch_exceptions=False,
    )
    assert start.exit_code == 0, start.output
    assert json.loads(start.output)["inquiry"]["inquiry_id"] == "inq_test_start_resume"

    resume = CliRunner().invoke(
        builderops_root,
        [
            "builderops",
            "inquiry",
            "resume",
            "inq_test_start_resume",
            "--json",
        ],
        env=env,
        catch_exceptions=False,
    )
    assert resume.exit_code == 0, resume.output
    assert json.loads(resume.output) == {
        "inquiry_id": "inq_test_start_resume",
        "next_sequence": 0,
        "pending_turn_ids": [],
        "skipped_turn_ids": [],
        "terminal_receipt_ids": [],
    }


def test_inquiry_evaluate_is_local_and_repository_independent(tmp_path: Path) -> None:
    env = _env(tmp_path)
    ModelInquiryService.from_env(env).start(
        question="Evaluate locally before any GitHub authority crossing",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_local_evaluate",
        source_refs=[{"ref_type": "github_issue", "ref": "#3293"}],
    )

    result = CliRunner().invoke(
        builderops_root,
        [
            "builderops",
            "inquiry",
            "evaluate",
            "inq_test_local_evaluate",
            "--json",
        ],
        env=env,
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    assert "terminal inquiry run" in result.output
    assert "repository" not in result.output.lower()
    assert not (
        Path(env["BUILDEROPS_VAULT_ROOT"])
        / "model-inquiries"
        / "inq_test_local_evaluate"
        / "readiness.json"
    ).exists()


def test_inquiry_artifacts_are_immutable_and_idempotent(tmp_path: Path) -> None:
    env = _env(tmp_path)
    service = ModelInquiryService.from_env(env)
    source_refs = [{"ref_type": "github_issue", "ref": "#3290"}]

    first = service.start(
        question="Immutable question",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_immutable",
        source_refs=source_refs,
    )
    retry = service.start(
        question="Immutable question",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_immutable",
        source_refs=source_refs,
    )
    assert retry == first

    with pytest.raises(BuilderOpsConflictError, match="immutable question"):
        service.start(
            question="Conflicting question",
            workflow="fable-gpt-architecture",
            inquiry_id="inq_test_immutable",
            source_refs=source_refs,
        )

    turn = service.commit_turn(
        "inq_test_immutable",
        turn_id="turn-a",
        sequence=0,
        role="fable",
        content="Candidate A",
        input_artifact_refs=["question"],
        source_refs=source_refs,
    )
    assert service.commit_turn(
        "inq_test_immutable",
        turn_id="turn-a",
        sequence=0,
        role="fable",
        content="Candidate A",
        input_artifact_refs=["question"],
        source_refs=source_refs,
    ) == turn

    with pytest.raises(BuilderOpsConflictError, match="immutable turn"):
        service.commit_turn(
            "inq_test_immutable",
            turn_id="turn-a",
            sequence=0,
            role="fable",
            content="Changed candidate",
            input_artifact_refs=["question"],
            source_refs=source_refs,
        )

    trace = service.trace("inq_test_immutable")
    assert trace["question"]["content"] == "Immutable question"
    assert trace["turns"] == [turn]


def test_concurrent_turns_reserve_one_sequence(tmp_path: Path) -> None:
    env = _env(tmp_path)
    service = ModelInquiryService.from_env(env)
    source_refs = [{"ref_type": "github_issue", "ref": "#3290"}]
    service.start(
        question="Reserve a successor slot",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_concurrent",
        source_refs=source_refs,
    )

    def commit(turn_id: str) -> object:
        try:
            return service.commit_turn(
                "inq_test_concurrent",
                turn_id=turn_id,
                sequence=0,
                role="reviewer",
                content=f"Candidate {turn_id}",
                input_artifact_refs=["question"],
                source_refs=source_refs,
            )
        except BuilderOpsConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(commit, ["turn-a", "turn-b"]))

    assert sum(isinstance(result, BuilderOpsConflictError) for result in results) == 1
    assert len(service.trace("inq_test_concurrent")["turns"]) == 1
    losing_id = ["turn-a", "turn-b"][
        next(index for index, result in enumerate(results) if isinstance(result, BuilderOpsConflictError))
    ]
    recovered = service.commit_turn(
        "inq_test_concurrent",
        turn_id=losing_id,
        sequence=1,
        role="reviewer",
        content=f"Candidate {losing_id}",
        input_artifact_refs=["question"],
        source_refs=source_refs,
    )
    assert recovered["turn_id"] == losing_id
    inquiry_dir = env["BUILDEROPS_VAULT_ROOT"]
    reservations = list(
        (Path(inquiry_dir) / "model-inquiries" / "inq_test_concurrent" / "turn-ids").glob(
            "*.json"
        )
    )
    assert len(reservations) == len(service.trace("inq_test_concurrent")["turns"])

    def reuse_id(sequence: int) -> object:
        try:
            return service.commit_turn(
                "inq_test_concurrent",
                turn_id="same-id",
                sequence=sequence,
                role="reviewer",
                content=f"Candidate {sequence}",
                input_artifact_refs=["question"],
                source_refs=source_refs,
            )
        except BuilderOpsConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        reused = list(executor.map(reuse_id, [2, 3]))

    assert sum(isinstance(result, BuilderOpsConflictError) for result in reused) == 1
    assert [turn["turn_id"] for turn in service.trace("inq_test_concurrent")["turns"]].count(
        "same-id"
    ) == 1


def test_crashed_turn_reservation_is_visible_and_retryable(tmp_path: Path, monkeypatch) -> None:
    env = _env(tmp_path)
    service = ModelInquiryService.from_env(env)
    refs = [{"ref_type": "github_issue", "ref": "#3290"}]
    service.start(
        question="Recover a reservation",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_crash_reservation",
        source_refs=refs,
    )
    original = service._write_immutable

    def crash_before_turn(path, payload, *, label):
        if label == "immutable turn artifact":
            raise KeyboardInterrupt("simulated process loss")
        return original(path, payload, label=label)

    monkeypatch.setattr(service, "_write_immutable", crash_before_turn)

    # Force a real wall-clock second boundary between the crashed reservation and
    # the exact retry -- the PR #3822 CI failure mode. utc_now() truncates to
    # whole seconds, so a retry that mints a fresh timestamp only sometimes lands
    # on a different second than the original attempt; pinning two distinct
    # values here makes the crossing happen on every run instead of by luck.
    reservation_timestamp = "2026-01-01T00:00:00Z"
    retry_timestamp = "2026-01-01T00:00:05Z"
    boundary_timestamps = iter([reservation_timestamp, retry_timestamp])
    monkeypatch.setattr(
        "app.builderops.model_inquiry.utc_now",
        lambda: next(boundary_timestamps),
    )

    with pytest.raises(KeyboardInterrupt, match="simulated process loss"):
        service.commit_turn(
            "inq_test_crash_reservation",
            turn_id="turn-a",
            sequence=0,
            role="reviewer",
            content="Recovered content",
            input_artifact_refs=["question"],
            source_refs=refs,
        )
    with pytest.raises(BuilderOpsValidationError, match=r"orphaned=\['turn-a'\]"):
        service.trace("inq_test_crash_reservation")

    monkeypatch.setattr(service, "_write_immutable", original)
    recovered = service.commit_turn(
        "inq_test_crash_reservation",
        turn_id="turn-a",
        sequence=0,
        role="reviewer",
        content="Recovered content",
        input_artifact_refs=["question"],
        source_refs=refs,
    )
    assert service.trace("inq_test_crash_reservation")["turns"] == [recovered]
    # The retry reproduces the reservation's original identity -- it must not
    # observe the later timestamp a fresh utc_now() call would have minted.
    assert recovered["created_at"] == reservation_timestamp


def test_legacy_orphaned_reservation_without_created_at_is_retryable(
    tmp_path: Path, monkeypatch
) -> None:
    """A reservation written before created_at joined the schema (pre-#3833 fix)
    has only 5 keys, with no way to recover its original created_at from the
    one-way artifact_hash it already committed to. Unconditionally requiring
    created_at on every retry write would make such a reservation permanently
    unretryable the instant this fix ships -- worse than its pre-fix odds. An
    exact retry must still be able to succeed (reproducing the pre-fix
    same-timestamp-luck outcome), not fail closed forever."""
    env = _env(tmp_path)
    service = ModelInquiryService.from_env(env)
    refs = [{"ref_type": "github_issue", "ref": "#3290"}]
    service.start(
        question="Recover a legacy reservation",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_legacy_orphan",
        source_refs=refs,
    )
    original = service._write_immutable

    def crash_before_turn(path, payload, *, label):
        if label == "immutable turn artifact":
            raise KeyboardInterrupt("simulated process loss")
        return original(path, payload, label=label)

    # Freeze utc_now() so the crash attempt and the later retry compute the same
    # created_at -- reproducing the pre-fix "got lucky, same timestamp" case this
    # test isolates, rather than re-testing the separate timestamp-boundary bug
    # AC1's regression already covers.
    frozen_timestamp = "2020-01-01T00:00:00Z"
    monkeypatch.setattr(service, "_write_immutable", crash_before_turn)
    monkeypatch.setattr("app.builderops.model_inquiry.utc_now", lambda: frozen_timestamp)
    with pytest.raises(KeyboardInterrupt, match="simulated process loss"):
        service.commit_turn(
            "inq_test_legacy_orphan",
            turn_id="turn-legacy",
            sequence=0,
            role="reviewer",
            content="Recovered legacy content",
            input_artifact_refs=["question"],
            source_refs=refs,
        )
    monkeypatch.setattr(service, "_write_immutable", original)

    # Downgrade the fix-shipped reservation to the pre-#3833 shape: strip
    # created_at but keep the artifact_hash that already encodes it, exactly
    # what a genuinely pre-fix crash would have left on disk.
    reservation_path = (
        Path(env["BUILDEROPS_VAULT_ROOT"])
        / "model-inquiries"
        / "inq_test_legacy_orphan"
        / "turn-ids"
        / "turn-legacy.json"
    )
    legacy_reservation = json.loads(reservation_path.read_text(encoding="utf-8"))
    assert "created_at" in legacy_reservation
    del legacy_reservation["created_at"]
    reservation_path.write_text(
        json.dumps(legacy_reservation, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(BuilderOpsValidationError, match=r"orphaned=\['turn-legacy'\]"):
        service.trace("inq_test_legacy_orphan")

    recovered = service.commit_turn(
        "inq_test_legacy_orphan",
        turn_id="turn-legacy",
        sequence=0,
        role="reviewer",
        content="Recovered legacy content",
        input_artifact_refs=["question"],
        source_refs=refs,
    )
    assert service.trace("inq_test_legacy_orphan")["turns"] == [recovered]
    # The reservation stays in its legacy 5-key shape -- this fix does not
    # retroactively upgrade pre-existing durable data.
    committed_reservation = json.loads(reservation_path.read_text(encoding="utf-8"))
    assert "created_at" not in committed_reservation


def test_turn_transaction_is_serialized_across_service_instances(tmp_path: Path, monkeypatch) -> None:
    env = _env(tmp_path)
    first = ModelInquiryService.from_env(env)
    second = ModelInquiryService.from_env(env)
    refs = [{"ref_type": "github_issue", "ref": "#3290"}]
    first.start(
        question="Serialize reservation cleanup",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_serialized",
        source_refs=refs,
    )
    first_entered = Event()
    release_first = Event()
    second_entered = Event()
    first_original = first._commit_turn_locked
    second_original = second._commit_turn_locked

    def hold_first(*args, **kwargs):
        first_entered.set()
        assert release_first.wait(2)
        return first_original(*args, **kwargs)

    def observe_second(*args, **kwargs):
        second_entered.set()
        return second_original(*args, **kwargs)

    monkeypatch.setattr(first, "_commit_turn_locked", hold_first)
    monkeypatch.setattr(second, "_commit_turn_locked", observe_second)

    def commit(service: ModelInquiryService, turn_id: str, sequence: int) -> object:
        try:
            return service.commit_turn(
                "inq_test_serialized",
                turn_id=turn_id,
                sequence=sequence,
                role="reviewer",
                content=f"Candidate {turn_id}",
                input_artifact_refs=["question"],
                source_refs=refs,
            )
        except BuilderOpsConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        pending_first = executor.submit(commit, first, "turn-a", 0)
        assert first_entered.wait(2)
        pending_second = executor.submit(commit, second, "turn-b", 0)
        assert not second_entered.wait(0.1)
        release_first.set()
        results = [pending_first.result(), pending_second.result()]

    assert second_entered.is_set()
    assert sum(isinstance(result, BuilderOpsConflictError) for result in results) == 1
    inquiry = Path(env["BUILDEROPS_VAULT_ROOT"]) / "model-inquiries" / "inq_test_serialized"
    assert len(list((inquiry / "turn-ids").glob("*.json"))) == 1
    assert len(first.trace("inq_test_serialized")["turns"]) == 1

    # A distinct service instance retains exactly one committed turn per
    # identity/sequence even across an orphaned reservation: a non-exact retry
    # (same turn_id/sequence, different content) against the other instance's
    # orphaned reservation still fails closed, while an exact retry from that
    # other instance reproduces the durably reserved artifact. Proven under
    # genuine concurrent contention -- a Barrier-released real-thread race, not
    # one fixed sequential event order -- so the flock's serialization is what
    # is exercised, not just the state machine's logic for a chosen ordering.
    orphan_turn_id = "turn-c"
    orphan_sequence = 1
    original_write_immutable = first._write_immutable

    def crash_before_turn(path, payload, *, label):
        if label == "immutable turn artifact":
            raise KeyboardInterrupt("simulated process loss")
        return original_write_immutable(path, payload, label=label)

    # Frozen (not advancing) on purpose: this sub-test's job is to prove
    # cross-instance retry safety under a genuine race, a concern orthogonal to
    # timestamp-boundary determinism, which test_crashed_turn_reservation_is_
    # visible_and_retryable already covers. A single frozen value also removes
    # any dependency on which racing thread's utc_now() call runs first.
    reservation_timestamp = "2026-02-01T00:00:00Z"
    monkeypatch.setattr(first, "_write_immutable", crash_before_turn)
    monkeypatch.setattr("app.builderops.model_inquiry.utc_now", lambda: reservation_timestamp)
    with pytest.raises(KeyboardInterrupt, match="simulated process loss"):
        first.commit_turn(
            "inq_test_serialized",
            turn_id=orphan_turn_id,
            sequence=orphan_sequence,
            role="reviewer",
            content="Original candidate",
            input_artifact_refs=["question"],
            source_refs=refs,
        )
    monkeypatch.setattr(first, "_write_immutable", original_write_immutable)

    race_barrier = Barrier(2)
    race_results: dict[str, object] = {}

    def race_exact() -> None:
        race_barrier.wait(timeout=2)
        try:
            race_results["exact"] = second.commit_turn(
                "inq_test_serialized",
                turn_id=orphan_turn_id,
                sequence=orphan_sequence,
                role="reviewer",
                content="Original candidate",
                input_artifact_refs=["question"],
                source_refs=refs,
            )
        except BuilderOpsConflictError as exc:
            race_results["exact"] = exc

    def race_divergent() -> None:
        race_barrier.wait(timeout=2)
        try:
            race_results["divergent"] = first.commit_turn(
                "inq_test_serialized",
                turn_id=orphan_turn_id,
                sequence=orphan_sequence,
                role="reviewer",
                content="Different candidate",
                input_artifact_refs=["question"],
                source_refs=refs,
            )
        except BuilderOpsConflictError as exc:
            race_results["divergent"] = exc

    # Both threads block on the barrier and are released at the same instant,
    # so their flock/RLock acquisition attempts genuinely overlap regardless of
    # which one the scheduler happens to grant the lock to first -- both
    # possible orderings must converge on the same correct outcome.
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending_exact = executor.submit(race_exact)
        pending_divergent = executor.submit(race_divergent)
        pending_exact.result(timeout=5)
        pending_divergent.result(timeout=5)

    assert isinstance(race_results["divergent"], BuilderOpsConflictError)
    recovered = race_results["exact"]
    assert isinstance(recovered, dict)
    assert recovered["turn_id"] == orphan_turn_id
    assert recovered["created_at"] == reservation_timestamp
    committed_turns = second.trace("inq_test_serialized")["turns"]
    assert [turn["turn_id"] for turn in committed_turns].count(orphan_turn_id) == 1
    orphan_turn = next(turn for turn in committed_turns if turn["turn_id"] == orphan_turn_id)
    assert orphan_turn["content"] == "Original candidate"


def test_turn_transaction_is_serialized_across_processes(tmp_path: Path) -> None:
    env = _env(tmp_path)
    service = ModelInquiryService.from_env(env)
    service.start(
        question="Serialize separate workers",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_process_lock",
        source_refs=[{"ref_type": "github_issue", "ref": "#3290"}],
    )
    context = multiprocessing.get_context("spawn")
    messages = context.Queue()
    process = context.Process(target=_commit_turn_in_process, args=(env, messages))

    with service._inquiry_process_lock("inq_test_process_lock"):
        process.start()
        assert messages.get(timeout=5) == "started"
        with pytest.raises(Empty):
            messages.get(timeout=0.2)

    assert messages.get(timeout=5) == "committed"
    process.join(timeout=5)
    assert process.exitcode == 0
    assert [turn["turn_id"] for turn in service.trace("inq_test_process_lock")["turns"]] == [
        "turn-a"
    ]


def test_inquiry_run_dry_run_uses_common_runner(tmp_path: Path) -> None:
    env = _env(tmp_path)
    env[INQUIRY_INTENT_CONFIG_ENV] = ""
    service = ModelInquiryService.from_env(env)
    service.start(
        question="Plan without provider calls",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_cli_run",
        source_refs=[{"ref_type": "github_issue", "ref": "#3291"}],
    )
    before = service.trace("inq_test_cli_run")

    result = CliRunner().invoke(
        builderops_root,
        [
            "builderops",
            "inquiry",
            "run",
            "inq_test_cli_run",
            "--dry-run",
            "--max-rounds",
            "2",
            "--json",
        ],
        env=env,
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["unavailable_roles"] == ["fable", "gpt_codex"]
    assert ModelInquiryService.from_env(env).trace("inq_test_cli_run") == before


def test_inquiry_start_honors_group_db_path_without_host_ack(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"
    vault.mkdir()
    question = tmp_path / "question.md"
    question.write_text("Which store should this inquiry use?", encoding="utf-8")
    explicit_db = tmp_path / "pinned" / "builderops.sqlite3"
    env = {
        "BUILDEROPS_VAULT_ROOT": str(vault),
        "HOME": str(tmp_path / "home-without-cutover-marker"),
    }

    result = CliRunner().invoke(
        builderops_root,
        [
            "builderops",
            "--db-path",
            str(explicit_db),
            "inquiry",
            "start",
            "--question-file",
            str(question),
            "--workflow",
            "fable-gpt-architecture",
            "--inquiry-id",
            "inq_test_explicit_db_bypass",
            "--json",
        ],
        env=env,
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert (
        json.loads(result.output)["inquiry"]["inquiry_id"]
        == "inq_test_explicit_db_bypass"
    )
