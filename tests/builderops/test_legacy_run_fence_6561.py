"""Synthetic projections only; no live Codex, process or GitHub access."""
import pytest

from app.builderops import legacy_codex_6561_guard as guard


def _digest(value, *, sort_keys=False):
    import hashlib
    import json
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=sort_keys,
                                     separators=(",", ":")).encode()).hexdigest()


def _jsonl(rows):
    import json
    return b"".join(json.dumps({"ordinal": i, **row}).encode() + b"\n" for i, row in enumerate(rows))


@pytest.fixture
def source_bound(tmp_path, monkeypatch):
    import hashlib
    import json
    import sqlite3
    from datetime import datetime, timezone

    synthetic_body = hashlib.sha256(b"synthetic body").hexdigest()
    monkeypatch.setattr(guard, "BODY", synthetic_body)
    child_path, parent_path, database = tmp_path / "child.jsonl", tmp_path / "parent.jsonl", tmp_path / "state.sqlite"
    monkeypatch.setattr(guard, "CHILD_JOURNAL", child_path)
    monkeypatch.setattr(guard, "PARENT_JOURNAL", parent_path)
    monkeypatch.setattr(guard, "STATE_DB", database)
    monkeypatch.setattr(guard.codex_session_relations, "STATE_DB", database)
    monkeypatch.setattr(guard.codex_session_relations, "CHILD_JOURNAL", child_path)
    monkeypatch.setattr(guard.codex_session_relations, "PARENT_JOURNAL", parent_path)
    commands = {identity: (pid, _digest(["read", str(i)]))
                for i, (identity, (pid, _)) in enumerate(guard.INVENTORY_COMMANDS.items())}
    calls = {identity: (name, _digest(f"read-only input {i}"))
             for i, (identity, (name, _)) in enumerate(guard.INVENTORY_CALLS.items())}
    mcps = dict(guard.INVENTORY_MCP)
    mcp_hashes = {identity: _digest({"issue": 6561}, sort_keys=True) for identity in mcps}
    pubs = guard.PUBLICATION_COMMANDS
    pub_hashes = {identity: _digest(["synthetic publication", identity]) for identity in pubs}
    parent_args = '{"target":"issue6561_normal_transport"}'
    parent_calls = {identity: (name, "2026-11-15T08:00:00Z", _digest(parent_args))
                    for identity, (name, _, _) in guard.PARENT_CALLS.items()}
    monkeypatch.setattr(guard, "INVENTORY_COMMANDS", commands)
    monkeypatch.setattr(guard, "INVENTORY_CALLS", calls)
    monkeypatch.setattr(guard, "MCP_ARGUMENT_HASHES", mcp_hashes)
    monkeypatch.setattr(guard, "PUBLICATION_HASHES", pub_hashes)
    monkeypatch.setattr(guard, "PARENT_CALLS", parent_calls)
    child = [{"type": "session_meta", "payload": {"id": guard.CHILD}}]
    for identity in pubs:
        child.append({"type": "event_msg", "payload": {"type": "item_completed", "thread_id": guard.CHILD,
            "turn_id": "01a19b1d-76b9-71c2-8d4c-edc8a0c5e0ce", "item": {"id": identity, "type": "CommandExecution",
            "status": "completed", "exit_code": 0, "command": ["synthetic publication", identity],
            "aggregated_output": json.dumps({"pr": 6562, "head": guard.HEAD, "body_sha256": guard.BODY,
                                               "state": "open"}) + "\ncomment link"}}})
    child.append({"type": "turn_context", "timestamp": "2026-11-15T07:55:12.559Z", "payload": {"turn_id": guard.TURN}})
    for i, (identity, (pid, _)) in enumerate(commands.items()):
        child.append({"type": "event_msg", "timestamp": f"2026-11-15T07:56:{i:02d}.000Z",
            "payload": {"type": "item_completed", "thread_id": guard.CHILD,
            "turn_id": guard.TURN, "item": {"id": identity,
            "type": "CommandExecution", "process_id": str(pid), "status": "completed", "exit_code": 0,
            "command": ["read", str(i)]}}})
    for i, identity in enumerate(mcps):
        child.append({"type": "event_msg", "timestamp": f"2026-11-15T07:57:{i:02d}.000Z",
            "payload": {"type": "item_completed", "thread_id": guard.CHILD,
            "turn_id": guard.TURN, "item": {"id": identity,
            "type": "McpToolCall", "server": "codex_apps", "tool": mcps[identity], "status": "completed",
            "arguments": {"issue": 6561}}}})
    for i, (identity, (name, _)) in enumerate(calls.items()):
        payload = {"type": "custom_tool_call" if name == "exec" else "function_call", "name": name,
                   "call_id": identity}
        payload["input" if name == "exec" else "arguments"] = f"read-only input {i}"
        child.append({"type": "response_item", "timestamp": f"2026-11-15T07:58:{i:02d}.000Z", "payload": payload})
    child.append({"type": "event_msg", "timestamp": "2026-11-15T08:03:36.536Z",
                  "payload": {"type": "turn_aborted", "turn_id": guard.TURN}})
    parent = [{"type": "session_meta", "payload": {"id": guard.PARENT}}]
    for identity, (name, _, _) in parent_calls.items():
        parent.append({"type": "response_item", "timestamp": "2026-11-15T08:00:00Z",
            "payload": {"type": "function_call", "call_id": identity, "name": name,
                        "arguments": parent_args}})
    parent.append({"type": "event_msg", "timestamp": "2026-11-15T08:16:25Z",
                   "payload": {"type": "task_complete", "turn_id": guard.PARENT_TURN}})
    parent.append({"type": "event_msg", "timestamp": "2026-11-15T10:15:58Z",
                   "payload": {"type": "token_count", "info": None, "rate_limits": None}})
    child_path.write_bytes(_jsonl(child))
    parent_path.write_bytes(_jsonl(parent))
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE threads(id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL, thread_source TEXT)")
        db.execute("CREATE TABLE thread_spawn_edges(parent_thread_id TEXT NOT NULL, child_thread_id TEXT PRIMARY KEY NOT NULL, status TEXT NOT NULL)")
        db.execute("INSERT INTO threads VALUES (?, ?, ?)", (guard.CHILD, str(child_path), "subagent"))
        db.execute("INSERT INTO threads VALUES (?, ?, ?)", (guard.PARENT, str(parent_path), "user"))
        db.execute("INSERT INTO thread_spawn_edges VALUES (?, ?, ?)", (guard.PARENT, guard.CHILD, "open"))
    # The synthetic host operator brackets a separate, read-only transaction
    # with source fingerprints. The host adapter independently re-reads target relations.
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("BEGIN")
        assert db.execute("SELECT id, rollout_path, thread_source FROM threads WHERE id=?",
                          (guard.CHILD,)).fetchall() == [(guard.CHILD, str(child_path), "subagent")]
        assert db.execute("SELECT id, rollout_path FROM threads WHERE id=?",
                          (guard.PARENT,)).fetchall() == [(guard.PARENT, str(parent_path))]
        assert db.execute("SELECT parent_thread_id FROM thread_spawn_edges WHERE child_thread_id=?",
                          (guard.CHILD,)).fetchall() == [(guard.PARENT,)]
        assert db.execute("SELECT child_thread_id FROM thread_spawn_edges WHERE parent_thread_id=?",
                          (guard.CHILD,)).fetchall() == []
    pub = {"state": "reconciled", "pr": 6562, "head": guard.HEAD, "repo": "RasmusTho/agentic-pkm-mvp",
           "branch": guard.BRANCH, "pr_state": "OPEN", "body_sha256": guard.BODY, "sources": {}}
    evidence = {"child_sha256": hashlib.sha256(child_path.read_bytes()).hexdigest(),
                "parent_sha256": hashlib.sha256(parent_path.read_bytes()).hexdigest(),
                "parent_prefix_bytes": parent_path.stat().st_size,
                "observed_at": "2026-11-15T10:16:00Z", "no_new_manual_starts": True,
                "historical_push_output": "unknown", "earlier_body": "unknown", "historical_ppids": "unknown",
                "unrecorded_effects": "unknown", "boot": "2026-11-14T21:48:30Z",
                "relations": {"source": str(database), "source_tables": ["threads", "thread_spawn_edges"],
                    "read_method": "sqlite_readonly_consistent_transaction", "child_thread_source": "subagent",
                    "parent_edge_count": 1, "child_thread_count": 1, "parent_thread_count": 1,
                    "parent": guard.PARENT, "child": guard.CHILD,
                    "child_rollout": str(child_path), "parent_rollout": str(parent_path),
                    "registered_children": [], "observation_complete": True,
                    "observed_at": "2026-11-15T10:15:59Z",
                    "coordination_started_at": "2026-11-15T08:04:00Z",
                    "coordination": "no_new_manual_starts_until_transition_complete"}}
    receipt = {"mode": "operator", "account": "RasmusTho", "issue": 6561,
        "mandate": {"repo": "RasmusTho/agentic-pkm-mvp", "issue": 6561, "reference": "synthetic mandate",
                    "effects": ["reconcile", "claim", "register", "acknowledge"]},
        "successor": {"session": "successor"}, "candidate": {"path": guard.WORKTREE, "branch": guard.BRANCH,
            "generation": "c98ea60e6e0d4592b08d1ce05e5517b3"},
        "registration": {"path": guard.WORKTREE, "branch": guard.BRANCH,
            "generation": "c98ea60e6e0d4592b08d1ce05e5517b3", "owner": "issue6561-normal-transport-20261102"},
        "predecessor": {"holder": "codex-issue6561-normal-transport", "lease_id": "lease-a0019077"},
        "writer": {"state": "stopped", "delegations": "stopped", "restart": "reconciled", "codex_custody": evidence,
                   "boot": "2026-11-14T21:48:30Z", "last_activity": "2026-11-15T08:03:36.536Z"},
        "publication": pub}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    comment = {"id": 42, "user": {"login": "RasmusTho"}, "author_association": "OWNER",
               "issue_url": "https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/6561",
               "created_at": now, "updated_at": now, "body": json.dumps({"operator_reconciliation.v1": receipt})}
    monkeypatch.setattr(guard.agent_worktree, "_read_github_transfer_comment", lambda comment_id, cwd: comment)
    def github(args, *, cwd):
        endpoint = args[0]
        if endpoint == "user":
            return "RasmusTho"
        if endpoint.endswith("/pulls/6562"):
            return json.dumps({"number": 6562, "state": "open", "body": "synthetic body",
                "head": {"sha": guard.HEAD, "ref": guard.BRANCH, "repo": {"full_name": "RasmusTho/agentic-pkm-mvp"}},
                "base": {"ref": "main", "repo": {"full_name": "RasmusTho/agentic-pkm-mvp"}}})
        if endpoint == "repos/RasmusTho/agentic-pkm-mvp":
            return json.dumps({"full_name": "RasmusTho/agentic-pkm-mvp", "default_branch": "main"})
        if "/git/ref/heads/" in endpoint:
            return json.dumps({"ref": f"refs/heads/{guard.BRANCH}", "object": {"sha": guard.HEAD}})
        if endpoint == "--method":
            return json.dumps([[{"number": 6562, "state": "open", "head": {"sha": guard.HEAD, "ref": guard.BRANCH},
                                 "base": {"ref": "main"}}]])
        if "/issues/comments/" in endpoint:
            return json.dumps({"id": int(endpoint.rsplit("/", 1)[1]), "user": {"login": "RasmusTho"},
                "issue_url": "https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/6561"})
        raise AssertionError(endpoint)
    monkeypatch.setattr(guard.legacy_owner_recovery, "_github_read", github)
    synthetic_body = hashlib.sha256(b"synthetic body").hexdigest()
    monkeypatch.setattr(guard, "BODY", synthetic_body)
    pub["body_sha256"] = synthetic_body
    comment["body"] = json.dumps({"operator_reconciliation.v1": receipt})
    host = {"/usr/sbin/sysctl": f"{{ sec = {int(guard.BOOT.timestamp())}, usec = 0 }}", "/bin/ps": "777 1 unrelated\n",
            "/bin/launchctl": "", "/usr/bin/crontab": ""}
    monkeypatch.setattr(guard, "_run_readback", lambda *args, **kwargs: host[args[0]])
    return {"child": child, "parent": parent, "child_path": child_path, "parent_path": parent_path,
            "database": database, "receipt": receipt, "comment": comment, "host": host, "calls": calls}


