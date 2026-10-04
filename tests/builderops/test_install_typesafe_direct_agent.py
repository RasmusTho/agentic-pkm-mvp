from __future__ import annotations

import os
from pathlib import Path
import stat

from scripts import install_jev_direct_agent_access


def test_installs_command_and_skill_for_both_agents(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source_root = install_jev_direct_agent_access.ROOT
    command_source = source_root / "scripts" / "ygg_jev.py"
    skill_source = source_root / ".codex" / "skills" / "jev-direct" / "SKILL.md"
    command_destination = home / ".local" / "bin" / "jev-direct"
    skill_destinations = [
        home / ".codex" / "skills" / "jev-direct" / "SKILL.md",
        home / ".claude" / "skills" / "jev-direct" / "SKILL.md",
    ]
    original_environment = dict(os.environ)

    assert install_jev_direct_agent_access.main(["--home", str(home)]) == 0
    assert dict(os.environ) == original_environment
    expected_command = command_source.read_bytes()
    expected_skill = skill_source.read_bytes()
    assert command_destination.read_bytes() == expected_command
    assert stat.S_IMODE(command_destination.stat().st_mode) == 0o755
    assert all(path.read_bytes() == expected_skill for path in skill_destinations)
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o644 for path in skill_destinations)

    first_mtime_ns = command_destination.stat().st_mtime_ns
    assert install_jev_direct_agent_access.main(["--home", str(home)]) == 0
    assert command_destination.read_bytes() == expected_command
    assert command_destination.stat().st_mtime_ns == first_mtime_ns
    assert all(path.read_bytes() == expected_skill for path in skill_destinations)

    assert "TYPESAFE_API_KEY" not in os.environ
