"""The one idempotent test-channel bootstrap (issue #1997 F3).

These tests pin two things:

* the bootstrap is **idempotent** — re-running produces identical state with no
  drift (the second run scaffolds nothing new);
* the bootstrap kills the six 2026-06-14 symptoms — its derived env is
  channel-correct, absolute, host-reachable, single-watcher, and passes the F2
  preflight.

Pure: no Docker, no network. The Docker bring-up lives in
``scripts/bootstrap_test_channel.sh`` and is exercised by the F1 CI gate.
"""

from __future__ import annotations

from pathlib import Path

from app.ops.channel_preflight import channel_env_preflight
from app.ops.test_channel_bootstrap import (
    TEST_DSN,
    bootstrap_test_channel,
    derive_test_channel_env,
)
from app.vault.manager import REQUIRED_SETTINGS_FILES


def test_bootstrap_brings_up_a_selected_channel_correct_vault(tmp_path: Path) -> None:
    vault = tmp_path / "vault-test"
    result = bootstrap_test_channel(repo_root=tmp_path, vault_root=vault)

    assert result.ok, (result.vault_status, result.preflight.format_report() if result.preflight else None)
    assert result.vault_status == "selected"
    # vault init actually scaffolded the #1991-required settings files.
    settings_dir = next(p for p in vault.iterdir() if p.is_dir())
    for required in REQUIRED_SETTINGS_FILES:
        assert (settings_dir / required).exists(), f"missing {required}"


def test_bootstrap_is_idempotent_no_drift(tmp_path: Path) -> None:
    vault = tmp_path / "vault-test"

    first = bootstrap_test_channel(repo_root=tmp_path, vault_root=vault)
    assert first.created_files, "first run should scaffold settings files"

    # Capture the on-disk settings after the first run.
    snapshot = {
        p: p.read_bytes()
        for p in sorted(vault.rglob("*"))
        if p.is_file()
    }

    second = bootstrap_test_channel(repo_root=tmp_path, vault_root=vault)

    # Idempotent: the second run scaffolds nothing new and keeps every file.
    assert second.created_files == ()
    assert set(second.skipped_files) >= set(first.created_files)
    assert second.ok

    after = {
        p: p.read_bytes()
        for p in sorted(vault.rglob("*"))
        if p.is_file()
    }
    assert after == snapshot, "re-running the bootstrap drifted on-disk vault state"

    # The derived env is byte-for-byte stable across runs.
    assert first.env == second.env


def test_derived_env_kills_the_six_symptoms(tmp_path: Path) -> None:
    # An explicit test vault remains supported and resolves to an absolute path.
    env = derive_test_channel_env(
        repo_root=tmp_path, environ={}, vault_root=tmp_path / "operator-test-vault"
    )

    # 1. vault init is run by bootstrap (covered above); here: channel identity.
    assert env["PKM_ENVIRONMENT"] == "test"
    assert env["COMPOSE_PROJECT_NAME"] == "pkm-test"

    # 2. shared, absolute INDEX_OUTBOX_PATH under tmp-test/ (not CWD-relative).
    assert Path(env["INDEX_OUTBOX_PATH"]).is_absolute()
    assert "tmp-test" in env["INDEX_OUTBOX_PATH"]

    # 3. channel-correct heartbeat paths under tmp-test/.
    assert "tmp-test" in env["WORKER_HEARTBEAT_PATH"]
    assert "tmp-test" in env["WATCHER_HEARTBEAT_PATH"]

    # 4. host-reachable DSN (127.0.0.1:15434, not db:5432).
    assert env["DATABASE_URL"] == TEST_DSN
    assert env["DB_DSN"] == TEST_DSN
    assert "@db:5432" not in env["DATABASE_URL"]
    assert "127.0.0.1:15434" in env["DATABASE_URL"]

    # 5. absolute, canonical TEST_VAULT_ROOT (not $(PWD)/...).
    assert Path(env["TEST_VAULT_ROOT"]).is_absolute()
    assert env["VAULT_ROOT"] == env["VAULT_ROOT_TEST"] == env["TEST_VAULT_ROOT"]

    # 6. single-watcher posture declared explicitly.
    assert env["WATCHER_AUTO_EXEC"] == "1"

    # And the whole thing passes the F2 preflight.
    assert channel_env_preflight(env, channel="test").ok


def test_explicit_vault_root_override_is_absolute(tmp_path: Path) -> None:
    # A relative override is resolved to an absolute path (no CWD leakage).
    env = derive_test_channel_env(repo_root=tmp_path, environ={}, vault_root="some-vault")
    assert Path(env["VAULT_ROOT"]).is_absolute()


def test_unset_vault_root_uses_repo_local_vault_test(tmp_path: Path) -> None:
    env = derive_test_channel_env(repo_root=tmp_path, environ={})

    assert env["VAULT_ROOT"] == str((tmp_path / "vault-test").resolve())
    assert env["VAULT_ROOT"] == env["VAULT_ROOT_TEST"] == env["TEST_VAULT_ROOT"]


def test_plain_vault_root_is_ignored_when_not_explicit(tmp_path: Path) -> None:
    # Plain VAULT_ROOT may point at the operator/prod vault; test selection uses
    # test-channel selectors or the repo-local scratch vault instead.
    operator_vault = tmp_path / "Bifröst"
    env = derive_test_channel_env(
        repo_root=tmp_path, environ={"VAULT_ROOT": str(operator_vault)}
    )
    assert env["VAULT_ROOT"] == str((tmp_path / "vault-test").resolve())
    assert env["VAULT_ROOT"] == env["VAULT_ROOT_TEST"] == env["TEST_VAULT_ROOT"]


def test_bootstrap_does_not_touch_operator_last_active_vault() -> None:
    # remember=False by default: bootstrapping the test vault must never rewrite
    # the operator's last-active vault pointer. Guard the default kwarg so a
    # future edit cannot silently flip it to True.
    import inspect

    from app.ops.test_channel_bootstrap import bootstrap_test_channel as fn

    assert inspect.signature(fn).parameters["remember"].default is False
