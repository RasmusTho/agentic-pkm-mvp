from pathlib import Path
import json

from click.testing import CliRunner

from app.cli import cli
from app.cli.uat import DEFAULT_FOLDER_NAME, DEFAULT_TARGET_SUBDIR
from app.store.object_store import ObjectStore
from app.store import object_store as object_store_module


PROMOTE_UUID = "11111111-1111-4111-8111-111111111111"


def _env(tmp_path: Path) -> dict[str, str]:
    return {
        "STORE_BACKEND": "memory",
        "INDEX_OUTBOX_PATH": str(tmp_path / "outbox.jsonl"),
        "WATCHER_AUTO_EXEC": "1",
    }


def test_uat_run_cli_end_to_end(tmp_path: Path) -> None:
    object_store_module._MEMORY_STORE.clear()
    runner = CliRunner()
    env = _env(tmp_path)

    seed_result = runner.invoke(
        cli,
        [
            "uat-seed-vault-test",
            "--vault-root",
            str(tmp_path),
        ],
        env=env,
    )
    assert seed_result.exit_code == 0, seed_result.output

    run_result = runner.invoke(
        cli,
        [
            "uat-run-vault-test",
            "--vault-root",
            str(tmp_path),
            "--assert",
        ],
        env=env,
    )
    assert run_result.exit_code == 0, run_result.output

    # ensure promotion applied
    store = ObjectStore()
    promoted = store.get_object(PROMOTE_UUID)
    assert promoted is not None
    assert (promoted.payload or {}).get("review_state")

    # manual/never note should remain skipped by policy
    summary_path = tmp_path / DEFAULT_TARGET_SUBDIR / DEFAULT_FOLDER_NAME / ".agentic-pkm" / "vault_watcher_uat_state.json"
    assert summary_path.exists()
    report_path = tmp_path / DEFAULT_TARGET_SUBDIR / DEFAULT_FOLDER_NAME / ".agentic-pkm" / "uat_report.json"
    assert report_path.exists()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    checks = report.get("checks") or {}
    assert checks
    assert all(bool(value) for value in checks.values())
    assert report.get("rerun", {}).get("watcher", {}).get("changed") == 0
    assert report.get("rerun", {}).get("promotion", {}).get("applied") == 0

    object_store_module._MEMORY_STORE.clear()