def _check():
    from pathlib import Path
    return guard.check(cwd=Path("."), issue=6561, pr=6562, worktree=Path(guard.WORKTREE),
                       session="successor", comment_id=42)


def _refresh_comment(data):
    import hashlib
    import json
    evidence = data["receipt"]["writer"]["codex_custody"]
    evidence["child_sha256"] = hashlib.sha256(data["child_path"].read_bytes()).hexdigest()
    evidence["parent_sha256"] = hashlib.sha256(data["parent_path"].read_bytes()).hexdigest()
    evidence["parent_prefix_bytes"] = data["parent_path"].stat().st_size
    data["comment"]["body"] = json.dumps({"operator_reconciliation.v1": data["receipt"]})


def test_real_entrypoint_checks_synthetic_sources_and_preserves_unknowns(source_bound):
    result = _check()
    assert result["historical_ppids"] == result["unrecorded_effects"] == "UNKNOWN"
    assert result["arbitrary_or_future_processes"] == "UNKNOWN"


@pytest.mark.parametrize("mutation", ["new_turn", "nonterminal", "new_call", "changed_command", "new_mcp"])
def test_entrypoint_refuses_changed_even_when_operator_hash_is_refreshed(source_bound, mutation):
    child = source_bound["child"]
    if mutation == "new_turn":
        child.append({"type": "turn_context", "timestamp": "2026-11-15T09:00:00Z", "payload": {"turn_id": "new"}})
    elif mutation == "nonterminal":
        next(x for x in child if x.get("payload", {}).get("turn_id") == guard.TURN
             and x["payload"].get("item", {}).get("type") == "CommandExecution")["payload"]["item"]["status"] = "in_progress"
    elif mutation == "new_call":
        child.append({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
                                                               "call_id": "extra", "input": "new"}})
    elif mutation == "changed_command":
        next(x for x in child if x.get("payload", {}).get("turn_id") == guard.TURN
             and x["payload"].get("item", {}).get("type") == "CommandExecution")["payload"]["item"]["command"] = ["write"]
    else:
        next(x for x in child if x.get("payload", {}).get("item", {}).get("type") == "McpToolCall")["payload"]["item"]["arguments"] = {"issue": 2}
    source_bound["child_path"].write_bytes(_jsonl(child))
    _refresh_comment(source_bound)
    with pytest.raises(guard.GuardRefused, match="UNKNOWN"):
        _check()


