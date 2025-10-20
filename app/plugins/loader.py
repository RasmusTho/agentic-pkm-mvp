from __future__ import annotations

from importlib import import_module
from typing import Mapping, Sequence

from .base import Tool


def load_tools(names: Sequence[str]) -> Mapping[str, Tool]:
    registry: dict[str, Tool] = {}
    for raw_name in names:
        module_name = f"app.plugins.{raw_name}"
        module = import_module(module_name)
        tool = getattr(module, "tool", None)
        if tool is None:
            raise ValueError(f"Tool '{raw_name}' did not expose a `tool` instance.")
        registry[raw_name] = tool
    return registry
