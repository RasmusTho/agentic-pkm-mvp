"""Factory for creating SyncLayer instances based on configuration."""

from __future__ import annotations

import logging
import os
from typing import Any

from app.sync.base import SyncLayer
from app.sync.filesystem import FilesystemTransport
from app.sync.git import GitTransport

logger = logging.getLogger(__name__)


def get_sync_layer(
    layer_type: str | None = None,
    **config: Any,
) -> SyncLayer:
    """Create a SyncLayer instance based on type.

    Args:
        layer_type: Type of sync layer (filesystem, git). Defaults to SYNC_LAYER env var or filesystem.
        **config: Additional configuration to pass to the transport

    Returns:
        SyncLayer instance (FilesystemTransport, GitTransport, etc.)
    """
    if layer_type is None:
        layer_type = os.getenv("SYNC_LAYER", "filesystem").lower()

    if layer_type == "git":
        return GitTransport(
            branch=config.get("branch", "main"),
            remote=config.get("remote", "origin"),
            auto_commit=config.get("auto_commit", False),
        )
    elif layer_type == "filesystem":
        return FilesystemTransport(
            ignore_patterns=config.get("ignore_patterns", None),
            use_mtime=config.get("use_mtime", True),
        )
    else:
        logger.warning(f"Unknown sync layer {layer_type}, using filesystem")
        return FilesystemTransport(
            ignore_patterns=config.get("ignore_patterns", None),
            use_mtime=config.get("use_mtime", True),
        )