def test_entrypoint_refuses_journal_tampering_and_unauthenticated_receipt(source_bound):
    source_bound["child_path"].write_bytes(source_bound["child_path"].read_bytes() + b"\n")
    with pytest.raises(guard.GuardRefused, match="journal changed"):
        _check()
    _refresh_comment(source_bound)
    source_bound["comment"]["user"]["login"] = "Mallory"
    with pytest.raises(guard.GuardRefused, match="authentication"):
        _check()


def test_entrypoint_refuses_new_parent_followup_and_registered_child(source_bound):
    import sqlite3
    source_bound["parent"].append({"type": "response_item", "timestamp": "2026-11-15T10:15:59Z",
        "payload": {"type": "function_call", "name": "followup_task", "call_id": "extra", "arguments": guard.CHILD}})
    source_bound["parent_path"].write_bytes(_jsonl(source_bound["parent"]))
    _refresh_comment(source_bound)
    with pytest.raises(guard.GuardRefused, match="parent activity"):
        _check()
    source_bound["parent"].pop()
    source_bound["parent_path"].write_bytes(_jsonl(source_bound["parent"]))
    _refresh_comment(source_bound)
    with sqlite3.connect(source_bound["database"]) as db:
        db.execute("INSERT INTO thread_spawn_edges VALUES (?, ?, ?)", (guard.CHILD, "00000000-0000-4000-8000-000000000001", "open"))
    with pytest.raises(guard.GuardRefused, match="target relations changed"):
        _check()


