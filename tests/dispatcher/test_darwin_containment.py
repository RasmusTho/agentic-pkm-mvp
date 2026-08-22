from __future__ import annotations

import pytest

from app.dispatcher.darwin_containment import (
    DARWIN_LAUNCHD_COALITION_PROFILE,
    select_verification_containment,
)
from app.dispatcher.linux_containment import (
    LINUX_SYSTEMD_CGROUP_V2_SCOPE_PROFILE,
)


def test_darwin_profile_contract_remains_fail_closed() -> None:
    for profile, platform in (
        (None, "darwin"),
        ("automatic", "darwin"),
        (LINUX_SYSTEMD_CGROUP_V2_SCOPE_PROFILE, "darwin"),
        (DARWIN_LAUNCHD_COALITION_PROFILE, "linux"),
    ):
        with pytest.raises(ValueError):
            select_verification_containment(profile, platform=platform)
