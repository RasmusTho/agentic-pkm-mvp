from __future__ import annotations

import pytest

from app.knowledge.obsidian_cli_scope import has_valid_vault_scope, scoped_cli_args


def test_scoped_cli_args_puts_vault_scope_first() -> None:
    argv = scoped_cli_args("Mimer", ["read", "Inbox/Note.md"])
    assert argv[0] == "vault=Mimer"
    assert argv[1:] == ["read", "Inbox/Note.md"]


def test_scoped_cli_args_requires_vault() -> None:
    with pytest.raises(ValueError):
        scoped_cli_args(" ", ["read", "Inbox/Note.md"])


def test_has_valid_vault_scope_accepts_first_arg() -> None:
    assert has_valid_vault_scope(["vault=Mimer", "read", "Inbox/Note.md"]) is True


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["read", "Inbox/Note.md"],
        ["vault=", "read", "Inbox/Note.md"],
        ["--json", "vault=Mimer", "read", "Inbox/Note.md"],
    ],
)
def test_has_valid_vault_scope_rejects_invalid_position_or_value(argv: list[str]) -> None:
    assert has_valid_vault_scope(argv) is False