def test_entrypoint_refuses_identified_process_restart_and_boot_drift(source_bound):
    source_bound["host"]["/bin/ps"] = f"{next(iter(guard.INVENTORY_COMMANDS.values()))[0]} 1 synthetic\n"
    with pytest.raises(guard.GuardRefused, match="process"):
        _check()
    source_bound["host"]["/bin/ps"] = "777 1 unrelated\n"
    source_bound["host"]["/bin/launchctl"] = guard.WORKTREE
    with pytest.raises(guard.GuardRefused, match="restart"):
        _check()
    source_bound["host"]["/bin/launchctl"] = ""
    source_bound["host"]["/usr/sbin/sysctl"] = "sec = 1"
    with pytest.raises(guard.GuardRefused, match="boot changed"):
        _check()


@pytest.mark.parametrize("field,value", [
    ("last_activity", "2026-11-14T20:00:00Z"),
    ("boot", "2026-11-15T09:00:00Z"),
    ("state", "unknown"),
    ("delegations", "unknown"),
    ("restart", "unknown"),
])
def test_operator_cannot_rebind_postboot_activity_or_mark_unknown_as_safe(source_bound, field, value):
    source_bound["receipt"]["writer"][field] = value
    _refresh_comment(source_bound)
    with pytest.raises(guard.GuardRefused, match="UNKNOWN"):
        _check()


def test_entrypoint_refuses_historical_effect_not_terminal(source_bound):
    event = next(x for x in source_bound["child"] if x.get("payload", {}).get("item", {}).get("id") == next(iter(guard.PUBLICATION_COMMANDS)))
    event["payload"]["item"]["exit_code"] = None
    source_bound["child_path"].write_bytes(_jsonl(source_bound["child"]))
    _refresh_comment(source_bound)
    with pytest.raises(guard.GuardRefused, match="publication command"):
        _check()


def test_entrypoint_refuses_publication_mismatch(source_bound):
    source_bound["receipt"]["publication"]["head"] = "f" * 40
    _refresh_comment(source_bound)
    with pytest.raises(guard.GuardRefused, match="publication changed"):
        _check()


