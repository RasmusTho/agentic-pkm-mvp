"""#2995 (EXP-2) -- the declined-proposal ledger.

Spec: ``docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`` §3, §5.
Invariant: ``docs/testing/invariant-tests.md :: declined_findings_not_reproposed``.

Covers every behavioral Acceptance Criterion from the issue:

- AC1: a declined finding is suppressed on the next pass run; the pass
  receipt reports the suppression count.
- AC2: after the finding's content basis changes (span/hash changed), the
  same underlying relationship is proposable again under its new finding_id.
- AC3: deleting the ledger store does not error; all previously-declined
  findings become re-proposable.
- AC4 (``test_ledger_never_enters_context``): the ledger is never returned
  by any retrieval or context-assembly code path.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.expansion.connect import (
    ConnectPassConfig,
    compute_connect_finding_id,
    default_declined_ledger as connect_default_ledger,
)
from app.curation.findings import FindingClass
from app.proposals.declined_ledger import (
    DeclinedLedger,
    default_declined_ledger,
    default_path_from_env,
)
from app.retrieval.capability import RetrievalHit, RetrievalRequest, RetrievalResponse
from app.write_guard import WriteGuard, WritesBlockedError

REPO_ROOT = Path(__file__).resolve().parents[2]


def _allow_all_guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "healthy", "reason": None})


def _blocked_guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "unhealthy", "reason": "test"})


# --- AC1: declined ⇒ suppressed, counted in the pass receipt -----------------


def test_declined_finding_is_suppressed_and_counted(tmp_path: Path) -> None:
    ledger = DeclinedLedger(tmp_path / "declined.jsonl")
    finding_id = compute_connect_finding_id(
        finding_class=FindingClass.CONNECT_RELATED_UNLINKED,
        note_uuids=frozenset({"uuid-a", "uuid-b"}),
        basis="high|alpha beta|alpha beta",
    )
    assert ledger.is_declined(finding_id) is False

    ledger.record_decline(
        finding_id,
        finding_class=FindingClass.CONNECT_RELATED_UNLINKED.value,
        reason="human declined via panel",
        write_guard=_allow_all_guard(),
    )

    assert ledger.is_declined(finding_id) is True


def test_declined_finding_suppressed_in_real_connect_pass(tmp_path: Path) -> None:
    """Production-call-site enforcement: run the real `run_connect_pass` with
    a finding pre-declined in a real `DeclinedLedger`, and assert the pass
    receipt reports it as `suppressed_by_decline`, not as an emitted finding."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    for rel, uuid in (("a.md", "uuid-a"), ("b.md", "uuid-b")):
        (vault_root / rel).write_text(
            f"---\nuuid: {uuid}\nkind: note\n---\n\n# {uuid}\n\n"
            "%% AI:Start %%\n## AI-instruktion\n\n## AI-åtgärder\n%% AI:End %%\n",
            encoding="utf-8",
        )
    outbox_path = tmp_path / "outbox.jsonl"

    def _fake_retrieve(request: RetrievalRequest) -> RetrievalResponse:
        return RetrievalResponse(
            query=request.query,
            hits=[
                RetrievalHit(
                    object_id="a",
                    doc_id="a",
                    text="shared alpha beta gamma",
                    score=0.9,
                    snippet="shared alpha beta gamma",
                    source_ref="a.md",
                    payload={"uuid": "uuid-a"},
                ),
                RetrievalHit(
                    object_id="b",
                    doc_id="b",
                    text="shared alpha beta gamma",
                    score=0.85,
                    snippet="shared alpha beta gamma",
                    source_ref="b.md",
                    payload={"uuid": "uuid-b"},
                ),
            ],
        )

    # First pass: nothing declined yet -- the pair is proposed.
    ledger = DeclinedLedger(tmp_path / "declined.jsonl")
    config = ConnectPassConfig(declined_ledger=ledger)
    from app.expansion.connect import run_connect_pass

    first = run_connect_pass(
        vault_root=vault_root,
        queries=["shared alpha beta gamma"],
        config=config,
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve,
    )
    assert first.findings
    assert first.suppressed_by_decline == 0
    finding_id = first.findings[0].finding_id

    # Human declines it.
    ledger.record_decline(
        finding_id,
        finding_class=FindingClass.CONNECT_RELATED_UNLINKED.value,
        write_guard=_allow_all_guard(),
    )

    # Second pass over the identical vault: the pair must be suppressed, not
    # re-emitted, and the pass receipt must report the suppression count.
    second = run_connect_pass(
        vault_root=vault_root,
        queries=["shared alpha beta gamma"],
        config=config,
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve,
    )
    assert second.findings == ()
    assert second.suppressed_by_decline == 1


