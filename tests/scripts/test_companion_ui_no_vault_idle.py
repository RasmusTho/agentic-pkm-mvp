"""No-vault idle boot for the shared Companion UI launcher (#2005).

The dev/test/prod Companion UI wrappers all delegate to
``scripts/lib/companion_ui_startup.sh``. Under the settled no-vault idle-boot
invariant (#2005) and in-app vault selection, the launcher must:

  * boot to the picker when no vault is configured (NOT hard-fail), and
  * treat a configured-but-mismatched vault as advisory (warn-only) on dev/test
    (scratch vaults; the active vault is selected in-app), but FATAL on prod,
    whose write-capable worker would otherwise bind and write the wrong real
    vault (Codex P1, PR #2652).

These tests exercise the bash guard functions directly so they need neither
Docker nor a real vault.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "scripts/lib/companion_ui_startup.sh"

# Minimal channel config the vault guard reads (test/Bifröst pattern).
_CONFIG = r"""
CUI_CHANNEL=test
CUI_EXPECTED_VAULT_PATTERN='bifr(ö|o)st'
CUI_EXPECTED_VAULT_LABEL='Bifröst/Bifrost'
"""


def _run(snippet: str) -> subprocess.CompletedProcess[str]:
    harness = f'set -o pipefail\nsource "{LIB}"\n{_CONFIG}\n{snippet}\n'
    return subprocess.run(
        ["bash", "-c", harness],
        cwd=REPO_ROOT,
        env=dict(os.environ),
        capture_output=True,
        text=True,
    )


def test_no_vault_idles_instead_of_dying() -> None:
    r = _run("unset VAULT_ROOT\ncui_guard_vault_name\necho GUARD_RETURNED")
    assert r.returncode == 0, r.stderr
    assert "GUARD_RETURNED" in r.stdout, "guard must return (not exit) when no vault is configured"
    assert "no-vault idle boot" in (r.stdout + r.stderr)


def test_matching_vault_passes() -> None:
    r = _run("VAULT_ROOT='/tmp/Bifrost'\ncui_guard_vault_name\necho GUARD_RETURNED")
    assert r.returncode == 0, r.stderr
    assert "GUARD_RETURNED" in r.stdout
    assert "vault guard OK" in (r.stdout + r.stderr)


def test_mismatched_vault_is_advisory_on_non_prod() -> None:
    # _CONFIG is the test channel: a mismatch warns but does not hard-fail.
    r = _run("VAULT_ROOT='/tmp/Niflheim'\ncui_guard_vault_name\necho GUARD_RETURNED")
    assert r.returncode == 0, "a mismatched dev/test vault must NOT hard-fail (advisory)"
    assert "GUARD_RETURNED" in r.stdout
    assert "advisory" in (r.stdout + r.stderr)


def test_mismatched_prod_vault_is_fatal() -> None:
    # Prod binds the operator's real vault and runs a write-capable worker, so a
    # configured-but-wrong prod vault must hard-fail rather than warn (Codex P1).
    harness = (
        "VAULT_ROOT='/tmp/Niflheim'\n"
        "CUI_CHANNEL=prod\n"
        "CUI_EXPECTED_VAULT_PATTERN='midg(å|a)rd'\n"
        "CUI_EXPECTED_VAULT_LABEL='Midgård/Midgard'\n"
        "cui_guard_vault_name\necho GUARD_RETURNED"
    )
    r = _run(harness)
    assert r.returncode != 0, "a mismatched prod vault must hard-fail"
    assert "GUARD_RETURNED" not in r.stdout, "guard must exit before returning on prod mismatch"
    assert "Refusing to boot the prod channel" in (r.stdout + r.stderr)


def test_matching_prod_vault_passes() -> None:
    harness = (
        "VAULT_ROOT='/tmp/Midgard'\n"
        "CUI_CHANNEL=prod\n"
        "CUI_EXPECTED_VAULT_PATTERN='midg(å|a)rd'\n"
        "CUI_EXPECTED_VAULT_LABEL='Midgård/Midgard'\n"
        "cui_guard_vault_name\necho GUARD_RETURNED"
    )
    r = _run(harness)
    assert r.returncode == 0, r.stderr
    assert "GUARD_RETURNED" in r.stdout
    assert "vault guard OK" in (r.stdout + r.stderr)


def test_doctor_prod_vault_mismatch_fails() -> None:
    # The read-only doctor must FAIL on a prod vault mismatch, mirroring the
    # launcher guard — otherwise prod-ui-doctor green-lights a vault prod-ui
    # refuses to boot against (Codex P2, PR #2652).
    harness = (
        "VAULT_ROOT='/tmp/Niflheim'\n"
        "CUI_CHANNEL=prod\n"
        "CUI_EXPECTED_VAULT_PATTERN='midg(å|a)rd'\n"
        "CUI_EXPECTED_VAULT_LABEL='Midgård/Midgard'\n"
        "cui_doctor_vault_name_status\necho RC=$?"
    )
    r = _run(harness)
    assert "[fail] prod vault" in (r.stdout + r.stderr)
    assert "RC=1" in r.stdout, "prod mismatch must fail the doctor check"


def test_doctor_non_prod_vault_mismatch_is_advisory() -> None:
    # _CONFIG is the test channel: a mismatch warns but does not fail the doctor.
    r = _run("VAULT_ROOT='/tmp/Niflheim'\ncui_doctor_vault_name_status\necho RC=$?")
    assert "[warn] vault" in (r.stdout + r.stderr)
    assert "[fail]" not in (r.stdout + r.stderr)
    assert "RC=0" in r.stdout


def test_doctor_no_vault_is_idle_not_failure() -> None:
    r = _run("unset VAULT_ROOT\ncui_doctor_vault_name_status\necho RC=$?")
    assert "no-vault idle boot" in (r.stdout + r.stderr)
    assert "RC=0" in r.stdout


def test_missing_channel_env_file_is_not_fatal(tmp_path: Path) -> None:
    # A repo root with no .env.test.local must not abort the launcher.
    snippet = (
        f'cui_repo_root() {{ printf "%s" "{tmp_path}"; }}\n'
        "cui_load_channel_env\n"
        "echo LOAD_RETURNED"
    )
    r = _run(snippet)
    assert r.returncode == 0, r.stderr
    assert "LOAD_RETURNED" in r.stdout
    assert "no .env.test.local" in (r.stdout + r.stderr)


def test_missing_channel_env_clears_inherited_vault_root(tmp_path: Path) -> None:
    # An ambient VAULT_ROOT must not leak into a channel with no env file —
    # otherwise `VAULT_ROOT=/x make test-ui` would mount the wrong vault instead
    # of idling to the picker (Codex review on PR #2652).
    snippet = (
        f'cui_repo_root() {{ printf "%s" "{tmp_path}"; }}\n'
        "export VAULT_ROOT=/tmp/Some-Other-Vault\n"
        "export VAULT_HOST_ROOT=/tmp/Some-Other-Vault\n"
        "cui_load_channel_env\n"
        'echo "VAULT_ROOT_AFTER=[${VAULT_ROOT:-}]"\n'
        'echo "VAULT_HOST_ROOT_AFTER=[${VAULT_HOST_ROOT:-}]"'
    )
    r = _run(snippet)
    assert r.returncode == 0, r.stderr
    assert "VAULT_ROOT_AFTER=[]" in r.stdout, (
        "inherited VAULT_ROOT must be cleared when the channel env file is absent"
    )
    assert "VAULT_HOST_ROOT_AFTER=[]" in r.stdout


def test_present_channel_env_overrides_inherited_vault_root(tmp_path: Path) -> None:
    # With .env.<channel>.local present AND an ambient VAULT_ROOT exported, the
    # channel file must win. load_env_defaults_file is defaults-only, so the
    # ambient value is cleared first; otherwise `VAULT_ROOT=/x make test-ui`
    # mounts the wrong vault for the channel (Codex P1 on PR #2652).
    (tmp_path / "scripts" / "lib").mkdir(parents=True)
    shutil.copy(
        REPO_ROOT / "scripts/lib/load_env_defaults.sh",
        tmp_path / "scripts/lib/load_env_defaults.sh",
    )
    (tmp_path / ".env.test.local").write_text(
        "VAULT_ROOT=/tmp/Bifrost-from-file\n", encoding="utf-8"
    )
    snippet = (
        f'cui_repo_root() {{ printf "%s" "{tmp_path}"; }}\n'
        "export VAULT_ROOT=/tmp/Ambient-Midgard\n"
        "cui_load_channel_env\n"
        'echo "VAULT_ROOT_AFTER=[${VAULT_ROOT:-}]"'
    )
    r = _run(snippet)
    assert r.returncode == 0, r.stderr
    assert "VAULT_ROOT_AFTER=[/tmp/Bifrost-from-file]" in r.stdout, (
        "the channel env file must define the vault; an ambient VAULT_ROOT must not win"
    )


def _load_env_with_file(tmp_path: Path, env_contents: str) -> subprocess.CompletedProcess[str]:
    (tmp_path / "scripts" / "lib").mkdir(parents=True)
    shutil.copy(
        REPO_ROOT / "scripts/lib/load_env_defaults.sh",
        tmp_path / "scripts/lib/load_env_defaults.sh",
    )
    (tmp_path / ".env.test.local").write_text(env_contents, encoding="utf-8")
    snippet = (
        f'cui_repo_root() {{ printf "%s" "{tmp_path}"; }}\n'
        "cui_load_channel_env\n"
        'echo "VAULT_ROOT_AFTER=[${VAULT_ROOT:-}]"'
    )
    return _run(snippet)


def test_channel_scoped_vault_root_is_promoted(tmp_path: Path) -> None:
    # .env.<channel>.local may pin the documented channel-scoped root
    # (VAULT_ROOT_TEST) instead of plain VAULT_ROOT; the launcher must promote it
    # so `make test-ui` binds the override instead of idling (Codex P2 on PR #2652).
    r = _load_env_with_file(tmp_path, "VAULT_ROOT_TEST=/tmp/Bifrost-scoped\n")
    assert r.returncode == 0, r.stderr
    assert "VAULT_ROOT_AFTER=[/tmp/Bifrost-scoped]" in r.stdout, (
        "a channel-scoped VAULT_ROOT_TEST must be promoted to VAULT_ROOT"
    )


def test_plain_vault_root_wins_over_channel_scoped(tmp_path: Path) -> None:
    # If the env file sets both, the explicit base VAULT_ROOT wins (promotion only
    # fills an empty VAULT_ROOT).
    r = _load_env_with_file(
        tmp_path,
        "VAULT_ROOT=/tmp/Bifrost-plain\nVAULT_ROOT_TEST=/tmp/Bifrost-scoped\n",
    )
    assert "VAULT_ROOT_AFTER=[/tmp/Bifrost-plain]" in r.stdout


def _run_start_runtime(
    tmp_path: Path, *, vault_root: str | None, mount_src: str, has_container: bool = True
) -> str:
    """Drive cui_start_runtime with a stubbed Docker layer; returns RECREATED|SKIPPED.

    The runtime API is stubbed healthy; cui_start_runtime either warm-skips or
    invokes a stub start_full_system.sh (which leaves a marker = recreate).
    """
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    stub = tmp_path / "scripts" / "start_full_system.sh"
    stub.write_text('#!/usr/bin/env bash\ntouch "$(pwd)/.full_system_ran"\n', encoding="utf-8")
    stub.chmod(0o755)
    vault_line = f"export VAULT_ROOT={vault_root}" if vault_root else "unset VAULT_ROOT"
    harness = (
        "set -o pipefail\n"
        f'source "{LIB}"\n'
        f"{_CONFIG}\n"
        "CUI_API_PORT=18002\n"
        "CUI_COMPOSE_PROJECT=pkm-test\n"
        "CUI_COMPOSE_FILES=docker-compose.yaml\n"
        "export CUI_FORCE_RECREATE=0\n"
        f'cui_repo_root() {{ printf "%s" "{tmp_path}"; }}\n'
        "cui_api_healthy_now() { return 0; }\n"
        f"cui_api_container_id() {{ printf '%s' '{'fakecid' if has_container else ''}'; }}\n"
        f"cui_container_vault_mount_source() {{ printf '%s' '{mount_src}'; }}\n"
        f"{vault_line}\n"
        "cui_start_runtime >/dev/null 2>&1 || true\n"
        f'if [ -f "{tmp_path}/.full_system_ran" ]; then echo RECREATED; else echo SKIPPED; fi'
    )
    result = subprocess.run(
        ["bash", "-c", harness],
        cwd=REPO_ROOT,
        env=dict(os.environ),
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().splitlines()[-1]


def test_no_vault_launch_recreates_stale_vault_mount(tmp_path: Path) -> None:
    # A healthy container still bound to a previous vault + a no-vault launch must
    # recreate so the in-app picker is served, not the stale vault (Codex P2 #2652).
    assert (
        _run_start_runtime(tmp_path, vault_root=None, mount_src="/tmp/Prev-Bifrost")
        == "RECREATED"
    )


def test_no_vault_launch_warm_skips_when_no_mount(tmp_path: Path) -> None:
    # An already-idle container (no vault mount) + a no-vault launch may warm-skip.
    assert _run_start_runtime(tmp_path, vault_root=None, mount_src="") == "SKIPPED"


def test_no_vault_launch_recreates_when_no_channel_container(tmp_path: Path) -> None:
    # A healthy /healthz with NO channel container (e.g. a foreign or stale process
    # answering on the channel port) must recreate the channel stack, not warm-skip
    # onto the unrelated runtime (Codex P2 on PR #2652).
    assert (
        _run_start_runtime(tmp_path, vault_root=None, mount_src="", has_container=False)
        == "RECREATED"
    )


def test_configured_vault_recreates_when_mount_missing(tmp_path: Path) -> None:
    # A non-prod channel with a configured vault but a container that has no mount
    # (e.g. booted earlier via the no-vault path, or a freshly added
    # .env.<channel>.local) must recreate so the configured vault takes effect —
    # not warm-skip just because /healthz is up (Codex P2 on PR #2652).
    assert (
        _run_start_runtime(tmp_path, vault_root="/tmp/Bifrost", mount_src="")
        == "RECREATED"
    )


def test_configured_vault_recreates_when_mount_wrong(tmp_path: Path) -> None:
    assert (
        _run_start_runtime(tmp_path, vault_root="/tmp/Bifrost", mount_src="/tmp/Niflheim")
        == "RECREATED"
    )


def test_configured_vault_warm_skips_when_mount_matches(tmp_path: Path) -> None:
    assert (
        _run_start_runtime(tmp_path, vault_root="/tmp/Bifrost", mount_src="/tmp/Bifrost")
        == "SKIPPED"
    )
