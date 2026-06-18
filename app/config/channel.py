"""Channel identity contract for the release-channel model.

Each release channel is identified by four mandatory properties that together
define exactly what is running and where. This module declares the contract
and the three canonical channels (stable, dev, test).

The channel layer is orthogonal to the existing dev/prod environment layer:
- environment (PKM_ENVIRONMENT) selects the code-execution path and settings profile.
- channel names the operational build and its storage/artifact roots.

Authority: docs/RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md
"""

from __future__ import annotations

from dataclasses import dataclass


CHANNEL_STABLE = "stable"
CHANNEL_DEV = "dev"
CHANNEL_TEST = "test"

VALID_CHANNELS = frozenset({CHANNEL_STABLE, CHANNEL_DEV, CHANNEL_TEST})


@dataclass(frozen=True)
class ChannelIdentity:
    """The four mandatory identity properties of a release channel.

    All four properties are required and must be non-empty strings.
    Together they answer: what is running, against which DB, in which vault,
    and where are the runtime artifacts?
    """

    channel: str
    code_ref: str
    db_name: str
    vault_root: str
    runtime_artifact_dir: str

    def __post_init__(self) -> None:
        missing = [
            f for f in ("channel", "code_ref", "db_name", "vault_root", "runtime_artifact_dir")
            if not getattr(self, f, "").strip()
        ]
        if missing:
            raise ValueError(
                f"ChannelIdentity requires non-empty values for: {', '.join(missing)}"
            )
        if self.channel not in VALID_CHANNELS:
            raise ValueError(
                f"Unknown channel {self.channel!r}; must be one of {sorted(VALID_CHANNELS)}"
            )


# Canonical channel definitions.
# vault_root is operator-configured for every channel (the VAULT_ROOT env var):
# the vault that backs a channel is one of the operator's own Obsidian vaults
# (e.g. dev/test/prod), whose names can change and must never be hardcoded. The
# placeholder only makes the identity inspectable before operator configuration.
STABLE = ChannelIdentity(
    channel=CHANNEL_STABLE,
    code_ref="stable",
    db_name="pkm_prod",
    vault_root="<operator-configured>",
    runtime_artifact_dir="tmp",
)

DEV = ChannelIdentity(
    channel=CHANNEL_DEV,
    code_ref="main",
    db_name="pkm_dev",
    vault_root="<operator-configured>",
    runtime_artifact_dir="tmp-dev",
)

TEST = ChannelIdentity(
    channel=CHANNEL_TEST,
    code_ref="<worktree>",
    db_name="pkm_test",
    vault_root="<operator-configured>",
    runtime_artifact_dir="tmp-test",
)

CHANNELS: dict[str, ChannelIdentity] = {
    CHANNEL_STABLE: STABLE,
    CHANNEL_DEV: DEV,
    CHANNEL_TEST: TEST,
}


def get_channel(name: str) -> ChannelIdentity:
    """Return the ChannelIdentity for the given channel name.

    Raises:
        ValueError: If the channel name is not one of stable, dev, test.
    """
    if name not in CHANNELS:
        raise ValueError(
            f"Unknown channel {name!r}; must be one of {sorted(VALID_CHANNELS)}"
        )
    return CHANNELS[name]


__all__ = [
    "CHANNEL_DEV",
    "CHANNEL_STABLE",
    "CHANNEL_TEST",
    "CHANNELS",
    "VALID_CHANNELS",
    "ChannelIdentity",
    "DEV",
    "STABLE",
    "TEST",
    "get_channel",
]
