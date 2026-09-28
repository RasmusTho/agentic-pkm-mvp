from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.knowledge.adapters import FsVaultAdapter, ObsidianCliAdapter
from app.knowledge.contracts import NoteLocator, WriteReceipt
from app.knowledge.errors import (
    KnowledgeCapabilityError,
    KnowledgeDependencyError,
    KnowledgeTransportError,
    KnowledgeWriteConflict,
)
from app.knowledge.multiwriter import NoteClass
from app.knowledge.service import HybridKnowledgePort, resolve_knowledge_port
from app.knowledge.settings import KnowledgeAdapter, KnowledgeSettings


def test_resolve_knowledge_port_strict_raises_on_missing_obsidian(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.knowledge.service.obsidian_dependency_status", lambda: type("S", (), {"ok": False, "details": {}})())
    settings = KnowledgeSettings(
        primary_adapter=KnowledgeAdapter.OBSIDIAN_CLI,
        fallback_adapter=KnowledgeAdapter.FS_VAULT,
        allow_fallback=False,
        strict_startup=True,
    )
    with pytest.raises(KnowledgeDependencyError):
        resolve_knowledge_port(settings=settings)


def test_resolve_knowledge_port_can_fallback_when_non_strict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("app.knowledge.service.obsidian_dependency_status", lambda: type("S", (), {"ok": False, "details": {}})())
    settings = KnowledgeSettings(
        primary_adapter=KnowledgeAdapter.OBSIDIAN_CLI,
        fallback_adapter=KnowledgeAdapter.FS_VAULT,
        allow_fallback=True,
        strict_startup=False,
    )
    port = resolve_knowledge_port(vault_root=tmp_path, settings=settings)
    assert isinstance(port, FsVaultAdapter)


def test_resolve_knowledge_port_uses_obsidian_adapter_when_dependencies_are_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.knowledge.service.obsidian_dependency_status", lambda: type("S", (), {"ok": True, "details": {}})())
    settings = KnowledgeSettings(
        primary_adapter=KnowledgeAdapter.OBSIDIAN_CLI,
        fallback_adapter=KnowledgeAdapter.FS_VAULT,
        allow_fallback=False,
        strict_startup=True,
    )
    port = resolve_knowledge_port(settings=settings)
    assert isinstance(port, ObsidianCliAdapter)


def test_resolve_knowledge_port_preserves_obsidian_primary_when_root_hint_is_given(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.knowledge.service.obsidian_dependency_status", lambda: type("S", (), {"ok": True, "details": {}})())
    settings = KnowledgeSettings(
        primary_adapter=KnowledgeAdapter.OBSIDIAN_CLI,
        fallback_adapter=KnowledgeAdapter.FS_VAULT,
        allow_fallback=False,
        strict_startup=True,
    )
    port = resolve_knowledge_port(vault_root=tmp_path, settings=settings)
    assert isinstance(port, ObsidianCliAdapter)


def test_obsidian_adapter_uses_configured_sources_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VAULT_SOURCES_DIR_REL", "Acquired")
    monkeypatch.setattr(
        "app.knowledge.service.obsidian_dependency_status",
        lambda: type("S", (), {"ok": True, "details": {}})(),
    )
    settings = KnowledgeSettings(
        primary_adapter=KnowledgeAdapter.OBSIDIAN_CLI,
        fallback_adapter=KnowledgeAdapter.FS_VAULT,
        allow_fallback=False,
        strict_startup=True,
    )
    port = resolve_knowledge_port(vault_root=tmp_path, settings=settings)
    assert isinstance(port, ObsidianCliAdapter)
    port.runner = lambda cmd, check, capture_output, text: subprocess.CompletedProcess(
        cmd, 0, stdout="", stderr=""
    )

    receipt = port.write_note(
        NoteLocator(vault="Vault", path="Acquired/source.md"),
        "source artifact",
    )

    assert receipt.note_class is NoteClass.CREATE_ONCE


def test_obsidian_adapter_classifies_symlink_alias_of_sources_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Acquired").mkdir()
    (vault / "SourcesAlias").symlink_to("Acquired", target_is_directory=True)
    monkeypatch.setenv("VAULT_SOURCES_DIR_REL", "SourcesAlias")
    settings = KnowledgeSettings(
        primary_adapter=KnowledgeAdapter.OBSIDIAN_CLI,
        fallback_adapter=KnowledgeAdapter.FS_VAULT,
        allow_fallback=False,
        strict_startup=True,
    )
    monkeypatch.setattr(
        "app.knowledge.service.obsidian_dependency_status",
        lambda: type("S", (), {"ok": True, "details": {}})(),
    )
    port = resolve_knowledge_port(vault_root=vault, settings=settings)
    assert isinstance(port, ObsidianCliAdapter)
    port.runner = lambda cmd, check, capture_output, text: subprocess.CompletedProcess(
        cmd, 0, stdout="", stderr=""
    )

    receipt = port.write_note(
        NoteLocator(vault="Vault", path="Acquired/source.md"),
        "source artifact",
    )

    assert receipt.note_class is NoteClass.CREATE_ONCE


def test_obsidian_adapter_classifies_unicode_alias_of_sources_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.vault import path_overlap

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Caf\u00e9").mkdir()
    # Model a filesystem that treats composed/decomposed names as equivalent;
    # Linux ext4 without the casefold flag treats them as distinct names.
    monkeypatch.setattr(
        path_overlap,
        "_filesystem_name_semantics",
        lambda _path: (False, True, False),
    )
    monkeypatch.setenv("VAULT_SOURCES_DIR_REL", "Cafe\u0301")
    settings = KnowledgeSettings(
        primary_adapter=KnowledgeAdapter.OBSIDIAN_CLI,
        fallback_adapter=KnowledgeAdapter.FS_VAULT,
        allow_fallback=False,
        strict_startup=True,
    )
    monkeypatch.setattr(
        "app.knowledge.service.obsidian_dependency_status",
        lambda: type("S", (), {"ok": True, "details": {}})(),
    )
    port = resolve_knowledge_port(vault_root=vault, settings=settings)
    assert isinstance(port, ObsidianCliAdapter)
    port.runner = lambda cmd, check, capture_output, text: subprocess.CompletedProcess(
        cmd, 0, stdout="", stderr=""
    )

    receipt = port.write_note(
        NoteLocator(vault="Vault", path="Caf\u00e9/source.md"),
        "source artifact",
    )

    assert receipt.note_class is NoteClass.CREATE_ONCE


def test_obsidian_classification_failure_precedes_external_create(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.vault import path_overlap

    calls: list[list[str]] = []

    def runner(cmd, check, capture_output, text):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def fail_classification(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("cannot verify selected Sources aliases")

    monkeypatch.setattr(path_overlap, "vault_path_is_within", fail_classification)
    adapter = ObsidianCliAdapter(
        runner=runner,
        sources_root_rel="SourcesAlias",
        vault_root=tmp_path,
    )

    with pytest.raises(RuntimeError, match="cannot verify selected Sources aliases"):
        adapter.write_note(
            NoteLocator(vault="Vault", path="Acquired/source.md"),
            "source artifact",
        )

    assert calls == []


def test_fallback_fs_port_supports_search_and_open_in_non_strict_mode(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    note = tmp_path / "Inbox" / "A.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("Body about mimer", encoding="utf-8")
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.knowledge.service.obsidian_dependency_status", lambda: type("S", (), {"ok": False, "details": {}})())
    settings = KnowledgeSettings(
        primary_adapter=KnowledgeAdapter.OBSIDIAN_CLI,
        fallback_adapter=KnowledgeAdapter.FS_VAULT,
        allow_fallback=True,
        strict_startup=False,
    )
    port = resolve_knowledge_port(settings=settings)
    hits = port.search_notes("Mimer", "mimer", limit=5)
    assert hits and hits[0].locator.path == "Inbox/A.md"
    # fs adapter open_note is intentionally a no-op but must remain callable.
    port.open_note(hits[0].locator)


def test_hybrid_port_falls_back_on_transport_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    locator = NoteLocator(vault="Vault", path="Inbox/test.md")

    class PrimaryPort:
        def write_note(self, locator, content):  # type: ignore[no-untyped-def]
            raise KnowledgeTransportError("cli timed out")

    fallback = FsVaultAdapter(tmp_path)
    port = HybridKnowledgePort(primary=PrimaryPort(), fallback=fallback, allow_fallback=True)

    receipt = port.write_note(locator, "body")

    assert receipt.adapter == "fs_vault"
    assert receipt.fallback_used is True
    assert (tmp_path / "Inbox" / "test.md").read_text(encoding="utf-8") == "body"
    assert "Knowledge fallback used for write_note" in caplog.text


def test_hybrid_port_forwards_rewritten_write_metadata() -> None:
    locator = NoteLocator(vault="Vault", path="Notes/test.md")
    captured: dict[str, object] = {}

    class PrimaryPort:
        def write_note(self, locator, content, **kwargs):  # type: ignore[no-untyped-def]
            captured["locator"] = locator
            captured["content"] = content
            captured.update(kwargs)
            return WriteReceipt(operation="write_note", locator=locator, adapter="primary")

    port = HybridKnowledgePort(primary=PrimaryPort(), fallback=None, allow_fallback=False)
    port.write_note(locator, "body", expected_version="abc", writer_identity="mac-runtime")

    assert captured["expected_version"] == "abc"
    assert captured["writer_identity"] == "mac-runtime"


def test_hybrid_port_does_not_fallback_on_capability_error(tmp_path: Path) -> None:
    locator = NoteLocator(vault="Vault", path="Inbox/test.md")

    class PrimaryPort:
        def write_note(self, locator, content):  # type: ignore[no-untyped-def]
            raise KnowledgeCapabilityError("semantic failure")

    fallback = FsVaultAdapter(tmp_path)
    port = HybridKnowledgePort(primary=PrimaryPort(), fallback=fallback, allow_fallback=True)

    with pytest.raises(KnowledgeCapabilityError):
        port.write_note(locator, "body")

    assert not (tmp_path / "Inbox" / "test.md").exists()


def test_hybrid_port_does_not_fallback_on_write_conflict(tmp_path: Path) -> None:
    locator = NoteLocator(vault="Vault", path="Inbox/test.md")

    class PrimaryPort:
        def write_note(self, locator, content):  # type: ignore[no-untyped-def]
            raise KnowledgeWriteConflict("conflict")

    fallback = FsVaultAdapter(tmp_path)
    port = HybridKnowledgePort(primary=PrimaryPort(), fallback=fallback, allow_fallback=True)

    with pytest.raises(KnowledgeWriteConflict):
        port.write_note(locator, "body")

    assert not (tmp_path / "Inbox" / "test.md").exists()
