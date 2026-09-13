"""Load only the committed #4836 constrained-reuse candidate assets."""

from pathlib import Path

from app.builderops.devui_assets import load_asset

_CANDIDATE_ROOT = Path(__file__).with_name("devui_candidate")


def load_devui_candidate_asset(path: str) -> tuple[str, bytes] | None:
    return load_asset(_CANDIDATE_ROOT, path)


__all__ = ["load_devui_candidate_asset"]
