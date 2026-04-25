"""Local Agent Issue Dispatcher MVP.

Operational coordination layer for multi-agent issue pickup. See
``docs/AGENT_ISSUE_DISPATCHER.md`` for the contract.
"""

from app.dispatcher import leases, queue
from app.dispatcher.config import DispatcherPaths, load_paths
from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.models import EventRecord, LeaseRecord, SyncState, TaskRecord
from app.dispatcher.store import DispatcherStore, SqliteStore

__all__ = [
    "DispatcherPaths",
    "DispatcherStore",
    "EventRecord",
    "JsonlEventWriter",
    "LeaseRecord",
    "SqliteStore",
    "SyncState",
    "TaskRecord",
    "leases",
    "load_paths",
    "queue",
]
