"""#2999 (G2-4) -- the `[!contradiction]` callout is never written by the pass.

Spec: ``docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md`` §4:
"an unchecked `AI-åtgärder` checkbox per contradiction ... plus optionally a
`[!contradiction]` callout only after confirmation -- the callout itself is a
body edit and therefore rides the confirmed action, never the pass."

This mirrors ``semantic_curation_never_autowrites``
(``tests/invariants/test_curation_invariants.py``): the production call site
(``run_contradiction_pass``) never writes anything outside the governed
unchecked-checkbox block -- in particular, it never writes a `[!contradiction]`
callout, never a checked box, and never any body edit outside the
``AI-åtgärder`` panel section.
"""
from __future__ import annotations

from pathlib import Path

from app.expansion.contradiction import ClaimCandidate, run_contradiction_pass
from app.write_guard import WriteGuard


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


def _panel_block_only_change(original: str, updated: str) -> bool:
    """True if every line unique to *updated* is an unchecked proposal
    checkbox line (i.e. the diff is additive-only, confined to the governed
    checkbox block -- no callout, no checked box, no other body edit)."""
    original_lines = set(original.splitlines())
    new_lines = [line for line in updated.splitlines() if line not in original_lines]
    return all(line.strip().startswith("- [ ]") for line in new_lines)


def test_contradiction_pass_never_writes_a_callout_or_checked_box(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(
        vault_root, "meeting-a.md", _panel_note("uuid-a", "Mötet är kl 14:00 på tisdag.\n\n")
    )
    _write_note(
        vault_root, "meeting-b.md", _panel_note("uuid-b", "The meeting is at 15:00 on Tuesday.\n\n")
    )
    outbox_path = tmp_path / "outbox.jsonl"

    original_a = (vault_root / "meeting-a.md").read_text(encoding="utf-8")
    original_b = (vault_root / "meeting-b.md").read_text(encoding="utf-8")

    a = ClaimCandidate(
        note_uuid="uuid-a",
        rel_path="meeting-a.md",
        scope=None,
        claim_text="Mötet är kl 14:00 på tisdag.",
        interpretation="Conflict on meeting time.",
    )
    b = ClaimCandidate(
        note_uuid="uuid-b",
        rel_path="meeting-b.md",
        scope=None,
        claim_text="The meeting is at 15:00 on Tuesday.",
        interpretation="Conflict on meeting time.",
    )

    report = run_contradiction_pass(
        vault_root=vault_root,
        claim_pairs=[(a, b)],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
    )
    assert len(report.findings) == 2  # sanity: the pass really did emit

    updated_a = (vault_root / "meeting-a.md").read_text(encoding="utf-8")
    updated_b = (vault_root / "meeting-b.md").read_text(encoding="utf-8")

    # Never a `[!contradiction]` callout -- that only ever rides a confirmed
    # action, and this module contains no code path that writes one.
    assert "[!contradiction]" not in updated_a
    assert "[!contradiction]" not in updated_b

    # Never a checked box.
    assert "- [x]" not in updated_a
    assert "- [x]" not in updated_b

    # Exactly one new unchecked checkbox per note, and nothing else changed
    # outside the governed checkbox block.
    assert updated_a.count("- [ ]") == 1
    assert updated_b.count("- [ ]") == 1
    assert _panel_block_only_change(original_a, updated_a)
    assert _panel_block_only_change(original_b, updated_b)


def test_contradiction_module_has_no_callout_writing_code() -> None:
    """Static guard: the module's source never mentions writing a
    `[!contradiction]` callout string -- it only ever hands findings to the
    existing propose writer. If a later change ever adds callout-writing
    code to this module, this test documents that as a contract violation
    to catch in review, not something to silently accept."""
    import inspect

    from app.expansion import contradiction

    source = inspect.getsource(contradiction)
    # The literal callout marker must appear only in documentation/comments
    # (explaining it is NOT written here), never as a string this module
    # writes to a file. We assert there is no `.write_text(` call anywhere
    # in this module other than none at all -- the only file-mutating call
    # is through `write_curation_proposals`.
    assert "write_text(" not in source
    assert "note_path.write_text" not in source


def test_run_contradiction_pass_only_writer_is_the_shared_propose_writer() -> None:
    """`run_contradiction_pass`'s only body-write path is
    `write_curation_proposals` (the same G2-2 writer Connect uses) -- there is
    no second, contradiction-specific writer that could grow a callout-writing
    branch independently."""
    import inspect

    from app.expansion import contradiction

    source = inspect.getsource(contradiction.run_contradiction_pass)
    assert "write_curation_proposals(" in source
