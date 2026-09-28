from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.capture as capture_route
from app.vault import path_overlap
from app.api.app import app
from tests.api._vault_test_helpers import bind_initialized_vault


def _setup_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    bind_initialized_vault(monkeypatch, vault, store_dir=tmp_path)
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Inbox")
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "index-outbox.jsonl"))
    monkeypatch.delenv("VAULT_CAPTURE_NOTE_REL", raising=False)
    monkeypatch.delenv("VAULT_SOURCES_DIR_REL", raising=False)
    return vault


def test_capture_append_adds_separator_when_existing_file_has_no_trailing_newline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    inbox = vault / "Inbox" / "inbox.md"
    inbox.parent.mkdir(parents=True)
    inbox.write_text("- [2026-06-10T08:00:00Z] Existing capture", encoding="utf-8")

    resp = TestClient(app).post(
        "/api/companion/capture",
        json={"text": "Follow-up capture"},
    )

    assert resp.status_code == 200, resp.text
    written = inbox.read_text(encoding="utf-8")
    assert "Existing capture\n- [" in written
    assert "] Follow-up capture\n" in written


def test_capture_append_preserves_empty_and_newline_terminated_inbox_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    client = TestClient(app)
    inbox = vault / "Inbox" / "inbox.md"
    inbox.parent.mkdir(parents=True)
    inbox.write_text("", encoding="utf-8")

    empty_resp = client.post(
        "/api/companion/capture",
        json={"text": "First capture"},
    )

    assert empty_resp.status_code == 200, empty_resp.text
    first_written = inbox.read_text(encoding="utf-8")
    assert first_written.startswith("- [")
    assert "] First capture\n" in first_written

    newline_resp = client.post(
        "/api/companion/capture",
        json={"text": "Second capture"},
    )

    assert newline_resp.status_code == 200, newline_resp.text
    written = inbox.read_text(encoding="utf-8")
    assert "First capture\n- [" in written
    assert "] Second capture\n" in written
    assert "\n\n- [" not in written


@pytest.mark.parametrize(
    ("inbox_rel", "sources_rel", "capture_note_rel", "expected_target"),
    [
        ("Inbox", "Sources", "Sources/capture.md", "Sources/capture.md"),
        ("Inbox", "Sources", r"Sources\capture.md", "Sources/capture.md"),
        ("Sources", "Sources", None, "Sources/inbox.md"),
        (r"Sources\Nested", "Sources", None, "Sources/Nested/inbox.md"),
    ],
    ids=(
        "capture-override-inside-sources",
        "capture-override-normalizes-backslashes",
        "inbox-and-sources-roots-match",
        "inbox-override-normalizes-backslashes",
    ),
)
def test_capture_rejects_sources_zone_overlap_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    inbox_rel: str,
    sources_rel: str,
    capture_note_rel: str | None,
    expected_target: str,
) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", inbox_rel)
    monkeypatch.setenv("VAULT_SOURCES_DIR_REL", sources_rel)
    if capture_note_rel is None:
        monkeypatch.delenv("VAULT_CAPTURE_NOTE_REL", raising=False)
    else:
        monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", capture_note_rel)

    token_issuance: list[object] = []

    def track_token_issuance(**kwargs: object) -> None:
        token_issuance.append(kwargs)

    monkeypatch.setattr(
        capture_route._GOVERNED_WRITE_ADAPTER,
        "issue_decision_token",
        track_token_issuance,
    )

    response = TestClient(app).post(
        "/api/companion/capture",
        json={"text": "This must not enter Sources"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error"] == "capture_sources_overlap"
    assert token_issuance == []
    assert not (vault / expected_target).exists()


def test_capture_allows_disjoint_sources_and_inbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "InboxArchive")
    monkeypatch.setenv("VAULT_SOURCES_DIR_REL", "Inbox")

    response = TestClient(app).post(
        "/api/companion/capture",
        json={"text": "A valid quick capture"},
    )

    assert response.status_code == 200, response.text
    assert (vault / "InboxArchive" / "inbox.md").read_text(encoding="utf-8").endswith(
        "] A valid quick capture\n"
    )
    assert not (vault / "Inbox" / "inbox.md").exists()


@pytest.mark.parametrize("sources_exists", [False, True], ids=("missing", "existing"))
def test_capture_respects_filesystem_case_alias_for_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sources_exists: bool,
) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    if sources_exists:
        (vault / "Sources").mkdir()
    try:
        case_insensitive = os.path.samefile(vault, vault.with_name(vault.name.swapcase()))
    except OSError:
        case_insensitive = False
    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", "sources/capture.md")
    monkeypatch.setenv("VAULT_SOURCES_DIR_REL", "Sources")
    token_issuance: list[object] = []

    def track_token_issuance(**kwargs: object) -> None:
        token_issuance.append(kwargs)

    if case_insensitive:
        monkeypatch.setattr(
            capture_route._GOVERNED_WRITE_ADAPTER,
            "issue_decision_token",
            track_token_issuance,
        )

    response = TestClient(app).post(
        "/api/companion/capture",
        json={"text": "Filesystem aliases must not enter Sources"},
    )

    expected_status = 409 if case_insensitive else 200
    assert response.status_code == expected_status, response.text
    if case_insensitive:
        assert response.json()["detail"]["error"] == "capture_sources_overlap"
        assert token_issuance == []
        assert not (vault / "Sources" / "capture.md").exists()
    else:
        assert (vault / "sources" / "capture.md").exists()


