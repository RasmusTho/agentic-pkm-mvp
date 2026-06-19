"""One idempotent test-channel bootstrap (issue #1997 F3).

The single source of truth that brings up a *correct* test channel and
self-checks it. It exists so a clean ``promote-to-test`` (and the in-process
IR-v1 UAT) need **zero** manual env workarounds — the six 2026-06-14 symptoms
die here:

1. vault init is run (the #1991 invariant) so settings are scaffolded;
2. a shared, **absolute** ``INDEX_OUTBOX_PATH`` under ``tmp-test/`` (never a
   CWD-relative default that splits watcher and consumer);
3. channel-correct heartbeat paths under ``tmp-test/``;
4. a **host-reachable** DSN (``127.0.0.1:15434``, not the in-container
   ``db:5432``);
5. an **absolute, canonical** ``TEST_VAULT_ROOT`` (not ``$(PWD)/...``);
6. a single-watcher posture (the container watcher; no host watcher race).

The deterministic core lives here in Python (vault init + env derivation +
the F2 preflight) so it is testable without Docker. ``scripts/bootstrap_test_channel.sh``
wraps this with the Docker bring-up. Re-running is safe: vault init keeps
existing files, env derivation is pure, and the preflight is read-only.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from app.ops.channel_preflight import (
    TEST_DB_HOST_PORT,
    ChannelEnvPreflight,
    channel_env_preflight,
)
from app.vault.manager import VaultManager

#: Canonical host-reachable test DSN (published port 15434 → app_test).
TEST_DSN = f"postgresql+psycopg://app:app@127.0.0.1:{TEST_DB_HOST_PORT}/app_test"


@dataclass(frozen=True)
class BootstrapResult:
    """Outcome of a single idempotent test-channel bootstrap."""

    env: dict[str, str]
    vault_root: str
    vault_status: str
    created_files: tuple[str, ...] = field(default=())
    skipped_files: tuple[str, ...] = field(default=())
    preflight: ChannelEnvPreflight | None = None

    @property
    def ok(self) -> bool:
        return (
            self.vault_status == "selected"
            and self.preflight is not None
            and self.preflight.ok
        )


def _repo_root(repo_root: str | os.PathLike[str] | None) -> Path:
    if repo_root is not None:
        return Path(repo_root).resolve()
    # app/ops/test_channel_bootstrap.py → repo root is two parents up from app/.
    return Path(__file__).resolve().parents[2]


def derive_test_channel_env(
    repo_root: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
    *,
    vault_root: str | os.PathLike[str] | None = None,
) -> dict[str, str]:
    """Return the canonical, absolute, channel-correct test-channel host env.

    Pure and deterministic: the same inputs always yield the same env. The test
    vault is operator-configured — an explicit ``vault_root`` wins, otherwise it
    is read from ``VAULT_ROOT_TEST`` / ``TEST_VAULT_ROOT`` / ``VAULT_ROOT`` in
    ``environ``. There is no synthetic default vault name: if none is supplied
    this fails loud rather than inventing a ``vault-test`` directory. All paths
    are resolved to absolute form so callers never depend on CWD.
    """
    env = os.environ if environ is None else environ
    root = _repo_root(repo_root)

    chosen_vault = (
        vault_root
        or env.get("VAULT_ROOT_TEST")
        or env.get("TEST_VAULT_ROOT")
        or env.get("VAULT_ROOT")
    )
    if not chosen_vault:
        raise ValueError(
            "test-channel vault root is unset: provide vault_root or set "
            "VAULT_ROOT_TEST / TEST_VAULT_ROOT / VAULT_ROOT to the operator's "
            "test vault. The synthetic 'vault-test' default was removed so the "
            "channel never silently targets a fabricated vault."
        )
    vault_abs = Path(chosen_vault).expanduser().resolve()
    tmp_test = root / "tmp-test"

    return {
        "PKM_ENVIRONMENT": "test",
        "PKM_CHANNEL": "test",
        "COMPOSE_FILE": "docker-compose.yaml:docker-compose.test.yml",
        "COMPOSE_PROJECT_NAME": "pkm-test",
        "VAULT_ROOT": str(vault_abs),
        "VAULT_ROOT_TEST": str(vault_abs),
        "TEST_VAULT_ROOT": str(vault_abs),
        "INDEX_OUTBOX_PATH": str(tmp_test / "index-outbox.jsonl"),
        "WORKER_HEARTBEAT_PATH": str(tmp_test / "worker_heartbeat.json"),
        "WATCHER_HEARTBEAT_PATH": str(tmp_test / "watcher_heartbeat.json"),
        "WATCHER_STATE_PATH": str(tmp_test / "watcher_state.json"),
        "DATABASE_URL": TEST_DSN,
        "DB_DSN": TEST_DSN,
        "TEST_API_BASE_URL": "http://127.0.0.1:18002",
        # Single-watcher posture: the container watcher is the only watcher.
        # The shell wrapper must not also launch a host-side watcher (issue
        # #1997, symptom 6 — two-watcher race).
        "WATCHER_AUTO_EXEC": "1",
    }


def bootstrap_test_channel(
    repo_root: str | os.PathLike[str] | None = None,
    *,
    vault_root: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
    remember: bool = False,
) -> BootstrapResult:
    """Bring up a correct test channel (config layer) and self-check it.

    Idempotent. Steps:

    1. derive the canonical channel env;
    2. ``vault init`` the test vault (scaffold settings; keep existing files);
    3. run the F2 channel-env preflight against the derived env and fail loud on
       any inconsistency.

    Does not touch Docker — the shell wrapper owns the stack bring-up.
    ``remember`` defaults to False so bootstrapping the test vault never
    rewrites the operator's last-active vault pointer.
    """
    env = derive_test_channel_env(repo_root, environ, vault_root=vault_root)
    vault_path = Path(env["VAULT_ROOT"])

    # Use a fresh VaultManager rather than the process-global singleton: the
    # bootstrap's durable effect is the scaffolded settings on disk, not a
    # selected-vault state on a shared singleton. A fresh instance keeps the
    # bootstrap hermetic — in-process callers (tests, the UAT) are not polluted
    # with a stale selected vault.
    init = VaultManager().initialize_vault(
        vault_path,
        machine_role="primary",
        remember=remember,
    )

    preflight = channel_env_preflight(env, channel="test", context="host")

    return BootstrapResult(
        env=env,
        vault_root=env["VAULT_ROOT"],
        vault_status=init.context.status,
        created_files=init.created_files,
        skipped_files=init.skipped_existing_files,
        preflight=preflight,
    )


__all__ = [
    "TEST_DSN",
    "BootstrapResult",
    "derive_test_channel_env",
    "bootstrap_test_channel",
]
