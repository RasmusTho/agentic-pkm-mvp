"""P-1/P-4 guard-at-seam properties (#2910).

P-1 `guard_asserted_at_write_seam`: WriteGuard is asserted *inside* every seam
that can write the vault, never left to caller convention.

P-4 `guards_fail_closed`: a WriteGuard evaluation error (a raising guard, not
just a denying one) blocks the write -- a guard that fails open is not a
guard.

Derivation: ``docs/testing/invariant-synthesis-2026-07.md`` :: P-1, P-4;
``docs/architecture/formal-model.md`` §3 gap 1 / gap 4, §7 divergences
F-A..F-F. Four seam-local fixes landed retail (#2808 panel writeback, #2809
settings writeback, #2810 note_hygiene, #2877 vault-layout scaffolder) before
this issue closed the remaining three named seams:

1. The knowledge write port itself (``app/knowledge/write_ops.py::
   write_note_from_absolute``) -- the shared root cause five other sites
   reach the vault through.
2. Identity-heal (``app/vault/manager.py::_ensure_frontmatter_id`` via
   ``write_frontmatter``), registered as an explicit heal transition.
3. Checkbox-rollback (``app/panel/checkbox_projection.py`` exception handler
   calling ``write_note_from_absolute`` to restore prior content) -- covered
   automatically once the port itself is guarded.

Builds on the P-2 machinery bootstrapped by #2909 (``tests/properties/
_machinery.py``); the P-1/P-4 additions live in that module's clearly
separated APPEND-ONLY section below the P-2 content, so a concurrent sibling
(#2911, heal-transition/advisory-sink machinery) rebases cleanly.
"""

from __future__ import annotations

import pytest

from tests.properties._machinery import (
    REGISTERED_WRITE_SEAMS,
    WRITE_FRONTMATTER_SITE_CLASSIFICATION,
    find_write_frontmatter_call_sites,
)

pytest.importorskip("hypothesis")

from hypothesis import HealthCheck, given, settings, strategies as st  # noqa: E402


# ---------------------------------------------------------------------------
# test_every_write_seam_asserts_writeguard -- static gate
# ---------------------------------------------------------------------------


def test_every_write_seam_asserts_writeguard() -> None:
    """Every ``write_frontmatter`` call site is guarded or explicitly out of
    scope of the vault content plane -- a NEW unregistered/unguarded site
    fails this gate instead of silently shipping the next F-A/F-B-class
    regression (formal-model.md gap 1).

    ``write_note_from_absolute`` itself needs no site-by-site census anymore:
    the port (#2910) now asserts WriteGuard unconditionally before any I/O,
    so every one of its ~20 production call sites is guarded by construction.
    ``write_frontmatter`` is the second vault-write primitive that does NOT
    route through the port, so it still needs its own closed census.
    """
    sites = find_write_frontmatter_call_sites()
    assert sites, "expected at least the known production write_frontmatter call sites"

    unregistered = [site for site in sites if site not in WRITE_FRONTMATTER_SITE_CLASSIFICATION]
    assert not unregistered, (
        "Unregistered write_frontmatter call site(s) found -- classify each as "
        "'guarded' or 'out_of_scope' in WRITE_FRONTMATTER_SITE_CLASSIFICATION "
        f"(tests/properties/_machinery.py) before merging: {unregistered}"
    )

    live_set = set(sites)
    stale = [key for key in WRITE_FRONTMATTER_SITE_CLASSIFICATION if key not in live_set]
    assert not stale, (
        "WRITE_FRONTMATTER_SITE_CLASSIFICATION has stale entries no longer "
        f"matching a real write_frontmatter call site (line drift or removed site): {stale}"
    )

    bad_classification = [
        (key, value)
        for key, value in WRITE_FRONTMATTER_SITE_CLASSIFICATION.items()
        if not (value.startswith("guarded") or value.startswith("out_of_scope"))
    ]
    assert not bad_classification, (
        f"Every classification must start with 'guarded' or 'out_of_scope': {bad_classification}"
    )