def test_entrypoint_refuses_unbound_or_missing_codex_state(source_bound):
    import sqlite3
    with sqlite3.connect(source_bound["database"]) as db:
        db.execute("UPDATE threads SET rollout_path=? WHERE id=?", ("/not/the/parent", guard.PARENT))
    with pytest.raises(guard.GuardRefused, match="relation source unavailable"):
        _check()
    source_bound["database"].unlink()
    with pytest.raises(guard.GuardRefused, match="relation source unavailable"):
        _check()


def test_entrypoint_refuses_uncoordinated_manual_starts(source_bound):
    source_bound["receipt"]["writer"]["codex_custody"]["no_new_manual_starts"] = False
    _refresh_comment(source_bound)
    with pytest.raises(guard.GuardRefused, match="operator source binding"):
        _check()


def test_entrypoint_refuses_operator_comment_change_during_check(source_bound, monkeypatch):
    initial = source_bound["comment"]
    changed = dict(initial, body=initial["body"] + " ")
    reads = iter((initial, changed))
    monkeypatch.setattr(guard.agent_worktree, "_read_github_transfer_comment", lambda comment_id, cwd: next(reads))
    with pytest.raises(guard.GuardRefused, match="comment changed"):
        _check()


def test_entrypoint_refuses_unexpected_journal_item(source_bound):
    source_bound["child"].append({"type": "event_msg", "payload": {"type": "item_completed", "thread_id": guard.CHILD,
        "turn_id": guard.TURN, "item": {"type": "FileChange", "id": "unexpected", "status": "completed"}}})
    source_bound["child_path"].write_bytes(_jsonl(source_bound["child"]))
    _refresh_comment(source_bound)
    with pytest.raises(guard.GuardRefused, match="unrecognized inventory"):
        _check()


def test_entrypoint_refuses_empty_process_observation(source_bound):
    source_bound["host"]["/bin/ps"] = ""
    with pytest.raises(guard.GuardRefused, match="empty process"):
        _check()


def test_entrypoint_refuses_missing_recorded_final_patch_body(source_bound):
    event = next(x for x in source_bound["child"] if x.get("payload", {}).get("item", {}).get("id")
                 == "exec-d79126fc-968a-47e6-aaed-89a64b7ae500")
    event["payload"]["item"]["aggregated_output"] = "truncated"
    source_bound["child_path"].write_bytes(_jsonl(source_bound["child"]))
    _refresh_comment(source_bound)
    with pytest.raises(guard.GuardRefused, match="PATCH body"):
        _check()


def _append_parent(data, row):
    import json
    with data["parent_path"].open("ab") as stream:
        stream.write(json.dumps(row).encode() + b"\n")


def _token_event(ordinal):
    return {"ordinal": ordinal, "type": "event_msg", "timestamp": "2026-11-15T10:16:01Z",
            "payload": {"type": "token_count", "info": None, "rate_limits": None}}


def test_same_bound_receipt_accepts_harmless_appends_at_repeated_real_entrypoint(source_bound):
    initial = _check()
    # Model preclaim and later prepared/resume checks without claiming or writing remotely.
    checkpoint = source_bound["receipt"]["writer"]["codex_custody"].copy()
    _append_parent(source_bound, _token_event(len(source_bound["parent"])))
    assert _check() == initial
    _append_parent(source_bound, _token_event(len(source_bound["parent"]) + 1))
    assert _check() == initial
    assert source_bound["receipt"]["writer"]["codex_custody"] == checkpoint


@pytest.mark.parametrize("kind", ["followup", "spawn", "write", "unknown", "ordinal_gap", "partial"])
def test_unverified_tail_activity_refuses_same_bound_receipt(source_bound, kind):
    _check()
    ordinal = len(source_bound["parent"])
    if kind == "partial":
        with source_bound["parent_path"].open("ab") as stream:
            stream.write(b'{"type":"event_msg"')
    elif kind == "ordinal_gap":
        _append_parent(source_bound, _token_event(ordinal + 1))
    elif kind == "unknown":
        _append_parent(source_bound, {"ordinal": ordinal, "type": "event_msg", "timestamp": "2026-11-15T10:16:01Z",
                                      "payload": {"type": "task_complete"}})
    else:
        name = {"followup": "followup_task", "spawn": "spawn_agent", "write": "exec"}[kind]
        _append_parent(source_bound, {"ordinal": ordinal, "type": "response_item", "timestamp": "2026-11-15T10:16:01Z",
                                     "payload": {"type": "function_call", "name": name,
                                                 "arguments": guard.CHILD}})
    with pytest.raises(guard.GuardRefused, match="parent"):
        _check()


