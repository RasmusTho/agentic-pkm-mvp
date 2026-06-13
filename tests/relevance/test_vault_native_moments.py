"""CRE-03 first runtime slice: vault-native moments, pull-only, governed.

Verifies the moment is computed from vault data and materialized as the CRE-01
artifact with provenance + a receipt via the write guard, and that the slice
reads no external source and emits no notification.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from app.relevance import (
    DeterministicRelevanceEvaluator,
    collect_now_moments,
    materialize_moment,
    query_moment_receipts,
)
from app.vault.manager import VaultContext

TODAY = date(2026, 6, 13)


def _build_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    daily = vault / "Daily" / f"{TODAY.isoformat()}.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text(
        "---\nuuid: daily-uuid\n---\n\n# 2026-06-13\n\nleave_point: mid-review of the gate\n",
        encoding="utf-8",
    )
    note = vault / "Projects" / "Contextual Relevance Engine.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\nuuid: cre-uuid\ndue: 2026-06-15\n---\n\n# CRE\n\n- [ ] finish the scarcity gate\n",
        encoding="utf-8",
    )
    return vault


def _vault_context(vault: Path) -> VaultContext:
    return VaultContext(status="selected", active_vault_id="v1", active_vault_path=str(vault))


def _frontmatter(text: str) -> dict:
    assert text.startswith("---")
    _, fm, _body = text.split("---", 2)
    return yaml.safe_load(fm)


def test_moment_materialized_from_vault_with_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _build_vault(tmp_path)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    receipts = tmp_path / "moment_receipts.jsonl"

    moments = DeterministicRelevanceEvaluator(vault, today=TODAY).evaluate()
    assert moments, "evaluator should compute at least one moment from vault data"

    result = materialize_moment(
        moments[0], vault_context=_vault_context(vault), outbox_path=receipts
    )

    # Materialized as the CRE-01 artifact in the system plane, with provenance.
    assert result.status == "materialized"
    assert result.artifact_path is not None
    artifact = vault / result.artifact_path
    assert artifact.is_file()
    assert "/moments/" in result.artifact_path

    frontmatter = _frontmatter(artifact.read_text(encoding="utf-8"))
    assert frontmatter["type"] == "moment"
    assert frontmatter["authority"] == "non-authoritative"
    assert frontmatter["authority_class"] == "proposal"
    assert frontmatter["receipt_ref"] == result.receipt_id
    # Provenance: source-linked surfaced refs + producing evaluator recorded.
    assert frontmatter["surfaced_refs"], "moment must carry source-linked refs"
    assert frontmatter["provenance"]["produced_by"]

    # Receipt exists, is queryable, and references the artifact (via the write guard).
    rows = query_moment_receipts(outbox_path=receipts, artifact_path=result.artifact_path)
    assert len(rows) == 1
    receipt_record = rows[0]
    assert receipt_record["payload"]["receipt_id"] == result.receipt_id
    assert receipt_record["payload"]["artifact_uuid"] == result.moment_uuid
    assert receipt_record["payload"]["outcome"]["status"] == "applied"


def test_no_external_source_and_no_notification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _build_vault(tmp_path)
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    receipts = tmp_path / "moment_receipts.jsonl"

    moments = DeterministicRelevanceEvaluator(vault, today=TODAY).evaluate()
    assert moments
    moment = moments[0]

    # No external source: every surfaced reference is a vault-relative path.
    for ref in moment.surfaced_refs:
        assert not ref.ref.startswith(("http://", "https://", "//"))
        assert (vault / ref.ref).exists(), f"surfaced ref must be vault-native: {ref.ref}"

    result = materialize_moment(
        moment, vault_context=_vault_context(vault), outbox_path=receipts
    )
    assert result.status == "materialized"

    # No notification: every emitted record is an Act-tier materialization, never
    # a push/notification/alert. Surfacing presence is not a reach-out.
    raw = receipts.read_text(encoding="utf-8")
    for token in ("push", "notify", "notification", "alert"):
        assert token not in raw.lower(), f"slice must emit no {token} signal"
    rows = query_moment_receipts(outbox_path=receipts)
    assert rows and all(row["event"] == "moment.materialized" for row in rows)
    assert all(row["payload"]["governance_tier"] == "act" for row in rows)

    # The glance projection is pull-only: rendering it reads, never reaches out.
    views = collect_now_moments(_vault_context(vault))
    assert views and views[0]["moment_id"] == result.moment_uuid
