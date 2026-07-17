import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
import pytest
import yaml

from app.cli import cli
from app.cli import uat as uat_module
from app.cli.uat import DEFAULT_FOLDER_NAME, DEFAULT_TARGET_SUBDIR
from app import objects as object_store_module
from app.receipts.settings_write import (
    ReceiptDurabilityUncertainError,
    emit_settings_write_receipt,
)


def _uat_transaction_marker(vault_root: Path) -> Path:
    return (
        vault_root
        / ".agentic-pkm"
        / "uat-settings-transactions"
        / "ingest-override.json"
    )


def test_uat_seed_cli_copies_notes(tmp_path: Path) -> None:
    runner = CliRunner()
    env = {"STORE_BACKEND": "memory"}

    result = runner.invoke(
        cli,
        [
            "uat-seed-vault-test",
            "--vault-root",
            str(tmp_path),
        ],
        env=env,
    )
    assert result.exit_code == 0, result.output

    dest = tmp_path / DEFAULT_TARGET_SUBDIR / DEFAULT_FOLDER_NAME
    files = sorted(dest.glob("*.md"))
    assert files, "expected seed files to be copied"

    target = dest / "evergreen-strategy.md"
    original = target.read_text(encoding="utf-8")

    target.write_text("changed", encoding="utf-8")
    result_no_overwrite = runner.invoke(
        cli,
        [
            "uat-seed-vault-test",
            "--vault-root",
            str(tmp_path),
        ],
        env=env,
    )
    assert result_no_overwrite.exit_code == 0, result_no_overwrite.output
    assert target.read_text(encoding="utf-8") == "changed"

    result_overwrite = runner.invoke(
        cli,
        [
            "uat-seed-vault-test",
            "--vault-root",
            str(tmp_path),
            "--overwrite",
        ],
        env=env,
    )
    assert result_overwrite.exit_code == 0, result_overwrite.output
    assert target.read_text(encoding="utf-8") == original

    object_store_module._MEMORY_STORE.clear()


def test_uat_seed_cli_extends_ingest_scope_with_test_folder(tmp_path: Path) -> None:
    runner = CliRunner()
    env = {"STORE_BACKEND": "memory"}

    result = runner.invoke(
        cli,
        [
            "uat-seed-vault-test",
            "--vault-root",
            str(tmp_path),
        ],
        env=env,
    )
    assert result.exit_code == 0, result.output

    override_path = tmp_path / "settings" / "ingest.override.md"
    assert override_path.exists()
    assert not (tmp_path / "⚙️ System" / "settings" / "ingest.override.md").exists()

    raw = override_path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    payload = yaml.safe_load(parts[1])
    assert payload["include_folders"] == [DEFAULT_TARGET_SUBDIR]


def test_uat_seed_reads_legacy_override_but_writes_only_canonical(tmp_path: Path) -> None:
    legacy = tmp_path / "Meta" / "settings" / "ingest.override.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        "---\ninclude_folders:\n  - Existing\n---\n",
        encoding="utf-8",
    )
    layout = tmp_path / "Meta" / "vault.layout.md"
    layout.write_text(
        "---\nsystem_folder: Meta\ninbox_folder: Inbox\ndesk_folder: Desk\n---\n",
        encoding="utf-8",
    )
    original_legacy = legacy.read_text(encoding="utf-8")
    runner = CliRunner()

    with patch(
        "app.cli.uat.emit_settings_write_receipt",
        wraps=emit_settings_write_receipt,
    ) as emit_receipt:
        result = runner.invoke(
            cli,
            ["uat-seed-vault-test", "--vault-root", str(tmp_path)],
            env={
                "STORE_BACKEND": "memory",
                "INDEX_OUTBOX_PATH": str(tmp_path / "outbox.jsonl"),
            },
        )

    assert result.exit_code == 0, result.output
    canonical = tmp_path / "settings" / "ingest.override.md"
    payload = yaml.safe_load(canonical.read_text(encoding="utf-8").split("---", 2)[1])
    assert payload["include_folders"] == ["Existing", DEFAULT_TARGET_SUBDIR]
    assert legacy.read_text(encoding="utf-8") == original_legacy
    emit_receipt.assert_called_once()
    receipt = emit_receipt.call_args.args[0]
    assert receipt.file == str(canonical)
    assert receipt.operation_id
    assert emit_receipt.call_args.kwargs["require_durable"] is True


