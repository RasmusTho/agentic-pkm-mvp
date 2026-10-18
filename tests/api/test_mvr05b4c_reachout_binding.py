"""MVR-05B4c3 (#6213): reach-out receipts are stamped per binding and ``/now`` nudges restored.

``AttentionLoop`` stamps the producing binding on every reach-out receipt at emission and
deduplicates per binding (a vault B decision is emitted even when vault A holds a receipt for
the same moment UUID). A scoped ``/now`` read restores the in-app nudge for the request
binding only; unstamped legacy receipts are never shown to a scoped read. The producer
resolves and proves its binding before any write and fails closed otherwise.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.instance.compatibility_binding import CompatibilityBindingUnavailableError
from app.instance.settings_rebind import _install_dormant_settings_rebind
from app.receipts.artifact_receipts import PRODUCING_BINDING_FIELD
from app.relevance import AttentionLoop, collect_now_moments, query_reachout_receipts
from app.relevance.attention_loop import _latest_reachout_by_moment
from app.relevance.evaluator import DeterministicRelevanceEvaluator
from app.relevance.materialization import materialize_moment
from app.vault.manager import VaultContext
from app.watcher.relevance_tick import run_relevance_tick
from tests._mvr03_principal_harness import provisioned_instance
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
from tests.helpers.vault_settings import initialize_test_vault

pytestmark = pytest.mark.not_pg


def _write_vault_content(root: Path) -> None:
    today = date.today()
    daily = root / "Daily" / f"{today.isoformat()}.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text("---\nuuid: daily-uuid\n---\n\n# Today\n", encoding="utf-8")
    note = root / "Projects" / "Contextual Relevance Engine.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\nuuid: cre-uuid\n---\n\n# CRE\n\n- [ ] finish the scarcity gate\n",
        encoding="utf-8",
    )


def _ctx(root: Path) -> VaultContext:
    return VaultContext(status="selected", active_vault_id=root.name, active_vault_path=str(root))


def _moments_of(root: Path):
    return DeterministicRelevanceEvaluator(root).evaluate()


def _set_live(monkeypatch: pytest.MonkeyPatch, holder: dict[str, str]) -> None:
    import app.instance.compatibility_binding as binding_module

    monkeypatch.setattr(binding_module, "live_compatibility_binding_id", lambda: holder["live"])


@pytest.fixture()
def two_bindings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import app.relevance.attention_loop as loop_module
    import app.vault.manager as vault_manager_module

    runtime, first, extra, _record = provisioned_instance(tmp_path, extra_roots=("two",))
    second = extra[0]
    _install_dormant_settings_rebind(
        runtime.registry,
        binding_id=first.vault_binding_id,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    for root in (Path(first.path), Path(second.path)):
        initialize_test_vault(root)
        _write_vault_content(root)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    monkeypatch.setenv("LEAVE_POINT_TRACE_DB", str(tmp_path / "leave-point.sqlite3"))
    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", None)
    selection_routes.reset_selection_store_for_tests()
    receipts = tmp_path / "reachout.jsonl"
    moments = tmp_path / "moments.jsonl"
    # The production route reads the default reach-out source; point it at the test file.
    monkeypatch.setattr(loop_module, "DEFAULT_REACHOUT_RECEIPTS_PATH", receipts)
    return TestClient(app), first, second, receipts, moments


def _headers(client: TestClient, binding_id: str) -> dict[str, str]:
    created = client.post(
        "/api/companion/active-context/selection", json={"vault_binding_ids": [binding_id]}
    )
    assert created.status_code == 201, created.text
    return {"X-Active-Context-Session": created.json()["context_selection_id"]}


def _tick(root: Path, receipts: Path, moments: Path) -> dict:
    return run_relevance_tick(
        root,
        vault_context=_ctx(root),
        outbox_path=moments,
        reachout_outbox_path=receipts,
        interruptibility="home",
    )


def _now(client: TestClient, headers: dict[str, str]) -> list[dict]:
    response = client.get("/api/companion/now", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_scoped_now_restores_in_app_nudges_for_binding(two_bindings) -> None:
    client, first, second, receipts, moments = two_bindings
    root_a, root_b = Path(first.path), Path(second.path)

    # Production tick for the compatibility vault (no injected binding): vault A.
    summary = _tick(root_a, receipts, moments)
    assert summary["in_app_nudges"] == 1
    [moment_id] = summary["moment_ids"]
    # Vault B holds the same moment UUID as a materialized artifact but has no nudge.
    [moment_b] = _moments_of(root_b)
    assert moment_b.uuid == moment_id
    materialize_moment(moment_b, vault_context=_ctx(root_b), outbox_path=moments)

    headers_a = _headers(client, first.vault_binding_id)
    headers_b = _headers(client, second.vault_binding_id)
    before = receipts.read_bytes()

    now_a = _now(client, headers_a)
    now_b = _now(client, headers_b)
    assert [m["moment_id"] for m in now_a] == [moment_id]
    assert now_a[0]["in_app_nudge"]["active"] is True
    assert [m["moment_id"] for m in now_b] == [moment_id]
    assert "in_app_nudge" not in now_b[0], "another binding's nudge must not surface"
    # A scoped read never writes.
    assert receipts.read_bytes() == before

    # Carrier-free behavior: the legacy view is the live compatibility binding's.
    assert collect_now_moments(_ctx(root_a))[0]["in_app_nudge"]["active"] is True


def test_blank_carrier_now_never_reads_nudges(two_bindings) -> None:
    client, first, _second, receipts, moments = two_bindings
    _tick(Path(first.path), receipts, moments)
    blank = client.get("/api/companion/now", headers={"X-Active-Context-Session": ""})
    assert blank.status_code >= 400
    assert "in_app_nudge" not in blank.text


def test_unstamped_legacy_receipts_are_never_shown_to_a_scoped_read(two_bindings) -> None:
    client, first, _second, receipts, moments = two_bindings
    root_a = Path(first.path)
    summary = _tick(root_a, receipts, moments)
    # Strip the stamp from every receipt: history written before this child.
    rows = [json.loads(line) for line in receipts.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        row["payload"].pop(PRODUCING_BINDING_FIELD)
    receipts.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    now = _now(client, _headers(client, first.vault_binding_id))
    assert [m["moment_id"] for m in now] == summary["moment_ids"]
    assert "in_app_nudge" not in now[0]
    # The carrier-free view still counts unstamped legacy receipts.
    assert collect_now_moments(_ctx(root_a))[0]["in_app_nudge"]["active"] is True


def test_reachout_dedup_is_keyed_by_binding(two_bindings, monkeypatch: pytest.MonkeyPatch) -> None:
    _client, first, second, receipts, moments = two_bindings
    root_a, root_b = Path(first.path), Path(second.path)
    holder = {"live": first.vault_binding_id}
    _set_live(monkeypatch, holder)

    first_tick = _tick(root_a, receipts, moments)
    assert first_tick["reachout_decisions"] == 1
    [row_a] = query_reachout_receipts(outbox_path=receipts)
    assert row_a["payload"][PRODUCING_BINDING_FIELD] == first.vault_binding_id
    # Same vault, same decision: deduplicated.
    assert _tick(root_a, receipts, moments)["reachout_decisions"] == 0

    # The compatibility vault rebinds to B; B holds the same moment UUID. The identical
    # decision is emitted even though A already holds a receipt for it.
    holder["live"] = second.vault_binding_id
    second_tick = _tick(root_b, receipts, moments)
    assert second_tick["moment_ids"] == first_tick["moment_ids"]
    assert second_tick["reachout_decisions"] == 1
    rows = query_reachout_receipts(outbox_path=receipts)
    assert [r["payload"][PRODUCING_BINDING_FIELD] for r in rows] == [
        first.vault_binding_id,
        second.vault_binding_id,
    ]
    assert _tick(root_b, receipts, moments)["reachout_decisions"] == 0

    # Restart / reload: the durable stamps keep each binding's own latest decision.
    moment_id = first_tick["moment_ids"][0]
    for binding in (first.vault_binding_id, second.vault_binding_id):
        assert moment_id in _latest_reachout_by_moment(outbox_path=receipts, bindings=(binding,))
    holder["live"] = first.vault_binding_id
    assert _tick(root_a, receipts, moments)["reachout_decisions"] == 0
    assert len(query_reachout_receipts(outbox_path=receipts)) == 2


def test_unstamped_receipt_never_suppresses_a_live_binding_emission(
    two_bindings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#6250 review: pre-upgrade history must not hide the scoped nudge forever."""

    client, first, second, receipts, moments = two_bindings
    root_a = Path(first.path)
    holder = {"live": first.vault_binding_id}
    _set_live(monkeypatch, holder)
    _tick(root_a, receipts, moments)
    rows = [json.loads(line) for line in receipts.read_text(encoding="utf-8").splitlines()]
    rows[0]["payload"].pop(PRODUCING_BINDING_FIELD)
    receipts.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    headers_a = _headers(client, first.vault_binding_id)
    assert not any(moment.get("in_app_nudge") for moment in _now(client, headers_a))
    # The live binding re-emits once under its own stamp, then dedups within it.
    assert _tick(root_a, receipts, moments)["reachout_decisions"] == 1
    stamps = [
        r["payload"].get(PRODUCING_BINDING_FIELD)
        for r in query_reachout_receipts(outbox_path=receipts)
    ]
    assert stamps == [None, first.vault_binding_id]
    assert any(moment.get("in_app_nudge") for moment in _now(client, headers_a))
    assert _tick(root_a, receipts, moments)["reachout_decisions"] == 0
    # A producer for another binding never adopts it.
    [moment] = _moments_of(root_a)
    other = AttentionLoop(
        _ctx(root_a), outbox_path=receipts, producing_binding_id=second.vault_binding_id
    )
    assert len(other.tick(moments=[moment], interruptibility="home")) == 1


