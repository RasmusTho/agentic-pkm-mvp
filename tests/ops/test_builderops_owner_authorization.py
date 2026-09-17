from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.builderops import owner_authorization


NOW = dt.datetime(2026, 9, 17, 5, 0, tzinfo=dt.timezone.utc)


def _profile(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "authorization_version": 1,
        "mode": "unattended",
        "authorized_by": "owner",
        "authorized_at": "2026-09-17T04:00:00Z",
        "expires_at": "2026-10-17T04:00:00Z",
        "repository": "RasmusTho/agentic-pkm-mvp",
        "source_ref": "refs/heads/main",
        "attestation_workflow": "RasmusTho/agentic-pkm-mvp/.github/workflows/app-image-build.yml",
        "project": "builderops-control-plane",
        "docker_context": "builderops",
        "engine_socket": "unix:///run/docker-builderops.sock",
        "vm_id": 102,
        "guest_hostname": "builder-system",
        "allowed_actions": ["deploy", "rollback"],
    }
    payload.update(overrides)
    return payload


def _patch_payload(monkeypatch: pytest.MonkeyPatch, payload: dict[str, object]) -> None:
    monkeypatch.setattr(owner_authorization, "_read_secure_profile", lambda _path: payload)


def test_unattended_profile_binds_target_scope_and_returns_stable_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = _profile()
    _patch_payload(monkeypatch, payload)

    loaded, fingerprint = owner_authorization.validate_profile(
        tmp_path / "profile.json",
        action="deploy",
        observed_hostname="builder-system",
        now=NOW,
    )

    assert loaded == payload
    assert len(fingerprint) == 64
    assert fingerprint == owner_authorization.validate_profile(
        tmp_path / "profile.json",
        action="rollback",
        observed_hostname="builder-system",
        now=NOW,
    )[1]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repository", "RasmusTho/other-repo"),
        ("source_ref", "refs/heads/release"),
        ("docker_context", "default"),
        ("engine_socket", "unix:///var/run/docker.sock"),
        ("vm_id", 101),
        ("guest_hostname", "ygg-prod"),
    ],
)
def test_unattended_profile_refuses_scope_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    payload = _profile(**{field: value})
    _patch_payload(monkeypatch, payload)

    with pytest.raises(owner_authorization.AuthorizationError):
        owner_authorization.validate_profile(
            tmp_path / "profile.json",
            action="deploy",
            observed_hostname="builder-system",
            now=NOW,
        )


def test_unattended_profile_refuses_expiry_and_action_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    expired = _profile(expires_at="2026-09-17T04:59:00Z")
    _patch_payload(monkeypatch, expired)
    with pytest.raises(owner_authorization.AuthorizationError, match="expired"):
        owner_authorization.validate_profile(
            tmp_path / "profile.json",
            action="deploy",
            observed_hostname="builder-system",
            now=NOW,
        )

    rollback_only = _profile(allowed_actions=["deploy"])
    _patch_payload(monkeypatch, rollback_only)
    with pytest.raises(owner_authorization.AuthorizationError, match="exactly deploy and rollback"):
        owner_authorization.validate_profile(
            tmp_path / "profile.json",
            action="deploy",
            observed_hostname="builder-system",
            now=NOW,
        )


def test_profile_file_must_be_root_owned_and_not_a_symlink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(owner_authorization, "_validate_ancestor_custody", lambda _path: None)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(_profile()), encoding="utf-8")
    with pytest.raises(owner_authorization.AuthorizationError, match="root-owned"):
        owner_authorization._read_secure_profile(path)

    link = tmp_path / "profile-link.json"
    link.symlink_to(path)
    with pytest.raises(owner_authorization.AuthorizationError, match="regular file"):
        owner_authorization._read_secure_profile(link)


def test_secure_profile_paths_must_be_absolute() -> None:
    with pytest.raises(owner_authorization.AuthorizationError, match="absolute"):
        owner_authorization._validate_ancestor_custody(Path("relative/profile.json"))


def test_issue_command_requires_root_and_explicit_owner_confirmation(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "python3",
            "scripts/builderops/owner_authorization.py",
            "issue",
            "--file",
            str(tmp_path / "profile.json"),
            "--authorized-by",
            "owner",
            "--expires-at",
            "2026-10-17T04:00:00Z",
            "--confirm",
            "wrong confirmation",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if os.geteuid() == 0:
        assert result.returncode == 77
        assert "explicit owner authorization confirmation" in result.stderr
    else:
        assert result.returncode == 77
        assert "must be installed by root" in result.stderr
