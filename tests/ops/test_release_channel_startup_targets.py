"""
Static inspection tests for canonical startup targets (Issue #967, #1629).

Verifies that the Makefile startup targets for test and prod channels
bind the correct compose file, compose project name, PKM_ENVIRONMENT,
and channel-appropriate vault root guard.

Also verifies (Issue #1629) that make test-start-full causes the generated
runtime.env to carry test-scoped artifact paths so containers under
pkm-test write to /app/tmp-test/ without manual post-processing.

No Docker required. Tests read the Makefile and invoke export_runtime_env.sh
directly.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from app.release_channels.prod_ref_fitness import (
    check_prod_head_matches_promotion_ref_and_clean,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"


def _git(repo: Path, *args: str) -> str:
    """Run a git command in ``repo`` and return stdout (test helper)."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _init_repo_on_main(repo: Path) -> str:
    """Initialise a throwaway git repo with one commit on a ``main`` branch.

    Returns the HEAD sha. No network, no shared identity required.
    """
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Release Channel Test")
    (repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "baseline")
    _git(repo, "branch", "-M", "main")
    return _git(repo, "rev-parse", "HEAD").strip()


def _makefile_target_body(makefile_text: str, target_name: str) -> str | None:
    """Extract the body of a Makefile target.

    Anchors on `^<target>:` to avoid matching .PHONY declarations.
    Body ends at the next non-tab line (next target or variable).
    """
    pattern = re.compile(
        rf"^{re.escape(target_name)}\s*:.*?(?=\n\S|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(makefile_text)
    return match.group(0) if match else None


def test_test_start_target_binds_test_environment() -> None:
    """test-start-full must explicitly bind PKM_ENVIRONMENT=test and use
    the test compose overlay and project name.

    Verify: Issue #967 AC1 —
      tests/ops/test_release_channel_startup_targets.py::test_test_start_target_binds_test_environment
    """
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    body = _makefile_target_body(makefile_text, "test-start-full")

    assert body is not None, (
        "Could not find 'test-start-full' target in Makefile. "
        "A canonical test full-stack startup target is required (Issue #967)."
    )
    assert re.search(r'PKM_ENVIRONMENT\s*=\s*["\']?test["\']?', body), (
        "Makefile 'test-start-full' target does not explicitly set "
        "PKM_ENVIRONMENT=test. Test startup must bind this to prevent "
        "test services from running with prod environment (Issue #967)."
    )
    assert re.search(r'COMPOSE_PROJECT_NAME\s*=\s*["\']?pkm-test["\']?', body), (
        "Makefile 'test-start-full' target does not set COMPOSE_PROJECT_NAME=pkm-test. "
        "Test and prod channels must use distinct project names (Issue #967)."
    )
    assert "COMPOSE_TEST_FILES" in body, (
        "Makefile 'test-start-full' target does not use COMPOSE_TEST_FILES. "
        "The test overlay and deploy pin env must be included in the test startup "
        "(Issue #967)."
    )
    assert "docker-compose.test.yml" in makefile_text, (
        "Makefile does not define docker-compose.test.yml for test startup "
        "(Issue #967)."
    )
    assert "docker-compose.test-vault.yml" in makefile_text, (
        "Explicit TEST vault startup must append the deterministic TEST vault "
        "activation overlay."
    )
    startup_script = (REPO_ROOT / "scripts/start_full_system.sh").read_text(
        encoding="utf-8"
    )
    assert 'COMPOSE_PROJECT_NAME:-}" = "pkm-test"' in startup_script
    assert "docker-compose.test-vault.yml" in startup_script


def test_prod_start_target_binds_prod_environment() -> None:
    """prod-start-full must explicitly bind PKM_ENVIRONMENT=prod and use
    the prod compose overlay and project name.

    Verify: Issue #967 AC2 —
      tests/ops/test_release_channel_startup_targets.py::test_prod_start_target_binds_prod_environment
    """
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    body = _makefile_target_body(makefile_text, "prod-start-full")

    assert body is not None, (
        "Could not find 'prod-start-full' target in Makefile. "
        "A canonical prod full-stack startup target is required (Issue #967)."
    )
    assert re.search(r'PKM_ENVIRONMENT\s*=\s*["\']?prod["\']?', body), (
        "Makefile 'prod-start-full' target does not explicitly set "
        "PKM_ENVIRONMENT=prod. Prod startup must bind this explicitly "
        "to prevent implicit env inheritance (Issue #967)."
    )
    assert re.search(r'COMPOSE_PROJECT_NAME\s*=\s*["\']?pkm-prod["\']?', body), (
        "Makefile 'prod-start-full' target does not set COMPOSE_PROJECT_NAME=pkm-prod. "
        "Prod channel must use an explicit project name (Issue #967)."
    )
    assert "COMPOSE_PROD_FILES" in body, (
        "Makefile 'prod-start-full' target does not use COMPOSE_PROD_FILES. "
        "The prod overlay and deploy pin env must be included in the prod startup "
        "(Issue #967)."
    )
    assert "docker-compose.prod.yml" in makefile_text, (
        "Makefile does not define docker-compose.prod.yml for prod startup "
        "(Issue #967)."
    )
    assert "scripts/prod/start_midgard_stack.sh" in body, (
        "Makefile 'prod-start-full' target must route through the Midgård prod "
        "vault preflight before the generic no-vault-capable startup script."
    )


def test_full_start_targets_use_channel_specific_vault_binding() -> None:
    """Full start targets must use channel-appropriate vault binding.

    Test startup remains explicitly supplied by the caller, while prod startup
    must not require an inline VAULT_ROOT because the prod channel default is
    loaded from .env.prod.local.

    Verify: Issue #967 AC3 —
      tests/ops/test_release_channel_startup_targets.py::test_full_start_targets_use_channel_specific_vault_binding
    """
    makefile_text = MAKEFILE.read_text(encoding="utf-8")

    test_body = _makefile_target_body(makefile_text, "test-start-full")
    assert test_body is not None, "Could not find 'test-start-full' target in Makefile."
    assert "require-vault-root" in test_body and re.search(r'VAULT_ROOT', test_body), (
        "Makefile 'test-start-full' must still require an explicit test VAULT_ROOT."
    )

    prod_body = _makefile_target_body(makefile_text, "prod-start-full")
    assert prod_body is not None, "Could not find 'prod-start-full' target in Makefile."
    assert "require-vault-root" not in prod_body, (
        "Makefile 'prod-start-full' must use .env.prod.local defaults instead of "
        "requiring an inline VAULT_ROOT."
    )
    assert not re.search(r'\bVAULT_ROOT\s*=', prod_body), (
        "Makefile 'prod-start-full' must not override the prod channel vault default "
        "with an inline VAULT_ROOT assignment."
    )


def test_prod_start_full_has_midgard_preflight() -> None:
    """prod-start-full must fail before generic startup if Midgård is not bound."""
    script = (REPO_ROOT / "scripts/prod/start_midgard_stack.sh").read_text(
        encoding="utf-8"
    )
    assert '.env.prod.local' in script
    assert 'VAULT_ROOT' in script
    assert 'midg(å|a)rd' in script
    assert 'source "scripts/lib/heimdal_cold_volume_preflight.sh"' in script
    assert 'heimdal_cold_volume_preflight prod "$ROOT"' in script
    assert script.index('heimdal_cold_volume_preflight prod "$ROOT"') < script.index(
        'exec scripts/start_full_system.sh'
    )
    assert 'exec scripts/start_full_system.sh' in script


@pytest.mark.parametrize(
    ("channel", "project", "compose_file", "expected"),
    [
        pytest.param("prod", "custom", "docker-compose.yaml", "prod", id="channel"),
        pytest.param(" PROD ", "custom", "docker-compose.yaml", "prod", id="normalized"),
        pytest.param("", "PKM-PROD", "docker-compose.yaml", "prod", id="project"),
        pytest.param(
            "",
            "custom",
            "docker-compose.yaml:/tmp/docker-compose.prod.yml",
            "prod",
            id="compose-overlay",
        ),
        pytest.param(
            "test",
            "pkm-test",
            "docker-compose.yaml:docker-compose.test.yml",
            "test",
            id="non-prod",
        ),
    ],
)
def test_archive_gate_uses_one_effective_channel_classifier(
    channel: str,
    project: str,
    compose_file: str,
    expected: str,
) -> None:
    helper = REPO_ROOT / "scripts/lib/heimdal_cold_volume_preflight.sh"
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; heimdal_cold_volume_effective_channel "$2" "$3" "$4"',
            "harness",
            str(helper),
            channel,
            project,
            compose_file,
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == expected


def test_every_supported_prod_forward_producer_routes_through_archive_gate() -> None:
    """Closed source census for all supported production forward entrypoints."""
    makefile = MAKEFILE.read_text(encoding="utf-8")
    full_start = (REPO_ROOT / "scripts/start_full_system.sh").read_text(encoding="utf-8")
    cold_boot = (REPO_ROOT / "scripts/cold_boot.sh").read_text(encoding="utf-8")
    deploy = (REPO_ROOT / "scripts/deploy_channel.sh").read_text(encoding="utf-8")
    companion = (REPO_ROOT / "scripts/lib/companion_ui_startup.sh").read_text(
        encoding="utf-8"
    )
    midgard_stack = (REPO_ROOT / "scripts/prod/start_midgard_stack.sh").read_text(
        encoding="utf-8"
    )
    midgard_ui = (REPO_ROOT / "scripts/prod/start_midgard_ui.sh").read_text(
        encoding="utf-8"
    )

    assert 'heimdal_cold_volume_preflight_effective "$ROOT"' in full_start
    assert 'heimdal_cold_volume_preflight_effective "$ROOT"' in cold_boot
    assert "heimdal_cold_volume_preflight_effective" in companion
    assert 'heimdal_cold_volume_preflight prod "$ROOT"' in midgard_stack
    assert 'source "${SCRIPT_DIR}/../lib/companion_ui_startup.sh"' in midgard_ui
    assert "cui_run_start" in midgard_ui
    assert 'if [ "${action}" = "deploy" ]; then' in deploy
    assert 'heimdal_cold_volume_preflight "${channel}" "${ROOT}"' in deploy

    prod_up = _makefile_target_body(makefile, "prod-up")
    prod_full = _makefile_target_body(makefile, "prod-start-full")
    prod_ui = _makefile_target_body(makefile, "prod-ui")
    assert prod_up is not None and "heimdal_cold_volume_preflight prod" in prod_up
    assert prod_full is not None and "scripts/prod/start_midgard_stack.sh" in prod_full
    assert prod_ui is not None and "scripts/prod/start_midgard_ui.sh" in prod_ui

    gate_index = cold_boot.index('heimdal_cold_volume_preflight_effective "$ROOT"')
    assert gate_index < cold_boot.index("prepare_instance_ownership_host_state_dir")
    assert gate_index < cold_boot.index("docker compose down -v")


@pytest.mark.parametrize(
    ("preflight_rc", "starts_runtime"),
    [
        pytest.param(0, True, id="ready"),
        pytest.param(78, False, id="archive-refused"),
    ],
)
def test_prod_start_wrapper_executes_archive_gate_before_runtime(
    tmp_path: Path,
    preflight_rc: int,
    starts_runtime: bool,
) -> None:
    """Exercise the production call site without touching host disk state."""
    root = tmp_path / "repo"
    for relative in (
        "scripts/prod/start_midgard_stack.sh",
        "scripts/lib/load_env_defaults.sh",
        "scripts/lib/heimdal_cold_volume_preflight.sh",
    ):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            (REPO_ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8"
        )

    vault = tmp_path / "fixture-midgard"
    vault.mkdir()
    metadata = tmp_path / "archive-metadata.json"
    (root / ".env.prod.local").write_text(
        f"VAULT_ROOT={vault}\nHEIMDAL_ARCHIVE_METADATA_FILE={metadata}\n",
        encoding="utf-8",
    )
    runtime_marker = tmp_path / "runtime-started"
    (root / "scripts/start_full_system.sh").write_text(
        f"#!/usr/bin/env bash\ntouch {runtime_marker!s}\n", encoding="utf-8"
    )
    (root / "scripts/start_full_system.sh").chmod(0o755)
    python = tmp_path / "python-fixture"
    python.write_text(
        "#!/usr/bin/env bash\n"
        "test \"${1:-}\" = -m\n"
        "test \"${2:-}\" = app.ops.heimdal_cold_volume\n"
        "test \"${3:-}\" = require-ready\n"
        f"exit {preflight_rc}\n",
        encoding="utf-8",
    )
    python.chmod(0o755)

    env = os.environ.copy()
    env["PYTHON"] = str(python)
    result = subprocess.run(
        ["bash", "scripts/prod/start_midgard_stack.sh"],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert (result.returncode == 0) is starts_runtime
    assert runtime_marker.exists() is starts_runtime
    if not starts_runtime:
        assert "output=redacted" in result.stderr


@pytest.mark.parametrize(
    ("entrypoint", "selector_env"),
    [
        pytest.param(
            "direct-full-start",
            {"PKM_ENVIRONMENT": "prod", "COMPOSE_PROJECT_NAME": "pkm-prod"},
            id="direct-full-start-canonical",
        ),
        pytest.param(
            "direct-full-start",
            {"PKM_ENVIRONMENT": " PROD ", "COMPOSE_PROJECT_NAME": "custom-prod"},
            id="direct-full-start-normalized-channel",
        ),
        pytest.param(
            "direct-full-start",
            {
                "PKM_ENVIRONMENT": "",
                "COMPOSE_PROJECT_NAME": "custom-prod",
                "COMPOSE_FILE": "docker-compose.yaml:docker-compose.prod.yml",
            },
            id="direct-full-start-explicit-prod-compose",
        ),
        pytest.param("make-prod-up", {}, id="make-prod-up"),
        pytest.param(
            "cold-boot",
            {
                "PKM_ENVIRONMENT": "",
                "COMPOSE_PROJECT_NAME": "custom-prod",
                "COMPOSE_FILE": "docker-compose.yaml:docker-compose.prod.yml",
            },
            id="cold-boot-prod-compose",
        ),
    ],
)
def test_direct_prod_entrypoints_refuse_before_host_mutation(
    tmp_path: Path,
    entrypoint: str,
    selector_env: dict[str, str],
) -> None:
    """Exercise direct prod paths with a refused fixture gate and fake Docker."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_marker = tmp_path / "docker-executed"
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        f"touch {docker_marker!s}\n"
        "exit 99\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    python = tmp_path / "python-fixture"
    python.write_text("#!/usr/bin/env bash\nexit 78\n", encoding="utf-8")
    python.chmod(0o755)

    env = os.environ.copy()
    host_state = tmp_path / "host-state"
    env.update(selector_env)
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "PYTHON": str(python),
            "HEIMDAL_ARCHIVE_METADATA_FILE": str(tmp_path / "archive-metadata.json"),
            "INSTANCE_OWNERSHIP_HOST_STATE_DIR": str(host_state),
        }
    )
    command = {
        "direct-full-start": ["bash", "scripts/start_full_system.sh"],
        "make-prod-up": ["make", "prod-up"],
        "cold-boot": ["bash", "scripts/cold_boot.sh"],
    }[entrypoint]

    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert docker_marker.exists() is False
    assert host_state.exists() is False
    assert "archive volume preflight failed: output=redacted" in result.stderr


def test_test_start_full_uses_tmp_test_runtime_artifact_paths(tmp_path: Path) -> None:
    """make test-start-full must generate a runtime.env file under tmp-test/
    that carries /app/tmp-test/ artifact paths for all six artifact variables,
    so pkm-test containers never write runtime artifacts to /app/tmp/.

    This test invokes export_runtime_env.sh with COMPOSE_PROJECT_NAME=pkm-test
    (mirroring what make test-start-full sets) and verifies the output file
    contains the expected test-scoped paths.  No Docker required.

    Verify: Issue #1629 AC1 —
      tests/ops/test_release_channel_startup_targets.py::test_test_start_full_uses_tmp_test_runtime_artifact_paths
    """
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    runtime_env_path = tmp_path / "runtime.env"

    env = os.environ.copy()
    env["COMPOSE_PROJECT_NAME"] = "pkm-test"
    env["VAULT_ROOT"] = str(vault_root)
    env["RUNTIME_ENV_PATH"] = str(runtime_env_path)
    env.setdefault("DATABASE_URL", "postgresql+psycopg://app:app@db:5432/app_test")
    # Clear any operator overrides so we test the auto-generation path
    for var in (
        "WATCHER_STATE_DIR",
        "WATCHER_STOP_FILE",
        "INDEX_OUTBOX_PATH",
        "WATCHER_HEARTBEAT_PATH",
        "WORKER_HEARTBEAT_PATH",
        "WATCHER_STATE_PATH",
    ):
        env.pop(var, None)

    subprocess.run(
        ["bash", "scripts/export_runtime_env.sh"],
        check=True,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )

    assert runtime_env_path.exists(), (
        "export_runtime_env.sh did not create runtime.env for pkm-test channel"
    )
    text = runtime_env_path.read_text(encoding="utf-8")

    assert re.search(r"^INDEX_OUTBOX_PATH=/app/tmp-test/", text, re.M), (
        "INDEX_OUTBOX_PATH must point to /app/tmp-test/ for the pkm-test channel "
        "(Issue #1629: test containers were inheriting /app/tmp defaults)"
    )
    assert re.search(r"^WATCHER_HEARTBEAT_PATH=/app/tmp-test/", text, re.M), (
        "WATCHER_HEARTBEAT_PATH must point to /app/tmp-test/ for the pkm-test channel"
    )
    assert re.search(r"^WORKER_HEARTBEAT_PATH=/app/tmp-test/", text, re.M), (
        "WORKER_HEARTBEAT_PATH must point to /app/tmp-test/ for the pkm-test channel"
    )
    assert re.search(r"^WATCHER_STATE_PATH=/app/tmp-test/", text, re.M), (
        "WATCHER_STATE_PATH must point to /app/tmp-test/ for the pkm-test channel"
    )
    assert re.search(r"^WATCHER_STATE_DIR=tmp-test$", text, re.M), (
        "WATCHER_STATE_DIR must be 'tmp-test' for the pkm-test channel"
    )
    assert re.search(r"^WATCHER_STOP_FILE=/app/tmp-test/", text, re.M), (
        "WATCHER_STOP_FILE must point to /app/tmp-test/ for the pkm-test channel"
    )
    # No bare /app/tmp/ artifact paths should remain for these variables
    for var in ("INDEX_OUTBOX_PATH", "WATCHER_HEARTBEAT_PATH", "WORKER_HEARTBEAT_PATH",
                "WATCHER_STATE_PATH", "WATCHER_STOP_FILE"):
        assert not re.search(rf"^{re.escape(var)}=/app/tmp/", text, re.M), (
            f"{var} must not point to bare /app/tmp/ in pkm-test runtime.env"
        )


def test_prod_head_matches_promotion_ref_and_clean(tmp_path: Path) -> None:
    """The prod-ref fitness guard must flag a prod checkout that diverges from
    the agreed promotion ref (``main``, ADR-0040) or runs a dirty working tree,
    and pass a clean checkout that is on the ref.

    This backs the #2527 reproducibility invariant — prod must be
    reconstructible from git alone — and is the logic the operator runs on the
    prod host to produce the AC2 "prod tree clean" receipt.

    Verify: Issue #2527 AC3 —
      tests/ops/test_release_channel_startup_targets.py::test_prod_head_matches_promotion_ref_and_clean
    """
    # --- clean checkout, on the promotion ref -> OK ------------------------
    repo = tmp_path / "prod-clean"
    head_sha = _init_repo_on_main(repo)

    result = check_prod_head_matches_promotion_ref_and_clean(repo)
    assert result.ok, f"clean main checkout should pass, got: {result.violations}"
    assert result.is_clean is True
    assert result.on_promotion_ref is True
    assert result.current_branch == "main"
    assert result.head_sha == head_sha
    assert result.violations == []

    # --- dirty working tree -> violation ----------------------------------
    (repo / "tracked.txt").write_text("uncommitted edit\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("new\n", encoding="utf-8")

    dirty = check_prod_head_matches_promotion_ref_and_clean(repo)
    assert not dirty.ok, "a dirty prod tree must be flagged"
    assert dirty.is_clean is False
    assert any("dirty" in v for v in dirty.violations), dirty.violations
    assert "tracked.txt" in dirty.dirty_paths
    assert "untracked.txt" in dirty.dirty_paths

    # --- wrong branch (not the promotion ref) -> violation ----------------
    feature_repo = tmp_path / "prod-feature"
    _init_repo_on_main(feature_repo)
    _git(feature_repo, "checkout", "-q", "-b", "feature/x")

    wrong_branch = check_prod_head_matches_promotion_ref_and_clean(feature_repo)
    assert not wrong_branch.ok, "a checkout off the promotion ref must be flagged"
    assert wrong_branch.on_promotion_ref is False
    assert any("feature/x" in v and "main" in v for v in wrong_branch.violations), (
        wrong_branch.violations
    )

    # --- a configurable promotion ref is honoured -------------------------
    on_feature_ok = check_prod_head_matches_promotion_ref_and_clean(
        feature_repo, promotion_ref="feature/x"
    )
    assert on_feature_ok.ok, on_feature_ok.violations

    # --- explicit divergence against an already-known ref -> violation ----
    diverge_repo = tmp_path / "prod-diverge"
    base_sha = _init_repo_on_main(diverge_repo)
    # Record a comparison ref at the current commit, then advance HEAD past it.
    _git(diverge_repo, "update-ref", "refs/remotes/origin/main", base_sha)
    (diverge_repo / "tracked.txt").write_text("advanced\n", encoding="utf-8")
    _git(diverge_repo, "add", "tracked.txt")
    _git(diverge_repo, "commit", "-q", "-m", "advance past origin/main")

    diverged = check_prod_head_matches_promotion_ref_and_clean(
        diverge_repo, compare_to_ref="origin/main"
    )
    assert not diverged.ok, "HEAD ahead of the compared promotion ref must be flagged"
    assert diverged.matches_compare_ref is False
    assert diverged.compare_to_sha == base_sha
    assert any("diverge" in v for v in diverged.violations), diverged.violations

    # --- untracked files are flagged even with status.showUntrackedFiles=no ---
    # A prod host configured (locally or globally) with showUntrackedFiles=no must
    # not silence the clean-tree receipt: the #2527 finding included untracked dirs
    # in the prod tree. The guard forces --untracked-files=all.
    hidden_repo = tmp_path / "prod-hidden-untracked"
    _init_repo_on_main(hidden_repo)
    _git(hidden_repo, "config", "status.showUntrackedFiles", "no")
    (hidden_repo / "machine_local.txt").write_text("local-only\n", encoding="utf-8")
    # Sanity: with showUntrackedFiles=no a plain porcelain status hides it...
    assert _git(hidden_repo, "status", "--porcelain").strip() == ""
    # ...but the guard must still flag it.
    hidden = check_prod_head_matches_promotion_ref_and_clean(hidden_repo)
    assert not hidden.ok, "untracked files must be flagged despite showUntrackedFiles=no"
    assert "machine_local.txt" in hidden.dirty_paths, hidden.dirty_paths