def test_uat_seed_canonical_override_shadows_legacy(tmp_path: Path) -> None:
    legacy = tmp_path / "Meta" / "settings" / "ingest.override.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("---\ninclude_folders: [Legacy]\n---\n", encoding="utf-8")
    (tmp_path / "Meta" / "vault.layout.md").write_text(
        "---\nsystem_folder: Meta\ninbox_folder: Inbox\ndesk_folder: Desk\n---\n",
        encoding="utf-8",
    )
    canonical = tmp_path / "settings" / "ingest.override.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("---\ninclude_folders: [Canonical]\n---\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        ["uat-seed-vault-test", "--vault-root", str(tmp_path)],
        env={"STORE_BACKEND": "memory"},
    )

    assert result.exit_code == 0, result.output
    payload = yaml.safe_load(canonical.read_text(encoding="utf-8").split("---", 2)[1])
    assert payload["include_folders"] == ["Canonical", DEFAULT_TARGET_SUBDIR]
    assert "Legacy" not in payload["include_folders"]


def test_uat_seed_idempotent_canonical_rerun_does_not_rewrite(tmp_path: Path) -> None:
    runner = CliRunner()
    env = {
        "STORE_BACKEND": "memory",
        "INDEX_OUTBOX_PATH": str(tmp_path / "outbox.jsonl"),
    }
    first = runner.invoke(
        cli, ["uat-seed-vault-test", "--vault-root", str(tmp_path)], env=env
    )
    assert first.exit_code == 0, first.output
    canonical = tmp_path / "settings" / "ingest.override.md"
    first_mtime = canonical.stat().st_mtime_ns
    outbox = tmp_path / "outbox.jsonl"
    first_receipts = outbox.read_text(encoding="utf-8").splitlines()

    second = runner.invoke(
        cli, ["uat-seed-vault-test", "--vault-root", str(tmp_path)], env=env
    )

    assert second.exit_code == 0, second.output
    assert canonical.stat().st_mtime_ns == first_mtime
    assert outbox.read_text(encoding="utf-8").splitlines() == first_receipts


def test_uat_seed_legacy_only_materialization_is_durably_receipted(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "Meta" / "settings" / "ingest.override.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("---\ninclude_folders: [Test]\n---\n", encoding="utf-8")
    (tmp_path / "Meta" / "vault.layout.md").write_text(
        "---\nsystem_folder: Meta\ninbox_folder: Inbox\ndesk_folder: Desk\n---\n",
        encoding="utf-8",
    )
    outbox = tmp_path / "outbox.jsonl"

    result = CliRunner().invoke(
        cli,
        ["uat-seed-vault-test", "--vault-root", str(tmp_path)],
        env={"STORE_BACKEND": "memory", "INDEX_OUTBOX_PATH": str(outbox)},
    )

    assert result.exit_code == 0, result.output
    records = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines()]
    receipt = next(
        record
        for record in records
        if record.get("payload", {}).get("key")
        == "ingest.override.__materialization__"
    )
    assert receipt["payload"]["old_value"] == str(legacy)
    assert receipt["payload"]["new_value"] == str(
        tmp_path / "settings" / "ingest.override.md"
    )


