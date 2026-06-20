"""Tests for index rebuild CLI resilience via embed_with_retry.

AC7: index rebuild continues past per-object embed dead-letter.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from click.testing import CliRunner

from app.llm.embed_queue import EmbedDeadLetterError
from app.objects import DomainObject, ObjectStore
from app.store import object_store as legacy_store
from app.stores import reset_store_backends


def _seed_object(text: str, *, source_ref: str = "vault/test.md") -> str:
    store = ObjectStore()
    obj_id = uuid4()
    store.save_object(
        DomainObject(
            uuid=str(obj_id),
            kind="note",
            payload={"text": text, "content": text},
            source_ref=source_ref,
            created_at=datetime.now(timezone.utc),
        ),
        emit_outbox=False,
        trace_id="trace-seed",
    )
    return str(obj_id)


# ---------------------------------------------------------------------------
# test_rebuild_completes_with_one_bad_note
#   AC7: one note dead-letters, rebuild records the failure and continues.
#   The canonical name from the issue's committed Verify targets.
# ---------------------------------------------------------------------------

def test_rebuild_completes_with_one_bad_note(monkeypatch, tmp_path):
    """One note causes EmbedDeadLetterError; rebuild records it and processes the rest."""
    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")
    monkeypatch.setenv("EMBED_RETRY_MAX", "1")
    monkeypatch.setenv("EMBED_RETRY_BASE_BACKOFF_S", "0.0")

    _seed_object("good note content", source_ref="vault/good.md")
    _seed_object("bad note content", source_ref="vault/bad.md")

    failures_path = tmp_path / "rebuild-failures.jsonl"

    call_count = 0

    def controlled_embed(
        text,
        *,
        provider=None,
        model=None,
        dim=None,
        normalize=True,
        object_id=None,
        embed_callable=None,
        dead_letter_on_exhaustion=True,
        max_attempts=None,
        _sleep=True,
    ):
        nonlocal call_count
        call_count += 1
        # First call fails (bad note), second succeeds (good note)
        if call_count == 1:
            raise EmbedDeadLetterError("embed exhausted after 1 attempts (transient): EOF")
        # Return a plausible mock vector
        return [0.1] * (dim or 8)

    from app.cli import cli

    with patch("app.cli.index_rebuild.embed_with_retry", side_effect=controlled_embed):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["index", "rebuild", "--backend", "memory", "--json", "--failures-path", str(failures_path)],
        )

    assert result.exit_code == 0, f"CLI exited non-zero: {result.output}\n{result.exception}"

    summary = json.loads(result.output)
    assert summary["total_objects"] == 2
    assert summary["processed"] == 1, f"Expected 1 processed, got {summary['processed']}"
    assert summary["error_count"] == 1, f"Expected 1 error, got {summary['error_count']}"

    errors = summary.get("errors", [])
    assert len(errors) == 1
    assert errors[0]["stage"] == "embed"
    assert errors[0]["exception_type"] == "EmbedDeadLetterError"
    assert errors[0]["retryable"] is True

    # JSONL failure file should have one record
    assert failures_path.exists(), "Failures JSONL was not written"
    lines = failures_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["stage"] == "embed"
    assert record["exception_type"] == "EmbedDeadLetterError"

    legacy_store._MEMORY_STORE.clear()


def test_rebuild_deterministic_profile_uses_resolved_client(monkeypatch):
    """`index rebuild --profile deterministic` must embed via the resolved
    deterministic client, not _embed_single (which only knows PROVIDER_REGISTRY
    adapters and would record every object as an embed failure). Regression guard
    for the Codex review on PR #2298 (rebuild embedding-client seam)."""
    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("EMBED_DIM", "8")
    monkeypatch.setenv("EMBED_RETRY_MAX", "1")
    monkeypatch.setenv("EMBED_RETRY_BASE_BACKOFF_S", "0.0")

    _seed_object("first deterministic note", source_ref="vault/d1.md")
    _seed_object("second deterministic note", source_ref="vault/d2.md")

    from app.cli import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["index", "rebuild", "--backend", "memory", "--json", "--profile", "deterministic"],
    )

    assert result.exit_code == 0, f"CLI exited non-zero: {result.output}\n{result.exception}"
    summary = json.loads(result.output)
    assert summary["total_objects"] == 2
    assert summary["processed"] == 2, f"deterministic rebuild should embed all objects, got {summary}"
    assert summary["error_count"] == 0, f"deterministic rebuild produced embed failures: {summary.get('errors')}"

    legacy_store._MEMORY_STORE.clear()


def test_rebuild_max_retries_wires_embed_attempt_budget(monkeypatch):
    """`index rebuild --max-retries N` must control embed attempts (N+1), not just
    upsert — embed_with_retry receives max_attempts. Regression guard for the Codex
    review on PR #2298 (rebuild retry options ignored for embeddings)."""
    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")
    # EMBED_RETRY_MAX would say 5, but --max-retries 0 must win (=> 1 attempt).
    monkeypatch.setenv("EMBED_RETRY_MAX", "5")

    _seed_object("retry-budget note", source_ref="vault/r.md")

    seen: list = []

    def capture_embed(text, **kwargs):
        seen.append(kwargs.get("max_attempts"))
        return [0.1] * 8

    from app.cli import cli

    with patch("app.cli.index_rebuild.embed_with_retry", side_effect=capture_embed):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["index", "rebuild", "--backend", "memory", "--json", "--max-retries", "0"],
        )

    assert result.exit_code == 0, f"CLI exited non-zero: {result.output}\n{result.exception}"
    assert seen == [1], f"--max-retries 0 should pass max_attempts=1 to embed_with_retry, got {seen}"

    legacy_store._MEMORY_STORE.clear()