def test_prefix_mutation_and_invalid_checkpoint_refuse(source_bound):
    _check()
    original = source_bound["parent_path"].read_bytes()
    source_bound["parent_path"].write_bytes(original.replace(b"session_meta", b"session_metb", 1))
    with pytest.raises(guard.GuardRefused, match="checkpoint changed"):
        _check()
    source_bound["parent_path"].write_bytes(original)
    source_bound["receipt"]["writer"]["codex_custody"]["parent_prefix_bytes"] -= 1
    import json
    source_bound["comment"]["body"] = json.dumps({"operator_reconciliation.v1": source_bound["receipt"]})
    with pytest.raises(guard.GuardRefused, match="checkpoint boundary"):
        _check()


def test_safe_append_between_initial_and_final_parent_reads(source_bound, monkeypatch):
    original = guard._read_source
    seen = 0
    def read_source(path, limit):
        nonlocal seen
        result = original(path, limit)
        if path == source_bound["parent_path"]:
            seen += 1
            if seen == 1:
                _append_parent(source_bound, _token_event(len(source_bound["parent"])))
        return result
    monkeypatch.setattr(guard, "_read_source", read_source)
    _check()
    assert seen == 2


def test_effectful_append_between_initial_and_final_parent_reads_refuses(source_bound, monkeypatch):
    original = guard._read_source
    seen = 0
    def read_source(path, limit):
        nonlocal seen
        result = original(path, limit)
        if path == source_bound["parent_path"]:
            seen += 1
            if seen == 1:
                _append_parent(source_bound, {"ordinal": len(source_bound["parent"]), "type": "response_item",
                    "timestamp": "2026-11-15T10:16:01Z", "payload": {"type": "function_call",
                                                                            "name": "spawn_agent"}})
        return result
    monkeypatch.setattr(guard, "_read_source", read_source)
    with pytest.raises(guard.GuardRefused, match="parent"):
        _check()
    assert seen == 2


def test_parent_tail_with_ambiguous_time_is_refused(source_bound):
    row = _token_event(len(source_bound["parent"]))
    row["timestamp"] = "not-a-time"
    _append_parent(source_bound, row)
    with pytest.raises(guard.GuardRefused, match="parent checkpoint"):
        _check()


def test_parent_tail_with_duplicate_json_fields_is_unknown(source_bound):
    ordinal = len(source_bound["parent"])
    raw = ('{"ordinal":' + str(ordinal) + ',"timestamp":"2026-11-15T10:16:01Z",'
           '"type":"response_item","type":"event_msg",'
           '"payload":{"type":"token_count","info":null,"rate_limits":null}}\n')
    with source_bound["parent_path"].open("ab") as stream:
        stream.write(raw.encode())
    with pytest.raises(guard.GuardRefused, match="parent checkpoint"):
        _check()


def test_parent_token_usage_append_is_allowed_only_for_same_parent(source_bound):
    _check()
    ordinal = len(source_bound["parent"])
    usage = {"ordinal": ordinal, "timestamp": "2026-11-15T10:16:01Z", "type": "token_usage_record",
             "payload": {"thread_id": guard.PARENT, "session_id": guard.PARENT, "turn_id": "turn",
                         "root_turn_id": "root", "response_id": "response", "usage": {},
                         "turn_token_usage": {}, "thread_token_usage": {}}}
    _append_parent(source_bound, usage)
    _check()
    usage["ordinal"] += 1
    usage["payload"]["thread_id"] = guard.CHILD
    _append_parent(source_bound, usage)
    with pytest.raises(guard.GuardRefused, match="parent checkpoint"):
        _check()


def test_guard_rechecks_real_adapter_twice(source_bound, monkeypatch):
    original = guard.codex_session_relations.read_6561
    reads = []
    def read():
        value = original()
        reads.append(value)
        return value
    monkeypatch.setattr(guard.codex_session_relations, "read_6561", read)
    result = _check()
    assert len(reads) == 2 and reads[0] == reads[1]
    assert "freshly read registered relations" in result["scope"]
    assert result["unregistered_delegations"] == "UNKNOWN"


@pytest.mark.parametrize("field,value", [
    ("registered_children", None),
    ("registered_children", ["new-child"]),
    ("observation_complete", False),
    ("parent", "wrong-parent"),
    ("child_rollout", "/wrong/child.jsonl"),
    ("child_thread_source", "user"),
    ("parent_edge_count", 0),
    ("child_thread_count", 2),
    ("parent_thread_count", True),
    ("read_method", "unchecked"),
    ("source_tables", ["thread_spawn_edges"]),
    ("coordination", "no future guarantees"),
])
def test_ambiguous_operator_relation_attestation_refuses(source_bound, field, value):
    source_bound["receipt"]["writer"]["codex_custody"]["relations"][field] = value
    _refresh_comment(source_bound)
    with pytest.raises(guard.GuardRefused, match="UNKNOWN"):
        _check()


