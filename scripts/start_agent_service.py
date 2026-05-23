from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path
from threading import Event

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "app" / "alembic.ini"
AGENT_LOG_PATH = Path("/tmp/agent_app.log")
DEFAULT_MIGRATION_TIMEOUT = 180  # seconds
RESTART_DELAY_SECONDS = 30

logger = logging.getLogger("agent.service.runner")
stop_event = Event()
DRY_RUN = False


def load_environment() -> None:
    """
    Load variables from .env if python-dotenv is available.
    Missing module should not be treated as an error.
    """
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        logger.info("No .env file found at %s; relying on existing environment.", env_path)
        return
    try:
        from dotenv import load_dotenv  # type: ignore

        loaded = load_dotenv(env_path)
        if loaded:
            logger.info("Environment loaded from %s", env_path)
        else:
            logger.info("dotenv.load_dotenv returned False for %s (variables may already be set).", env_path)
    except ModuleNotFoundError:
        logger.info("python-dotenv not installed; skipping .env load.")


def mask_dsn(dsn: str) -> str:
    if "@" not in dsn or "://" not in dsn:
        return dsn
    prefix, rest = dsn.split("://", 1)
    if "@" not in rest:
        return f"{prefix}://***@"
    credentials, host_part = rest.split("@", 1)
    if ":" in credentials:
        user, _ = credentials.split(":", 1)
        masked_credentials = f"{user}:***"
    else:
        masked_credentials = "***"
    return f"{prefix}://{masked_credentials}@{host_part}"


def get_database_dsn() -> str | None:
    dsn = os.environ.get("DB_DSN") or os.environ.get("DATABASE_URL")
    if dsn:
        logger.info("Database DSN detected: %s", mask_dsn(dsn))
    else:
        logger.warning("No DB_DSN or DATABASE_URL found in environment.")
    return dsn


def run_command(
    cmd: list[str],
    *,
    capture_output: bool = True,
    timeout: int | None = None,
    check: bool = True,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    Wrapper around subprocess.run that respects the DRY_RUN flag.
    """
    cwd = cwd or REPO_ROOT
    logger.debug("Executing command: %s (cwd=%s, timeout=%s)", " ".join(cmd), cwd, timeout)

    if DRY_RUN:
        logger.info("[dry-run] Would execute: %s", " ".join(cmd))
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            check=check,
            capture_output=capture_output,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
        )
        return result
    except subprocess.TimeoutExpired as exc:
        logger.error("Command timed out after %ss: %s", exc.timeout, " ".join(cmd))
        raise
    except subprocess.CalledProcessError as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        logger.error(
            "Command failed with exit code %s: %s\nstdout:\n%s\nstderr:\n%s",
            exc.returncode,
            " ".join(cmd),
            stdout.strip(),
            stderr.strip(),
        )
        raise


def alembic_at_head() -> bool:
    cmd = ["alembic", "-c", str(ALEMBIC_INI), "current"]
    try:
        result = run_command(cmd, timeout=30)
    except subprocess.CalledProcessError:
        return False

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if stdout:
        logger.info("Alembic current output:\n%s", stdout)
    if stderr:
        logger.info("Alembic current stderr:\n%s", stderr)
    return "(head)" in stdout


def migrate_if_needed() -> None:
    if alembic_at_head():
        logger.info("Detected Alembic at HEAD — skipping migrations.")
        return

    logger.info("Running Alembic upgrade head…")
    cmd = ["alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"]
    run_command(cmd, timeout=DEFAULT_MIGRATION_TIMEOUT)
    logger.info("Alembic upgrade completed.")


def launch_agent_once() -> int:
    # run_agent.py was retired when app/agent was removed in #1171.
    # Update this function to invoke the replacement runner before using this script.
    raise RuntimeError(
        "start_agent_service.py still references the retired run_agent.py entry point "
        "(removed in #1171). Update launch_agent_once() to use the replacement runner "
        "before invoking this script."
    )


def agent_loop() -> None:
    logger.info("Starting agent loop…")
    while not stop_event.is_set():
        exit_code = launch_agent_once()
        if stop_event.is_set():
            logger.info("Stop event set; exiting agent loop.")
            break
        logger.info("Agent exited with code %s — restarting in %ss", exit_code, RESTART_DELAY_SECONDS)
        if stop_event.wait(RESTART_DELAY_SECONDS):
            logger.info("Stop event set during restart delay; exiting agent loop.")
            break


def handle_signal(signum: int, frame: object | None) -> None:
    logger.info("Received signal %s; initiating shutdown.", signum)
    stop_event.set()


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the agent service with supervised agent loop.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without executing.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    global DRY_RUN

    args = parse_args(argv or [])
    DRY_RUN = args.dry_run

    configure_logging(args.verbose)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    logger.info("Starting agent service runner (dry-run=%s)", DRY_RUN)
    load_environment()
    get_database_dsn()

    try:
        migrate_if_needed()
    except subprocess.CalledProcessError:
        logger.error("Migration step failed; exiting with error.")
        return 1
    except subprocess.TimeoutExpired:
        logger.error("Migration step timed out; exiting with error.")
        return 1

    if DRY_RUN:
        logger.info("[dry-run] Agent loop skipped; exiting.")
        return 0

    agent_loop()
    logger.info("Agent service runner exiting cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