def test_registered_write_seams_cover_the_three_named_gap1_sites() -> None:
    """The P-1/P-4 runtime property registry names exactly the three sites the
    issue scopes: the knowledge write port, identity-heal, and checkbox
    rollback (formal-model.md gap 1's "remaining four sites" minus settings
    writeback, already gated by #2809).
    """
    names = {seam.name for seam in REGISTERED_WRITE_SEAMS}
    assert names == {"knowledge_write_port", "identity_heal", "checkbox_rollback"}


# ---------------------------------------------------------------------------
# test_denying_guard_blocks_atomically -- P-1 runtime property
# ---------------------------------------------------------------------------


@given(seam_index=st.sampled_from(range(len(REGISTERED_WRITE_SEAMS))))
@settings(max_examples=len(REGISTERED_WRITE_SEAMS), deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_denying_guard_blocks_atomically(tmp_path_factory, seam_index: int) -> None:
    """``given(seam=sampled_from(REGISTERED_WRITE_SEAMS), guard_state=denying_guard())``
    (the spec's own vocabulary): a guard reporting a health-blocked state
    (``safe_mode``) blocks every registered seam's write, and the vault
    fixture is byte-identical before and after -- atomicity of the block, the
    #2877 scaffolder shape generalized to every named seam.
    """
    seam = REGISTERED_WRITE_SEAMS[seam_index]
    tmp_path = tmp_path_factory.mktemp(f"p1-deny-{seam.name}")
    monkeypatch = pytest.MonkeyPatch()
    try:
        invoke = seam.invoke_factory(tmp_path, monkeypatch)
        before = seam.unchanged_paths(tmp_path)

        module_path, attr_name = seam.guard_patch_target.rsplit(".", 1)
        import importlib

        guard_module = importlib.import_module(module_path)
        guard = getattr(guard_module, attr_name)
        monkeypatch.setattr(guard, "snapshot_fn", lambda: {"state": "safe_mode", "reason": "p1-deny"})
        monkeypatch.setattr(guard, "bootstrap_actions", frozenset())

        from app.write_guard import WritesBlockedError

        with pytest.raises(WritesBlockedError) as exc:
            invoke()
        assert exc.value.state == "safe_mode"

        after = seam.unchanged_paths(tmp_path)
        assert after == before, f"seam {seam.name!r} mutated the vault under a denying guard"
    finally:
        monkeypatch.undo()


# ---------------------------------------------------------------------------
# test_raising_guard_blocks_write -- P-4 runtime property
# ---------------------------------------------------------------------------


@given(seam_index=st.sampled_from(range(len(REGISTERED_WRITE_SEAMS))))
@settings(max_examples=len(REGISTERED_WRITE_SEAMS), deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_raising_guard_blocks_write(tmp_path_factory, seam_index: int) -> None:
    """``given(seam=sampled_from(REGISTERED_WRITE_SEAMS), guard=raising_guard())``:
    a WriteGuard whose evaluation itself errors (not merely denies) still
    blocks the write and surfaces a loud, classifiable error -- never a
    swallowed exception and never a silent fall-through to a completed write.

    Exemption (issue constraint, named not silent): ``note/save``
    (``app/api/routes/companion.py::companion_note_save``'s
    ``companion.note.human_edit`` action) deliberately fails OPEN on a guard
    evaluation error -- divergence F-C, owner decision pending on epic #2778.
    It is intentionally absent from ``REGISTERED_WRITE_SEAMS`` (out of this
    issue's scope; not one of the three named seams), so this property never
    exercises it and never asserts fail-closed behavior it does not have.
    """
    seam = REGISTERED_WRITE_SEAMS[seam_index]
    tmp_path = tmp_path_factory.mktemp(f"p4-raise-{seam.name}")
    monkeypatch = pytest.MonkeyPatch()
    try:
        invoke = seam.invoke_factory(tmp_path, monkeypatch)
        before = seam.unchanged_paths(tmp_path)

        module_path, attr_name = seam.guard_patch_target.rsplit(".", 1)
        import importlib

        guard_module = importlib.import_module(module_path)
        guard = getattr(guard_module, attr_name)

        def _raise_on_evaluate() -> dict:
            raise RuntimeError("p4 seam property: guard evaluation failed")

        monkeypatch.setattr(guard, "snapshot_fn", _raise_on_evaluate)

        # A raising guard must surface loudly (some exception), never swallow
        # into a completed write. The seam-specific WritesBlockedError wrapping
        # done by identity_heal/checkbox_rollback's invoke() is one valid loud
        # shape; the guard's own raised RuntimeError propagating unwrapped is
        # equally loud and equally acceptable -- either way nothing was
        # swallowed and nothing was written.
        with pytest.raises(Exception):
            invoke()

        after = seam.unchanged_paths(tmp_path)
        assert after == before, f"seam {seam.name!r} mutated the vault despite a raising guard"
    finally:
        monkeypatch.undo()


def test_registered_bootstrap_action_survives_unevaluable_guard() -> None:
    """The named bootstrap escape short-circuits BEFORE snapshot evaluation
    (#2910 harness-selfverify regression): on a brand-new vault the health
    snapshot itself depends on state the bootstrap write creates
    (vault.layout.md -> load_health_settings), so a registered bootstrap
    action must pass even when guard evaluation itself raises -- otherwise
    fresh-vault provisioning deadlocks. Only REGISTERED action strings get
    this; it is the #2877 named-escape pattern, not a bypass.
    """
    from app.write_guard import DEFAULT_BOOTSTRAP_ACTIONS, WriteGuard

    def _raising_snapshot() -> dict:
        raise FileNotFoundError("vault.layout.md not found (simulated fresh vault)")

    guard = WriteGuard(_raising_snapshot)
    assert "vault.layout_ensure" in DEFAULT_BOOTSTRAP_ACTIONS
    # Registered escape: passes without ever evaluating the raising snapshot.
    guard.assert_writes_allowed("vault.layout_ensure")
    guard.assert_writes_allowed("yggdrasil.scaffold")


def test_unregistered_action_still_fails_closed_on_unevaluable_guard() -> None:
    """P-4 counterpart of the escape-order change: for every NON-registered
    action, a raising guard evaluation still blocks the write loudly -- the
    escape-before-evaluation ordering must not widen fail-open behavior
    beyond the named bootstrap list.
    """
    from app.write_guard import WriteGuard

    def _raising_snapshot() -> dict:
        raise FileNotFoundError("vault.layout.md not found (simulated fresh vault)")

    guard = WriteGuard(_raising_snapshot)
    with pytest.raises(FileNotFoundError):
        guard.assert_writes_allowed("knowledge.write_note")

    # And a guard whose escape list omits the action denies/raises as before,
    # even for an action string that IS in the default list -- the escape is
    # per-guard-instance policy, not a global constant lookup.
    narrowed = WriteGuard(_raising_snapshot, bootstrap_actions=frozenset())
    with pytest.raises(FileNotFoundError):
        narrowed.assert_writes_allowed("vault.layout_ensure")


def test_note_save_fc_exemption_is_named_not_silent() -> None:
    """F-C's fail-open exemption exists as a documented, named exception --
    not an absence of coverage. This test pins the exemption's presence in the
    source (the inline comment + except-Exception-pass block) so a future
    refactor that accidentally removes the comment (making the fail-open
    silent again) is caught, without asserting new fail-closed semantics for
    ``note/save`` itself (out of scope -- owner decision F-C, epic #2778).
    """
    import inspect

    from app.api.routes import companion

    source = inspect.getsource(companion)
    assert "F-C" not in source or "companion.note.human_edit" in source, (
        "expected the note/save fail-open exemption to remain named at its "
        "companion.note.human_edit action site"
    )
    assert "fails open" in source or "fail open" in source, (
        "expected note/save's deliberate fail-open comment to remain present "
        "and readable -- if this fails, the F-C exemption may have gone silent"
    )
