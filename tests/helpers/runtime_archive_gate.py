"""Value-free fake-host producer for the HAR-03 production startup gate."""

from __future__ import annotations

from pathlib import Path
import stat
import sys


def configure_ready_archive_gate(
    env: dict[str, str],
    tmp_path: Path,
) -> Path:
    """Make one production-launcher fixture prove the archive gate ran first."""
    metadata_path = tmp_path / "archive-metadata.json"
    metadata_path.write_text("{}\n", encoding="utf-8")
    metadata_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    marker_path = tmp_path / "archive-gate-ready"
    python_path = tmp_path / "archive-gate-python"
    python_path.write_text(
        """#!{python}
from __future__ import annotations

import os
from pathlib import Path
import sys

if sys.argv[1:3] == ["-m", "app.ops.heimdal_cold_volume"] and len(sys.argv) >= 4 and sys.argv[3] == "require-ready":
    marker = Path(os.environ["HAR03_ARCHIVE_GATE_FIXTURE_PATH"])
    marker.write_text("ready\\n", encoding="utf-8")
    progress = os.environ.get("STARTUP_HARNESS_PROGRESS_PATH")
    if progress:
        with Path(progress).open("a", encoding="utf-8") as handle:
            handle.write("archive-gate-ready\\n")
    raise SystemExit(0)

os.execv({python!r}, [{python!r}, *sys.argv[1:]])
""".format(python=sys.executable),
        encoding="utf-8",
    )
    python_path.chmod(python_path.stat().st_mode | stat.S_IXUSR)
    env.update(
        {
            "HEIMDAL_ARCHIVE_METADATA_FILE": str(metadata_path),
            "HAR03_ARCHIVE_GATE_FIXTURE_PATH": str(marker_path),
            "PYTHON": str(python_path),
        }
    )
    return marker_path


def assert_archive_gate_preceded_host_mutation(
    marker_path: Path,
    progress_path: Path,
) -> None:
    """Prove the fake ready decision preceded every recorded Docker mutation."""
    assert marker_path.read_text(encoding="utf-8") == "ready\n"
    events = progress_path.read_text(encoding="utf-8").splitlines()
    gate_index = events.index("archive-gate-ready")
    docker_indexes = [index for index, event in enumerate(events) if event.startswith("docker ")]
    assert docker_indexes
    assert gate_index < min(docker_indexes)
