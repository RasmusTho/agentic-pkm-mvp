"""P-3 read-purity route-walk property (#2911).

Purpose: no GET/read path mutates durable state, except transitions on a
registered heal list (``tests/properties/_machinery.py::
REGISTERED_HEAL_TRANSITIONS``) -- heal-on-read is legal only when declared,
per ``docs/architecture/formal-model.md`` §3 invariant Q4 and
``docs/testing/invariant-synthesis-2026-07.md :: P-3``.

Method: enumerate every GET route DYNAMICALLY from the real FastAPI route
table (``app.api.app.app.routes`` -- not a static list, so a new route cannot
silently escape classification, mirroring the #2773 no-silent-cap precedent),
call each route through a real ``TestClient`` with spy wrappers on the two
durable-write primitives P-3's registered heals actually reach
(``WriteSpy`` / ``spy_on_durable_writes`` in ``_machinery.py``), across fixture
vault states (with/without frontmatter uuid; healthy/unhealthy WriteGuard).
Assert zero durable writes for every route UNLESS the seam that wrote is a
registered heal transition -- and every registered heal that is WG-gated
must actually respect a denying guard (no write, atomic).

Both known-reachable Q4 cases are exercised here:
  1. uuid-heal (``GET /api/companion/workspace``) -- WG-gated at
     ``app.services.note_uuid::ensure_note_uuid``.
  2. lazy identity-heal (``GET /api/companion/workspace`` and siblings, on a
     cold ``VaultManager``) -- NOT WG-gated, pinned as current reality.
The third case (ASK's J-sink receipt appends) is a POST route and is
documented in ``_machinery.py::REGISTERED_ADVISORY_J_SINKS`` rather than
exercised by this GET-only route-walk (see that module's P-3 section).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Route

from app.api.app import app
from app.health_contract import WRITE_BLOCKED_STATES
from app.write_guard import DEFAULT_WRITE_GUARD

from tests.api._vault_test_helpers import bind_initialized_vault
from tests.properties._machinery import (
    REGISTERED_HEAL_TRANSITIONS,
    WriteSpy,
    spy_on_durable_writes,
)

# ---------------------------------------------------------------------------
# Dynamic route enumeration -- no static list (the #2773 no-silent-cap rule)
# ---------------------------------------------------------------------------


def _enumerate_get_routes() -> list[Route]:
    """Every GET route on the real, fully-configured production app.

    Reads ``app.routes`` fresh at call time (not a module-level constant)
    so a route registered after import is still picked up by any caller that
    re-invokes this function -- the route table itself is the generator, per
    the property spec ("enumerated from the FastAPI app's route table --
    dynamic, so a new route cannot silently escape").
    """
    return [
        route
        for route in app.routes
        if isinstance(route, Route) and route.methods and "GET" in route.methods
    ]


# A small per-route argument map for the handful of GET routes that require a
# path/query parameter to resolve without a 422 before reaching any write
# path. Placeholder values are deliberately generic (non-existent ids) --
# routes that then 404 must STILL show zero durable writes, which is exactly
# what this property intends to prove for the "no fixture matches" case.
_ROUTE_PARAMS: dict[str, dict[str, Any]] = {
    "/api/orientation/bundle/{bundle_id}": {"bundle_id": "does-not-exist"},
    "/api/artifacts/note": {"params": {"note_path": "notes/note.md"}},
    "/api/companion/workspace": {"params": {"note_path": "notes/note.md"}},
    "/api/companion/tts/audio/{cache_key}.wav": {"cache_key": "does-not-exist"},
    "/api/builderops/records/{record_id}": {"record_id": "does-not-exist"},
    "/api/context-bundles/{bundle_id}": {"bundle_id": "does-not-exist"},
    "/api/resurfacing/bundle/{bundle_id}": {"bundle_id": "does-not-exist"},
}


def _call_route(client: TestClient, route: Route) -> Any:
    """Invoke one GET route with sensible placeholder args, tolerating any
    response status -- the property is about writes, not response shape."""
    path = route.path
    kwargs = dict(_ROUTE_PARAMS.get(path, {}))
    path_params = {k: v for k, v in kwargs.items() if k != "params"}
    query_params = kwargs.get("params", {})
    resolved_path = path.format(**path_params) if path_params else path
    return client.get(resolved_path, params=query_params)


# ---------------------------------------------------------------------------
# Fixture vault states
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _write_note(path: Path, *, with_uuid: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = "uuid: note-uuid-1\n" if with_uuid else ""
    path.write_text(
        f"---\n{frontmatter}title: Property Note\n---\n\n# Property Note\n\nBody text.\n",
        encoding="utf-8",
    )


@pytest.fixture()
def vault_with_uuid_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bind_initialized_vault(monkeypatch, tmp_path)
    note = tmp_path / "notes" / "note.md"
    _write_note(note, with_uuid=True)
    return tmp_path


@pytest.fixture()
def vault_missing_uuid_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bind_initialized_vault(monkeypatch, tmp_path)
    note = tmp_path / "notes" / "note.md"
    _write_note(note, with_uuid=False)
    return tmp_path


@pytest.fixture()
def _healthy_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "healthy"})


@pytest.fixture()
def _unhealthy_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    state = sorted(WRITE_BLOCKED_STATES)[0]
    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": state, "reason": "property test lock"}
    )


# ---------------------------------------------------------------------------
# test_get_routes_do_not_write_durably -- the route-walk property
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("guard_state", ["healthy", "unhealthy"])
@pytest.mark.parametrize("uuid_state", ["with_uuid", "missing_uuid"])
def test_get_routes_do_not_write_durably(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    guard_state: str,
    uuid_state: str,
) -> None:
    """Every real GET route, called across (with/without uuid) x
    (healthy/unhealthy guard) fixture states, must show zero durable writes
    from the two spied write primitives UNLESS the seam that wrote is a
    registered heal transition (``REGISTERED_HEAL_TRANSITIONS``).

    For a registered, WG-gated heal (case 1, uuid-heal): an unhealthy guard
    must block the write entirely (spy records nothing for that seam) --
    this is the "registered heals must additionally be WG-gated" half of the
    property. For a registered, non-WG-gated heal (case 2, identity-heal):
    it may legitimately write under either guard state, per the pinned
    current-reality classification -- this issue does not change that.
    """
    request.getfixturevalue(
        "vault_with_uuid_note" if uuid_state == "with_uuid" else "vault_missing_uuid_note"
    )
    if guard_state == "healthy":
        monkeypatch.setattr(DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "healthy"})
    else:
        blocked = sorted(WRITE_BLOCKED_STATES)[0]
        monkeypatch.setattr(
            DEFAULT_WRITE_GUARD,
            "snapshot_fn",
            lambda: {"state": blocked, "reason": "property test lock"},
        )

    client = TestClient(app)
    routes = _enumerate_get_routes()
    assert routes, "expected at least one GET route on the real app"

    spy = WriteSpy()
    with spy_on_durable_writes(monkeypatch, spy):
        for route in routes:
            # Response status is deliberately not asserted -- a 404/422/200
            # must all show the same write-purity property. Network/setup
            # errors surfacing as 5xx still must not have produced an
            # unregistered write, so no status filtering happens here.
            _call_route(client, route)

    unregistered = spy.seams_hit() - set(REGISTERED_HEAL_TRANSITIONS)
    assert not unregistered, (
        "GET route(s) produced durable write(s) via unregistered seam(s) -- "
        "either this is a new heal that needs registering in "
        "REGISTERED_HEAL_TRANSITIONS (tests/properties/_machinery.py) with a "
        f"justification, or it is a genuine read-purity regression: {unregistered}"
    )

    if guard_state == "unhealthy":
        for seam, call in ((c.seam, c) for c in spy.calls):
            transition = REGISTERED_HEAL_TRANSITIONS.get(seam)
            if transition is not None and transition.wg_gated:
                pytest.fail(
                    f"WG-gated heal transition {seam!r} wrote while WriteGuard "
                    f"was denying (guard_state={guard_state!r}); a WG-gated "
                    "heal must block atomically under a denying guard "
                    f"(call={call!r})"
                )


# ---------------------------------------------------------------------------
# test_unregistered_route_write_fails -- fixture-proven negative
# ---------------------------------------------------------------------------


def test_unregistered_route_write_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An unclassified GET route with a durable write FAILS the property.

    Fixture-proven negative (the AC's explicit requirement): register a throw-
    away GET route on a cloned route table whose handler calls the real
    ``write_note_from_absolute`` seam directly, with NO entry in
    ``REGISTERED_HEAL_TRANSITIONS`` for it, and assert the same walk-and-assert
    logic this module uses actually catches it -- proving the property is not
    vacuously green (the registry's "verify-the-verifier" posture, per
    ``invariant-synthesis-2026-07.md`` :: CI placement).
    """
    from fastapi import FastAPI

    import app.knowledge.write_ops as write_ops_mod
    from tests.properties._machinery import spy_on_durable_writes as _spy_ctx
    from tests.properties._machinery import WriteSpy as _WriteSpy

    vault_root = tmp_path
    note = vault_root / "notes" / "unregistered.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("---\ntitle: X\n---\n\nBody\n", encoding="utf-8")

    probe_app = FastAPI()

    @probe_app.get("/__test_only/unregistered_write")
    def _unregistered_write_route() -> dict:
        # A GET route with a durable write reachable through the SAME spied
        # seam as the uuid-heal, but with no registration -- the negative
        # fixture the AC requires. Call through the MODULE reference (not a
        # name imported before the spy patches it) so the monkeypatch inside
        # spy_on_durable_writes actually intercepts this call.
        write_ops_mod.write_note_from_absolute(note, "---\ntitle: X\n---\n\nBody\n", vault_root=vault_root)
        return {"ok": True}

    probe_client = TestClient(probe_app)
    spy = _WriteSpy()
    with _spy_ctx(monkeypatch, spy):
        probe_client.get("/__test_only/unregistered_write")

    unregistered = spy.seams_hit() - set(REGISTERED_HEAL_TRANSITIONS)
    assert unregistered, (
        "expected the unregistered probe route's write to be detected as "
        "unregistered by the same seam classification the real property uses"
    )
    assert any("_unregistered_write_route" in caller for caller in unregistered), (
        f"expected the probe handler itself to be the unregistered caller; got {unregistered}"
    )
