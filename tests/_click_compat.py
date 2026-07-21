"""Click-version-tolerant CliRunner construction.

Click 8.2 removed ``CliRunner``'s ``mix_stderr`` parameter: ``Result`` now
always exposes both ``.output`` (stdout+stderr merged, in write order) and
``.stderr`` (isolated) regardless of capture mode, so the flag became a
no-op and was dropped. ``cli_runner()`` requests the old explicit behavior
when the installed Click still accepts it and falls back to the
(equivalent) default otherwise, so call sites work unchanged across the
CI-pinned Click 8.1.x and Click 8.2+.
"""

from __future__ import annotations

from click.testing import CliRunner


def cli_runner(*, mix_stderr: bool = True) -> CliRunner:
    try:
        return CliRunner(mix_stderr=mix_stderr)
    except TypeError:
        return CliRunner()
