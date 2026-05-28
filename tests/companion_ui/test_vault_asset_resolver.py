from companion_ui.renderer.asset_resolver import VaultAssetResolver


def test_allowed() -> None:
    resolver = VaultAssetResolver({"test-image.png": "/api/assets/test-image.png"})

    result = resolver.resolve(
        {
            "notePath": "Notes/Current.md",
            "rawTarget": "![[test-image.png|100x145]]",
            "kind": "obsidian-embed",
        }
    )

    assert result.kind == "allowed"
    assert result.src == "/api/assets/test-image.png"
    assert result.display_name == "test-image.png"
    assert result.width == 100
    assert result.height == 145


def test_missing() -> None:
    resolver = VaultAssetResolver({"test-image.png": "/api/assets/test-image.png"})

    result = resolver.resolve(
        note_path="Notes/Current.md",
        raw_target="missing.png",
        kind="markdown-image",
    )

    assert result.kind == "missing"
    assert result.display_name == "missing.png"
    assert result.reason


def test_blocked_remote() -> None:
    resolver = VaultAssetResolver({"test-image.png": "/api/assets/test-image.png"})

    result = resolver.resolve(
        note_path="Notes/Current.md",
        raw_target="![[https://external.example.com/file.png]]",
        kind="obsidian-embed",
    )

    assert result.kind == "blocked"
    assert result.src is None
    assert result.reason


def test_unsupported() -> None:
    resolver = VaultAssetResolver({"test-image.png": "/api/assets/test-image.png"})

    result = resolver.resolve(
        {
            "notePath": "Notes/Current.md",
            "rawTarget": "![[document.pdf]]",
            "kind": "obsidian-embed",
        }
    )

    assert result.kind == "unsupported"
    assert result.display_name == "document.pdf"
    assert result.reason


def test_no_file_urls() -> None:
    resolver = VaultAssetResolver(
        {
            "test-image.png": "file:///Users/rasmusthornberg/vault/test-image.png",
            "safe-image.png": None,
        }
    )

    blocked = resolver.resolve(
        note_path="Notes/Current.md",
        raw_target="![[test-image.png]]",
        kind="obsidian-embed",
    )
    allowed = resolver.resolve(
        note_path="Notes/Current.md",
        raw_target="![[safe-image.png]]",
        kind="obsidian-embed",
    )

    assert blocked.kind == "blocked"
    assert blocked.src is None
    assert allowed.kind == "allowed"
    assert allowed.src is not None
    assert not allowed.src.startswith("file://")
    assert "file://" not in str(blocked.to_dict())
    assert "file://" not in str(allowed.to_dict())