# --- AC2: content-basis change -> new finding_id -> proposable again --------


def test_content_basis_change_reopens_proposal(tmp_path: Path) -> None:
    ledger = DeclinedLedger(tmp_path / "declined.jsonl")
    note_uuids = frozenset({"uuid-a", "uuid-b"})

    original_id = compute_connect_finding_id(
        finding_class=FindingClass.CONNECT_RELATED_UNLINKED,
        note_uuids=note_uuids,
        basis="high|alpha beta|alpha beta",
    )
    ledger.record_decline(
        original_id,
        finding_class=FindingClass.CONNECT_RELATED_UNLINKED.value,
        write_guard=_allow_all_guard(),
    )
    assert ledger.is_declined(original_id) is True

    # One of the notes is rewritten: its supporting span changes, so the
    # basis changes, so `compute_connect_finding_id` mints a DIFFERENT id --
    # the ledger needs no bespoke reset logic, this falls out of the
    # content-derived id scheme it consumes.
    changed_id = compute_connect_finding_id(
        finding_class=FindingClass.CONNECT_RELATED_UNLINKED,
        note_uuids=note_uuids,
        basis="high|alpha beta GAMMA REWRITTEN|alpha beta",
    )
    assert changed_id != original_id
    assert ledger.is_declined(changed_id) is False


# --- AC3: deleting the store never errors; re-enables re-proposal -----------


def test_missing_ledger_file_never_errors_and_is_not_declined(tmp_path: Path) -> None:
    ledger = DeclinedLedger(tmp_path / "does-not-exist" / "declined.jsonl")
    assert ledger.is_declined("any-finding-id") is False


def test_deleting_ledger_reenables_all_previously_declined_findings(tmp_path: Path) -> None:
    path = tmp_path / "declined.jsonl"
    ledger = DeclinedLedger(path)
    finding_id = "some-finding-id"
    ledger.record_decline(
        finding_id,
        finding_class=FindingClass.CONNECT_RELATED_UNLINKED.value,
        write_guard=_allow_all_guard(),
    )
    assert ledger.is_declined(finding_id) is True

    path.unlink()  # the "operator deletes the derived store" scenario

    assert ledger.is_declined(finding_id) is False  # never raises, never errors


def test_corrupt_ledger_line_degrades_to_not_declined_rather_than_raising(tmp_path: Path) -> None:
    path = tmp_path / "declined.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json\nalso not json\n", encoding="utf-8")
    ledger = DeclinedLedger(path)

    assert ledger.is_declined("anything") is False


def test_empty_ledger_directory_is_provisioned_lazily(tmp_path: Path) -> None:
    """The ledger never requires the runtime dir to pre-exist -- recording the
    first decline creates it, matching every sibling receipts store's
    posture (`runtime/<module>/...`)."""
    path = tmp_path / "fresh" / "declined.jsonl"
    ledger = DeclinedLedger(path)
    assert not path.parent.exists()

    ledger.record_decline(
        "fid-1", finding_class="connect.related_unlinked", write_guard=_allow_all_guard()
    )

    assert path.exists()
    assert ledger.is_declined("fid-1") is True


# --- Idempotency of the record itself ---------------------------------------