def test_sentinel_journey_and_explicit_producing_binding(tmp_path: Path) -> None:
    receipts = tmp_path / "r.jsonl"
    moments = tmp_path / "m.jsonl"
    root = tmp_path / "v"
    _write_vault_content(root)
    summary = _tick(root, receipts, moments)
    # No registry: the explicit sentinel journey stamps the sentinel; dedup unchanged.
    [row] = query_reachout_receipts(outbox_path=receipts)
    assert row["payload"][PRODUCING_BINDING_FIELD] == COMPATIBILITY_BINDING_ID
    assert _tick(root, receipts, moments)["reachout_decisions"] == 0

    # A producer that knows its binding stamps THAT and dedups within it alone.
    loop = AttentionLoop(_ctx(root), outbox_path=receipts, producing_binding_id="binding-B")
    [moment] = _moments_of(root)
    assert moment.uuid == summary["moment_ids"][0]
    [decision] = loop.tick(moments=[moment], interruptibility="home")
    assert decision.reached_out
    stamps = [
        r["payload"][PRODUCING_BINDING_FIELD] for r in query_reachout_receipts(outbox_path=receipts)
    ]
    assert stamps == [COMPATIBILITY_BINDING_ID, "binding-B"]
    assert loop.tick(moments=[moment], interruptibility="home") == []