def test_uat_seed_receipt_failure_persists_pending_journal_without_rollback(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "settings" / "ingest.override.md"
    marker = _uat_transaction_marker(tmp_path)
    publication_observed = False

    def fail_after_publication(*_args, **_kwargs):
        nonlocal publication_observed
        publication_observed = canonical.exists()
        assert canonical.exists()
        raise RuntimeError("receipt unavailable")

    with patch(
        "app.cli.uat.emit_settings_write_receipt",
        side_effect=fail_after_publication,
    ):
        result = CliRunner().invoke(
            cli,
            ["uat-seed-vault-test", "--vault-root", str(tmp_path)],
            env={"STORE_BACKEND": "memory"},
        )

    assert result.exit_code != 0
    assert publication_observed
    assert canonical.exists()
    transaction = json.loads(marker.read_text(encoding="utf-8"))
    assert transaction["state"] == "published_receipt_pending"
    assert Path(transaction["target"]) == canonical


def test_uat_seed_replace_failure_emits_no_receipt_and_preserves_canonical(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "settings" / "ingest.override.md"
    canonical.parent.mkdir(parents=True)
    original = b"---\ninclude_folders: [Existing]\n---\n\noriginal bytes\n"
    canonical.write_bytes(original)
    real_replace = uat_module.os.replace

    def fail_publication(source, target):
        if Path(target) == canonical:
            raise OSError("replace failed")
        return real_replace(source, target)

    with (
        patch("app.cli.uat.os.replace", side_effect=fail_publication),
        patch("app.cli.uat.emit_settings_write_receipt") as emit_receipt,
    ):
        result = CliRunner().invoke(
            cli,
            ["uat-seed-vault-test", "--vault-root", str(tmp_path)],
            env={"STORE_BACKEND": "memory"},
        )

    assert result.exit_code != 0
    assert canonical.read_bytes() == original
    emit_receipt.assert_not_called()
    assert not _uat_transaction_marker(tmp_path).exists()


def test_uat_seed_rerun_reconciles_pending_receipt_once_without_canonical_write(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "settings" / "ingest.override.md"
    canonical.parent.mkdir(parents=True)
    original = b"---\r\ninclude_folders: [Existing]\r\n---\r\n\r\nexact old bytes\r\n"
    canonical.write_bytes(original)
    outbox = tmp_path / "outbox.jsonl"
    env = {"STORE_BACKEND": "memory", "INDEX_OUTBOX_PATH": str(outbox)}

    def fail_after_publication(*_args, **_kwargs):
        assert canonical.read_bytes() != original
        raise RuntimeError("receipt unavailable")

    with patch(
        "app.cli.uat.emit_settings_write_receipt",
        side_effect=fail_after_publication,
    ):
        first = CliRunner().invoke(
            cli,
            ["uat-seed-vault-test", "--vault-root", str(tmp_path)],
            env=env,
        )

    assert first.exit_code != 0
    published = canonical.read_bytes()
    published_mtime = canonical.stat().st_mtime_ns

    with patch(
        "app.cli.uat._write_ingest_override", wraps=uat_module._write_ingest_override
    ) as write_override:
        second = CliRunner().invoke(
            cli,
            ["uat-seed-vault-test", "--vault-root", str(tmp_path)],
            env=env,
        )

    assert second.exit_code == 0, second.output
    write_override.assert_not_called()
    assert canonical.read_bytes() == published
    assert canonical.stat().st_mtime_ns == published_mtime
    records = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines()]
    operation_ids = [
        record["payload"]["operation_id"]
        for record in records
        if record.get("payload", {}).get("operation_id")
    ]
    assert len(operation_ids) == 1
    assert not _uat_transaction_marker(tmp_path).exists()


def test_uat_seed_recovers_publication_crash_before_pending_marker_without_rewrite(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "settings" / "ingest.override.md"
    outbox = tmp_path / "outbox.jsonl"
    real_write_marker = uat_module._write_transaction_marker
    crashed = False

    def crash_before_pending_marker(marker, transaction):
        nonlocal crashed
        if transaction["state"] == "published_receipt_pending" and not crashed:
            crashed = True
            raise SystemExit("simulated power loss")
        real_write_marker(marker, transaction)

    with (
        patch(
            "app.cli.uat._write_transaction_marker",
            side_effect=crash_before_pending_marker,
        ),
        pytest.raises(SystemExit, match="simulated power loss"),
    ):
        uat_module._write_ingest_override(
            canonical,
            {"include_folders": [DEFAULT_TARGET_SUBDIR]},
            previous={},
            source_path=canonical,
        )

    published = canonical.read_bytes()
    published_mtime = canonical.stat().st_mtime_ns
    transaction = json.loads(
        _uat_transaction_marker(tmp_path).read_text(encoding="utf-8")
    )
    assert transaction["state"] == "prepared"
    transaction_dir = _uat_transaction_marker(tmp_path).parent
    assert not (transaction_dir / transaction["stage"]).exists()
    assert (transaction_dir / transaction["witness"]).exists()

    recovered = CliRunner().invoke(
        cli,
        ["uat-seed-vault-test", "--vault-root", str(tmp_path)],
        env={"STORE_BACKEND": "memory", "INDEX_OUTBOX_PATH": str(outbox)},
    )

    assert recovered.exit_code == 0, recovered.output
    assert canonical.read_bytes() == published
    assert canonical.stat().st_mtime_ns == published_mtime
    assert not _uat_transaction_marker(tmp_path).exists()


def test_uat_seed_discards_unpublished_prepared_stage_after_crash(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "settings" / "ingest.override.md"

    with (
        patch(
            "app.cli.uat._atomic_rename_noreplace",
            side_effect=SystemExit("simulated power loss"),
        ),
        pytest.raises(SystemExit, match="simulated power loss"),
    ):
        uat_module._write_ingest_override(
            canonical,
            {"include_folders": [DEFAULT_TARGET_SUBDIR]},
            previous={},
            source_path=canonical,
        )

    transaction = json.loads(
        _uat_transaction_marker(tmp_path).read_text(encoding="utf-8")
    )
    transaction_dir = _uat_transaction_marker(tmp_path).parent
    assert transaction["state"] == "prepared"
    assert (transaction_dir / transaction["stage"]).exists()
    assert not canonical.exists()

    recovered = CliRunner().invoke(
        cli,
        ["uat-seed-vault-test", "--vault-root", str(tmp_path)],
        env={
            "STORE_BACKEND": "memory",
            "INDEX_OUTBOX_PATH": str(tmp_path / "outbox.jsonl"),
        },
    )

    assert recovered.exit_code == 0, recovered.output
    assert canonical.exists()
    assert not _uat_transaction_marker(tmp_path).exists()


def test_uat_seed_receipt_durability_uncertainty_reconciles_visible_receipt(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "settings" / "ingest.override.md"
    canonical.parent.mkdir(parents=True)
    original = b"---\ninclude_folders: [Existing]\n---\n\noriginal bytes\n"
    canonical.write_bytes(original)
    outbox = tmp_path / "outbox.jsonl"

    def write_then_report_uncertain(receipt, *, require_durable):
        emit_settings_write_receipt(receipt, require_durable=require_durable)
        raise ReceiptDurabilityUncertainError("parent fsync failed")

    with patch(
        "app.cli.uat.emit_settings_write_receipt",
        side_effect=write_then_report_uncertain,
    ):
        result = CliRunner().invoke(
            cli,
            ["uat-seed-vault-test", "--vault-root", str(tmp_path)],
            env={"STORE_BACKEND": "memory", "INDEX_OUTBOX_PATH": str(outbox)},
        )

    assert result.exit_code == 0, result.output
    assert canonical.read_bytes() != original
    payload = yaml.safe_load(canonical.read_text(encoding="utf-8").split("---", 2)[1])
    assert payload["include_folders"] == ["Existing", DEFAULT_TARGET_SUBDIR]
    records = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines()]
    assert len([record for record in records if record["payload"].get("operation_id")]) == 1
    assert not _uat_transaction_marker(tmp_path).exists()


def test_uat_seed_receipt_failure_preserves_concurrent_existing_canonical_write(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "settings" / "ingest.override.md"
    canonical.parent.mkdir(parents=True)
    original = b"---\ninclude_folders: [Existing]\n---\n\noriginal bytes\n"
    concurrent = b"---\ninclude_folders: [Concurrent]\n---\n\nconcurrent bytes\n"
    canonical.write_bytes(original)

    def replace_then_fail(*_args, **_kwargs):
        canonical.write_bytes(concurrent)
        raise RuntimeError("receipt unavailable")

    with patch(
        "app.cli.uat.emit_settings_write_receipt",
        side_effect=replace_then_fail,
    ):
        first = CliRunner().invoke(
            cli,
            ["uat-seed-vault-test", "--vault-root", str(tmp_path)],
            env={
                "STORE_BACKEND": "memory",
                "INDEX_OUTBOX_PATH": str(tmp_path / "outbox.jsonl"),
            },
        )

    assert first.exit_code != 0
    assert canonical.read_bytes() == concurrent

    second = CliRunner().invoke(
        cli,
        ["uat-seed-vault-test", "--vault-root", str(tmp_path)],
        env={
            "STORE_BACKEND": "memory",
            "INDEX_OUTBOX_PATH": str(tmp_path / "outbox.jsonl"),
        },
    )
    assert second.exit_code == 0, second.output
    assert canonical.read_bytes() == concurrent
    assert not _uat_transaction_marker(tmp_path).exists()


def test_uat_seed_receipt_failure_preserves_concurrent_new_canonical_write(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "settings" / "ingest.override.md"
    concurrent = b"---\ninclude_folders: [Concurrent]\n---\n\nconcurrent bytes\n"

    def concurrent_create_then_fail(_source, _target):
        canonical.write_bytes(concurrent)
        raise FileExistsError("concurrent creator won")

    with (
        patch(
            "app.cli.uat._atomic_rename_noreplace",
            side_effect=concurrent_create_then_fail,
        ),
        patch("app.cli.uat.emit_settings_write_receipt") as emit_receipt,
    ):
        result = CliRunner().invoke(
            cli,
            ["uat-seed-vault-test", "--vault-root", str(tmp_path)],
            env={"STORE_BACKEND": "memory"},
        )

    assert result.exit_code != 0
    assert canonical.read_bytes() == concurrent
    emit_receipt.assert_not_called()
    assert not _uat_transaction_marker(tmp_path).exists()
