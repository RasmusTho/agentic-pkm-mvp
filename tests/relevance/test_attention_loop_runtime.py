"""Runtime wiring for CRE proactive reach-out decisions (#1964).

The attention loop is invoked by the governed relevance tick over freshly
materialized moments. It records Act-tier receipts for each reach-out or
deliberate suppression, and the Companion "now" projection exposes an in-app
nudge only when the in-app threshold is cleared.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from app.relevance import collect_now_moments, query_reachout_receipts
from app.vault.manager import VaultContext
from app.watcher.relevance_tick import run_relevance_tick


def _build_vault(tmp_path: Path, *, due: date | None = None) -> Path:
    today = date.today()
    vault = tmp_path / "vault"
    daily = vault / "Daily" / f"{today.isoformat()}.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text("---\nuuid: daily-uuid\n---\n\n# Today\n", encoding="utf-8")

    note = vault / "Projects" / "Contextual Relevance Engine.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = "---\nuuid: cre-uuid\n"
    if due is not None:
        frontmatter += f"due: {due.isoformat()}\n"
    frontmatter += "---\n\n"
    note.write_text(
        f"{frontmatter}# CRE\n\n- [ ] finish the scarcity gate\n",
        encoding="utf-8",
    )
    return vault


def _ctx(vault: Path) -> VaultContext:
    return VaultContext(status="selected", active_vault_id="v1", active_vault_path=str(vault))


def test_tick_emits_governed_reachout_decisions(tmp_path: Path) -> None:
    vault = _build_vault(tmp_path)
    moment_receipts = tmp_path / "moment_receipts.jsonl"
    reachout_receipts = tmp_path / "reachout_receipts.jsonl"

    summary = run_relevance_tick(
        vault,
        vault_context=_ctx(vault),
        outbox_path=moment_receipts,
        reachout_outbox_path=reachout_receipts,
        interruptibility="home",
    )

    assert summary["materialized"] == 1
    assert summary["reachout_decisions"] == 1
    assert summary["in_app_nudges"] == 1

    [row] = query_reachout_receipts(outbox_path=reachout_receipts)
    payload = row["payload"]
    assert row["event"] == "moment.reachout"
    assert payload["moment_uuid"] in summary["moment_ids"]
    assert payload["governance_tier"] == "act"
    assert payload["external_side_effect"] is False
    assert payload["receipt"]["action_taken"] == "moment.reachout"
    assert payload["reachout"]["outcome"] == "in_app"
    assert payload["reachout"]["rung"] == "in_app_nudge"
    assert payload["reachout"]["interruptibility_state"] == "home"


def test_repeated_tick_dedupes_unchanged_reachout(tmp_path: Path) -> None:
    vault = _build_vault(tmp_path, due=date.today() + timedelta(days=2))
    moment_receipts = tmp_path / "moment_receipts.jsonl"
    reachout_receipts = tmp_path / "reachout_receipts.jsonl"

    first = run_relevance_tick(
        vault,
        vault_context=_ctx(vault),
        outbox_path=moment_receipts,
        reachout_outbox_path=reachout_receipts,
        interruptibility="focus",
    )
    second = run_relevance_tick(
        vault,
        vault_context=_ctx(vault),
        outbox_path=moment_receipts,
        reachout_outbox_path=reachout_receipts,
        interruptibility="focus",
    )

    assert first["moment_ids"] == second["moment_ids"]
    assert first["reachout_decisions"] == 1
    assert second["reachout_decisions"] == 0
    assert len(query_reachout_receipts(outbox_path=reachout_receipts)) == 1


def test_later_defer_clears_existing_in_app_nudge(tmp_path: Path) -> None:
    vault = _build_vault(tmp_path)
    moment_receipts = tmp_path / "moment_receipts.jsonl"
    reachout_receipts = tmp_path / "reachout_receipts.jsonl"

    first = run_relevance_tick(
        vault,
        vault_context=_ctx(vault),
        outbox_path=moment_receipts,
        reachout_outbox_path=reachout_receipts,
        interruptibility="home",
    )
    [home_view] = collect_now_moments(_ctx(vault), reachout_outbox_path=reachout_receipts)
    assert home_view["in_app_nudge"]["active"] is True

    second = run_relevance_tick(
        vault,
        vault_context=_ctx(vault),
        outbox_path=moment_receipts,
        reachout_outbox_path=reachout_receipts,
        interruptibility="sleep",
    )

    assert first["moment_ids"] == second["moment_ids"]
    assert second["reachout_decisions"] == 1
    [sleep_view] = collect_now_moments(_ctx(vault), reachout_outbox_path=reachout_receipts)
    assert "in_app_nudge" not in sleep_view
    assert [
        row["payload"]["reachout"]["outcome"]
        for row in query_reachout_receipts(outbox_path=reachout_receipts)
    ] == ["in_app", "defer"]


def test_in_app_nudge_respects_threshold_and_floor(tmp_path: Path) -> None:
    home_vault = _build_vault(tmp_path / "home")
    home_moments = tmp_path / "home_moment_receipts.jsonl"
    home_reachout = tmp_path / "home_reachout.jsonl"
    run_relevance_tick(
        home_vault,
        vault_context=_ctx(home_vault),
        outbox_path=home_moments,
        reachout_outbox_path=home_reachout,
        interruptibility="home",
    )

    [home_view] = collect_now_moments(_ctx(home_vault), reachout_outbox_path=home_reachout)
    assert home_view["urgency_band"] == "timely"
    assert home_view["in_app_nudge"]["active"] is True
    assert home_view["in_app_nudge"]["rung"] == "in_app_nudge"

    sleep_vault = _build_vault(tmp_path / "sleep")
    sleep_moments = tmp_path / "sleep_moment_receipts.jsonl"
    sleep_reachout = tmp_path / "sleep_reachout.jsonl"
    run_relevance_tick(
        sleep_vault,
        vault_context=_ctx(sleep_vault),
        outbox_path=sleep_moments,
        reachout_outbox_path=sleep_reachout,
        interruptibility="sleep",
    )

    [sleep_view] = collect_now_moments(_ctx(sleep_vault), reachout_outbox_path=sleep_reachout)
    assert sleep_view["urgency_band"] == "timely"
    assert "in_app_nudge" not in sleep_view

    [sleep_receipt] = query_reachout_receipts(outbox_path=sleep_reachout)
    reachout = sleep_receipt["payload"]["reachout"]
    assert reachout["zero_tolerance"] is True
    assert reachout["outcome"] == "defer"
    assert reachout["rung"] == "glance"
