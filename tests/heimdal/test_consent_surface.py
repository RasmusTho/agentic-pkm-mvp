"""Heimdal `consent.md` readout tests -- Epic #3019 slice A19 (#3044).

Covers the governing Issue's two behavioral Acceptance Criteria:

- ``test_selfrecord_readout`` -- `consent.md` renders a faithful `self_record`
  readout mirroring the ledger. Drives the readout from real ledger state
  (via the production `app.heimdal.consent_ledger` grant/revoke API) and
  asserts the note reflects that state, not a hardcoded string: granting a
  new grant or revoking the standing grant changes the rendered readout.
- ``test_bshaped_fields_present_dormant`` -- the B-shaped withhold-span-review
  + retention/erasure fields are present but dormant/inert in v1.

Both tests exercise the real production call sites
(`app.heimdal.consent_surface.write_consent_readout` /
`read_consent_readout`, backed by `app.heimdal.settings_notes.write_settings_note`
+ `app.knowledge.write_ops.write_note_relative` + `app.write_guard.WriteGuard`),
mirroring `tests/heimdal/test_settings_notes.py`'s temp-vault-fixture
convention: no network, no real Postgres, no real vault.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.heimdal.consent_ledger import (
    SELF_RECORD_BASIS,
    SELF_RECORD_GRANT_REF,
    SELF_RECORD_SCOPE,
    grant_consent,
    reset_memory_consent_ledger,
    revoke_consent,
)
from app.heimdal.consent_surface import (
    build_consent_readout_values,
    read_consent_readout,
    render_consent_readout,
    write_consent_readout,
)
from app.heimdal.settings_notes import CONSENT, note_rel_path
from app.write_guard import WriteGuard, WritesBlockedError

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def _reset_consent_ledger():
    reset_memory_consent_ledger()
    yield
    reset_memory_consent_ledger()


def _vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _blocking_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "safe_mode", "reason": "test-induced block"})


def _grant_refs(values: dict) -> set[str]:
    return {g["grant_ref"] for g in values["grants"]}


# ---------------------------------------------------------------------------
# AC: consent.md renders a faithful self_record readout mirroring the ledger
# ---------------------------------------------------------------------------


def test_selfrecord_readout(tmp_path: Path) -> None:
    """`consent.md` mirrors the standing `self_record` grant, driven by real
    ledger state -- not a hardcoded string. Granting/revoking changes the
    rendered readout, proving the readout is actually derived."""
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    # 1. With only the standing seeded self_record grant active, the readout
    #    reflects exactly that one grant, faithfully (every field mirrored).
    note = write_consent_readout(vault_root, write_guard=guard)
    assert note.values["grants"], "readout must include the standing self_record grant"
    assert len(note.values["grants"]) == 1
    mirrored = note.values["grants"][0]
    assert mirrored["grant_ref"] == SELF_RECORD_GRANT_REF
    assert mirrored["basis"] == SELF_RECORD_BASIS
    assert mirrored["scope"] == SELF_RECORD_SCOPE
    assert mirrored["granted_by"] == "operator"
    # B-shaped grant fields (vad_gate/third_party/retention/erasure) mirrored
    # verbatim from the ledger grant, not summarized away.
    assert mirrored["vad_gate"] == {"enabled": False}
    assert mirrored["third_party"] == {"policy": "degrade"}

    # 2. The write actually landed on disk at the A14 `_heimdal/consent.md`
    #    path -- this is a real vault write through the governed seam, not
    #    just an in-memory object.
    path = vault_root / note_rel_path(CONSENT)
    assert path.exists()
    assert path.name == "consent.md"
    on_disk_text = path.read_text(encoding="utf-8")
    assert SELF_RECORD_GRANT_REF in on_disk_text

    # 3. Reading back through the production read call site reproduces the
    #    same mirrored grant (round-trips through YAML frontmatter losslessly).
    read_back = read_consent_readout(vault_root)
    assert read_back is not None
    assert read_back.values["grants"][0]["grant_ref"] == SELF_RECORD_GRANT_REF

    # 4. Granting a NEW real ledger grant and rebuilding the readout changes
    #    what is rendered -- proving the readout is driven by ledger state,
    #    not a fixed/hardcoded snapshot.
    grant_consent(
        grant_ref="grant-session-extra-1",
        basis="session_optin",
        scope="device+adapter:extra-scope",
        granted_by="operator",
    )
    rebuilt = write_consent_readout(vault_root, write_guard=guard)
    assert _grant_refs(rebuilt.values) == {SELF_RECORD_GRANT_REF, "grant-session-extra-1"}

    # 5. Revoking the standing self_record grant and rebuilding removes it
    #    from the readout (mirrors the ledger's `list_active_grants`, which
    #    excludes revoked grants) -- further proof the readout is a live
    #    mirror, not a cache of the first render.
    revoke_consent(grant_ref=SELF_RECORD_GRANT_REF, revoked_by="operator")
    after_revoke = write_consent_readout(vault_root, write_guard=guard)
    assert _grant_refs(after_revoke.values) == {"grant-session-extra-1"}
    assert SELF_RECORD_GRANT_REF not in _grant_refs(after_revoke.values)


def test_readout_reflects_no_active_grants() -> None:
    """Negative/completeness coverage: an empty ledger (nothing active)
    renders an empty grants list, not an error or a stale default."""
    revoke_consent(grant_ref=SELF_RECORD_GRANT_REF, revoked_by="operator")
    values = build_consent_readout_values()
    assert values["grants"] == []


def test_readout_orders_grants_by_ledger_append_order() -> None:
    """Multiple active grants render in ledger (append) order, so the oldest
    standing grant is always listed first -- a faithful mirror preserves
    ledger ordering rather than an arbitrary or reversed order."""
    grant_consent(grant_ref="grant-second", basis="session_optin", scope="device+adapter:s2", granted_by="operator")
    grant_consent(grant_ref="grant-third", basis="session_optin", scope="device+adapter:s3", granted_by="operator")
    values = build_consent_readout_values()
    refs_in_order = [g["grant_ref"] for g in values["grants"]]
    assert refs_in_order == [SELF_RECORD_GRANT_REF, "grant-second", "grant-third"]


def test_readout_is_read_mostly_not_an_independent_write_path() -> None:
    """The readout write path accepts no caller-supplied grant data: the only
    input to what gets written is the ledger itself. This is the structural
    proof behind the governing Issue's boundary risk ("the readout must not
    become a control that mutates consent independently of the ledger") --
    there is no parameter on the write call site through which a caller could
    inject a grant that bypasses `consent_ledger.grant_consent`."""
    import inspect

    from app.heimdal import consent_surface

    write_sig = inspect.signature(consent_surface.write_consent_readout)
    render_sig = inspect.signature(consent_surface.render_consent_readout)
    build_sig = inspect.signature(consent_surface.build_consent_readout_values)
    for sig in (write_sig, render_sig, build_sig):
        param_names = set(sig.parameters)
        # No parameter accepts grant/grants data directly; the only knobs are
        # vault_root/write_guard/action/at (plumbing), never grant content.
        assert "grants" not in param_names
        assert "grant" not in param_names

    # No mutation-shaped function exists on the module's public surface.
    public_names = set(consent_surface.__all__)
    mutating_names = {
        name for name in public_names if any(tok in name.lower() for tok in ("grant_consent", "revoke", "mutate", "update_grant"))
    }
    assert mutating_names == set()


def test_write_consent_readout_honors_write_guard_block(tmp_path: Path) -> None:
    """The governed write seam is real, not decorative: a blocked WriteGuard
    prevents the write entirely (fail-loud), mirroring
    `test_settings_notes.py::test_write_settings_note_honors_write_guard_block`."""
    vault_root = _vault(tmp_path)
    with pytest.raises(WritesBlockedError):
        write_consent_readout(vault_root, write_guard=_blocking_guard())
    assert read_consent_readout(vault_root) is None


# ---------------------------------------------------------------------------
# AC: B-shaped withhold-span-review + retention/erasure fields present,
# dormant in v1.
# ---------------------------------------------------------------------------


def test_bshaped_fields_present_dormant(tmp_path: Path) -> None:
    """The withhold-span-review and retention/erasure surfaces render as
    present-but-inert structures (ADR-0049 §3: "the consent note already
    writes the B-shaped mechanism, dormant") -- checked both on the pure
    values dict and on the note actually written to disk."""
    values = build_consent_readout_values()

    # Present: structured dicts, not missing/None/placeholder strings.
    assert isinstance(values["withhold_span_review"], dict)
    assert isinstance(values["retention_erasure"], dict)

    # Dormant: v1-inert -- nothing here is live in posture A.
    withhold = values["withhold_span_review"]
    assert withhold["enabled"] is False
    assert withhold["pending_review_count"] == 0
    assert withhold["queue"] == []

    retention = values["retention_erasure"]
    assert retention["supported"] is False
    assert retention["hard_retention_days"] is None
    assert retention["erasure_requests"] == []

    # And on the real written note (round-trips through the governed write
    # seam + YAML frontmatter, not just the in-memory values dict).
    vault_root = _vault(tmp_path)
    note = write_consent_readout(vault_root, write_guard=_allowing_guard())
    assert note.values["withhold_span_review"]["enabled"] is False
    assert note.values["retention_erasure"]["supported"] is False

    read_back = read_consent_readout(vault_root)
    assert read_back is not None
    assert read_back.values["withhold_span_review"]["enabled"] is False
    assert read_back.values["retention_erasure"]["supported"] is False


def test_bshaped_fields_remain_dormant_across_rebuilds(tmp_path: Path) -> None:
    """Granting new (even session-scoped) consent does not flip the B-shaped
    fields live -- they stay structurally present but inert regardless of
    ledger activity, since no v1 code path ever sets them True."""
    vault_root = _vault(tmp_path)
    grant_consent(
        grant_ref="grant-session-2",
        basis="session_optin",
        scope="device+adapter:s-extra",
        granted_by="operator",
    )
    note = write_consent_readout(vault_root, write_guard=_allowing_guard())
    assert note.values["withhold_span_review"]["enabled"] is False
    assert note.values["retention_erasure"]["supported"] is False


def test_render_consent_readout_returns_settings_note_with_consent_spec() -> None:
    """`render_consent_readout` produces a `SettingsNote` bound to the A14
    `CONSENT` spec, so it goes through the same schema/authority machinery
    every other `_heimdal/**` note uses -- not a bespoke ad hoc shape."""
    note = render_consent_readout()
    assert note.spec is CONSENT
    assert note.spec.kind == "consent"