@pytest.mark.parametrize("field,value", [
    ("coordination_started_at", "2026-11-15T08:03:35Z"),
    ("coordination_started_at", "2026-11-15T10:16:01Z"),
    ("observed_at", "2026-11-15T08:03:00Z"),
    ("observed_at", "2026-11-15T10:16:01Z"),
    ("observed_at", "2026-11-15T10:15:59"),
])
def test_relation_observation_must_be_inside_attested_stopped_window(source_bound, field, value):
    source_bound["receipt"]["writer"]["codex_custody"]["relations"][field] = value
    _refresh_comment(source_bound)
    with pytest.raises(guard.GuardRefused, match="relation timing"):
        _check()


def test_source_drift_during_host_readback_is_unknown(source_bound, monkeypatch):
    original = guard._check_host
    def host_with_drift():
        import sqlite3
        original()
        with sqlite3.connect(source_bound["database"]) as db:
            db.execute("INSERT INTO thread_spawn_edges VALUES (?, ?, ?)", (guard.CHILD, "00000000-0000-4000-8000-000000000001", "open"))
    monkeypatch.setattr(guard, "_check_host", host_with_drift)
    with pytest.raises(guard.GuardRefused, match="target relations changed"):
        _check()


def test_source_fingerprint_rejects_symlink(source_bound):
    source_bound["database"].unlink()
    source_bound["database"].symlink_to(source_bound["parent_path"])
    with pytest.raises(guard.GuardRefused, match="relation source unavailable"):
        _check()


def test_unrelated_wal_commit_between_guard_checks_does_not_block(source_bound, monkeypatch):
    import sqlite3
    database = source_bound["database"]
    writer = sqlite3.connect(database)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("CREATE TABLE unrelated(id INTEGER PRIMARY KEY, note TEXT)")
        writer.commit()
        original = guard.codex_session_relations.read_6561
        reads = []
        def read():
            projection = original()
            reads.append(projection)
            if len(reads) == 1:
                writer.execute("INSERT INTO unrelated(note) VALUES ('unrelated session')")
                writer.commit()
            return projection
        monkeypatch.setattr(guard.codex_session_relations, "read_6561", read)
        result = _check()
        assert len(reads) == 2 and reads[0] == reads[1]
        assert result["unregistered_delegations"] == "UNKNOWN"
    finally:
        writer.close()


def test_new_target_child_in_wal_between_guard_checks_is_refused(source_bound, monkeypatch):
    import sqlite3
    writer = sqlite3.connect(source_bound["database"])
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("CREATE TABLE unrelated(id INTEGER PRIMARY KEY)")
        writer.commit()
        original = guard.codex_session_relations.read_6561
        reads = []
        def read():
            projection = original()
            reads.append(projection)
            if len(reads) == 1:
                writer.execute("INSERT INTO thread_spawn_edges VALUES (?, ?, ?)",
                               (guard.CHILD, "00000000-0000-4000-8000-000000000001", "open"))
                writer.commit()
            return projection
        monkeypatch.setattr(guard.codex_session_relations, "read_6561", read)
        with pytest.raises(guard.GuardRefused, match="target relations changed"):
            _check()
        assert len(reads) == 2
    finally:
        writer.close()