def test_capture_rejects_unicode_normalization_alias_on_apfs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    monkeypatch.setattr(
        path_overlap,
        "_filesystem_name_semantics",
        lambda _path: (False, True, False),
    )
    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", "Ka\u0308llor/capture.md")
    monkeypatch.setenv("VAULT_SOURCES_DIR_REL", "K\u00e4llor")

    token_issuance: list[object] = []

    def track_token_issuance(**kwargs: object) -> None:
        token_issuance.append(kwargs)

    monkeypatch.setattr(
        capture_route._GOVERNED_WRITE_ADAPTER,
        "issue_decision_token",
        track_token_issuance,
    )

    response = TestClient(app).post(
        "/api/companion/capture",
        json={"text": "Unicode-normalized aliases must not enter Sources"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error"] == "capture_sources_overlap"
    assert token_issuance == []
    assert not (vault / "K\u00e4llor" / "capture.md").exists()


def test_unicode_normalization_sensitive_comparison_keeps_names_distinct(
    tmp_path: Path,
) -> None:
    composed = tmp_path / "K\u00e4llor"
    decomposed = tmp_path / "Ka\u0308llor"

    assert not capture_route._same_path_prefix(
        decomposed,
        composed,
        case_insensitive=False,
        normalization_insensitive=False,
    )


@pytest.mark.parametrize(
    ("casefolded", "expected_semantics", "expected_overlap"),
    [
        (True, (True, True, True), True),
        (False, (False, False, False), False),
    ],
    ids=("ext4-casefold-directory", "ext4-case-sensitive-directory"),
)
def test_linux_ext4_uses_exact_lookup_directory_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    casefolded: bool,
    expected_semantics: tuple[bool, bool, bool],
    expected_overlap: bool,
) -> None:
    vault = tmp_path / "vault"
    lookup_dir = vault / "Archive"
    lookup_dir.mkdir(parents=True)
    monkeypatch.setattr(path_overlap.sys, "platform", "linux")
    inspected: list[Path] = []

    def ext4_flag(path: Path) -> bool:
        inspected.append(path)
        return casefolded

    monkeypatch.setattr(path_overlap, "_linux_ext4_casefolded", ext4_flag)
    monkeypatch.setattr(path_overlap, "_probe_case_insensitive_directory", pytest.fail)

    assert capture_route._filesystem_name_semantics(lookup_dir) == expected_semantics
    assert inspected == [lookup_dir.resolve()]

    capture_target = lookup_dir / "sources" / "capture.md"
    sources_root = lookup_dir / "Sources"
    assert capture_route._path_is_within(capture_target, sources_root) is expected_overlap


def test_linux_ext4_does_not_infer_casefold_from_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    casefolded_parent = vault / "Archive"
    lookup_dir = casefolded_parent / "Nested"
    lookup_dir.mkdir(parents=True)
    monkeypatch.setattr(path_overlap.sys, "platform", "linux")
    inspected: list[Path] = []

    def ext4_flag(path: Path) -> bool:
        inspected.append(path)
        return path == casefolded_parent.resolve()

    monkeypatch.setattr(path_overlap, "_linux_ext4_casefolded", ext4_flag)

    assert capture_route._filesystem_name_semantics(lookup_dir) == (False, False, False)
    assert inspected == [lookup_dir.resolve()]


@pytest.mark.parametrize(
    ("casefolded", "expected_semantics", "expected_overlap"),
    [
        (True, (True, True, True), True),
        (False, (False, False, False), False),
    ],
    ids=("inherits-ext4-casefold", "inherits-ext4-case-sensitive"),
)
def test_linux_ext4_missing_lookup_directory_inherits_nearest_existing_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    casefolded: bool,
    expected_semantics: tuple[bool, bool, bool],
    expected_overlap: bool,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    lookup_dir = vault / "Archive"
    monkeypatch.setattr(path_overlap.sys, "platform", "linux")
    inspected: list[Path] = []

    def ext4_flag(path: Path) -> bool:
        inspected.append(path)
        return casefolded

    monkeypatch.setattr(path_overlap, "_linux_ext4_casefolded", ext4_flag)
    assert capture_route._filesystem_name_semantics(lookup_dir) == expected_semantics
    assert inspected == [vault.resolve()]

    inspected.clear()
    capture_target = lookup_dir / "sources" / "capture.md"
    sources_root = lookup_dir / "Sources"
    assert capture_route._path_is_within(capture_target, sources_root) is expected_overlap
    assert inspected == [vault.resolve()]


def test_ext4_casefold_comparison_removes_default_ignorable_characters(
    tmp_path: Path,
) -> None:
    sources = tmp_path / "Sources"
    capture = tmp_path / "Sou\u200brces"

    assert capture_route._same_path_prefix(
        capture,
        sources,
        case_insensitive=True,
        normalization_insensitive=True,
        default_ignorables_insensitive=True,
    )


def test_existing_distinct_paths_override_unknown_normalization_comparison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composed = tmp_path / "K\u00e4llor"
    decomposed = tmp_path / "Ka\u0308llor"
    composed.mkdir()
    if not decomposed.exists():
        decomposed.mkdir()
    monkeypatch.setattr(capture_route.os.path, "samefile", lambda _left, _right: False)

    assert not capture_route._same_path_prefix(
        decomposed,
        composed,
        case_insensitive=False,
        normalization_insensitive=True,
        default_ignorables_insensitive=False,
    )


def test_capture_rejects_default_ignorable_alias_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    monkeypatch.setattr(
        path_overlap,
        "_filesystem_name_semantics",
        lambda _path: (True, True, True),
    )
    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", "Sou\u200brces/capture.md")
    monkeypatch.setenv("VAULT_SOURCES_DIR_REL", "Sources")
    token_issuance: list[object] = []

    def track_token_issuance(**kwargs: object) -> None:
        token_issuance.append(kwargs)

    monkeypatch.setattr(
        capture_route._GOVERNED_WRITE_ADAPTER,
        "issue_decision_token",
        track_token_issuance,
    )

    response = TestClient(app).post(
        "/api/companion/capture",
        json={"text": "Default-ignorable aliases must not enter Sources"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error"] == "capture_sources_overlap"
    assert token_issuance == []
    assert not (vault / "Sources" / "capture.md").exists()


def test_capture_rejects_sources_symlink_alias_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    sources = vault / "Archive" / "Sources"
    sources.mkdir(parents=True)
    (vault / "SourcesAlias").symlink_to(sources, target_is_directory=True)
    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", "SourcesAlias/capture.md")
    monkeypatch.setenv("VAULT_SOURCES_DIR_REL", "Archive/Sources")

    token_issuance: list[object] = []

    def track_token_issuance(**kwargs: object) -> None:
        token_issuance.append(kwargs)

    monkeypatch.setattr(
        capture_route._GOVERNED_WRITE_ADAPTER,
        "issue_decision_token",
        track_token_issuance,
    )

    response = TestClient(app).post(
        "/api/companion/capture",
        json={"text": "This symlink must not enter Sources"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error"] == "capture_sources_overlap"
    assert token_issuance == []
    assert not (sources / "capture.md").exists()


@pytest.mark.parametrize(
    "settings_yaml",
    [
        "---\npaths:\n  sources_dir_rel: ../Sources\n---\n",
        "---\npaths: []\n---\n",
    ],
    ids=("invalid-source-path", "invalid-paths-container"),
)
def test_capture_fails_closed_for_malformed_sources_setting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_yaml: str,
) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    settings_file = vault / "settings" / "system-settings.md"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(settings_yaml, encoding="utf-8")

    token_issuance: list[object] = []

    def track_token_issuance(**kwargs: object) -> None:
        token_issuance.append(kwargs)

    monkeypatch.setattr(
        capture_route._GOVERNED_WRITE_ADAPTER,
        "issue_decision_token",
        track_token_issuance,
    )

    response = TestClient(app).post(
        "/api/companion/capture",
        json={"text": "Invalid Sources settings must refuse"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error"] == "sources_zone_unresolved"
    assert token_issuance == []
    assert not (vault / "Inbox" / "inbox.md").exists()


@pytest.mark.parametrize("document", ["[]", "false", "0", "null"])
def test_capture_fails_closed_for_non_mapping_sources_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    document: str,
) -> None:
    vault = _setup_vault(tmp_path, monkeypatch)
    settings_file = vault / "settings" / "system-settings.md"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(f"---\n{document}\n---\n", encoding="utf-8")

    token_issuance: list[object] = []

    def track_token_issuance(**kwargs: object) -> None:
        token_issuance.append(kwargs)

    monkeypatch.setattr(
        capture_route._GOVERNED_WRITE_ADAPTER,
        "issue_decision_token",
        track_token_issuance,
    )

    response = TestClient(app).post(
        "/api/companion/capture",
        json={"text": "Non-mapping Sources settings must refuse"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error"] == "sources_zone_unresolved"
    assert token_issuance == []
    assert not (vault / "Inbox" / "inbox.md").exists()
