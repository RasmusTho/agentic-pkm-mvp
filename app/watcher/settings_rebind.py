"""Dormant SETTINGS-05B reconciliation for the production registry watcher.

The durable instance-state record is transition authority.  This module never
prepares or commits a revision and never resolves or scans the candidate root.
It only brackets an already-prepared/committed revision with scans of the
watcher's captured old root and keeps an atomic restart journal for the old-root
observation buffer and receipts.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

from app.instance._storage_boundary import RegistryError
from app.instance.filesystem_identity import (
    resolve_filesystem_root_identity,
    same_filesystem_root,
)
from app.instance.settings_rebind import SettingsRebindRecord, SettingsRebindStore
from app.instance.vault_registry import RegistrySnapshot, VaultRegistryStore

if TYPE_CHECKING:
    from app.watcher.registry import RegistryConfig
    from app.watcher.state import WatcherState


SETTINGS_REBIND_WATCHER_SCHEMA = "settings_rebind_watcher.v1"
SETTINGS_REBIND_WATCHER_FILENAME = "settings-rebind-watcher.json"
_STAGES = {"acknowledged", "drained", "completed"}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _checksum(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_text(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise RegistryError(f"settings rebind watcher {name} is invalid")
    return value


def _optional_text(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, name=name)


def _revision(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RegistryError("settings rebind watcher desired revision is invalid")
    return value


def _mtime(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RegistryError("settings rebind watcher observation mtime is invalid")
    return float(value)


@dataclass(frozen=True)
class BufferedObservation:
    watcher: str
    relative_path: str
    content_hash: str
    mtime: float
    trace_id: str | None

    def as_payload(self) -> dict[str, object]:
        return {
            "watcher": self.watcher,
            "relativePath": self.relative_path,
            "contentHash": self.content_hash,
            "mtime": self.mtime,
            "traceId": self.trace_id,
        }

    @classmethod
    def from_payload(cls, value: object) -> BufferedObservation:
        if not isinstance(value, dict) or set(value) != {
            "watcher",
            "relativePath",
            "contentHash",
            "mtime",
            "traceId",
        }:
            raise RegistryError("settings rebind watcher buffer entry is invalid")
        mtime = value["mtime"]
        return cls(
            watcher=_required_text(value["watcher"], name="observation watcher"),
            relative_path=_required_text(
                value["relativePath"], name="observation relative path"
            ),
            content_hash=_required_text(
                value["contentHash"], name="observation content hash"
            ),
            mtime=_mtime(mtime),
            trace_id=_optional_text(value["traceId"], name="observation trace id"),
        )


@dataclass(frozen=True)
class RebindScanReceipt:
    scan_kind: str
    desired_revision: int
    observed_at: str
    watcher_ticks: dict[str, int]

    def as_payload(self) -> dict[str, object]:
        return {
            "scanKind": self.scan_kind,
            "desiredRevision": self.desired_revision,
            "observedAt": self.observed_at,
            "watcherTicks": dict(sorted(self.watcher_ticks.items())),
        }

    @classmethod
    def from_payload(cls, value: object) -> RebindScanReceipt:
        if not isinstance(value, dict) or set(value) != {
            "scanKind",
            "desiredRevision",
            "observedAt",
            "watcherTicks",
        }:
            raise RegistryError("settings rebind watcher scan receipt is invalid")
        scan_kind = value["scanKind"]
        if scan_kind not in {"pre_commit", "post_commit"}:
            raise RegistryError("settings rebind watcher scan kind is invalid")
        raw_ticks = value["watcherTicks"]
        if not isinstance(raw_ticks, dict):
            raise RegistryError("settings rebind watcher tick receipt is invalid")
        ticks: dict[str, int] = {}
        for name, count in raw_ticks.items():
            if (
                not isinstance(name, str)
                or not name
                or not isinstance(count, int)
                or isinstance(count, bool)
                or count < 0
            ):
                raise RegistryError("settings rebind watcher tick receipt is invalid")
            ticks[name] = count
        return cls(
            scan_kind=scan_kind,
            desired_revision=_revision(value["desiredRevision"]),
            observed_at=_required_text(value["observedAt"], name="scan timestamp"),
            watcher_ticks=ticks,
        )


@dataclass(frozen=True)
class SettingsRebindWatcherReceipt:
    desired_revision: int
    prior_binding_id: str
    candidate_binding_id: str
    stage: str
    buffer: tuple[BufferedObservation, ...]
    acknowledgement: RebindScanReceipt | None
    drain_receipt: RebindScanReceipt | None
    resume_ready_at: str | None

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": SETTINGS_REBIND_WATCHER_SCHEMA,
            "desiredRevision": self.desired_revision,
            "priorBindingId": self.prior_binding_id,
            "candidateBindingId": self.candidate_binding_id,
            "stage": self.stage,
            "buffer": [item.as_payload() for item in self.buffer],
            "acknowledgement": (
                self.acknowledgement.as_payload()
                if self.acknowledgement is not None
                else None
            ),
            "drainReceipt": (
                self.drain_receipt.as_payload()
                if self.drain_receipt is not None
                else None
            ),
            "resumeReadyAt": self.resume_ready_at,
        }
        payload["checksum"] = _checksum(payload)
        return payload

    @classmethod
    def from_payload(cls, value: object) -> SettingsRebindWatcherReceipt:
        fields = {
            "schema",
            "desiredRevision",
            "priorBindingId",
            "candidateBindingId",
            "stage",
            "buffer",
            "acknowledgement",
            "drainReceipt",
            "resumeReadyAt",
            "checksum",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise RegistryError("settings rebind watcher receipt shape is invalid")
        if value["schema"] != SETTINGS_REBIND_WATCHER_SCHEMA:
            raise RegistryError("settings rebind watcher receipt schema is invalid")
        checksum = value["checksum"]
        expected = _checksum({key: item for key, item in value.items() if key != "checksum"})
        if not isinstance(checksum, str) or checksum != expected:
            raise RegistryError("settings rebind watcher receipt checksum is invalid")
        stage = value["stage"]
        if stage not in _STAGES:
            raise RegistryError("settings rebind watcher receipt stage is invalid")
        raw_buffer = value["buffer"]
        if not isinstance(raw_buffer, list):
            raise RegistryError("settings rebind watcher buffer is invalid")
        acknowledgement = (
            RebindScanReceipt.from_payload(value["acknowledgement"])
            if value["acknowledgement"] is not None
            else None
        )
        drain_receipt = (
            RebindScanReceipt.from_payload(value["drainReceipt"])
            if value["drainReceipt"] is not None
            else None
        )
        if acknowledgement is None:
            raise RegistryError("settings rebind watcher acknowledgement is missing")
        if stage in {"drained", "completed"} and drain_receipt is None:
            raise RegistryError("settings rebind watcher drain receipt is missing")
        resume_ready_at = _optional_text(
            value["resumeReadyAt"], name="resume-ready timestamp"
        )
        if stage == "completed" and resume_ready_at is None:
            raise RegistryError("settings rebind watcher resume receipt is missing")
        desired_revision = _revision(value["desiredRevision"])
        for scan in (acknowledgement, drain_receipt):
            if scan is not None and scan.desired_revision != desired_revision:
                raise RegistryError("settings rebind watcher receipt revisions disagree")
        return cls(
            desired_revision=desired_revision,
            prior_binding_id=_required_text(
                value["priorBindingId"], name="prior binding"
            ),
            candidate_binding_id=_required_text(
                value["candidateBindingId"], name="candidate binding"
            ),
            stage=stage,
            buffer=tuple(BufferedObservation.from_payload(item) for item in raw_buffer),
            acknowledgement=acknowledgement,
            drain_receipt=drain_receipt,
            resume_ready_at=resume_ready_at,
        )


def load_settings_rebind_watcher_receipt(path: Path) -> SettingsRebindWatcherReceipt:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise RegistryError("settings rebind watcher receipt is unreadable") from exc
    return SettingsRebindWatcherReceipt.from_payload(payload)


def _write_receipt(path: Path, receipt: SettingsRebindWatcherReceipt) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(
        receipt.as_payload(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temp_path = Path(temp_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=True) as handle:
            handle.write(rendered)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _rebind_fault_point(stage: str) -> None:
    """Test seam for crash recovery; production has no fault injection control."""

    del stage


@dataclass(frozen=True)
class RebindCycle:
    record: SettingsRebindRecord
    mode: str
    receipt: SettingsRebindWatcherReceipt | None


class DormantSettingsRebindReconciler:
    def __init__(self, *, registry_path: Path, receipt_path: Path) -> None:
        self._registry = VaultRegistryStore(registry_path)
        self._store = SettingsRebindStore(self._registry)
        self.receipt_path = receipt_path

    @classmethod
    def from_config(
        cls,
        cfg: RegistryConfig,
    ) -> DormantSettingsRebindReconciler | None:
        registry_value = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
        if not registry_value:
            return None
        return cls(
            registry_path=Path(registry_value).expanduser(),
            receipt_path=cfg.state_dir / SETTINGS_REBIND_WATCHER_FILENAME,
        )

    def begin_cycle(self, cfg: RegistryConfig) -> RebindCycle:
        snapshot = self._registry.load()
        if snapshot.settings_rebind is None:
            raise RegistryError("settings rebind record is not installed")
        record = SettingsRebindRecord.from_payload(snapshot.settings_rebind)
        if record.phase == "dormant":
            return RebindCycle(record=record, mode="dormant", receipt=None)
        if record.phase == "no_lifecycle":
            return RebindCycle(record=record, mode="no_lifecycle", receipt=None)
        self._validate_record_bindings(record)
        if not cfg.enable:
            if record.phase != "prepared":
                raise RegistryError(
                    "disabled watcher encountered a committed settings rebind revision"
                )
            acknowledged = self._store.acknowledge_no_lifecycle(
                desired_revision=record.desired_revision
            )
            return RebindCycle(
                record=acknowledged,
                mode="no_lifecycle",
                receipt=None,
            )
        self._validate_old_root(snapshot, record, cfg)
        receipt = self._load_matching_receipt(record)
        if record.phase == "prepared":
            if receipt is not None and receipt.stage != "acknowledged":
                raise RegistryError(
                    "prepared settings rebind has an invalid watcher receipt stage"
                )
            return RebindCycle(record=record, mode="prepared", receipt=receipt)
        if record.phase != "committed":
            raise RegistryError("settings rebind watcher phase is unsupported")
        if receipt is None:
            raise RegistryError(
                "committed settings rebind has no durable watcher acknowledgement"
            )
        _rebind_fault_point("commit")
        return RebindCycle(record=record, mode="committed", receipt=receipt)

    def finish_cycle(
        self,
        cycle: RebindCycle,
        *,
        summaries: Mapping[str, Mapping[str, object]],
        states: Mapping[str, WatcherState],
    ) -> SettingsRebindWatcherReceipt | None:
        if cycle.mode not in {"prepared", "committed"}:
            return cycle.receipt
        self._assert_scan_success(summaries)
        observations = self._observations(summaries, states=states)
        watcher_ticks = {
            name: state.ticks_run
            for name, state in states.items()
        }
        if cycle.mode == "prepared":
            if cycle.receipt is not None:
                return cycle.receipt
            self._assert_authority_unchanged(cycle)
            _rebind_fault_point("acknowledge")
            receipt = SettingsRebindWatcherReceipt(
                desired_revision=cycle.record.desired_revision,
                prior_binding_id=self._required_binding(
                    cycle.record.prior_binding_id, name="prior"
                ),
                candidate_binding_id=self._required_binding(
                    cycle.record.candidate_binding_id, name="candidate"
                ),
                stage="acknowledged",
                buffer=observations,
                acknowledgement=RebindScanReceipt(
                    scan_kind="pre_commit",
                    desired_revision=cycle.record.desired_revision,
                    observed_at=_now_iso(),
                    watcher_ticks=watcher_ticks,
                ),
                drain_receipt=None,
                resume_ready_at=None,
            )
            _write_receipt(self.receipt_path, receipt)
            return receipt

        assert cycle.receipt is not None
        if cycle.receipt.stage == "completed":
            return cycle.receipt
        if cycle.receipt.stage == "drained":
            self._assert_authority_unchanged(cycle)
            _rebind_fault_point("resume")
            completed = replace(
                cycle.receipt,
                stage="completed",
                resume_ready_at=_now_iso(),
            )
            _write_receipt(self.receipt_path, completed)
            return completed
        self._assert_authority_unchanged(cycle)
        _rebind_fault_point("drain")
        drained = replace(
            cycle.receipt,
            stage="drained",
            buffer=self._merge_buffer(cycle.receipt.buffer, observations),
            drain_receipt=RebindScanReceipt(
                scan_kind="post_commit",
                desired_revision=cycle.record.desired_revision,
                observed_at=_now_iso(),
                watcher_ticks=watcher_ticks,
            ),
        )
        _write_receipt(self.receipt_path, drained)
        _rebind_fault_point("resume")
        completed = replace(
            drained,
            stage="completed",
            resume_ready_at=_now_iso(),
        )
        _write_receipt(self.receipt_path, completed)
        return completed

    def _load_matching_receipt(
        self,
        record: SettingsRebindRecord,
    ) -> SettingsRebindWatcherReceipt | None:
        if not self.receipt_path.exists():
            return None
        receipt = load_settings_rebind_watcher_receipt(self.receipt_path)
        expected_prior = self._required_binding(record.prior_binding_id, name="prior")
        expected_candidate = self._required_binding(
            record.candidate_binding_id, name="candidate"
        )
        if (
            receipt.desired_revision != record.desired_revision
            or receipt.prior_binding_id != expected_prior
            or receipt.candidate_binding_id != expected_candidate
        ):
            raise RegistryError("settings rebind watcher receipt does not match durable authority")
        return receipt

    @staticmethod
    def _validate_old_root(
        snapshot: RegistrySnapshot,
        record: SettingsRebindRecord,
        cfg: RegistryConfig,
    ) -> None:
        prior = DormantSettingsRebindReconciler._required_binding(
            record.prior_binding_id, name="prior"
        )
        registration = snapshot.registrations.get(prior)
        if registration is None:
            raise RegistryError("settings rebind prior watcher binding is missing")
        configured = resolve_filesystem_root_identity(cfg.vault_path)
        expected = resolve_filesystem_root_identity(registration.path)
        if not same_filesystem_root(configured, expected):
            raise RegistryError("settings rebind watcher is not bound to the durable prior root")

    @staticmethod
    def _validate_record_bindings(record: SettingsRebindRecord) -> None:
        prior = DormantSettingsRebindReconciler._required_binding(
            record.prior_binding_id, name="prior"
        )
        candidate = DormantSettingsRebindReconciler._required_binding(
            record.candidate_binding_id, name="candidate"
        )
        if prior == candidate:
            raise RegistryError(
                "settings rebind watcher requires distinct old and candidate bindings"
            )

    def _assert_authority_unchanged(self, cycle: RebindCycle) -> None:
        current = self._store.read()
        if current != cycle.record:
            raise RegistryError(
                "settings rebind authority changed during the watcher scan"
            )

    @staticmethod
    def _required_binding(value: str | None, *, name: str) -> str:
        if value is None:
            raise RegistryError(f"settings rebind watcher {name} binding is missing")
        return value

    @staticmethod
    def _assert_scan_success(
        summaries: Mapping[str, Mapping[str, object]],
    ) -> None:
        for name, summary in summaries.items():
            if name in {"briefing", "journal_review"}:
                continue
            if bool(summary.get("backoff_active")) or int(
                summary.get("errors_in_tick", 0)
            ):
                raise RegistryError(
                    f"settings rebind watcher scan failed for {name}"
                )
            if int(summary.get("rate_limited_in_tick", 0)):
                raise RegistryError(
                    f"settings rebind watcher scan was rate limited for {name}"
                )
            if int(summary.get("rebind_unemitted_observations", 0)):
                raise RegistryError(
                    f"settings rebind watcher retained unemitted observations for {name}"
                )

    @staticmethod
    def _observations(
        summaries: Mapping[str, Mapping[str, object]],
        *,
        states: Mapping[str, WatcherState],
    ) -> tuple[BufferedObservation, ...]:
        observations: dict[
            tuple[str, str, str], BufferedObservation
        ] = {}
        for watcher, summary in summaries.items():
            raw = summary.get("rebind_observations") or []
            if not isinstance(raw, list):
                raise RegistryError("settings rebind watcher observations are invalid")
            for item in raw:
                if not isinstance(item, dict):
                    raise RegistryError("settings rebind watcher observation is invalid")
                observation = BufferedObservation(
                    watcher=watcher,
                    relative_path=_required_text(
                        item.get("relative_path"), name="observation relative path"
                    ),
                    content_hash=_required_text(
                        item.get("content_hash"), name="observation content hash"
                    ),
                    mtime=_mtime(item.get("mtime")),
                    trace_id=_optional_text(
                        item.get("trace_id"), name="observation trace id"
                    ),
                )
                if observation.trace_id is None:
                    raise RegistryError(
                        "settings rebind watcher observation was not durably emitted"
                    )
                observations[
                    (watcher, observation.relative_path, observation.content_hash)
                ] = observation
        # A crash may happen after the production tick durably advances its
        # per-file observation cursor but before the prepare acknowledgement is
        # written. Reconstruct that same buffer from the state file on restart.
        for watcher, state in states.items():
            for relative_path, item in state.files.items():
                content_hash = item.get("hash")
                mtime = item.get("mtime")
                trace_id = item.get("trace_id")
                if (
                    not isinstance(content_hash, str)
                    or not content_hash
                    or not isinstance(mtime, (int, float))
                    or isinstance(mtime, bool)
                    or not isinstance(trace_id, str)
                    or not trace_id
                ):
                    continue
                observation = BufferedObservation(
                    watcher=watcher,
                    relative_path=relative_path,
                    content_hash=content_hash,
                    mtime=float(mtime),
                    trace_id=trace_id,
                )
                observations[(watcher, relative_path, content_hash)] = observation
        return tuple(observations[key] for key in sorted(observations))

    @staticmethod
    def _merge_buffer(
        existing: tuple[BufferedObservation, ...],
        observed: tuple[BufferedObservation, ...],
    ) -> tuple[BufferedObservation, ...]:
        merged = {
            (item.watcher, item.relative_path, item.content_hash): item
            for item in existing
        }
        for item in observed:
            merged[(item.watcher, item.relative_path, item.content_hash)] = item
        return tuple(
            merged[key]
            for key in sorted(merged)
        )


__all__ = [
    "DormantSettingsRebindReconciler",
    "SettingsRebindWatcherReceipt",
    "load_settings_rebind_watcher_receipt",
]
