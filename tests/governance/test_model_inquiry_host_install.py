from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.install_model_inquiry_host as host_installer


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "scripts" / "install_model_inquiry_host.py"


def _run_installer(
    *arguments: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(INSTALLER), *arguments],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _install(bin_dir: Path) -> subprocess.CompletedProcess[str]:
    return _run_installer(
        "install",
        "--repo-root",
        str(REPO_ROOT),
        "--bin-dir",
        str(bin_dir),
        "--python",
        sys.executable,
    )


def _init_adapter_checkout(root: Path) -> Path:
    adapter = root / "scripts" / host_installer.VERSIONED_ADAPTER_NAME
    adapter.parent.mkdir(parents=True)
    adapter.write_bytes(
        (REPO_ROOT / "scripts" / host_installer.VERSIONED_ADAPTER_NAME).read_bytes()
    )
    (root / "scripts" / host_installer.VERSIONED_LAUNCHER_NAME).write_bytes(
        (REPO_ROOT / "scripts" / host_installer.VERSIONED_LAUNCHER_NAME).read_bytes()
    )
    return adapter


def test_installer_creates_both_role_entrypoints_and_exact_retry_is_noop(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    first = _install(bin_dir)
    second = _install(bin_dir)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert first_payload["roles"] == {
        "fable": {"entrypoint": "fable-model-inquiry-role", "status": "installed"},
        "gpt_codex": {
            "entrypoint": "codex-model-inquiry-role",
            "status": "installed",
        },
    }
    assert second_payload["roles"] == {
        "fable": {"entrypoint": "fable-model-inquiry-role", "status": "unchanged"},
        "gpt_codex": {
            "entrypoint": "codex-model-inquiry-role",
            "status": "unchanged",
        },
    }
    assert first_payload["launcher"] == {
        "entrypoint": "yggdrasil-model-inquiry-provider-api",
        "lineage": "repo-owned-declared-credential",
        "status": "installed",
    }
    assert second_payload["launcher"] == {
        "entrypoint": "yggdrasil-model-inquiry-provider-api",
        "lineage": "repo-owned-declared-credential",
        "status": "unchanged",
    }
    assert host_installer.FIXED_LAUNCHER_NAME == "yggdrasil-model-inquiry-provider-api"
    assert (bin_dir / "yggdrasil-model-inquiry-provider-api").is_file()
    assert not (bin_dir / "yggdrasil-model-inquiry").exists()
    for name in ("fable-model-inquiry-role", "codex-model-inquiry-role"):
        path = bin_dir / name
        assert path.is_file()
        assert path.stat().st_mode & 0o777 == 0o700


def test_installer_rejects_conflicting_or_unsafe_destinations(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    conflicting = bin_dir / "fable-model-inquiry-role"
    conflicting.write_text("unrelated host command\n", encoding="utf-8")
    conflicting.chmod(0o700)

    conflict = _install(bin_dir)

    assert conflict.returncode == 2
    assert "conflicting entrypoint" in conflict.stderr
    assert conflicting.read_text(encoding="utf-8") == "unrelated host command\n"
    assert not (bin_dir / "codex-model-inquiry-role").exists()

    stale_launcher_bin = tmp_path / "stale-launcher-bin"
    stale_launcher_bin.mkdir()
    stale_launcher = stale_launcher_bin / host_installer.FIXED_LAUNCHER_NAME
    stale_launcher.write_text(
        "#!/bin/sh\nexec fable-subscription-cli \"$@\"\n",
        encoding="utf-8",
    )
    stale_launcher.chmod(0o700)
    stale_conflict = _install(stale_launcher_bin)

    assert stale_conflict.returncode == 2
    assert (
        "conflicting entrypoint: yggdrasil-model-inquiry-provider-api"
        in stale_conflict.stderr
    )
    assert "fable-subscription-cli" in stale_launcher.read_text(encoding="utf-8")
    assert not (stale_launcher_bin / "fable-model-inquiry-role").exists()
    assert not (stale_launcher_bin / "codex-model-inquiry-role").exists()

    real_bin = tmp_path / "real-bin"
    real_bin.mkdir()
    symlinked_bin = tmp_path / "symlinked-bin"
    symlinked_bin.symlink_to(real_bin, target_is_directory=True)
    unsafe = _install(symlinked_bin)

    assert unsafe.returncode == 2
    assert "bin directory must not contain symlinks" in unsafe.stderr
    assert not list(real_bin.iterdir())

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    symlinked_parent = tmp_path / "symlinked-parent"
    symlinked_parent.symlink_to(real_parent, target_is_directory=True)
    unsafe_ancestor = _install(symlinked_parent / "bin")

    assert unsafe_ancestor.returncode == 2
    assert "bin directory must not contain symlinks" in unsafe_ancestor.stderr
    assert not (real_parent / "bin").exists()

    symlink_target_bin = tmp_path / "symlink-target-bin"
    symlink_target_bin.mkdir()
    unrelated = tmp_path / "unrelated-command"
    unrelated.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (symlink_target_bin / "fable-model-inquiry-role").symlink_to(unrelated)
    symlink_target = _install(symlink_target_bin)

    assert symlink_target.returncode == 2
    assert "conflicting entrypoint" in symlink_target.stderr
    assert (symlink_target_bin / "fable-model-inquiry-role").is_symlink()
    assert not (symlink_target_bin / "codex-model-inquiry-role").exists()

    missing_checkout = _run_installer(
        "install",
        "--repo-root",
        str(tmp_path / "not-a-checkout"),
        "--bin-dir",
        str(tmp_path / "missing-checkout-bin"),
        "--python",
        sys.executable,
    )

    assert missing_checkout.returncode == 2
    assert "repo root is unavailable" in missing_checkout.stderr
    assert not (tmp_path / "missing-checkout-bin").exists()

    fake_checkout = tmp_path / "fake-checkout"
    _init_adapter_checkout(fake_checkout)
    foreign_checkout = _run_installer(
        "install",
        "--repo-root",
        str(fake_checkout),
        "--bin-dir",
        str(tmp_path / "fake-checkout-bin"),
        "--python",
        sys.executable,
    )

    assert foreign_checkout.returncode == 2
    assert "trusted installer checkout" in foreign_checkout.stderr
    assert not (tmp_path / "fake-checkout-bin").exists()


def test_installer_rejects_dirty_tracked_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "checkout"
    adapter = _init_adapter_checkout(checkout)
    monkeypatch.setattr(host_installer, "TRUSTED_REPO_ROOT", checkout.resolve())

    clean = host_installer._resolve_repo_root(checkout)
    assert clean.adapter_sha256 == hashlib.sha256(adapter.read_bytes()).hexdigest()

    adapter.write_text("raise SystemExit('modified')\n", encoding="utf-8")
    with pytest.raises(
        host_installer.HostInstallError,
        match="must match the installer digest",
    ):
        host_installer._resolve_repo_root(checkout)


def test_installer_rejects_dirty_tracked_fixed_launcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "checkout"
    _init_adapter_checkout(checkout)
    launcher = checkout / "scripts" / host_installer.VERSIONED_LAUNCHER_NAME
    monkeypatch.setattr(host_installer, "TRUSTED_REPO_ROOT", checkout.resolve())

    host_installer._resolve_repo_root(checkout)
    launcher.write_text("raise SystemExit('stale subscription launcher')\n", encoding="utf-8")

    with pytest.raises(
        host_installer.HostInstallError,
        match="fixed launcher must match the installer digest",
    ):
        host_installer._resolve_repo_root(checkout)

def test_installer_does_not_require_git_on_host(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    result = _run_installer(
        "install",
        "--repo-root",
        str(REPO_ROOT),
        "--bin-dir",
        str(bin_dir),
        "--python",
        sys.executable,
        env={**os.environ, "PATH": ""},
    )

    assert result.returncode == 0, result.stderr
    assert (bin_dir / "fable-model-inquiry-role").is_file()


def test_new_bin_directory_is_durably_linked_from_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = tmp_path / "bin"
    parent_identity = (tmp_path.stat().st_dev, tmp_path.stat().st_ino)
    real_fsync = host_installer.os.fsync
    parent_fsynced = False

    def record_fsync(fd: int) -> None:
        nonlocal parent_fsynced
        details = os.fstat(fd)
        if (details.st_dev, details.st_ino) == parent_identity:
            parent_fsynced = True
        real_fsync(fd)

    monkeypatch.setattr(host_installer.os, "fsync", record_fsync)
    directory_fd = host_installer._open_directory_chain(
        bin_dir,
        label="bin directory",
        create_final=True,
    )
    os.close(directory_fd)

    assert parent_fsynced
    assert bin_dir.is_dir()


def test_new_bin_parent_fsync_failure_fails_install_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = tmp_path / "bin"
    parent_identity = (tmp_path.stat().st_dev, tmp_path.stat().st_ino)
    real_fsync = host_installer.os.fsync

    def fail_parent_fsync(fd: int) -> None:
        details = os.fstat(fd)
        if (details.st_dev, details.st_ino) == parent_identity:
            raise OSError("injected parent fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(host_installer.os, "fsync", fail_parent_fsync)
    with pytest.raises(host_installer.HostInstallError, match="unable to create bin directory"):
        host_installer.install(
            repo_root=REPO_ROOT,
            bin_dir=bin_dir,
            python=Path(sys.executable),
        )

    assert bin_dir.is_dir()
    assert not list(bin_dir.iterdir())


def test_installer_rejects_checkout_replacement_during_wrapper_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "checkout"
    _init_adapter_checkout(checkout)
    original_checkout = tmp_path / "original-checkout"
    bin_dir = tmp_path / "bin"
    monkeypatch.setattr(host_installer, "TRUSTED_REPO_ROOT", checkout.resolve())
    real_wrapper_content = host_installer._wrapper_content
    replaced = False

    def replace_during_wrapper(
        *,
        role: str,
        python: Path,
        adapter: Path,
        adapter_sha256: str,
    ) -> str:
        nonlocal replaced
        if not replaced:
            replaced = True
            checkout.rename(original_checkout)
            _init_adapter_checkout(checkout)
        return real_wrapper_content(
            role=role,
            python=python,
            adapter=adapter,
            adapter_sha256=adapter_sha256,
        )

    monkeypatch.setattr(host_installer, "_wrapper_content", replace_during_wrapper)
    with pytest.raises(host_installer.HostInstallError, match="identity changed"):
        host_installer.install(
            repo_root=checkout,
            bin_dir=bin_dir,
            python=Path(sys.executable),
        )

    assert replaced
    assert original_checkout.is_dir()
    assert checkout.is_dir()
    assert not bin_dir.exists()


def test_install_rejects_checkout_replacement_after_bin_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "checkout"
    _init_adapter_checkout(checkout)
    original_checkout = tmp_path / "original-checkout"
    bin_dir = tmp_path / "bin"
    monkeypatch.setattr(host_installer, "TRUSTED_REPO_ROOT", checkout.resolve())
    real_open_bin_dir = host_installer._open_bin_dir

    def replace_checkout_after_bin_open(
        path: Path,
        *,
        create: bool,
    ) -> tuple[Path, int, tuple[int, int]]:
        opened = real_open_bin_dir(path, create=create)
        checkout.rename(original_checkout)
        replacement = _init_adapter_checkout(checkout)
        replacement.write_text("raise SystemExit('foreign')\n", encoding="utf-8")
        return opened

    monkeypatch.setattr(
        host_installer,
        "_open_bin_dir",
        replace_checkout_after_bin_open,
    )
    with pytest.raises(host_installer.HostInstallError, match="identity changed"):
        host_installer.install(
            repo_root=checkout,
            bin_dir=bin_dir,
            python=Path(sys.executable),
        )

    assert original_checkout.is_dir()
    assert checkout.is_dir()
    assert bin_dir.is_dir()
    assert not list(bin_dir.iterdir())


def test_installer_rejects_adapter_replacement_during_wrapper_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "checkout"
    adapter = _init_adapter_checkout(checkout)
    original_adapter = checkout / "scripts" / "original-adapter.py"
    bin_dir = tmp_path / "bin"
    monkeypatch.setattr(host_installer, "TRUSTED_REPO_ROOT", checkout.resolve())
    real_wrapper_content = host_installer._wrapper_content
    replaced = False

    def replace_adapter_during_wrapper(
        *,
        role: str,
        python: Path,
        adapter: Path,
        adapter_sha256: str,
    ) -> str:
        nonlocal replaced
        if not replaced:
            replaced = True
            payload = adapter.read_bytes()
            adapter.rename(original_adapter)
            adapter.write_bytes(payload)
        return real_wrapper_content(
            role=role,
            python=python,
            adapter=adapter,
            adapter_sha256=adapter_sha256,
        )

    monkeypatch.setattr(
        host_installer,
        "_wrapper_content",
        replace_adapter_during_wrapper,
    )
    with pytest.raises(host_installer.HostInstallError, match="adapter identity changed"):
        host_installer.install(
            repo_root=checkout,
            bin_dir=bin_dir,
            python=Path(sys.executable),
        )

    assert replaced
    assert original_adapter.is_file()
    assert adapter.is_file()
    assert not bin_dir.exists()


def test_installed_entrypoints_bind_exact_role_and_versioned_adapter(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    result = _install(bin_dir)
    assert result.returncode == 0, result.stderr

    expected = {
        "fable-model-inquiry-role": "fable",
        "codex-model-inquiry-role": "gpt_codex",
    }
    adapter = str((REPO_ROOT / "scripts" / host_installer.VERSIONED_ADAPTER_NAME).resolve())
    adapter_sha256 = hashlib.sha256(Path(adapter).read_bytes()).hexdigest()
    assert host_installer.VERSIONED_ADAPTER_SHA256 == adapter_sha256
    python = str(Path(sys.executable))
    for name, role in expected.items():
        content = (bin_dir / name).read_text(encoding="utf-8")
        assert f"--role {role}" in content
        assert adapter in content
        assert f"adapter-sha256={adapter_sha256}" in content
        assert python in content
        assert "BUILDEROPS_INQUIRY_ROLE_INTENT_JSON" not in content
        assert "TOKEN" not in content
        assert "KEY" not in content

    launcher = (bin_dir / host_installer.FIXED_LAUNCHER_NAME).read_text(
        encoding="utf-8"
    )
    assert host_installer.VERSIONED_LAUNCHER_NAME in launcher
    assert f"launcher-sha256={host_installer.VERSIONED_LAUNCHER_SHA256}" in launcher
    assert "launcher-lineage=repo-owned-declared-credential" in launcher
    assert "--run-on-credential-unavailable" in launcher
    assert "model_inquiry_subscription_adapter" not in launcher


def test_installed_entrypoints_retain_selected_interpreter_path(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    selected_python = tmp_path / "selected-python"
    interpreter_target = tmp_path / "interpreter-target"
    interpreter_target.write_text(
        f"#!/bin/sh\n[ \"$0\" = {shlex.quote(str(selected_python))} ]\n",
        encoding="utf-8",
    )
    interpreter_target.chmod(0o700)
    selected_python.symlink_to(interpreter_target)

    result = _run_installer(
        "install",
        "--repo-root",
        str(REPO_ROOT),
        "--bin-dir",
        str(bin_dir),
        "--python",
        str(selected_python),
    )

    assert result.returncode == 0, result.stderr
    for entrypoint in ("fable-model-inquiry-role", "codex-model-inquiry-role"):
        content = (bin_dir / entrypoint).read_text(encoding="utf-8")
        assert str(selected_python) in content
        executed = subprocess.run([str(bin_dir / entrypoint)], check=False)
        assert executed.returncode == 0


def test_check_mode_is_sanitized_read_only_and_complete(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    assert _install(bin_dir).returncode == 0
    for command in ("claude", "codex"):
        executable = bin_dir / command
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o700)
    env = {**os.environ, "PATH": str(bin_dir)}
    before = {
        path.relative_to(tmp_path): (path.stat().st_mode, path.read_bytes())
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    result = _run_installer(
        "check",
        "--repo-root",
        str(REPO_ROOT),
        "--bin-dir",
        str(bin_dir),
        "--python",
        sys.executable,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "schema": "builderops.model-inquiry-host-check.v1",
        "ok": True,
        "launcher": {
            "command": "yggdrasil-model-inquiry-provider-api",
            "lineage": "repo-owned-declared-credential",
            "status": "available",
        },
        "roles": {
            "fable": {
                "entrypoint": "fable-model-inquiry-role",
                "entrypoint_status": "available",
                "credential_resolution": "host-secret-contract",
            },
            "gpt_codex": {
                "entrypoint": "codex-model-inquiry-role",
                "entrypoint_status": "available",
                "credential_resolution": "host-secret-contract",
            },
        },
    }
    assert str(tmp_path) not in result.stdout
    assert "BUILDEROPS_" not in result.stdout
    assert not any("model-inquir" in path.name for path in tmp_path.rglob("*") if path.is_dir())
    after = {
        path.relative_to(tmp_path): (path.stat().st_mode, path.read_bytes())
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before

    provider_bin = tmp_path / "provider-bin"
    provider_bin.mkdir()
    for command in ("claude", "codex", "yggdrasil-model-inquiry-provider-api"):
        executable = provider_bin / command
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o700)
    missing_from_path = _run_installer(
        "check",
        "--repo-root",
        str(REPO_ROOT),
        "--bin-dir",
        str(bin_dir),
        "--python",
        sys.executable,
        env={**os.environ, "PATH": str(provider_bin)},
    )

    assert missing_from_path.returncode == 1
    missing_payload = json.loads(missing_from_path.stdout)
    assert missing_payload["roles"]["fable"] == {
        "entrypoint": "fable-model-inquiry-role",
        "entrypoint_status": "unavailable",
        "credential_resolution": "host-secret-contract",
    }
    assert missing_payload["roles"]["gpt_codex"]["entrypoint_status"] == "unavailable"


def test_check_rejects_conflicting_command_at_provider_api_name(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    assert _install(bin_dir).returncode == 0
    stale_bin = tmp_path / "stale-bin"
    stale_bin.mkdir()
    stale_launcher = stale_bin / host_installer.FIXED_LAUNCHER_NAME
    stale_launcher.write_text(
        "#!/bin/sh\nexec fable-subscription-cli \"$@\"\n",
        encoding="utf-8",
    )
    stale_launcher.chmod(0o700)

    result = _run_installer(
        "check",
        "--repo-root",
        str(REPO_ROOT),
        "--bin-dir",
        str(bin_dir),
        "--python",
        sys.executable,
        env={**os.environ, "PATH": f"{stale_bin}{os.pathsep}{bin_dir}"},
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["launcher"] == {
        "command": "yggdrasil-model-inquiry-provider-api",
        "lineage": "repo-owned-declared-credential",
        "status": "unavailable",
    }
    assert payload["roles"]["fable"]["entrypoint_status"] == "available"
    assert payload["roles"]["gpt_codex"]["entrypoint_status"] == "available"


def test_partial_install_is_retained_for_exact_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = tmp_path / "bin"
    real_install = host_installer._install_no_overwrite

    def fail_second_role(directory_fd: int, name: str, content: str) -> bool:
        if name == "codex-model-inquiry-role":
            raise host_installer.HostInstallError("injected second-role failure")
        return real_install(directory_fd, name, content)

    monkeypatch.setattr(host_installer, "_install_no_overwrite", fail_second_role)
    with pytest.raises(host_installer.HostInstallError, match="second-role failure"):
        host_installer.install(
            repo_root=REPO_ROOT,
            bin_dir=bin_dir,
            python=Path(sys.executable),
        )

    assert (bin_dir / "fable-model-inquiry-role").is_file()
    assert not (bin_dir / "codex-model-inquiry-role").exists()
    monkeypatch.undo()

    retry = _install(bin_dir)
    assert retry.returncode == 0, retry.stderr
    assert json.loads(retry.stdout)["roles"] == {
        "fable": {"entrypoint": "fable-model-inquiry-role", "status": "unchanged"},
        "gpt_codex": {
            "entrypoint": "codex-model-inquiry-role",
            "status": "installed",
        },
    }


def test_temporary_cleanup_failure_cannot_return_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    directory_fd = os.open(bin_dir, os.O_RDONLY | os.O_DIRECTORY)
    real_unlink = os.unlink

    def fail_temp_cleanup(
        path: str | bytes,
        *,
        dir_fd: int | None = None,
    ) -> None:
        if isinstance(path, str) and path.startswith(".test-entrypoint."):
            raise OSError("injected cleanup failure")
        real_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(host_installer.os, "unlink", fail_temp_cleanup)
    try:
        with pytest.raises(
            host_installer.HostInstallError,
            match="temporary entrypoint cleanup failed",
        ):
            host_installer._install_no_overwrite(
                directory_fd,
                "test-entrypoint",
                "#!/bin/sh\nexit 0\n",
            )
    finally:
        os.close(directory_fd)
        monkeypatch.undo()

    assert (bin_dir / "test-entrypoint").is_file()
    assert len(list(bin_dir.glob(".test-entrypoint.*.tmp"))) == 1


def test_concurrent_exact_writer_produces_truthful_unchanged_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = tmp_path / "bin"
    real_install = host_installer._install_no_overwrite
    raced: set[str] = set()

    def exact_writer_wins(directory_fd: int, name: str, content: str) -> bool:
        if name not in raced:
            raced.add(name)
            assert real_install(directory_fd, name, content) is True
        return real_install(directory_fd, name, content)

    monkeypatch.setattr(host_installer, "_install_no_overwrite", exact_writer_wins)
    receipt = host_installer.install(
        repo_root=REPO_ROOT,
        bin_dir=bin_dir,
        python=Path(sys.executable),
    )

    assert receipt["roles"] == {
        "fable": {"entrypoint": "fable-model-inquiry-role", "status": "unchanged"},
        "gpt_codex": {
            "entrypoint": "codex-model-inquiry-role",
            "status": "unchanged",
        },
    }


def test_concurrent_conflicting_writer_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = tmp_path / "bin"
    real_install = host_installer._install_no_overwrite

    def conflicting_writer_wins(directory_fd: int, name: str, content: str) -> bool:
        if name == "fable-model-inquiry-role":
            fd = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o700,
                dir_fd=directory_fd,
            )
            try:
                os.write(fd, b"unrelated concurrent command\n")
            finally:
                os.close(fd)
        return real_install(directory_fd, name, content)

    monkeypatch.setattr(
        host_installer,
        "_install_no_overwrite",
        conflicting_writer_wins,
    )
    with pytest.raises(host_installer.HostInstallError, match="conflicting entrypoint"):
        host_installer.install(
            repo_root=REPO_ROOT,
            bin_dir=bin_dir,
            python=Path(sys.executable),
        )

    assert (bin_dir / "fable-model-inquiry-role").read_text(encoding="utf-8") == (
        "unrelated concurrent command\n"
    )
    assert not (bin_dir / "codex-model-inquiry-role").exists()


def test_install_rejects_bin_directory_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = tmp_path / "bin"
    detached_bin = tmp_path / "detached-bin"
    real_install = host_installer._install_no_overwrite
    replaced = False

    def replace_bin_before_write(directory_fd: int, name: str, content: str) -> bool:
        nonlocal replaced
        if not replaced:
            replaced = True
            bin_dir.rename(detached_bin)
            bin_dir.mkdir()
        return real_install(directory_fd, name, content)

    monkeypatch.setattr(
        host_installer,
        "_install_no_overwrite",
        replace_bin_before_write,
    )
    with pytest.raises(host_installer.HostInstallError, match="identity changed"):
        host_installer.install(
            repo_root=REPO_ROOT,
            bin_dir=bin_dir,
            python=Path(sys.executable),
        )

    assert replaced
    assert not list(bin_dir.iterdir())
    assert (detached_bin / "fable-model-inquiry-role").is_file()
    assert (detached_bin / "codex-model-inquiry-role").is_file()


def test_check_rejects_bin_directory_replacement_during_path_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = tmp_path / "bin"
    detached_bin = tmp_path / "detached-bin"
    assert _install(bin_dir).returncode == 0
    real_which = host_installer.shutil.which
    replaced = False

    def replace_bin_before_discovery(command: str, *, path: str | None = None) -> str | None:
        nonlocal replaced
        if command != "git" and not replaced:
            replaced = True
            bin_dir.rename(detached_bin)
            bin_dir.mkdir()
            for name in (
                "fable-model-inquiry-role",
                "codex-model-inquiry-role",
                "claude",
                "codex",
                "yggdrasil-model-inquiry-provider-api",
            ):
                executable = bin_dir / name
                executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                executable.chmod(0o700)
        return real_which(command, path=path)

    monkeypatch.setattr(host_installer.shutil, "which", replace_bin_before_discovery)
    with pytest.raises(host_installer.HostInstallError, match="identity changed"):
        host_installer.check(
            repo_root=REPO_ROOT,
            bin_dir=bin_dir,
            python=Path(sys.executable),
            path=str(bin_dir),
        )

    assert replaced
    assert (detached_bin / "fable-model-inquiry-role").is_file()
    assert (bin_dir / "fable-model-inquiry-role").read_text(encoding="utf-8") == (
        "#!/bin/sh\nexit 0\n"
    )


def test_check_rejects_checkout_replacement_after_bin_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "checkout"
    _init_adapter_checkout(checkout)
    original_checkout = tmp_path / "original-checkout"
    bin_dir = tmp_path / "bin"
    monkeypatch.setattr(host_installer, "TRUSTED_REPO_ROOT", checkout.resolve())
    host_installer.install(
        repo_root=checkout,
        bin_dir=bin_dir,
        python=Path(sys.executable),
    )
    _add_fake_host_dependencies(bin_dir)
    real_open_bin_dir = host_installer._open_bin_dir

    def replace_checkout_after_bin_open(
        path: Path,
        *,
        create: bool,
    ) -> tuple[Path, int, tuple[int, int]]:
        opened = real_open_bin_dir(path, create=create)
        checkout.rename(original_checkout)
        replacement = _init_adapter_checkout(checkout)
        replacement.write_text("raise SystemExit('foreign')\n", encoding="utf-8")
        return opened

    monkeypatch.setattr(
        host_installer,
        "_open_bin_dir",
        replace_checkout_after_bin_open,
    )
    with pytest.raises(host_installer.HostInstallError, match="identity changed"):
        host_installer.check(
            repo_root=checkout,
            bin_dir=bin_dir,
            python=Path(sys.executable),
            path=str(bin_dir),
        )

    assert original_checkout.is_dir()
    assert checkout.is_dir()


def test_install_revalidates_all_wrappers_before_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = tmp_path / "bin"
    real_install = host_installer._install_no_overwrite

    def replace_first_during_second(
        directory_fd: int,
        name: str,
        content: str,
    ) -> bool:
        if name == "codex-model-inquiry-role":
            os.unlink("fable-model-inquiry-role", dir_fd=directory_fd)
            fd = os.open(
                "fable-model-inquiry-role",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o700,
                dir_fd=directory_fd,
            )
            try:
                os.write(fd, b"unrelated replacement\n")
            finally:
                os.close(fd)
        return real_install(directory_fd, name, content)

    monkeypatch.setattr(
        host_installer,
        "_install_no_overwrite",
        replace_first_during_second,
    )
    with pytest.raises(
        host_installer.HostInstallError,
        match="entrypoint changed during installation",
    ):
        host_installer.install(
            repo_root=REPO_ROOT,
            bin_dir=bin_dir,
            python=Path(sys.executable),
        )

    assert (bin_dir / "fable-model-inquiry-role").read_text(encoding="utf-8") == (
        "unrelated replacement\n"
    )


def _add_fake_host_dependencies(bin_dir: Path) -> None:
    for command in ("claude", "codex"):
        executable = bin_dir / command
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o700)


def test_check_revalidates_earlier_wrapper_after_later_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = tmp_path / "bin"
    assert _install(bin_dir).returncode == 0
    _add_fake_host_dependencies(bin_dir)
    real_which = host_installer.shutil.which
    replaced = False

    def replace_fable_during_codex_discovery(
        command: str,
        *,
        path: str | None = None,
    ) -> str | None:
        nonlocal replaced
        if command == "codex-model-inquiry-role" and not replaced:
            replaced = True
            fable = bin_dir / "fable-model-inquiry-role"
            fable.unlink()
            fable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fable.chmod(0o700)
        return real_which(command, path=path)

    monkeypatch.setattr(
        host_installer.shutil,
        "which",
        replace_fable_during_codex_discovery,
    )
    payload = host_installer.check(
        repo_root=REPO_ROOT,
        bin_dir=bin_dir,
        python=Path(sys.executable),
        path=str(bin_dir),
    )

    assert replaced
    assert payload["ok"] is False
    roles = payload["roles"]
    assert isinstance(roles, dict)
    fable = roles["fable"]
    assert isinstance(fable, dict)
    assert fable["entrypoint_status"] == "unavailable"


def test_check_rejects_bin_replacement_during_launcher_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = tmp_path / "bin"
    detached_bin = tmp_path / "detached-bin"
    assert _install(bin_dir).returncode == 0
    _add_fake_host_dependencies(bin_dir)
    real_which = host_installer.shutil.which
    replaced = False

    def replace_bin_for_launcher(
        command: str,
        *,
        path: str | None = None,
    ) -> str | None:
        nonlocal replaced
        if command == "yggdrasil-model-inquiry-provider-api" and not replaced:
            replaced = True
            bin_dir.rename(detached_bin)
            bin_dir.mkdir()
        return real_which(command, path=path)

    monkeypatch.setattr(host_installer.shutil, "which", replace_bin_for_launcher)
    with pytest.raises(host_installer.HostInstallError, match="identity changed"):
        host_installer.check(
            repo_root=REPO_ROOT,
            bin_dir=bin_dir,
            python=Path(sys.executable),
            path=str(bin_dir),
        )

    assert replaced
    assert not list(bin_dir.iterdir())


def test_installed_launcher_pins_python_against_hostile_ambient_override(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    selected_python = tmp_path / "selected-python"
    hostile_python = tmp_path / "hostile-python"
    capture = tmp_path / "selected-environment"
    hostile_marker = tmp_path / "hostile-executed"
    selected_python.write_text(
        '#!/bin/sh\nprintf "%s" "$BUILDEROPS_PYTHON" > "$CAPTURE_PATH"\n',
        encoding="utf-8",
    )
    hostile_python.write_text(
        '#!/bin/sh\nprintf "executed" > "$HOSTILE_MARKER"\n',
        encoding="utf-8",
    )
    selected_python.chmod(0o700)
    hostile_python.chmod(0o700)

    installed = host_installer.install(
        repo_root=REPO_ROOT,
        bin_dir=bin_dir,
        python=selected_python,
    )
    assert installed["ok"] is True

    result = subprocess.run(
        [str(bin_dir / host_installer.FIXED_LAUNCHER_NAME), "--help"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "BUILDEROPS_PYTHON": str(hostile_python),
            "CAPTURE_PATH": str(capture),
            "HOSTILE_MARKER": str(hostile_marker),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert capture.read_text(encoding="utf-8") == str(selected_python.resolve())
    assert not hostile_marker.exists()


def test_headless_entrypoints_do_not_require_subscription_session(
    tmp_path: Path,
) -> None:
    """The installer's own installation path must produce credential-resolving roles."""
    bin_dir = tmp_path / "bin"
    installed = _install(bin_dir)
    assert installed.returncode == 0, installed.stderr

    installer_source = INSTALLER.read_text(encoding="utf-8")
    assert "model_inquiry_subscription_adapter" not in installer_source
    assert host_installer.VERSIONED_ADAPTER_NAME == "model_inquiry_role_adapter.py"
    assert all(
        not hasattr(spec, "provider_command") for spec in host_installer.ROLE_SPECS
    )

    adapter_source = (
        REPO_ROOT / "scripts" / host_installer.VERSIONED_ADAPTER_NAME
    ).read_text(encoding="utf-8")
    assert "host secret contract" in " ".join(adapter_source.split())
    # It resolves a declared credential; it launches no CLI and no session.
    assert "model_inquiry_subscription_adapter" not in adapter_source
    assert "subprocess" not in adapter_source
    assert "shutil.which" not in adapter_source
    for wrapper_name in ("fable-model-inquiry-role", "codex-model-inquiry-role"):
        content = (bin_dir / wrapper_name).read_text(encoding="utf-8")
        assert host_installer.VERSIONED_ADAPTER_NAME in content
        assert "credential-resolution=host-secret-contract" in content
        exec_line = next(
            line for line in content.splitlines() if line.startswith("exec ")
        )
        executed = shlex.split(exec_line)[1:]
        assert executed[1:8] == [
            "-m",
            "app.ops.host_secret_bootstrap",
            "--channel",
            "dev",
            "--consumer",
            "builderops-model-inquiry",
            "--",
        ]
        assert Path(executed[9]).name == host_installer.VERSIONED_ADAPTER_NAME
        assert executed[10] == "--role"
        assert not any(
            Path(argument).name in {"claude", "codex"} for argument in executed
        )
        assert "subscription" not in " ".join(
            Path(argument).name for argument in executed
        )

    payload = json.loads(installed.stdout)
    assert "provider_command" not in json.dumps(payload)

    # The installed entrypoint fails closed on the declared credential and never
    # looks for an interactive session: no provider CLI exists on this PATH.
    intent = (
        REPO_ROOT / "config" / "builderops" / "model_inquiry_role_intent.example.json"
    ).read_text(encoding="utf-8")
    executed = subprocess.run(
        [str(bin_dir / "fable-model-inquiry-role")],
        input=json.dumps({"phase": "draft", "system_prompt": "x"}),
        env={
            "PATH": str(bin_dir),
            "HOME": str(tmp_path),
            "BUILDEROPS_INQUIRY_ROLE_INTENT_JSON": intent,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert executed.returncode == 78, executed.stderr
    assert "anthropic.api-key" in executed.stderr
    assert "ANTHROPIC_API_KEY" not in executed.stderr
    assert executed.stdout == ""
