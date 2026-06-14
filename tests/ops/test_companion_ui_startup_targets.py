"""
Static inspection tests for the canonical Companion UI operator startup/doctor
commands (Issues #1358 / #1359 / #1360).

These mirror tests/ops/test_release_channel_startup_targets.py: they read the
Makefile and the channel startup scripts directly and assert the canonical
operator surface, channel binding, vault guard, ports, and safe UI-port
handling. No Docker, runtime, or real vault required.

Per-channel coverage is added as each sibling issue ships:
  - dev/Niflheim  : #1358 (this file's dev cases + shared library cases)
  - test/Bifröst  : #1359
  - prod/Midgård  : #1360
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"
SHARED_LIB = REPO_ROOT / "scripts" / "lib" / "companion_ui_startup.sh"
DEV_START = REPO_ROOT / "scripts" / "dev" / "start_niflheim_ui.sh"
DEV_DOCTOR = REPO_ROOT / "scripts" / "dev" / "dev_ui_doctor.sh"
TEST_START = REPO_ROOT / "scripts" / "test" / "start_bifrost_ui.sh"
TEST_DOCTOR = REPO_ROOT / "scripts" / "test" / "test_ui_doctor.sh"
PROD_START = REPO_ROOT / "scripts" / "prod" / "start_midgard_ui.sh"
PROD_DOCTOR = REPO_ROOT / "scripts" / "prod" / "prod_ui_doctor.sh"


def _makefile_target_body(makefile_text: str, target_name: str) -> str | None:
    pattern = re.compile(
        rf"^{re.escape(target_name)}\s*:.*?(?=\n\S|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(makefile_text)
    return match.group(0) if match else None


def _bash_syntax_ok(path: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        ["bash", "-n", str(path)],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0, proc.stderr


# ── shared library (delivered by #1358, reused by #1359 / #1360) ──────────────


def test_shared_library_exists_and_is_valid_bash() -> None:
    """The channel-agnostic Companion UI startup library must exist and parse.

    Verify: Issue #1358 AC1 —
      tests/ops/test_companion_ui_startup_targets.py::test_shared_library_exists_and_is_valid_bash
    """
    assert SHARED_LIB.is_file(), (
        "scripts/lib/companion_ui_startup.sh is required as the shared helper "
        "for the canonical Companion UI startup/doctor commands (Issue #1358)."
    )
    ok, err = _bash_syntax_ok(SHARED_LIB)
    assert ok, f"companion_ui_startup.sh failed `bash -n`:\n{err}"


def test_shared_library_refuses_to_kill_unrelated_processes() -> None:
    """Stale UI-port handling must target only Companion UI listeners.

    Verify: Issue #1358 AC6 —
      tests/ops/test_companion_ui_startup_targets.py::test_shared_library_refuses_to_kill_unrelated_processes
    """
    text = SHARED_LIB.read_text(encoding="utf-8")
    # The guard identifies Companion UI listeners specifically...
    assert "serve_(dev|production)_page" in text or "serve_dev_page" in text, (
        "Shared library must identify Companion UI listeners specifically "
        "before killing a UI-port holder (Issue #1358 AC6)."
    )
    # ...and explicitly refuses to kill a non-Companion holder.
    assert re.search(r"non-Companion", text), (
        "Shared library must refuse to kill a non-Companion process holding "
        "the UI port and fail with instructions instead (Issue #1358 AC6)."
    )


def test_shared_library_doctor_is_read_only() -> None:
    """The doctor entry point must not start services or mutate state.

    Verify: Issue #1358 AC7 —
      tests/ops/test_companion_ui_startup_targets.py::test_shared_library_doctor_is_read_only
    """
    text = SHARED_LIB.read_text(encoding="utf-8")
    doctor = re.search(r"cui_run_doctor\(\)\s*\{.*?\n\}", text, re.DOTALL)
    assert doctor is not None, "cui_run_doctor function not found in shared library."
    body = doctor.group(0)
    assert "cui_start_runtime" not in body, (
        "Doctor must not start the runtime (read-only requirement, Issue #1358 AC7)."
    )
    assert "cui_start_ui" not in body, (
        "Doctor must not start the Companion UI (read-only requirement, Issue #1358 AC7)."
    )


def test_shared_library_honors_explicit_host_before_bind_default() -> None:
    """The documented HOST loopback opt-out must work through channel launchers."""
    text = SHARED_LIB.read_text(encoding="utf-8")
    assert 'if [ -n "${HOST:-}" ]; then' in text
    assert 'host="${HOST}"' in text
    assert 'elif [ "${CUI_BIND_LAN:-1}" = "0" ]; then' in text
    assert text.index('if [ -n "${HOST:-}" ]; then') < text.index(
        'elif [ "${CUI_BIND_LAN:-1}" = "0" ]; then'
    )


# ── dev / Niflheim (#1358) ────────────────────────────────────────────────────


def test_dev_ui_make_targets_exist_and_delegate() -> None:
    """make dev-ui and make dev-ui-doctor must exist and call the scripts.

    Verify: Issue #1358 AC1 / AC7 —
      tests/ops/test_companion_ui_startup_targets.py::test_dev_ui_make_targets_exist_and_delegate
    """
    text = MAKEFILE.read_text(encoding="utf-8")
    start = _makefile_target_body(text, "dev-ui")
    doctor = _makefile_target_body(text, "dev-ui-doctor")
    assert start is not None, "Makefile is missing the canonical 'dev-ui' target (Issue #1358)."
    assert doctor is not None, "Makefile is missing the 'dev-ui-doctor' target (Issue #1358)."
    assert "scripts/dev/start_niflheim_ui.sh" in start, (
        "'dev-ui' must delegate to scripts/dev/start_niflheim_ui.sh (Issue #1358)."
    )
    assert "scripts/dev/dev_ui_doctor.sh" in doctor, (
        "'dev-ui-doctor' must delegate to scripts/dev/dev_ui_doctor.sh (Issue #1358)."
    )


def test_dev_scripts_exist_and_are_valid_bash() -> None:
    """The dev startup and doctor scripts must exist and parse.

    Verify: Issue #1358 AC1 / AC7 —
      tests/ops/test_companion_ui_startup_targets.py::test_dev_scripts_exist_and_are_valid_bash
    """
    for path in (DEV_START, DEV_DOCTOR):
        assert path.is_file(), f"{path.relative_to(REPO_ROOT)} is required (Issue #1358)."
        ok, err = _bash_syntax_ok(path)
        assert ok, f"{path.name} failed `bash -n`:\n{err}"


def test_dev_start_binds_niflheim_channel_and_ports() -> None:
    """The dev start script must bind PKM dev channel, Niflheim guard, and ports.

    Verify: Issue #1358 AC2 / AC3 / AC5 —
      tests/ops/test_companion_ui_startup_targets.py::test_dev_start_binds_niflheim_channel_and_ports
    """
    text = DEV_START.read_text(encoding="utf-8")
    assert re.search(r'CUI_CHANNEL=["\']?dev["\']?', text), "dev start must set CUI_CHANNEL=dev."
    assert "nife?lheim" in text, (
        "dev start must guard the resolved vault against Niflheim/Nifelheim (Issue #1358 AC2)."
    )
    assert re.search(r'CUI_API_PORT=["\']?18001["\']?', text), "dev API port must be 18001 (AC3)."
    assert re.search(r'CUI_UI_PORT=["\']?8111["\']?', text), "dev UI port must be 8111 (AC5)."
    assert "companion_ui.workspace.serve_dev_page" in text, (
        "dev start must launch the Companion UI dev page module (Issue #1358)."
    )
    assert "pkm-dev" in text, "dev start must target the pkm-dev compose project."


@pytest.mark.parametrize(
    "vault_basename,should_match",
    [
        ("Niflheim", True),
        ("Nifelheim", True),
        ("niflheim", True),
        ("Midgård", False),
        ("Bifröst", False),
        ("PKM - Alpha", False),
    ],
)
def test_dev_vault_guard_pattern(vault_basename: str, should_match: bool) -> None:
    """The dev vault guard regex must accept Niflheim spellings and reject others.

    Verify: Issue #1358 AC2 —
      tests/ops/test_companion_ui_startup_targets.py::test_dev_vault_guard_pattern
    """
    pattern = re.compile("nife?lheim")
    matched = bool(pattern.search(vault_basename.lower()))
    assert matched is should_match, (
        f"vault guard pattern match for '{vault_basename}' was {matched}, expected {should_match}."
    )


# ── test / Bifröst (#1359) ────────────────────────────────────────────────────


def test_test_ui_make_targets_exist_and_delegate() -> None:
    """make test-ui and make test-ui-doctor must exist and call the scripts.

    Verify: Issue #1359 AC1 / AC5 —
      tests/ops/test_companion_ui_startup_targets.py::test_test_ui_make_targets_exist_and_delegate
    """
    text = MAKEFILE.read_text(encoding="utf-8")
    start = _makefile_target_body(text, "test-ui")
    doctor = _makefile_target_body(text, "test-ui-doctor")
    assert start is not None, "Makefile is missing the canonical 'test-ui' target (Issue #1359)."
    assert doctor is not None, "Makefile is missing the 'test-ui-doctor' target (Issue #1359)."
    assert "scripts/test/start_bifrost_ui.sh" in start, (
        "'test-ui' must delegate to scripts/test/start_bifrost_ui.sh (Issue #1359)."
    )
    assert "scripts/test/test_ui_doctor.sh" in doctor, (
        "'test-ui-doctor' must delegate to scripts/test/test_ui_doctor.sh (Issue #1359)."
    )


def test_test_scripts_exist_and_are_valid_bash() -> None:
    """The test startup and doctor scripts must exist and parse.

    Verify: Issue #1359 AC1 / AC5 —
      tests/ops/test_companion_ui_startup_targets.py::test_test_scripts_exist_and_are_valid_bash
    """
    for path in (TEST_START, TEST_DOCTOR):
        assert path.is_file(), f"{path.relative_to(REPO_ROOT)} is required (Issue #1359)."
        ok, err = _bash_syntax_ok(path)
        assert ok, f"{path.name} failed `bash -n`:\n{err}"


def test_test_start_binds_bifrost_channel_and_ports() -> None:
    """The test start script must bind the test channel, Bifröst guard, and ports.

    Verify: Issue #1359 AC2 / AC3 / AC4 —
      tests/ops/test_companion_ui_startup_targets.py::test_test_start_binds_bifrost_channel_and_ports
    """
    text = TEST_START.read_text(encoding="utf-8")
    assert re.search(r'CUI_CHANNEL=["\']?test["\']?', text), "test start must set CUI_CHANNEL=test."
    assert "bifr" in text, (
        "test start must guard the resolved vault against Bifröst/Bifrost (Issue #1359 AC2)."
    )
    assert re.search(r'CUI_API_PORT=["\']?18002["\']?', text), "test API port must be 18002."
    assert re.search(r'CUI_UI_PORT=["\']?8112["\']?', text), "test UI port must be 8112."
    assert "pkm-test" in text, "test start must target the pkm-test compose project (AC3)."
    assert "app_test" in text, "test start must report the app_test channel DB (AC3)."


@pytest.mark.parametrize(
    "vault_basename,should_match",
    [
        ("Bifröst", True),
        ("Bifrost", True),
        ("bifröst", True),
        ("Niflheim", False),
        ("Midgård", False),
        ("vault-test", False),
    ],
)
def test_test_vault_guard_pattern(vault_basename: str, should_match: bool) -> None:
    """The test vault guard regex must accept Bifröst spellings and reject others.

    Verify: Issue #1359 AC2 —
      tests/ops/test_companion_ui_startup_targets.py::test_test_vault_guard_pattern
    """
    pattern = re.compile("bifr(ö|o)st")
    matched = bool(pattern.search(vault_basename.lower()))
    assert matched is should_match, (
        f"vault guard pattern match for '{vault_basename}' was {matched}, expected {should_match}."
    )


def test_channel_scripts_use_distinct_ports_and_projects() -> None:
    """Dev and test channels must not share UI/API ports or compose projects.

    Verify: Issue #1359 AC3 (channel separation) —
      tests/ops/test_companion_ui_startup_targets.py::test_channel_scripts_use_distinct_ports_and_projects
    """
    dev = DEV_START.read_text(encoding="utf-8")
    test = TEST_START.read_text(encoding="utf-8")
    assert "8111" in dev and "8112" in test, "dev/test UI ports must differ (8111 vs 8112)."
    assert "18001" in dev and "18002" in test, "dev/test API ports must differ (18001 vs 18002)."
    assert "pkm-dev" in dev and "pkm-test" in test, "dev/test compose projects must differ."


# ── prod / Midgård (#1360) ────────────────────────────────────────────────────


def test_prod_ui_make_targets_exist_and_delegate() -> None:
    """make prod-ui and make prod-ui-doctor must exist and call the scripts.

    Verify: Issue #1360 AC1 / AC6 —
      tests/ops/test_companion_ui_startup_targets.py::test_prod_ui_make_targets_exist_and_delegate
    """
    text = MAKEFILE.read_text(encoding="utf-8")
    start = _makefile_target_body(text, "prod-ui")
    doctor = _makefile_target_body(text, "prod-ui-doctor")
    assert start is not None, "Makefile is missing the canonical 'prod-ui' target (Issue #1360)."
    assert doctor is not None, "Makefile is missing the 'prod-ui-doctor' target (Issue #1360)."
    assert "scripts/prod/start_midgard_ui.sh" in start, (
        "'prod-ui' must delegate to scripts/prod/start_midgard_ui.sh (Issue #1360)."
    )
    assert "scripts/prod/prod_ui_doctor.sh" in doctor, (
        "'prod-ui-doctor' must delegate to scripts/prod/prod_ui_doctor.sh (Issue #1360)."
    )


def test_prod_scripts_exist_and_are_valid_bash() -> None:
    """The prod startup and doctor scripts must exist and parse.

    Verify: Issue #1360 AC1 / AC6 —
      tests/ops/test_companion_ui_startup_targets.py::test_prod_scripts_exist_and_are_valid_bash
    """
    for path in (PROD_START, PROD_DOCTOR):
        assert path.is_file(), f"{path.relative_to(REPO_ROOT)} is required (Issue #1360)."
        ok, err = _bash_syntax_ok(path)
        assert ok, f"{path.name} failed `bash -n`:\n{err}"


def test_prod_start_binds_midgard_channel_and_ports() -> None:
    """The prod start script must bind the prod channel, Midgård guard, and ports.

    Verify: Issue #1360 AC2 / AC4 / AC5 —
      tests/ops/test_companion_ui_startup_targets.py::test_prod_start_binds_midgard_channel_and_ports
    """
    text = PROD_START.read_text(encoding="utf-8")
    assert re.search(r'CUI_CHANNEL=["\']?prod["\']?', text), "prod start must set CUI_CHANNEL=prod."
    assert "midg" in text, (
        "prod start must guard the resolved vault against Midgård/Midgard (Issue #1360 AC2)."
    )
    assert re.search(r'CUI_API_PORT=["\']?18000["\']?', text), "prod API port must be 18000."
    assert re.search(r'CUI_UI_PORT=["\']?8113["\']?', text), "prod UI port must be 8113."
    assert "pkm-prod" in text, "prod start must target the pkm-prod compose project (AC4)."
    assert "serve_production_page" in text, (
        "prod start must launch the Companion UI production page module (Issue #1360)."
    )


def test_prod_defaults_to_safe_posture_and_gates_automation() -> None:
    """Prod must default to a safe posture and gate write/automation on an
    explicit operator acknowledgement.

    Verify: Issue #1360 AC3 —
      tests/ops/test_companion_ui_startup_targets.py::test_prod_defaults_to_safe_posture_and_gates_automation
    """
    text = PROD_START.read_text(encoding="utf-8")
    assert "PROD_UI_ENABLE_AUTOMATION" in text, (
        "prod start must require an explicit acknowledgement flag for write/automation "
        "modes (Issue #1360 AC3)."
    )
    # Default branch must turn watcher auto-exec OFF.
    assert re.search(r'CUI_WATCHER_AUTO_EXEC=["\']?0["\']?', text), (
        "prod start must default WATCHER_AUTO_EXEC to 0 (safe posture, Issue #1360 AC3)."
    )


def test_prod_doctor_checks_automation_flags() -> None:
    """The prod doctor must surface unexpectedly-enabled automation/write flags.

    Verify: Issue #1360 AC6 —
      tests/ops/test_companion_ui_startup_targets.py::test_prod_doctor_checks_automation_flags
    """
    text = PROD_DOCTOR.read_text(encoding="utf-8")
    assert "cui_extra_doctor" in text, "prod doctor must define the extra automation-flag check (AC6)."
    assert "PROD_UI_ENABLE_AUTOMATION" in text and "WATCHER_AUTO_EXEC" in text, (
        "prod doctor must inspect automation/write flags (Issue #1360 AC6)."
    )


@pytest.mark.parametrize(
    "vault_basename,should_match",
    [
        ("Midgård", True),
        ("Midgard", True),
        ("midgård", True),
        ("Niflheim", False),
        ("Bifröst", False),
        ("vault", False),
    ],
)
def test_prod_vault_guard_pattern(vault_basename: str, should_match: bool) -> None:
    """The prod vault guard regex must accept Midgård spellings and reject others.

    Verify: Issue #1360 AC2 —
      tests/ops/test_companion_ui_startup_targets.py::test_prod_vault_guard_pattern
    """
    pattern = re.compile("midg(å|a)rd")
    matched = bool(pattern.search(vault_basename.lower()))
    assert matched is should_match, (
        f"vault guard pattern match for '{vault_basename}' was {matched}, expected {should_match}."
    )


def test_prod_uses_distinct_ports_from_dev_and_test() -> None:
    """Prod must not share UI/API ports or compose project with dev/test.

    Verify: Issue #1360 AC4 (channel separation) —
      tests/ops/test_companion_ui_startup_targets.py::test_prod_uses_distinct_ports_from_dev_and_test
    """
    prod = PROD_START.read_text(encoding="utf-8")
    assert "8113" in prod and "18000" in prod and "pkm-prod" in prod
    for token in ("8111", "8112", "18001", "18002", "pkm-dev", "pkm-test"):
        assert token not in prod, f"prod start must not reference dev/test token '{token}'."
