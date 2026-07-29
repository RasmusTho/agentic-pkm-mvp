"""P-1/P-4 guard-at-seam properties (#2910, extended by #2953).

P-1 `guard_asserted_at_write_seam`: WriteGuard is asserted *inside* every seam
that can write the vault, never left to caller convention.

P-4 `guards_fail_closed`: a WriteGuard evaluation error (a raising guard, not
just a denying one) blocks the write -- a guard that fails open is not a
guard.

Derivation: ``docs/testing/invariant-synthesis-2026-07.md`` :: P-1, P-4;
``docs/architecture/formal-model.md`` §3 gap 1 / gap 4, §7 divergences
F-A..F-F. Four seam-local fixes landed retail (#2808 panel writeback, #2809
settings writeback, #2810 note_hygiene, #2877 vault-layout scaffolder) before
#2910 closed the remaining three named seams:

1. The knowledge write port itself (``app/knowledge/write_ops.py::
   write_note_from_absolute``) -- the shared root cause five other sites
   reach the vault through.
2. Identity-heal (``app/vault/manager.py::_ensure_frontmatter_id`` via
   ``write_frontmatter``), registered as an explicit heal transition.
3. Checkbox-rollback (``app/panel/checkbox_projection.py`` exception handler
   calling ``write_note_from_absolute`` to restore prior content) -- covered
   automatically once the port itself is guarded.

#2953 closed a follow-on P-1 census gap discovered by the KA-05 (#2800) opus
review: ``write_note_relative`` (the relative-path sibling port) was left
unguarded at the port itself, with a live unguarded caller in
``app/mcp/vault_tools.py``. This file now also censuses every
``write_note_relative`` call site (mirroring the ``write_frontmatter``
census) and registers that live violator as a fourth runtime P-1/P-4 seam.

Builds on the P-2 machinery bootstrapped by #2909 (``tests/properties/
_machinery.py``); the P-1/P-4 additions live in that module's clearly
separated APPEND-ONLY section below the P-2 content, so a concurrent sibling
(#2911, heal-transition/advisory-sink machinery) rebases cleanly.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.properties._machinery import (
    REGISTERED_WRITE_SEAMS,
    WRITE_FRONTMATTER_SITE_CLASSIFICATION,
    WRITE_MISSING_SITE_CLASSIFICATION,
    WRITE_NOTE_RELATIVE_SITE_CLASSIFICATION,
    find_write_frontmatter_call_sites,
    find_write_missing_call_sites,
    find_write_note_relative_call_sites,
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
    assert (
        not bad_classification
    ), f"Every classification must start with 'guarded' or 'out_of_scope': {bad_classification}"

    write_missing_sites = find_write_missing_call_sites()
    assert write_missing_sites, "expected known production write_missing call sites"
    unregistered_write_missing = [
        site for site in write_missing_sites if site not in WRITE_MISSING_SITE_CLASSIFICATION
    ]
    assert not unregistered_write_missing, (
        "Unregistered write_missing call site(s) found; classify each guarded or "
        f"explicit bootstrap caller: {unregistered_write_missing}"
    )
    stale_write_missing = [
        site for site in WRITE_MISSING_SITE_CLASSIFICATION if site not in set(write_missing_sites)
    ]
    assert not stale_write_missing, (
        "WRITE_MISSING_SITE_CLASSIFICATION has stale entries: " f"{stale_write_missing}"
    )
    invalid_write_missing = [
        (site, classification)
        for site, classification in WRITE_MISSING_SITE_CLASSIFICATION.items()
        if not classification.startswith(("guarded", "bootstrap"))
    ]
    assert not invalid_write_missing, (
        "write_missing classifications must be guarded or bootstrap: " f"{invalid_write_missing}"
    )


def _assert_write_note_relative_census_is_closed(
    sites: list[tuple[str, str, int]],
) -> None:
    """Require every stable call-site identity to have one live classification."""
    unregistered = [site for site in sites if site not in WRITE_NOTE_RELATIVE_SITE_CLASSIFICATION]
    assert not unregistered, (
        "Unregistered write_note_relative call site(s) found -- classify each as "
        "'guarded_by_port' or 'guarded_by_caller' in "
        "WRITE_NOTE_RELATIVE_SITE_CLASSIFICATION (tests/properties/_machinery.py) "
        f"before merging: {unregistered}"
    )

    live_set = set(sites)
    stale = [key for key in WRITE_NOTE_RELATIVE_SITE_CLASSIFICATION if key not in live_set]
    assert not stale, (
        "WRITE_NOTE_RELATIVE_SITE_CLASSIFICATION has stale entries no longer "
        f"matching a real write_note_relative call site (removed or moved site): {stale}"
    )

    bad_classification = [
        (key, value)
        for key, value in WRITE_NOTE_RELATIVE_SITE_CLASSIFICATION.items()
        if not (value.startswith("guarded_by_port") or value.startswith("guarded_by_caller"))
    ]
    assert not bad_classification, (
        "Every classification must start with 'guarded_by_port' or "
        f"'guarded_by_caller': {bad_classification}"
    )


def test_every_write_note_relative_seam_has_port_coverage(tmp_path) -> None:
    """P-1 census gap closed (#2953): every ``write_note_relative`` call site
    is classified in ``WRITE_NOTE_RELATIVE_SITE_CLASSIFICATION`` as either
    ``guarded_by_port`` (covered by construction now that the port itself
    asserts WriteGuard) or ``guarded_by_caller`` (port coverage plus a
    pre-existing caller-side assert) -- a NEW call site with neither
    classification fails this gate instead of silently shipping an unguarded
    seam, mirroring ``test_every_write_seam_asserts_writeguard``'s shape for
    ``write_frontmatter``.
    """
    sites = find_write_note_relative_call_sites()
    assert sites, "expected at least the known production write_note_relative call sites"

    _assert_write_note_relative_census_is_closed(sites)

    # Prove the stable identifier did not turn into an allowlist escape hatch:
    # a genuinely new producer has a new (path, enclosing scope, ordinal) key
    # and therefore still fails loudly even though ordinary line drift does not.
    synthetic_app = tmp_path / "app"
    synthetic_app.mkdir()
    (synthetic_app / "new_producer.py").write_text(
        "def produce():\n    write_note_relative('new.md', 'content')\n",
        encoding="utf-8",
    )
    new_sites = find_write_note_relative_call_sites(synthetic_app, repo_root=tmp_path)
    assert new_sites == [("app/new_producer.py", "produce", 1)]

    (synthetic_app / "new_producer.py").write_text(
        "def produce():\n\n\n    write_note_relative('new.md', 'content')\n",
        encoding="utf-8",
    )
    assert find_write_note_relative_call_sites(synthetic_app, repo_root=tmp_path) == new_sites
    with pytest.raises(AssertionError, match="app/new_producer.py"):
        _assert_write_note_relative_census_is_closed(new_sites)


def test_every_candidate_create_once_seam_has_port_coverage() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    write_ops_path = repo_root / "app" / "knowledge" / "write_ops.py"
    writeback_path = repo_root / "app" / "knowledge_acquisition" / "candidate_writeback.py"
    write_ops_tree = ast.parse(write_ops_path.read_text(encoding="utf-8"))
    create = next(
        node
        for node in ast.walk(write_ops_tree)
        if isinstance(node, ast.FunctionDef) and node.name == "create_candidate_note_once"
    )
    probe = next(
        node
        for node in ast.walk(write_ops_tree)
        if isinstance(node, ast.FunctionDef) and node.name == "candidate_note_exists_durable"
    )

    def call_name(call: ast.Call) -> str | None:
        if isinstance(call.func, ast.Name):
            return call.func.id
        if isinstance(call.func, ast.Attribute):
            return call.func.attr
        return None

    calls = [node for node in ast.walk(create) if isinstance(node, ast.Call)]
    guard_calls = [node for node in calls if call_name(node) == "assert_writes_allowed"]
    assert len(guard_calls) == 1
    mutation_names = {
        "_atomic_rename_noreplace_at",
        "mkdir",
        "unlink",
        "write",
    }
    mutation_calls = [node for node in calls if call_name(node) in mutation_names]
    assert mutation_calls
    assert guard_calls[0].lineno < min(node.lineno for node in mutation_calls)

    forbidden_wrapper_names = {
        "FileIO",
        "dup",
        "dup2",
        "dup3",
        "fdopen",
    }
    for function in (create, probe):
        assert not any(isinstance(node, (ast.With, ast.AsyncWith)) for node in ast.walk(function))
        for call in (node for node in ast.walk(function) if isinstance(node, ast.Call)):
            assert call_name(call) not in forbidden_wrapper_names
            assert not (isinstance(call.func, ast.Name) and call.func.id == "open")

    call_sites: list[tuple[str, str]] = []
    for path in (repo_root / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            if call_name(call) != "create_candidate_note_once":
                continue
            owner: ast.AST | None = call
            while owner is not None and not isinstance(owner, ast.FunctionDef):
                owner = parents.get(owner)
            assert isinstance(owner, ast.FunctionDef)
            call_sites.append((str(path.relative_to(repo_root)), owner.name))
    assert call_sites == [
        ("app/knowledge_acquisition/candidate_writeback.py", "write_candidate_note")
    ]

    writeback_tree = ast.parse(writeback_path.read_text(encoding="utf-8"))
    write_candidate = next(
        node
        for node in ast.walk(writeback_tree)
        if isinstance(node, ast.FunctionDef) and node.name == "write_candidate_note"
    )
    assert (
        sum(
            call_name(call) == "create_candidate_note_once"
            for call in ast.walk(write_candidate)
            if isinstance(call, ast.Call)
        )
        == 1
    )

    mutant_tree = ast.parse(
        write_ops_path.read_text(encoding="utf-8").replace(
            "guard.assert_writes_allowed(action)",
            "guard_was_not_asserted = action",
            1,
        )
    )
    mutant_create = next(
        node
        for node in ast.walk(mutant_tree)
        if isinstance(node, ast.FunctionDef) and node.name == "create_candidate_note_once"
    )
    assert not any(
        isinstance(node, ast.Call) and call_name(node) == "assert_writes_allowed"
        for node in ast.walk(mutant_create)
    )


def test_registered_write_seams_cover_the_named_gap1_and_gap2_sites() -> None:
    """The P-1/P-4 runtime property registry names exactly the four sites
    this issue and its predecessor scope: the knowledge write port,
    identity-heal, checkbox rollback (formal-model.md gap 1's "remaining
    four sites" minus settings writeback, already gated by #2809), plus the
    #2953 P-1 census-gap fix's named live violator (``app/mcp/vault_tools.py``
    via the relative-path port).
    """
    names = {seam.name for seam in REGISTERED_WRITE_SEAMS}
    assert names == {
        "knowledge_write_port",
        "identity_heal",
        "checkbox_rollback",
        "mcp_vault_tools_append_note",
    }


# ---------------------------------------------------------------------------
# test_denying_guard_blocks_atomically -- P-1 runtime property
# ---------------------------------------------------------------------------


@given(seam_index=st.sampled_from(range(len(REGISTERED_WRITE_SEAMS))))
@settings(
    max_examples=len(REGISTERED_WRITE_SEAMS),
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
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
        monkeypatch.setattr(
            guard, "snapshot_fn", lambda: {"state": "safe_mode", "reason": "p1-deny"}
        )
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
@settings(
    max_examples=len(REGISTERED_WRITE_SEAMS),
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
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