def test_runtime_readback_excludes_publication_and_preserves_source_checks(source_bound, monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(guard, "_read_publication", lambda *_: pytest.fail("runtime-only check read publication"))
    result = guard.check_runtime(cwd=Path("."), issue=6561, pr=6562, worktree=Path(guard.WORKTREE),
                                 session="successor", comment_id=42)
    assert "host targets only" in result["scope"]
    assert result["unrecorded_effects"] == "UNKNOWN"
    source_bound["child_path"].write_bytes(b"invalid")
    with pytest.raises(guard.GuardRefused, match="UNKNOWN"):
        guard.check_runtime(cwd=Path("."), issue=6561, pr=6562, worktree=Path(guard.WORKTREE),
                            session="successor", comment_id=42)


def test_6561_executor_lineage_refuses_without_native_source_check():
    from app.builderops import openhands_pr_cycle as cycle
    with pytest.raises(cycle.CycleError, match="executor lineage is unsupported"):
        cycle._operator_lineage(events=[], owner={}, origin={}, registration={}, records={}, comments=[],
                                issue_comments=[], issue=6561, pr_number=6562, branch="x", head="x",
                                files=[], entry={})


def test_identified_pid_is_not_ignored_when_reused_by_current_process(source_bound, monkeypatch):
    pid = next(iter(guard.INVENTORY_COMMANDS.values()))[0]
    monkeypatch.setattr(guard.os, "getpid", lambda: pid)
    monkeypatch.setattr(guard.os, "getppid", lambda: 777)
    source_bound["host"]["/bin/ps"] = f"{pid} 1 current-process\n777 1 parent-process\n"
    with pytest.raises(guard.GuardRefused, match="UNKNOWN"):
        _check()


@pytest.mark.parametrize("last_activity, accepted", [
    ("2026-11-15T08:03:36.535Z", False),
    ("2026-11-15T08:03:36.536Z", True),
    ("2026-11-15T08:03:36.537Z", True),
])
def test_stopped_window_uses_actual_interruption_millisecond(source_bound, last_activity, accepted):
    source_bound["receipt"]["writer"]["last_activity"] = last_activity
    _refresh_comment(source_bound)
    if accepted:
        assert _check()["historical_ppids"] == "UNKNOWN"
    else:
        with pytest.raises(guard.GuardRefused, match="stopped window precedes"):
            _check()


@pytest.mark.parametrize("started, accepted", [
    ("2026-11-15T08:03:36.535Z", False),
    ("2026-11-15T08:03:36.536Z", True),
])
def test_coordination_cannot_precede_actual_interruption(source_bound, started, accepted):
    source_bound["receipt"]["writer"]["codex_custody"]["relations"]["coordination_started_at"] = started
    _refresh_comment(source_bound)
    if accepted:
        assert _check()["historical_ppids"] == "UNKNOWN"
    else:
        with pytest.raises(guard.GuardRefused, match="relation timing"):
            _check()


@pytest.mark.parametrize("mutation", ["after_abort_time", "row_after_abort", "reordered", "missing_time", "naive_time"])
def test_identified_inventory_requires_ordered_interruption_timeline(source_bound, mutation):
    child = source_bound["child"]
    item = next(row for row in reversed(child)
                if row.get("payload", {}).get("item", {}).get("type") == "CommandExecution"
                and row["payload"].get("turn_id") == guard.TURN)
    if mutation == "after_abort_time":
        item["timestamp"] = "2026-11-15T08:04:00.000Z"
    elif mutation == "row_after_abort":
        child.remove(item)
        item["timestamp"] = "2026-11-15T08:03:36.536Z"
        child.append(item)
    elif mutation == "reordered":
        index = child.index(item)
        child[index - 1], child[index] = child[index], child[index - 1]
    elif mutation == "missing_time":
        del item["timestamp"]
    else:
        item["timestamp"] = "2026-11-15T07:56:07.000"
    source_bound["child_path"].write_bytes(_jsonl(child))
    _refresh_comment(source_bound)
    with pytest.raises(guard.GuardRefused, match="UNKNOWN"):
        _check()


def test_same_millisecond_before_interruption_remains_admissible(source_bound):
    child = source_bound["child"]
    call = next(row for row in reversed(child) if row.get("type") == "response_item")
    call["timestamp"] = "2026-11-15T08:03:36.536Z"
    child_path = source_bound["child_path"]
    child_path.write_bytes(_jsonl(child))
    _refresh_comment(source_bound)
    assert _check()["historical_ppids"] == "UNKNOWN"


@pytest.mark.parametrize("abort_time, accepted", [
    ("2026-11-15T08:03:36.530Z", False),
    ("2026-11-15T08:03:36.536Z", True),
])
def test_abort_follows_the_recorded_parent_interrupt(source_bound, monkeypatch, abort_time, accepted):
    calls = dict(guard.PARENT_CALLS)
    identity = next(key for key, value in calls.items() if value[0] == "interrupt_agent")
    name, _, digest = calls[identity]
    calls[identity] = (name, "2026-11-15T08:03:36.531Z", digest)
    monkeypatch.setattr(guard, "PARENT_CALLS", calls)
    parent_call = next(row for row in source_bound["parent"]
                       if row.get("payload", {}).get("call_id") == identity)
    parent_call["timestamp"] = "2026-11-15T08:03:36.531Z"
    abort = next(row for row in source_bound["child"]
                 if row.get("payload", {}).get("type") == "turn_aborted")
    abort["timestamp"] = abort_time
    source_bound["parent_path"].write_bytes(_jsonl(source_bound["parent"]))
    source_bound["child_path"].write_bytes(_jsonl(source_bound["child"]))
    _refresh_comment(source_bound)
    if accepted:
        assert _check()["historical_ppids"] == "UNKNOWN"
    else:
        with pytest.raises(guard.GuardRefused, match="interruption and completion ordering"):
            _check()
