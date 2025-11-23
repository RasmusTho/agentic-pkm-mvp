from pathlib import Path

# Alpha-only default vault root for the PKM - Alpha Obsidian vault.
# TODO: replace this hard-coded path with settings-driven configuration when we leave alpha.
DEFAULT_VAULT_ROOT = Path(
    "/Users/rasmus/Library/Mobile Documents/iCloud~md~obsidian/Documents/PKM - Alpha"
)

__all__ = ["DEFAULT_VAULT_ROOT"]
