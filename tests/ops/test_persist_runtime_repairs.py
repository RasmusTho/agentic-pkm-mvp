from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_persist_runtime_repairs_updates_dotenv(tmp_path) -> None:
    status_path = tmp_path / "startup_status.json"
    env_path = tmp_path / ".env"
    status_path.write_text(
        json.dumps(
            {
                "ollama_endpoint_drift": True,
                "ollama_effective_base_url": "http://host.docker.internal:11434",
            }
        ),
        encoding="utf-8",
    )
    env_path.write_text("OLLAMA_URL=http://100.86.38.44:11434\n", encoding="utf-8")

    subprocess.run(
        ["bash", "scripts/persist_runtime_repairs.sh"],
        check=True,
        cwd=Path.cwd(),
        env={
            "PATH": str(Path("/usr/bin")) + ":" + str(Path("/bin")) + ":" + str(Path("/usr/local/bin")),
            "STARTUP_STATUS_PATH": str(status_path),
            "ENV_PATH": str(env_path),
        },
        capture_output=True,
        text=True,
    )

    text = env_path.read_text(encoding="utf-8")
    assert "OLLAMA_URL=http://host.docker.internal:11434" in text
    assert "OLLAMA_HOST=http://host.docker.internal:11434" in text
