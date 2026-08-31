from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "mac_vault_bridge_probe.py"


def _run(root: Path, *paths: str) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(SCRIPT), "--root", str(root)]
    for path in paths:
        command.extend(("--path", path))
    return subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True)


def _report(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    return json.loads(result.stdout)


def _make_vault(root: Path) -> None:
    (root / "settings").mkdir(parents=True)
    (root / "settings" / "vault.md").write_text(
        "---\nvaultId: test-vault\n---\n# marker\n", encoding="utf-8"
    )
    (root / "Notes").mkdir()
    (root / "Notes" / "secret.md").write_bytes(b"private note content\n")


def test_probe_emits_redacted_read_only_report(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _make_vault(vault)

    result = _run(vault, "Notes/secret.md")

    assert result.returncode == 0, result.stderr
    report = _report(result)
    assert report["probe_version"] == "mac-vault-bridge-probe.v1"
    assert report["read_only"] is True
    assert report["root"]["valid"] is True
    assert report["valid_root"]["status"] == "true"
    assert report["marker"]["status"] == "present"
    assert report["platform"]["status"] in {"supported", "unsupported"}
    observation = report["observations"][0]
    assert observation["status"] == "observed"
    assert observation["relative_path"] == "Notes/secret.md"
    assert observation["bytes_read"] == len(b"private note content\n")
    assert observation["filesystem_identity_digest"].startswith("sha256:")
    assert "private note content" not in result.stdout
    assert str(vault) not in result.stdout
    assert observation["content_digest"] == "sha256:" + hashlib.sha256(b"private note content\n").hexdigest()
    assert report["unknown_reasons"]

    large = vault / "large.md"
    large.write_bytes(b"x" * (64 * 1024 + 3))
    bounded = _run(vault, "large.md")
    assert bounded.returncode == 0, bounded.stderr
    bounded_observation = _report(bounded)["observations"][0]
    assert bounded_observation["bytes_read"] == 64 * 1024
    assert bounded_observation["truncated"] is True


def test_probe_rejects_invalid_or_escaping_targets(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _make_vault(vault)
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (vault / "escape.md").symlink_to(outside)

    missing = _run(tmp_path / "missing", "Notes/secret.md")
    assert missing.returncode != 0
    assert _report(missing)["root"]["reason"] == "root_missing"

    escaping = _run(vault, "../outside.md")
    assert escaping.returncode != 0
    assert "outside" not in escaping.stdout

    symlink = _run(vault, "escape.md")
    assert symlink.returncode != 0
    symlink_report = _report(symlink)
    assert symlink_report["observations"][0]["status"] == "unknown"
    assert "symlink" in symlink_report["observations"][0]["reason"]

    unreadable = vault / "unreadable.md"
    unreadable.write_text("not observable", encoding="utf-8")
    unreadable.chmod(0)
    try:
        unreadable_result = _run(vault, "unreadable.md")
    finally:
        unreadable.chmod(0o600)
    assert unreadable_result.returncode != 0
    assert _report(unreadable_result)["observations"][0]["reason"] == "target_unreadable"

    unreadable_root = tmp_path / "unreadable-root"
    unreadable_root.mkdir()
    unreadable_root.chmod(0)
    try:
        unreadable_root_result = _run(unreadable_root)
    finally:
        unreadable_root.chmod(0o700)
    assert unreadable_root_result.returncode != 0
    assert _report(unreadable_root_result)["root"]["reason"] == "root_unreadable"

    regular_file = tmp_path / "not-a-root"
    regular_file.write_text("not a directory", encoding="utf-8")
    non_directory = _run(regular_file)
    assert non_directory.returncode != 0
    assert _report(non_directory)["root"]["reason"] == "root_not_directory"

    no_marker = tmp_path / "no-marker"
    no_marker.mkdir()
    (no_marker / "note.md").write_text("local", encoding="utf-8")
    custom_without_marker = _run(no_marker, "note.md")
    assert custom_without_marker.returncode != 0
    assert _report(custom_without_marker)["marker"]["status"] == "missing"

    if hasattr(os, "mkfifo"):
        special = vault / "pipe"
        os.mkfifo(special)
        special_result = _run(vault, "pipe")
        assert special_result.returncode != 0
        assert _report(special_result)["observations"][0]["reason"] == "unsupported_special_file"

    root_link = tmp_path / "root-link"
    root_link.symlink_to(vault, target_is_directory=True)
    linked_root = _run(root_link)
    assert linked_root.returncode != 0
    assert _report(linked_root)["root"]["reason"] == "root_symlink_rejected"


def test_probe_is_read_only_and_not_a_runtime_selector(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _make_vault(vault)
    before = {path.relative_to(vault): path.read_bytes() for path in vault.rglob("*") if path.is_file()}

    result = _run(vault, "Notes/secret.md", "settings/vault.md")

    assert result.returncode == 0, result.stderr
    after = {path.relative_to(vault): path.read_bytes() for path in vault.rglob("*") if path.is_file()}
    assert after == before
    source = SCRIPT.read_text(encoding="utf-8")
    assert "write_text" not in source
    assert "write_bytes" not in source
    assert "mkdir" not in source
    assert "unlink" not in source
    assert "rename" not in source
    assert "registry" not in source.lower()
    assert "settings" in _report(result)["marker"]["relative_path"]


def test_probe_has_no_production_vault_selection_seam() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "VAULT_ROOT" not in source
    assert "activeVault" not in source
    assert "active_vault" not in source
    assert "resolve_vault_root" not in source
    assert "from app." not in source
