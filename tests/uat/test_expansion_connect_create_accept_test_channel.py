"""No-mock, opt-in UAT for the isolated Connect -> Create -> Accept path.

This module deliberately uses the live test-channel retrieval, WriteGuard, and
vault paths.  It never substitutes a retrieval result, embedding provider,
write guard, or acceptance function.  The final checkbox is intentionally a
separate human-operated phase; see the companion runbook.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from app.expansion.accept import DraftNotAcceptedError, accept_draft
from app.expansion.connect import run_connect_pass
from app.expansion.create import CreateRequest, OutputKind, SourceInput, run_create_pass
from app.retrieval.capability import RetrievalRequest, retrieve
from scripts.yaml_roundtrip import load_frontmatter


RUN_ENV = "RUN_EXPANSION_CONNECT_CREATE_ACCEPT_UAT"
HUMAN_ACCEPT_ENV = "RUN_EXPANSION_CONNECT_CREATE_ACCEPT_HUMAN_ACCEPT"
EXPECTED_IDENTITY = {
    "provider": "ollama",
    "model": "bge-m3:latest",
    "dim": 1024,
    "normalize": True,
}

pytestmark = pytest.mark.uat_integrated_runtime

_TEST_CHANNEL_ENV_KEYS = (
    "PKM_ENVIRONMENT",
    "PKM_CHANNEL",
    "DATABASE_URL",
    "DB_DSN",
    "STORE_BACKEND",
    "INDEX_OUTBOX_PATH",
    "LLM_FORCE_PROVIDER",
    "LLM_FORCE_MODEL",
    "LLM_PROVIDER_ENFORCE",
    "LLM_PROVIDER",
    "LLM_CHAT_MODEL",
    "LLM_EMBED_MODEL",
)
# Capture only channel/runtime selectors before the root autouse fixture replaces
# ordinary tests' DB and LLM settings.  VAULT_ROOT is intentionally absent: the
# root conftest removes it at collection time, and this UAT derives it solely
# from VAULT_ROOT_TEST below.
_TEST_CHANNEL_ENV = {name: os.getenv(name) for name in _TEST_CHANNEL_ENV_KEYS}


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        pytest.fail(f"{name} is required for this no-mock test-channel UAT")
    return value


def _json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _test_channel_subprocess_env(vault_root: Path) -> dict[str, str]:
    """Bind subprocesses to the already-proven test vault, never an operator vault."""
    environment = os.environ.copy()
    environment["VAULT_ROOT"] = str(vault_root)
    environment["VAULT_ROOT_TEST"] = str(vault_root)
    return environment


def _restore_test_channel_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in _TEST_CHANNEL_ENV.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def _outside_ai_blocks(text: str) -> str:
    """Remove only Panel proposal blocks to compare canonical note content."""
    result: list[str] = []
    in_block = False
    for line in text.splitlines(keepends=True):
        if line.strip() == "%% AI:Start %%":
            in_block = True
            continue
        if line.strip() == "%% AI:End %%":
            in_block = False
            continue
        if not in_block:
            result.append(line)
    assert not in_block, "source note ended with an unterminated AI proposal block"
    return "".join(result)


@dataclass(frozen=True)
class UatContext:
    vault_root: Path
    outbox_path: Path
    source_paths: tuple[Path, ...]
    sources: tuple[SourceInput, ...]
    connect_query: str
    receipt_path: Path

    def receipt(self) -> dict[str, Any]:
        return _json(self.receipt_path)

    def record(self, **values: Any) -> None:
        receipt = self.receipt()
        receipt.update(values)
        receipt["contract"] = "expansion-connect-create-accept-test-channel.v1"
        _write_json(self.receipt_path, receipt)


@pytest.fixture
def uat_context(monkeypatch: pytest.MonkeyPatch) -> UatContext:
    if not _enabled(RUN_ENV):
        pytest.skip(f"opt-in no-mock UAT; set {RUN_ENV}=1 after test-channel bootstrap")

    _restore_test_channel_env(monkeypatch)
    test_root = Path(_required_env("VAULT_ROOT_TEST")).expanduser().resolve()
    assert os.getenv("PKM_ENVIRONMENT") == "test"
    assert os.getenv("PKM_CHANNEL") == "test"
    assert "app_test" in (os.getenv("DATABASE_URL") or os.getenv("DB_DSN") or "")
    assert test_root.is_dir() and test_root.name != "", "test vault must exist"

    # The root conftest deliberately removes VAULT_ROOT before every test to
    # protect the operator vault.  Rebind it only here, after that autouse
    # sanitization, from the independently required test-scoped selector.
    # The production APIs below still receive vault_root explicitly.
    monkeypatch.setenv("VAULT_ROOT", str(test_root))
    vault_root = test_root
    subprocess_env = _test_channel_subprocess_env(vault_root)

    preflight = subprocess.run(
        [sys.executable, "-m", "app.cli", "ops", "channel-preflight", "--channel", "test", "--context", "host"],
        check=False,
        capture_output=True,
        text=True,
        env=subprocess_env,
    )
    assert preflight.returncode == 0, preflight.stdout + preflight.stderr

    raw_sources = [item.strip() for item in _required_env("UAT_EXPANSION_SOURCE_PATHS").split(",") if item.strip()]
    assert len(raw_sources) >= 2, "UAT_EXPANSION_SOURCE_PATHS must name at least two indexed source notes"
    source_paths: list[Path] = []
    sources: list[SourceInput] = []
    for relative in raw_sources:
        candidate = (vault_root / relative).resolve()
        assert candidate.is_relative_to(vault_root), f"source escapes test vault: {relative}"
        assert "_system/drafts" not in candidate.relative_to(vault_root).as_posix()
        text = candidate.read_text(encoding="utf-8")
        frontmatter, body = load_frontmatter(text)
        object_id = str(frontmatter.get("uuid") or candidate.relative_to(vault_root).as_posix())
        quoted = next((line.strip() for line in body.splitlines() if line.strip() and not line.startswith("#")), None)
        assert quoted, f"source lacks a quotable body span: {relative}"
        source_paths.append(candidate)
        sources.append(
            SourceInput(
                object_id=object_id,
                note_path=candidate.relative_to(vault_root).as_posix(),
                text=text,
                quoted_spans=(quoted,),
                language=str(frontmatter.get("language") or "und"),
                review_state=str(frontmatter.get("review_state") or "reviewed"),
            )
        )

    run_id = _required_env("UAT_EXPANSION_RUN_ID")
    assert all(ch.isalnum() or ch in "-_" for ch in run_id), "UAT_EXPANSION_RUN_ID must be filesystem-safe"
    return UatContext(
        vault_root=vault_root,
        outbox_path=Path(_required_env("INDEX_OUTBOX_PATH")).expanduser().resolve(),
        source_paths=tuple(source_paths),
        sources=tuple(sources),
        connect_query=_required_env("UAT_EXPANSION_CONNECT_QUERY"),
        receipt_path=vault_root / "_system" / "receipts" / f"expansion-connect-create-accept-{run_id}.json",
    )


def test_test_channel_subprocess_env_binds_vault_root_to_test_root(tmp_path: Path) -> None:
    test_root = tmp_path / "vault-test"
    environment = _test_channel_subprocess_env(test_root)

    assert environment["VAULT_ROOT"] == str(test_root)
    assert environment["VAULT_ROOT_TEST"] == str(test_root)


def test_test_channel_env_restore_survives_root_sanitization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(_TEST_CHANNEL_ENV, "DATABASE_URL", "postgresql://app:app@127.0.0.1:15434/app_test")
    monkeypatch.setitem(_TEST_CHANNEL_ENV, "STORE_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")

    _restore_test_channel_env(monkeypatch)

    assert os.environ["DATABASE_URL"].endswith("/app_test")
    assert os.environ["STORE_BACKEND"] == "postgres"


def test_test_channel_identity_and_doctor_are_strict(uat_context: UatContext) -> None:
    doctor = subprocess.run(
        [sys.executable, "-m", "app.cli", "index", "doctor", "--strict", "--json"],
        check=False,
        capture_output=True,
        text=True,
        env=_test_channel_subprocess_env(uat_context.vault_root),
    )
    assert doctor.returncode == 0, doctor.stdout + doctor.stderr
    report = json.loads(doctor.stdout)
    assert report["expected_identity"] == EXPECTED_IDENTITY
    assert report["stored_identity"] == EXPECTED_IDENTITY
    uat_context.record(technical_phase="doctor_pass", index_doctor=report)


def test_connect_is_candidate_only_and_unchecked(uat_context: UatContext) -> None:
    before = {path: path.read_text(encoding="utf-8") for path in uat_context.source_paths}
    drafts_before = set((uat_context.vault_root / "_system" / "drafts").glob("*.md"))

    report = run_connect_pass(
        vault_root=uat_context.vault_root,
        queries=[uat_context.connect_query],
        outbox_path=uat_context.outbox_path,
    )
    assert report.findings, "live test-channel retrieval produced no Connect candidate"
    assert all(finding.track.value == "propose" for finding in report.findings)

    changed = [path for path, original in before.items() if path.read_text(encoding="utf-8") != original]
    assert changed, "Connect did not materialize its governed candidate checkbox"
    for path in changed:
        after = path.read_text(encoding="utf-8")
        before_frontmatter, _ = load_frontmatter(before[path])
        after_frontmatter, _ = load_frontmatter(after)
        assert before_frontmatter == after_frontmatter
        assert _outside_ai_blocks(before[path]) == _outside_ai_blocks(after)
        assert "- [x]" not in after
        assert "[curation:connect." in after
    assert set((uat_context.vault_root / "_system" / "drafts").glob("*.md")) == drafts_before
    uat_context.record(connect="candidate_propose_unchecked", connect_mutated_sources=[p.relative_to(uat_context.vault_root).as_posix() for p in changed])


def test_create_stages_resolvable_sources_and_excludes_draft_from_retrieval(uat_context: UatContext) -> None:
    request = CreateRequest(
        kind=OutputKind.OVERVIEW,
        title=f"UAT Connect Create Accept {uat_context.receipt_path.stem}",
        sources=uat_context.sources,
        question=uat_context.connect_query,
        trace_id=uat_context.receipt_path.stem,
    )
    report = run_create_pass(request, vault_root=uat_context.vault_root, outbox_path=uat_context.outbox_path)
    assert report.activatable and report.draft_path and report.receipt_id
    draft = uat_context.vault_root / report.draft_path
    frontmatter, _body = load_frontmatter(draft.read_text(encoding="utf-8"))
    assert frontmatter["authority_state"] == "proposal"
    assert frontmatter["sources"] == [source.object_id for source in uat_context.sources]
    assert "- [ ] Accept this draft" in draft.read_text(encoding="utf-8")
    retrieval = retrieve(RetrievalRequest(query=uat_context.connect_query, k=20))
    draft_rel = draft.relative_to(uat_context.vault_root).as_posix()
    assert all(hit.source_ref != draft_rel for hit in retrieval.hits)
    uat_context.record(technical_phase="create_staged", draft_path=report.draft_path, create_receipt_id=report.receipt_id)


def test_accept_rejects_unchecked_checkbox(uat_context: UatContext) -> None:
    draft_path = uat_context.receipt().get("draft_path")
    assert isinstance(draft_path, str), "run the Create technical phase before unchecked acceptance"
    draft = uat_context.vault_root / draft_path
    assert "- [ ] Accept this draft" in draft.read_text(encoding="utf-8")
    canonical_before = {path.relative_to(uat_context.vault_root) for path in uat_context.vault_root.rglob("*.md") if "_system/drafts" not in path.as_posix()}
    with pytest.raises(DraftNotAcceptedError):
        accept_draft(draft, vault_root=uat_context.vault_root, outbox_path=uat_context.outbox_path)
    canonical_after = {path.relative_to(uat_context.vault_root) for path in uat_context.vault_root.rglob("*.md") if "_system/drafts" not in path.as_posix()}
    assert canonical_after == canonical_before
    assert draft.exists()
    uat_context.record(technical_phase="pass", unchecked_acceptance="rejected", human_checkbox_result="pending")


def test_checked_checkbox_uses_only_governed_materialization_path(uat_context: UatContext) -> None:
    if not _enabled(HUMAN_ACCEPT_ENV):
        pytest.skip(f"human-only phase; set {HUMAN_ACCEPT_ENV}=1 after checking exactly one staged draft checkbox")
    draft_path = uat_context.receipt().get("draft_path")
    assert isinstance(draft_path, str), "technical receipt does not name a staged draft"
    draft = uat_context.vault_root / draft_path
    text = draft.read_text(encoding="utf-8")
    assert text.count("- [x] Accept this draft") == 1
    assert "- [ ] Accept this draft" not in text
    result = accept_draft(draft, vault_root=uat_context.vault_root, outbox_path=uat_context.outbox_path)
    assert result.status == "accepted" and result.final_note_path and result.receipt_id
    final = uat_context.vault_root / result.final_note_path
    frontmatter, _body = load_frontmatter(final.read_text(encoding="utf-8"))
    assert frontmatter["sources"] == [source.object_id for source in uat_context.sources]
    assert frontmatter["accepted_by"] == "human"
    assert frontmatter["acceptance_receipt_id"] == result.receipt_id
    uat_context.record(human_checkbox_result="accepted", final_note_path=result.final_note_path, acceptance_receipt_id=result.receipt_id)