def test_recording_the_same_decline_twice_is_idempotent(tmp_path: Path) -> None:
    ledger = DeclinedLedger(tmp_path / "declined.jsonl")
    guard = _allow_all_guard()
    ledger.record_decline("fid-1", finding_class="connect.related_unlinked", write_guard=guard)
    ledger.record_decline("fid-1", finding_class="connect.related_unlinked", write_guard=guard)

    lines = (tmp_path / "declined.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert ledger.is_declined("fid-1") is True


def test_record_decline_is_write_guard_gated(tmp_path: Path) -> None:
    ledger = DeclinedLedger(tmp_path / "declined.jsonl")
    with pytest.raises(WritesBlockedError):
        ledger.record_decline(
            "fid-1", finding_class="connect.related_unlinked", write_guard=_blocked_guard()
        )
    # A blocked write must not have touched the filesystem at all.
    assert not (tmp_path / "declined.jsonl").exists()


def test_is_declined_read_path_is_not_write_guard_gated(tmp_path: Path) -> None:
    """Reads must survive a health-blocked runtime -- suppression of
    previously-declined proposals is not itself a new write."""
    path = tmp_path / "declined.jsonl"
    ledger = DeclinedLedger(path)
    ledger.record_decline("fid-1", finding_class="connect.related_unlinked", write_guard=_allow_all_guard())

    # Constructing a fresh ledger handle over the same path and reading it
    # must not consult any WriteGuard at all -- is_declined takes no guard
    # argument, so there is no way for a caller to gate it even by mistake.
    reread = DeclinedLedger(path)
    assert reread.is_declined("fid-1") is True


# --- Wiring: connect.py's default factory is the REAL ledger, not a no-op ---


def test_connect_default_declined_ledger_is_the_real_ledger(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The consultation point `app.expansion.connect.default_declined_ledger`
    must now resolve to the real, durable ledger -- not the permanent no-op
    stub the pre-#2995 code shipped. This is the exact seam EXP-1 wired for
    this slice to complete."""
    monkeypatch.setenv("DECLINED_LEDGER_PATH", str(tmp_path / "declined.jsonl"))
    ledger = connect_default_ledger()
    assert isinstance(ledger, DeclinedLedger)

    finding_id = "wired-fid"
    assert ledger.is_declined(finding_id) is False
    ledger.record_decline(finding_id, finding_class="connect.related_unlinked", write_guard=_allow_all_guard())
    # A second construction (mirroring a second pass invocation) must observe
    # the same durable state -- proving this is a real store, not per-call
    # ephemeral state.
    assert connect_default_ledger().is_declined(finding_id) is True


def test_default_path_from_env_falls_back_to_ratified_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DECLINED_LEDGER_PATH", raising=False)
    from app.proposals.declined_ledger import DEFAULT_DECLINED_LEDGER_PATH

    assert default_path_from_env() == DEFAULT_DECLINED_LEDGER_PATH


def test_default_declined_ledger_factory_honors_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    override = tmp_path / "custom" / "declined.jsonl"
    monkeypatch.setenv("DECLINED_LEDGER_PATH", str(override))
    ledger = default_declined_ledger()
    assert ledger.path == override


# --- AC4: the ledger never enters retrieval/context -------------------------


def test_ledger_never_enters_context() -> None:
    """Static + runtime enforcement that the ledger cannot reach a context or
    retrieval path, mirroring the posture already proven for staged drafts
    (`staged_drafts_invisible_to_retrieval`) and for connect evidence roles
    (`connect_proposals_candidate_only`).

    Static half: no module under the retrieval/context-assembly/knowledge-
    compilation seams imports `app.proposals` at all -- if a future change
    wired the ledger into one of those seams, this import-graph assertion
    fails immediately, before any runtime behavior could leak ledger content
    into a prompt or a `RetrievalResponse`.

    Runtime half: the concrete types those seams return
    (`RetrievalResponse`/`RetrievalHit`) do not, and structurally cannot,
    carry a `DeclinedLedger`/`DeclineReceipt` -- proposal_builders' own
    machine-derivation refusal already treats `retrieval` output as
    non-authoritative; this test proves the ledger doesn't even reach that
    far upstream.
    """
    forbidden_roots = [
        REPO_ROOT / "app" / "retrieval",
        REPO_ROOT / "app" / "context_bundles",
        REPO_ROOT / "app" / "knowledge_compilation",
    ]
    offending: list[str] = []
    for root in forbidden_roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module] if node.module else []
                else:
                    continue
                for name in names:
                    if name and (name == "app.proposals" or name.startswith("app.proposals.")):
                        offending.append(f"{path.relative_to(REPO_ROOT)} imports {name}")
    assert not offending, (
        "app.proposals (the declined-proposal ledger) must never be imported by "
        f"a retrieval/context-assembly/knowledge-compilation module: {offending}"
    )

    # Runtime half: RetrievalResponse/RetrievalHit are frozen/plain dataclasses
    # with a fixed, enumerable field set -- assert no field could plausibly
    # carry ledger content (no field named/typed for decline receipts).
    hit_fields = set(RetrievalHit.__dataclass_fields__)
    response_fields = set(RetrievalResponse.__dataclass_fields__)
    assert not any("declin" in f.lower() for f in hit_fields)
    assert not any("declin" in f.lower() for f in response_fields)


def test_declined_ledger_module_has_no_retrieval_or_context_imports() -> None:
    """The reverse direction: the ledger module itself never imports from the
    retrieval/context-assembly/knowledge-compilation seams either -- keeping
    the dependency edge absent in both directions, not just one."""
    path = REPO_ROOT / "app" / "proposals" / "declined_ledger.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden_prefixes = ("app.retrieval", "app.context_bundles", "app.knowledge_compilation")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module] if node.module else []
        else:
            continue
        for name in names:
            if name and name.startswith(forbidden_prefixes):
                pytest.fail(f"app.proposals.declined_ledger must not import {name}")
