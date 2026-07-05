"""#2999 (G2-4) -- the `[!contradiction]` callout is never written by the pass.

Spec: ``docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md`` §4:
"a `[!contradiction]` callout only after confirmation -- the callout itself is
a body edit and therefore rides the confirmed action, never the pass."

This is the enforcement test for the ``semantic_curation_never_autowrites``
invariant as it applies to the contradiction pass specifically: running the
real ``run_contradiction_pass`` end to end must never write a
``[!contradiction]`` callout block, must never check a box itself, and must
never body-edit a note outside the governed unchecked-checkbox line. The
callout only appears after a human confirms the checkbox through the ordinary
Panel confirm flow -- proven here by showing (a) the pass output contains no
callout marker anywhere in the vault, and (b) the module itself has no
callable/code path that writes one.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.curation import contradiction as contradiction_module
from app.curation.contradiction import ContradictionPassConfig, run_contradiction_pass
from app.write_guard import WriteGuard
from app.retrieval.capability import RetrievalHit, RetrievalRequest, RetrievalResponse


def _allow_all_guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "healthy", "reason": None})


def _panel_note(uuid: str, extra_body: str = "") -> str:
    return (
        f"---\nuuid: {uuid}\nkind: note\n---\n\n"
        f"# {uuid}\n\n{extra_body}"
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        "\n"
        "## AI-åtgärder\n"
        "%% AI:End %%\n"
    )


def _write_note(vault_root: Path, rel_path: str, content: str) -> Path:
    path = vault_root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _hit(doc_id: str, *, uuid: str, text: str, source_ref: str, score: float = 0.8) -> RetrievalHit:
    return RetrievalHit(
        object_id=doc_id,
        doc_id=doc_id,
        text=text,
        score=score,
        snippet=text,
        source_ref=source_ref,
        payload={"uuid": uuid},
    )


def test_pass_never_writes_contradiction_callout_or_checked_box(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(vault_root, "a.md", _panel_note("uuid-a", "Mötet börjar kl 9.\n\n"))
    _write_note(vault_root, "b.md", _panel_note("uuid-b", "The meeting starts at 10am.\n\n"))
    outbox_path = tmp_path / "outbox.jsonl"

    hits = [
        _hit("a", uuid="uuid-a", text="Mötet börjar kl 9.", source_ref="a.md"),
        _hit("b", uuid="uuid-b", text="The meeting starts at 10am.", source_ref="b.md", score=0.75),
    ]

    def _fake_retrieve(request: RetrievalRequest) -> RetrievalResponse:
        return RetrievalResponse(query=request.query, hits=list(hits), trace_id=request.trace_id)

    report = run_contradiction_pass(
        vault_root=vault_root,
        queries=["when does the meeting start"],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve,
    )

    assert report.findings  # sanity: the pass actually found the contradiction

    for rel in ("a.md", "b.md"):
        text = (vault_root / rel).read_text(encoding="utf-8")
        # No callout of any kind was written by the pass.
        assert "[!contradiction]" not in text
        assert "!contradiction" not in text
        # No checkbox was auto-checked -- confirmation is exclusively human.
        assert "- [x]" not in text
        # Exactly one unchecked proposal checkbox per note.
        assert text.count("- [ ]") == 1


def test_no_config_flag_can_make_the_pass_write_a_callout(tmp_path: Path) -> None:
    """Even with every knob maximally permissive (materialize=True, an empty
    cap so nothing is suppressed), there is still no branch that writes a
    callout -- the callout is categorically out of this module's write
    surface, not merely disabled by a default flag value."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(vault_root, "a.md", _panel_note("uuid-a", "Deadline is Friday.\n\n"))
    _write_note(vault_root, "b.md", _panel_note("uuid-b", "Deadline is Monday.\n\n"))
    outbox_path = tmp_path / "outbox.jsonl"

    hits = [
        _hit("a", uuid="uuid-a", text="Deadline is Friday.", source_ref="a.md"),
        _hit("b", uuid="uuid-b", text="Deadline is Monday.", source_ref="b.md", score=0.7),
    ]

    def _fake_retrieve(request: RetrievalRequest) -> RetrievalResponse:
        return RetrievalResponse(query=request.query, hits=list(hits), trace_id=request.trace_id)

    run_contradiction_pass(
        vault_root=vault_root,
        queries=["deadline"],
        config=ContradictionPassConfig(max_findings_per_note=1000, max_findings_total=1000),
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        materialize=True,
        retrieve_fn=_fake_retrieve,
    )

    for rel in ("a.md", "b.md"):
        text = (vault_root / rel).read_text(encoding="utf-8")
        assert "[!contradiction]" not in text


def test_module_has_no_callout_writing_code_path() -> None:
    """Static guard: no *executable* line in the contradiction module
    constructs a `[!contradiction]` callout block string -- the callout is not
    merely unreached at runtime, it does not exist as a code path in this
    module at all (spec: "never written by the pass itself" is a hard
    invariant, not a default). The module docstring is allowed to name the
    marker in prose (it documents the invariant); only non-comment,
    non-docstring source lines are checked here."""
    source = inspect.getsource(contradiction_module)
    tree = ast.parse(source)
    module_docstring = ast.get_docstring(tree)
    body_source = source
    if module_docstring:
        # Strip the module docstring (the triple-quoted literal itself) before
        # scanning -- it is documentation prose, not a code path.
        body_source = source.replace(module_docstring, "", 1)
    assert "[!contradiction]" not in body_source


def test_run_contradiction_pass_only_calls_the_propose_track_writer() -> None:
    """The only materialization call this module makes is the shared,
    propose-only `write_curation_proposals` -- there is no second,
    contradiction-specific body-write path that could grow a callout-writing
    branch independent of the shared writer's own propose-only guarantee."""
    source = inspect.getsource(contradiction_module.run_contradiction_pass)
    assert "write_curation_proposals" in source
    assert "_write_proposals_to_panel" not in source
