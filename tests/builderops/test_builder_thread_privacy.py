from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.builderops.builder_threads_serialized import (
    BuilderThreadClient,
    BuilderThreadError,
    InProcessWriterEndpoint,
    SerializedThreadWriter,
    initialize_external_writer_root,
)


def _writer(tmp_path: Path) -> tuple[SerializedThreadWriter, Path]:
    root = tmp_path / "external-builderops-vault"
    initialize_external_writer_root(root, vault_id="builderops-mac-mini")
    return SerializedThreadWriter(vault_id="builderops-mac-mini", state_root=root), root


def _client(writer: SerializedThreadWriter) -> BuilderThreadClient:
    return BuilderThreadClient(
        InProcessWriterEndpoint(writer, client_id="codex:desktop"), client_id="codex:desktop"
    )


@pytest.mark.parametrize(
    "rejected_text",
    (
        "/root/.ssh/id_rsa",
        "C:\\Users\\operator\\.ssh\\id_rsa",
        "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789",
    ),
)
def test_private_paths_and_secret_forms_fail_closed(tmp_path: Path, rejected_text: str) -> None:
    writer, _ = _writer(tmp_path)

    with pytest.raises(BuilderThreadError, match="shared_non_sensitive"):
        _client(writer).create(
            request_id="privacy-admission-4728",
            actor="codex:desktop",
            recipient="claude:mac",
            subject="Bounded question",
            content=rejected_text,
            source_refs=("github:4728",),
        )

    assert writer.accepted_mutation_count == 0


def test_rejected_text_never_reaches_external_artifact(tmp_path: Path) -> None:
    writer, root = _writer(tmp_path)

    with pytest.raises(BuilderThreadError, match="shared_non_sensitive"):
        _client(writer).create(
            request_id="privacy-no-write-4728",
            actor="codex:desktop",
            recipient="claude:mac",
            subject="Bounded question",
            content="sk-proj-abcdefghijklmnopqrstuvwxyz0123456789",
            source_refs=("github:4728",),
        )

    assert tuple((root / "builder-thread-entries").glob("*.json")) == ()
    assert writer.accepted_mutation_count == 0


@pytest.mark.parametrize(
    "ordinary_text",
    (
        "Read https://example.test/users/guide before replying.",
        "The support URL is https://example.test/home/start.",
    ),
)
def test_ordinary_urls_remain_shared_non_sensitive(tmp_path: Path, ordinary_text: str) -> None:
    writer, _ = _writer(tmp_path)

    _client(writer).create(
        request_id="ordinary-url-4728",
        actor="codex:desktop",
        recipient="claude:mac",
        subject="Bounded question",
        content=ordinary_text,
        source_refs=("github:4728",),
    )

    assert writer.accepted_mutation_count == 1


def test_recovery_rejects_privacy_invalid_persisted_envelope(tmp_path: Path) -> None:
    _, root = _writer(tmp_path)
    command = {
        "actor": "codex:desktop",
        "content": "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789",
        "kind": "create",
        "recipient": "claude:mac",
        "request_id": "privacy-recovery-4728",
        "source_refs": ["github:4728"],
        "subject": "Bounded question",
        "thread_id": None,
    }
    command_bytes = json.dumps(command, separators=(",", ":"), sort_keys=True).encode() + b"\n"
    payload = {
        "command": command,
        "request_digest": hashlib.sha256(command_bytes).hexdigest(),
        "sequence": 1,
        "schema": "builder-thread-command.v1",
        "vault_id": "builderops-mac-mini",
    }
    (root / "builder-thread-entries" / "privacy-recovery-4728.json").write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(BuilderThreadError, match="shared_non_sensitive"):
        SerializedThreadWriter(vault_id="builderops-mac-mini", state_root=root)
