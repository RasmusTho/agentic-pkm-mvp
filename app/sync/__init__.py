"""Sync layer abstraction for transport-agnostic file change detection and synchronization.

Decouples file-change detection from transport mechanism (filesystem, git, iCloud, etc).
Provides a unified interface for Watcher and Worker to operate across different sync transports.
"""

from app.sync.base import FileChange, FileOperation, SyncLayer, SyncResult, SyncStatus
from app.sync.factory import get_sync_layer
from app.sync.filesystem import FilesystemTransport
from app.sync.git import GitTransport

__all__ = [
    "FileChange",
    "FileOperation",
    "SyncResult",
    "SyncStatus",
    "SyncLayer",
    "FilesystemTransport",
    "GitTransport",
    "get_sync_layer",
]