def test_unprovable_binding_fails_closed_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "v"
    _write_vault_content(root)
    registry = tmp_path / "registry.json"
    registry.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(registry))
    receipts, moments = tmp_path / "r.jsonl", tmp_path / "m.jsonl"

    with pytest.raises(CompatibilityBindingUnavailableError):
        _tick(root, receipts, moments)
    assert not receipts.exists() and not moments.exists()
    assert list(root.rglob("moments/*.md")) == []

    loop = AttentionLoop(_ctx(root), outbox_path=receipts, moment_outbox_path=moments)
    with pytest.raises(CompatibilityBindingUnavailableError):
        loop.tick(moments=_moments_of(root), interruptibility="home")
    assert not receipts.exists() and not moments.exists()


def test_root_that_is_not_the_live_binding_fails_closed(two_bindings) -> None:
    _client, first, second, receipts, moments = two_bindings
    assert first.vault_binding_id != second.vault_binding_id
    # The live compatibility binding is A's; a tick handed B's root must not stamp A.
    with pytest.raises(CompatibilityBindingUnavailableError):
        _tick(Path(second.path), receipts, moments)
    assert not receipts.exists() and not moments.exists()
    assert list(Path(second.path).rglob("moments/*.md")) == []


def test_tick_refuses_a_root_that_is_not_the_context_vault(two_bindings) -> None:
    """#6250 review: B's moments are never materialized into, or stamped as, vault A."""

    _client, first, second, receipts, moments = two_bindings
    summary = run_relevance_tick(
        Path(second.path),
        vault_context=_ctx(Path(first.path)),
        outbox_path=moments,
        reachout_outbox_path=receipts,
        interruptibility="home",
    )
    assert summary["skipped"] == "vault-root-context-mismatch"
    assert not receipts.exists() or receipts.read_text(encoding="utf-8") == ""
    assert not moments.exists() or moments.read_text(encoding="utf-8") == ""
