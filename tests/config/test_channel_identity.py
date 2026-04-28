"""Tests for the channel identity contract.

Verifies that:
- All three canonical channels carry all four required properties.
- ChannelIdentity rejects invalid or incomplete definitions with clear errors.

Authority: docs/RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md
Issue: #610
"""

from __future__ import annotations

import pytest

from app.config.channel import (
    CHANNEL_DEV,
    CHANNEL_STABLE,
    CHANNEL_TEST,
    CHANNELS,
    VALID_CHANNELS,
    ChannelIdentity,
    get_channel,
)


class TestChannelIdentityContract:
    """All canonical channels must carry the four mandatory identity properties."""

    @pytest.mark.parametrize("channel_name", [CHANNEL_STABLE, CHANNEL_DEV, CHANNEL_TEST])
    def test_channel_has_all_four_required_properties(self, channel_name: str) -> None:
        identity = CHANNELS[channel_name]
        assert identity.channel.strip(), "channel must be non-empty"
        assert identity.code_ref.strip(), "code_ref must be non-empty"
        assert identity.db_name.strip(), "db_name must be non-empty"
        assert identity.vault_root.strip(), "vault_root must be non-empty"
        assert identity.runtime_artifact_dir.strip(), "runtime_artifact_dir must be non-empty"

    def test_stable_channel_properties(self) -> None:
        stable = CHANNELS[CHANNEL_STABLE]
        assert stable.db_name == "pkm_prod"
        assert stable.code_ref == "stable"
        assert stable.runtime_artifact_dir == "tmp"

    def test_dev_channel_properties(self) -> None:
        dev = CHANNELS[CHANNEL_DEV]
        assert dev.db_name == "pkm_dev"
        assert dev.vault_root == "vault-dev"
        assert dev.runtime_artifact_dir == "tmp-dev"

    def test_test_channel_properties(self) -> None:
        test = CHANNELS[CHANNEL_TEST]
        assert test.db_name == "pkm_test"
        assert test.vault_root == "vault-test"
        assert test.runtime_artifact_dir == "tmp-test"

    def test_all_three_channels_present(self) -> None:
        assert VALID_CHANNELS == {CHANNEL_STABLE, CHANNEL_DEV, CHANNEL_TEST}
        assert set(CHANNELS.keys()) == VALID_CHANNELS

    def test_db_names_are_distinct_across_channels(self) -> None:
        db_names = [ch.db_name for ch in CHANNELS.values()]
        assert len(db_names) == len(set(db_names)), "each channel must use a distinct DB"

    def test_get_channel_returns_correct_identity(self) -> None:
        for name in (CHANNEL_STABLE, CHANNEL_DEV, CHANNEL_TEST):
            assert get_channel(name) is CHANNELS[name]


class TestChannelIdentityValidation:
    """ChannelIdentity must reject invalid definitions with clear error messages."""

    def test_missing_code_ref_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="code_ref"):
            ChannelIdentity(
                channel=CHANNEL_DEV,
                code_ref="",
                db_name="pkm_dev",
                vault_root="vault-dev",
                runtime_artifact_dir="tmp-dev",
            )

    def test_missing_db_name_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="db_name"):
            ChannelIdentity(
                channel=CHANNEL_DEV,
                code_ref="main",
                db_name="",
                vault_root="vault-dev",
                runtime_artifact_dir="tmp-dev",
            )

    def test_missing_vault_root_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="vault_root"):
            ChannelIdentity(
                channel=CHANNEL_DEV,
                code_ref="main",
                db_name="pkm_dev",
                vault_root="",
                runtime_artifact_dir="tmp-dev",
            )

    def test_missing_runtime_artifact_dir_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="runtime_artifact_dir"):
            ChannelIdentity(
                channel=CHANNEL_DEV,
                code_ref="main",
                db_name="pkm_dev",
                vault_root="vault-dev",
                runtime_artifact_dir="",
            )

    def test_unknown_channel_name_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown channel"):
            ChannelIdentity(
                channel="production",
                code_ref="main",
                db_name="pkm_dev",
                vault_root="vault-dev",
                runtime_artifact_dir="tmp-dev",
            )

    def test_get_channel_unknown_name_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown channel"):
            get_channel("production")

    def test_whitespace_only_property_fails(self) -> None:
        with pytest.raises(ValueError, match="db_name"):
            ChannelIdentity(
                channel=CHANNEL_DEV,
                code_ref="main",
                db_name="   ",
                vault_root="vault-dev",
                runtime_artifact_dir="tmp-dev",
            )
