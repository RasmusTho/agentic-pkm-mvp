"""#4214 D5 gate: self-owned outbox producers must be classified, not remembered.

`required_db` is a durability *classification*. Until this gate existed the set
of classified producers lived in a hand-maintained table in `docs/DB_SCHEMA.md`,
and a per-callsite test could only prove that the producers someone happened to
name were classified — never that the set was complete. That is exactly how the
`POST /ingest` route (#4214 D2) and the vault-watcher delete tombstone (#4214
D3) were missed: both defaulted to `required_db=False` and silently dropped
events.

The rule enforced here, modelled on
`tests/architecture/test_outbox_producer_idempotency.py`:

    every self-owned (`conn`-less) `write_outbox_event` /
    `insert_object_and_outbox` call site in `app/` either passes an explicit
    `required_db=` keyword, or names its enclosing function on the reviewed
    allowlist below with the reason a silent skip is survivable there.

The allowlist is keyed on `(module, enclosing function)` — never on line
numbers, which shift under any unrelated edit — and is itself checked for rot:
an entry whose call site has since been classified (or removed) fails the gate,
so the allowlist cannot accumulate stale permissions.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "app"

PRODUCER_NAMES = {"write_outbox_event", "insert_object_and_outbox"}

# The defining module: `insert_object_and_outbox` forwards `required_db` to
# `write_outbox_event` over a caller-owned `conn`, so it is not a producer.
DEFINING_MODULE = APP_ROOT / "services" / "outbox.py"

# Reviewed exemptions. Every entry must state WHY a silent skip is survivable —
# in practice: the call site has a compensating sink that outlives the skip, so
# the record is not lost and no success is reported on the strength of the DB
# row alone.
ALLOWLIST: dict[tuple[str, str], str] = {
    ("app/receipts/settings_write.py", "emit_settings_write_receipt"): (
        "the fsync'd JSONL receipt written just above IS the durability contract "
        "(durable_settings_write_receipt_exists reads it back); the DB row is a mirror"
    ),
    ("app/watcher/registry.py", "_process_panel_note"): (
        "_write_jsonl_event (append_jsonl_outbox_event) compensates unconditionally "
        "on the same path"
    ),
    ("app/panel/confirmation.py", "_emit_projection_event"): (
        "JSONL is the declared primary sink and the caller raises "
        "PanelReceiptPersistenceError when NO sink took the event"
    ),
    ("app/agents/panel_agent/runtime.py", "_write_db_outbox_events"): (
        "the caller's unguarded append_jsonl_outbox_event loop is the required sink; "
        "this DB write is the documented mirror"
    ),
    ("app/cli/__init__.py", "pipe"): (
        "append_jsonl to INDEX_OUTBOX_PATH records the pipeline run on the same path "
        "before this call; the DB emission is an operator-facing convenience on a "
        "one-shot CLI, not a durability contract"
    ),
    ("app/services/vault_sync.py", "_enqueue"): (
        "the conn=None default is vestigial: all three call sites (delete_note, "
        "upsert_note, and the object sync) pass a live conn_rw() connection inside "
        "the same transaction as the store write, so this never runs self-owned"
    ),
    ("app/knowledge_acquisition/acquisition_requests.py", "_emit"): (
        "self-owned at runtime (every facade that reaches it defaults conn=None), but "
        "the acquisition queue is volatile in exactly the configurations where the "
        "write skips: _resolve_backend lets an explicit STORE_BACKEND win, so a memory "
        "backend means _MEMORY_REQUESTS holds the rows these events describe. Unlike "
        "stage_events, this lane has no require_configured_database_url, and the return "
        "is discarded. Classifying it required_db=True breaks source sync on a memory "
        "runtime (tests/knowledge_acquisition/test_playlist_discovery.py)"
    ),
    ("app/heimdal/entity_register.py", "_emit"): (
        "conn=self._conn may be None, but the register note written before this call "
        "is the canonical identity record and survives the skip; the event is a "
        "projection trigger and no caller derives a success signal from the return"
    ),
    ("app/api/routes/capture.py", "_emit_capture_event"): (
        "JSONL is the declared primary sink and the caller raises "
        "CaptureEventPersistenceError when NO sink took the event"
    ),
    ("app/workers/outbox_worker.py", "_emit_ka_consumer_signal"): (
        "documented audit-only observability signal; JSONL is written first and a "
        "failure must never re-block the poll loop"
    ),
    ("app/workers/outbox_worker.py", "_emit_retry_dead_letter"): (
        "JSONL audit append runs unconditionally first; the message is dropped either way"
    ),
    ("app/workers/outbox_worker.py", "_dead_letter_outbox_message"): (
        "self-owned fallback taken only when open_outbox_txn_conn() returned None; "
        "the JSONL audit append above already recorded the dead letter"
    ),
    # The Heimdal meeting family sets `emitted = True` on a normal return
    # rather than on the returned row id, because its idempotency keys are
    # derived from stable identity: a deduplicated "" there is proof the event
    # was already committed by a prior attempt, so treating "" as failure would
    # refuse the capture forever. That reading is only sound while a normal
    # return cannot mean "skipped", so each of these guards its DB branch with
    # `self_owned_write_would_skip()` — the policy itself, not a re-derived
    # STORE_BACKEND/DSN predicate. The unconditional JSONL append above the
    # guard is what survives a skip.
    ("app/api/routes/heimdal_meeting.py", "_emit_user_note_event"): (
        "unconditional JSONL append survives a skip, and the DB branch runs only when "
        "self_owned_write_would_skip() is False, so a normal return proves the row exists"
    ),
    ("app/heimdal/media_ingress.py", "_emit_admission_event"): (
        "unconditional JSONL append survives a skip, and the DB branch runs only when "
        "self_owned_write_would_skip() is False, so a normal return proves the row exists"
    ),
    ("app/heimdal/meeting_finalization.py", "_emit_finalized_event"): (
        "unconditional JSONL append survives a skip, and the DB branch runs only when "
        "self_owned_write_would_skip() is False, so a normal return proves the row exists"
    ),
    ("app/heimdal/meeting_ledger.py", "_emit_late_admitted_event"): (
        "documented non-acknowledging emission: the segment ledger row is already "
        "committed before this runs, the JSONL append precedes the DB branch, and the "
        "caller discards the result"
    ),
    ("app/instance/default_vault.py", "_emit_default_mutation_event"): (
        "MVR-02 (#3856): the compensating sink is the durable registry revision itself. "
        "set_instance_default commits the new default to the instance-state volume BEFORE "
        "this runs, and the Multi-Vault Runtime cross-task invariant is that background "
        "supervisors reconcile durable registry revisions, never event delivery — wake-up "
        "hints are explicitly not the transition authority. No caller derives a success "
        "signal from the return. Classifying it required_db=True would make the headless "
        "`python -m app.instance.runtime default-vault-set` command unusable on a bare "
        "instance that has no configured outbox at all"
    ),
    ("app/instance/vault_dimensions.py", "emit_dimension_mutation_event"): (
        "MVR-04 (#3858): identical durability posture to the MVR-02 default mutation "
        "above, and for the same reason. set_dimension_state commits the new membership "
        "to the instance-state volume under the registry writer lock BEFORE this runs, so "
        "the durable registry revision is the compensating sink; the Multi-Vault Runtime "
        "cross-task invariant is that background supervisors reconcile durable registry "
        "revisions, never event delivery. The event is additionally non-authoritative by "
        "construction — a dimension grants nothing, so a dropped mirror cannot cost a "
        "consumer any authority decision. No caller derives a success signal from the "
        "return. Classifying it required_db=True would make the headless "
        "`python -m app.instance.runtime dimension-*` commands unusable on a bare "
        "instance that has no configured outbox at all"
    ),
}


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def test_every_outbox_producer_routes_through_the_binding_aware_choke_point() -> None:
    """MVR-05A7: one binding-aware insert seam and explicit worker inheritance."""
    direct_inserts: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if "insert into outbox" in " ".join(arg.value.lower().split()):
                        direct_inserts.append(str(path.relative_to(APP_ROOT.parent)))
    assert direct_inserts == ["app/services/outbox.py"]

    outbox_source = DEFINING_MODULE.read_text(encoding="utf-8")
    assert "derive_binding_scoped_idempotency_key" in outbox_source
    assert "_resolve_outbox_vault_binding_id" in outbox_source
    normalized_outbox_source = " ".join(outbox_source.split())
    assert "legacy_key" in normalized_outbox_source
    assert "vault_binding_id" in normalized_outbox_source

    worker_path = APP_ROOT / "workers" / "outbox_worker.py"
    worker_tree = ast.parse(worker_path.read_text(encoding="utf-8"), filename=str(worker_path))
    worker_writes = [
        node
        for node in ast.walk(worker_tree)
        if isinstance(node, ast.Call) and _call_name(node) == "write_outbox_event"
    ]
    assert len(worker_writes) == 5
    assert all(
        any(keyword.arg == "vault_binding_id" for keyword in call.keywords)
        for call in worker_writes
    )


def _enclosing_function_node(
    node: ast.AST, parents: dict[ast.AST, ast.AST]
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
        current = parents.get(current)
    return None


def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    enclosing = _enclosing_function_node(node, parents)
    return enclosing.name if enclosing is not None else "<module>"


def _names_bound_to_a_call(
    enclosing: ast.FunctionDef | ast.AsyncFunctionDef | None,
) -> set[str]:
    """Local names assigned from a call or bound by a ``with`` in this function.

    ``with _conn() as conn:`` / ``conn = conn_rw()`` are the only shapes in this
    repo that PROVE a live connection at the call site without leaving the file.
    """
    if enclosing is None:
        return set()
    bound: set[str] = set()
    for node in ast.walk(enclosing):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound.add(target.id)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if isinstance(item.context_expr, ast.Call) and isinstance(
                    item.optional_vars, ast.Name
                ):
                    bound.add(item.optional_vars.id)
    return bound


def _conn_is_caller_owned(
    conn_arg: ast.expr | None,
    enclosing: ast.FunctionDef | ast.AsyncFunctionDef | None,
) -> bool:
    """Whether a ``conn=`` argument really proves a caller-owned transaction.

    Only a value that provably cannot be ``None`` does, and inside one function
    that means a name bound from a call (``with _conn() as conn``). Everything
    else — a literal ``None``, a forwarded parameter, an attribute such as
    ``self._conn`` — is unprovable here and owes a classification or a reviewed
    allowlist reason.

    A forwarded parameter is unprovable EVEN WHEN it has no default of its own,
    because the caller one frame up may itself default it to ``None``. That is
    not hypothetical: ``AcquisitionRequests._emit`` declares ``conn: Any`` with
    no default, while every facade that reaches it (``enqueue``, ``claim_batch``,
    ``_emit_failed``) defaults ``conn=None`` and the production caller in
    ``playlist_discovery`` passes none at all. Reading "no default" as "caller
    owns it" let that site escape the gate entirely, so the gate's completeness
    claim — the whole point of #4214 D5 — was false.
    """
    if conn_arg is None:
        return False
    if isinstance(conn_arg, ast.Name):
        return conn_arg.id in _names_bound_to_a_call(enclosing)
    return False


def _unclassified_self_owned_producers() -> dict[tuple[str, str], list[int]]:
    """Map (module, function) -> line numbers of unclassified self-owned calls."""
    found: dict[tuple[str, str], list[int]] = {}
    for path in sorted(APP_ROOT.rglob("*.py")):
        if path == DEFINING_MODULE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) not in PRODUCER_NAMES:
                continue
            keywords = {kw.arg: kw.value for kw in node.keywords}
            enclosing = _enclosing_function_node(node, parents)
            if _conn_is_caller_owned(keywords.get("conn"), enclosing):
                # A conn that cannot be None bypasses the self-owned policy
                # entirely and owes nothing here.
                continue
            required_db = keywords.get("required_db")
            if required_db is not None and not (
                isinstance(required_db, ast.Constant) and required_db.value is False
            ):
                # A resolved expression (`required_db=db_outbox_required()`) or
                # a literal True is a real classification. A literal
                # `required_db=False` is NOT — it re-states the risky default,
                # so it still owes a reviewed allowlist reason rather than
                # silently satisfying the gate.
                continue
            key = (str(path.relative_to(APP_ROOT.parent)), _enclosing_function(node, parents))
            found.setdefault(key, []).append(node.lineno)
    return found


def test_every_self_owned_producer_is_classified_or_allowlisted() -> None:
    unclassified = _unclassified_self_owned_producers()
    unreviewed = {key: lines for key, lines in unclassified.items() if key not in ALLOWLIST}

    assert not unreviewed, (
        "self-owned outbox producers with no required_db= classification and no reviewed "
        "allowlist entry — an unclassified producer defaults to the SKIPPING path and can "
        "silently drop the event (#4214 D5): "
        + ", ".join(f"{module}::{function} (lines {lines})" for (module, function), lines in sorted(unreviewed.items()))
    )


def test_allowlist_has_no_stale_entries() -> None:
    """A producer that has since been classified must lose its exemption."""
    unclassified = _unclassified_self_owned_producers()
    stale = sorted(key for key in ALLOWLIST if key not in unclassified)

    assert not stale, (
        "allowlisted producers that no longer have an unclassified self-owned call site; "
        "remove the entry so the allowlist keeps meaning what it says: "
        + ", ".join(f"{module}::{function}" for module, function in stale)
    )


def test_allowlist_entries_state_a_reason() -> None:
    missing = sorted(key for key, reason in ALLOWLIST.items() if not reason.strip())
    assert not missing, f"allowlist entries without a stated reason: {missing}"


def test_the_two_producers_this_gate_exists_for_are_classified() -> None:
    """The #4214 D2/D3 call sites specifically may never regress to the default."""
    unclassified = _unclassified_self_owned_producers()
    for module, function in (
        ("app/api/routes/ingest.py", "ingest"),
        ("app/watcher/vault_watcher.py", "_emit_watcher_delete_event"),
    ):
        assert (module, function) not in unclassified, (
            f"{module}::{function} lost its required_db classification; it has no "
            "compensating sink, so a silent skip is unrecoverable data loss"
        )
        assert (module, function) not in ALLOWLIST, (
            f"{module}::{function} may not be allowlisted — it has no compensating sink"
        )


def test_required_db_signature_stays_keyword_only_with_a_false_default() -> None:
    """The gate above is only meaningful while the unclassified default is the risky one."""
    tree = ast.parse(DEFINING_MODULE.read_text(encoding="utf-8"))
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in PRODUCER_NAMES:
            continue
        kwonly = dict(zip(node.args.kwonlyargs, node.args.kw_defaults))
        defaults = {arg.arg: default for arg, default in kwonly.items()}
        assert "required_db" in defaults, f"{node.name} must take required_db keyword-only"
        default = defaults["required_db"]
        assert isinstance(default, ast.Constant) and default.value is False, (
            f"{node.name}'s required_db default changed; this gate assumes the "
            "unclassified default is the skipping path"
        )
        checked += 1
    assert checked == len(PRODUCER_NAMES), "both producer definitions must be checked"
