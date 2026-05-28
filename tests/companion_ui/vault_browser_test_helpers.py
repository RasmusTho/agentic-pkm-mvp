from __future__ import annotations

from typing import Any


def default_vault_browser_payload() -> dict[str, Any]:
    return {
        "notes": [],
        "query": "",
        "total_notes": 0,
        "filtered_notes": 0,
        "read_only": True,
        "vault_identity": {
            "vault_name": "Niflheim",
            "channel": "dev",
            "provenance": "test",
        },
        "identity_available": True,
        "active_filters": {},
    }


def is_vault_browser_get(url: str) -> bool:
    return url == "/api/companion/vault-browser" or url.endswith(
        "/api/companion/vault-browser"
    )
