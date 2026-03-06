from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ObsidianDependencyStatus:
    ok: bool
    cli_present: bool
    installer_ok: bool
    details: dict[str, str]


_SEMVER_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def _parse_semver(value: str) -> tuple[int, int, int] | None:
    match = _SEMVER_RE.search(value)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def obsidian_dependency_status(
    *,
    required_installer: str = "1.12.4",
    cli_name: str = "obsidian",
    which_fn: Callable[[str], str | None] = shutil.which,
    get_installer_version: Callable[[], str | None] | None = None,
) -> ObsidianDependencyStatus:
    cli_path = which_fn(cli_name)
    cli_present = cli_path is not None
    details: dict[str, str] = {"required_installer": required_installer}
    if cli_path:
        details["cli_path"] = cli_path

    required = _parse_semver(required_installer)
    installer_ok = True
    if get_installer_version is not None:
        installed_raw = (get_installer_version() or "").strip()
        details["installer_version"] = installed_raw
        installed = _parse_semver(installed_raw)
        if required is None or installed is None:
            installer_ok = False
        else:
            installer_ok = installed >= required

    return ObsidianDependencyStatus(
        ok=cli_present and installer_ok,
        cli_present=cli_present,
        installer_ok=installer_ok,
        details=details,
    )


__all__ = ["ObsidianDependencyStatus", "obsidian_dependency_status"]
