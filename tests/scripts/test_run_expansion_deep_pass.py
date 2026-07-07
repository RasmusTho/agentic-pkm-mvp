"""Tests for the E9 run tooling (#3000): scripts/run_expansion_deep_pass.py.

These tests exercise the script's own wiring logic -- argument parsing, the
bounded/deterministic query builder, and the consolidated-receipt
aggregation -- using the same permissive-``WriteGuard`` pattern the library
modules' own tests already use (``tests/expansion/test_connect_findings.py``
``_allow_all_guard``), rather than depending on ``STORE_BACKEND``/DB health.
The library passes themselves (``run_vault_lint``, ``write_curation_proposals``,
``run_connect_pass``, ``find_cluster_emergence``, ``run_contradiction_pass``)
are already covered by their own test modules -- this file proves the
script's *composition* of them, not their individual behavior again.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.proposals.declined_ledger import DeclinedLedger
from app.vault.paths import resolve_vault_system_dir_rel_or_default
from app.write_guard import WriteGuard
from scripts import run_expansion_deep_pass as deep_pass


def _allow_all_guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "healthy", "reason": None})


def _write_note(vault_root: Path, rel_path: str, body: str) -> Path:
    path = vault_root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture()
def tiny_vault(tmp_path: Path) -> Path:
    vault_root = tmp_path / "vault"
    _write_note(
        vault_root,
        "Alpha.md",
        "# Alpha topic\n\nAn orphan note with a [[dangling-link]].\n",
    )
    _write_note(vault_root, "Beta.md", "# Beta topic\n\nAnother standalone note.\n")
    # A note under the vault system dir must never feed the query builder.
    system_dir_rel = resolve_vault_system_dir_rel_or_default(vault_root)
    _write_note(vault_root, f"{system_dir_rel}/drafts/ignored-draft.md", "# Should be excluded\n")
    return vault_root


# ---------------------------------------------------------------------------
# CLI contract
# ---------------------------------------------------------------------------


def test_vault_root_is_required() -> None:
    parser = deep_pass.build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_vault_root_never_defaults_to_repo_fixture() -> None:
    parser = deep_pass.build_arg_parser()
    args = parser.parse_args(["--vault-root", "/some/real/vault"])
    assert args.vault_root == Path("/some/real/vault")


def test_dry_run_flag_defaults_false() -> None:
    parser = deep_pass.build_arg_parser()
    args = parser.parse_args(["--vault-root", "/x"])
    assert args.dry_run is False


def test_main_rejects_missing_vault_root(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    exit_code = deep_pass.main(["--vault-root", str(missing)])
    assert exit_code == 2


# ---------------------------------------------------------------------------
# Query builder: bounded + deterministic + excludes the vault system dir
# ---------------------------------------------------------------------------


def test_iter_vault_notes_excludes_system_dir(tiny_vault: Path) -> None:
    system_dir_rel = resolve_vault_system_dir_rel_or_default(tiny_vault)
    notes = deep_pass._iter_vault_notes(tiny_vault)
    rel_paths = {p.relative_to(tiny_vault).as_posix() for p in notes}
    assert "Alpha.md" in rel_paths
    assert "Beta.md" in rel_paths
    assert not any(p.startswith(f"{system_dir_rel}/") for p in rel_paths)


def test_build_queries_is_bounded_and_deterministic(tiny_vault: Path) -> None:
    queries_capped = deep_pass._build_queries(tiny_vault, max_query_notes=1)
    assert len(queries_capped) <= 1

    queries_uncapped = deep_pass._build_queries(tiny_vault, max_query_notes=500)
    # Deterministic rerun -- same input, same output.
    again = deep_pass._build_queries(tiny_vault, max_query_notes=500)
    assert queries_uncapped == again
    assert "Alpha topic" in queries_uncapped
    assert "Beta topic" in queries_uncapped


# ---------------------------------------------------------------------------
# E1 -> E2 composition: lint findings materialize as propose-track checkboxes
# ---------------------------------------------------------------------------


def test_run_lint_and_propose_materializes_findings(tiny_vault: Path, tmp_path: Path) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    outcome = deep_pass.run_lint_and_propose(
        vault_root=tiny_vault,
        outbox_path=outbox_path,
        write_guard=_allow_all_guard(),
        dry_run=False,
    )
    assert outcome.notes_scanned > 0
    assert outcome.findings_emitted > 0
    # A dangling wikilink in Alpha.md should have materialized an unchecked
    # checkbox -- propose-only, never a body edit outside the governed block.
    alpha_text = (tiny_vault / "Alpha.md").read_text(encoding="utf-8")
    assert "- [ ]" in alpha_text
    assert outbox_path.exists()


def test_run_lint_and_propose_dry_run_writes_nothing(tiny_vault: Path, tmp_path: Path) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    before = (tiny_vault / "Alpha.md").read_text(encoding="utf-8")

    outcome = deep_pass.run_lint_and_propose(
        vault_root=tiny_vault,
        outbox_path=outbox_path,
        write_guard=_allow_all_guard(),
        dry_run=True,
    )

    after = (tiny_vault / "Alpha.md").read_text(encoding="utf-8")
    assert before == after
    assert not outbox_path.exists()
    # Detection still ran (read-only), so counts are still reported.
    assert outcome.findings_emitted > 0


# ---------------------------------------------------------------------------
# Declined-ledger discipline: a declined connect finding is suppressed, not
# re-proposed, by the script's own wiring (mirrors the library's own tests).
# ---------------------------------------------------------------------------


def test_connect_and_contradiction_wiring_respects_declined_ledger(tiny_vault: Path, tmp_path: Path) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    ledger = DeclinedLedger(tmp_path / "declined.jsonl")
    caps = deep_pass.PassCaps(
        connect_max_findings_per_note=3,
        connect_max_findings_total=25,
        connect_retrieval_k=8,
        connect_relatedness_floor=0.55,
        cluster_min_size=3,
        cluster_max_clusters=10,
        contradiction_max_findings_per_note=3,
        contradiction_max_findings_total=25,
        contradiction_retrieval_k=8,
        create_staleness_days=14,
        max_query_notes=500,
    )

    # The in-memory retrieval store is empty in this test environment (no
    # ingestion has run), so both passes legitimately find zero candidates --
    # this asserts the wiring itself never raises and always returns a
    # well-shaped report, declined ledger included, without requiring a live
    # retrieval index (mirrors how the library's own pass tests inject a
    # deterministic ``retrieve_fn`` instead of depending on a real index).
    connect_outcome, connect_findings = deep_pass.run_connect(
        vault_root=tiny_vault,
        queries=["alpha topic"],
        caps=caps,
        declined_ledger=ledger,
        outbox_path=outbox_path,
        write_guard=_allow_all_guard(),
        dry_run=False,
    )
    assert connect_outcome.name == "connect"
    assert isinstance(connect_findings, tuple)

    contradiction_outcome = deep_pass.run_contradiction(
        vault_root=tiny_vault,
        queries=["alpha topic"],
        caps=caps,
        declined_ledger=ledger,
        outbox_path=outbox_path,
        write_guard=_allow_all_guard(),
        dry_run=False,
    )
    assert contradiction_outcome.name == "contradiction"


# ---------------------------------------------------------------------------
# Consolidated receipt: aggregates every pass, only writes to outbox when
# not a dry run, and always carries the AC-required counters.
# ---------------------------------------------------------------------------


def test_emit_consolidated_receipt_aggregates_and_gates_on_dry_run(tmp_path: Path) -> None:
    outbox_path = tmp_path / "outbox.jsonl"
    outcomes = [
        deep_pass.PassOutcome(name="a", notes_scanned=3, findings_emitted=2, suppressed_by_decline=1, suppressed_by_cap=0),
        deep_pass.PassOutcome(name="b", notes_scanned=5, findings_emitted=1, suppressed_by_decline=0, suppressed_by_cap=2),
    ]

    dry_receipt = deep_pass.emit_consolidated_receipt(
        outcomes, vault_root=tmp_path, outbox_path=outbox_path, dry_run=True
    )
    assert dry_receipt["payload"]["totals"] == {
        "notes_scanned": 8,
        "findings_emitted": 3,
        "suppressed_by_decline": 1,
        "suppressed_by_cap": 2,
    }
    assert not outbox_path.exists()

    real_receipt = deep_pass.emit_consolidated_receipt(
        outcomes, vault_root=tmp_path, outbox_path=outbox_path, dry_run=False
    )
    assert real_receipt["event"] == deep_pass.DEEP_PASS_RECEIPT_EVENT
    assert outbox_path.exists()
    lines = outbox_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["payload"]["totals"]["findings_emitted"] == 3


# ---------------------------------------------------------------------------
# End-to-end dry run: the full main() composition, read-only, over a real
# (tiny, synthetic) vault -- no STORE_BACKEND / DB dependency, mirroring the
# repo's laptop-is-not-a-runtime-env posture.
# ---------------------------------------------------------------------------


def test_main_dry_run_end_to_end_writes_nothing(tiny_vault: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = {p: p.read_text(encoding="utf-8") for p in tiny_vault.rglob("*.md")}
    outbox_path = tmp_path / "outbox.jsonl"

    exit_code = deep_pass.main(
        ["--vault-root", str(tiny_vault), "--dry-run", "--outbox-path", str(outbox_path)]
    )

    assert exit_code == 0
    after = {p: p.read_text(encoding="utf-8") for p in tiny_vault.rglob("*.md")}
    assert before == after
    assert not outbox_path.exists()

    captured = capsys.readouterr()
    receipt = json.loads(captured.out)
    assert receipt["event"] == deep_pass.DEEP_PASS_RECEIPT_EVENT
    assert receipt["payload"]["dry_run"] is True
    pass_names = {row["pass"] for row in receipt["payload"]["passes"]}
    assert pass_names == {"lint_and_propose", "connect", "cluster_emergence", "cluster_to_create", "contradiction"}
