"""Host-local BWS admission. This lock is not cross-host/provider fencing.

Only cooperating entrypoints are serialized. No exception, timeout, lock release,
marker or generation pointer can terminate a possibly applied remote mutation.
Operation-specific callers must obtain authoritative evidence before finish/reconcile.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import re
import stat
from uuid import UUID, uuid4


class HostSecretAdmissionError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "host secret operation refused; admission or terminal evidence unavailable"
        )


class PreserveJournalBodyError(Exception):
    """Marker for a typed downstream refusal that must survive journal scope."""


def _validate_deploy_image_binding(raw: object, target: object) -> None:
    """Validate the exact value-free deploy plan carried by every host event."""
    from app.ops.pg_acceptance import IMAGE_REPOSITORY
    try:
        if type(raw) is not str or len(raw) > 16384 or target not in {"dev", "test"}:
            raise ValueError()
        binding = json.loads(raw)
        if (type(binding) is not dict or set(binding) != {
                "schema", "repository", "channel", "revision", "image_digest", "plan_fingerprint",
            }
                or binding["schema"] != "host-deploy-image-binding.v1"
                or binding["repository"] != IMAGE_REPOSITORY
                or binding["channel"] != target
                or type(binding["revision"]) is not str
                or re.fullmatch(r"[0-9a-f]{40}", binding["revision"]) is None
                or type(binding["image_digest"]) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", binding["image_digest"]) is None
                or type(binding["plan_fingerprint"]) is not str
                or re.fullmatch(r"[0-9a-f]{64}", binding["plan_fingerprint"]) is None
                or raw != json.dumps(binding, sort_keys=True, separators=(",", ":"))):
            raise ValueError()
    except Exception:
        raise HostSecretAdmissionError() from None


def _validate_source_image_binding(raw: object, target: object) -> None:
    from app.ops.pg_acceptance import IMAGE_REPOSITORY

    try:
        if type(raw) is not str or len(raw) > 4096 or target not in {"dev", "test"}:
            raise ValueError()
        binding = json.loads(raw)
        if (type(binding) is not dict
                or set(binding) != {"schema", "repository", "channel", "revision", "image_digest", "plan_fingerprint"}
                or binding["schema"] != "host-source-image-binding.v1"
                or binding["repository"] != IMAGE_REPOSITORY or binding["channel"] != target
                or type(binding["revision"]) is not str
                or re.fullmatch(r"[0-9a-f]{40}", binding["revision"]) is None
                or type(binding["image_digest"]) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", binding["image_digest"]) is None
                or type(binding["plan_fingerprint"]) is not str
                or re.fullmatch(r"[0-9a-f]{64}", binding["plan_fingerprint"]) is None
                or raw != json.dumps(binding, sort_keys=True, separators=(",", ":"))):
            raise ValueError()
    except Exception:
        raise HostSecretAdmissionError() from None


_KINDS = {
    "check", "import", "token-push", "deploy", "bootstrap", "source-persistence",
    "operator-identity-restoration", "source-diagnostic",
}
_TARGETS = {"dev", "test", "prod", "shared", "bob-1"}
_TERMINAL_SOURCES = {
    "check": "read-complete",
    "import": "provider-terminal",
    "bootstrap": "provider-terminal",
    "token-push": "remote-terminal",
    "deploy": "remote-terminal",
    "source-persistence": "remote-terminal",
    "source-diagnostic": "remote-terminal",
    "operator-identity-restoration": "remote-terminal",
}
_TOKEN_PUSH_LOCAL_ABORT_SOURCE = "host-preflight"
_DEPLOY_ABSENCE_SOURCE = "postmerge-controller"
_DEPLOY_ABSENCE_STAGE = "retired-before-admission"
_SOURCE_PERSISTENCE_ABSENCE_SOURCE = "native-absence-proof"
_OPERATOR_UNKNOWN_CLEANUP_RESULT = "reconciled-unknown"
_OPERATOR_UNKNOWN_CLEANUP_SOURCE = "remote-terminal-unknown-cleanup-complete"
_DEPLOY_UNKNOWN_FENCE_SOURCE = "remote-terminal-unknown-deploy-fenced"


@dataclass(frozen=True)
class TerminalEvidence:
    operation_id: str
    kind: str
    target: str
    result: str
    source: str


class HostSecretOperation:
    def __init__(
        self,
        journal_fd: int,
        operation_id: str,
        kind: str,
        target: str,
        *,
        prior_generation: str | None = None,
        allow_bootstrap: bool | None = None,
        prepared: bool = False,
        mutation_started: bool = False,
        completed_result: str | None = None,
        completed_source: str | None = None,
        producer_kind: str | None = None,
        source_mode: str | None = None,
        source_request_fingerprint: str | None = None,
        deploy_image_binding: str | None = None,
        source_image_binding: str | None = None,
        reconciliation_only: bool = False,
    ) -> None:
        self._journal_fd = journal_fd
        self.operation_id = operation_id
        self.kind = kind
        self.target = target
        self.prior_generation = prior_generation
        self.allow_bootstrap = allow_bootstrap
        self._finished = False
        self._active = True
        self._deferred_prepared = False
        self._prepared = prepared
        self._mutation_started = mutation_started
        self._completed_result = completed_result
        self._completed_source = completed_source
        self.producer_kind = producer_kind
        self.source_mode = source_mode
        self.source_request_fingerprint = source_request_fingerprint
        self.deploy_image_binding = deploy_image_binding
        self.source_image_binding = source_image_binding
        self.reconciliation_only = reconciliation_only

    def _record(self, stage: str, source: str | None = None) -> None:
        if not self._active or self._finished or self._completed_result is not None:
            raise HostSecretAdmissionError()
        record: dict[str, str | bool | None] = {
            "operation_id": self.operation_id,
            "kind": self.kind,
            "target": self.target,
            "stage": stage,
            "source": source,
        }
        if self.kind == "token-push":
            if not self._prepared:
                raise HostSecretAdmissionError()
            record["prior_generation"] = self.prior_generation
        elif self.kind == "deploy" and self.allow_bootstrap is not None:
            record["allow_bootstrap"] = self.allow_bootstrap
        elif self.kind == "source-persistence" and self.producer_kind is not None:
            record["producer_kind"] = self.producer_kind
        if self.source_mode is not None:
            record["source_mode"] = self.source_mode
            record["source_request_fingerprint"] = self.source_request_fingerprint
        if self.kind == "deploy" and self.deploy_image_binding is not None:
            record["deploy_image_binding"] = self.deploy_image_binding
        if self.kind == "source-persistence" and self.source_image_binding is not None:
            record["source_image_binding"] = self.source_image_binding
        raw = (json.dumps(record, sort_keys=True) + "\n").encode()
        # A partial write or failed fsync leaves a poison/pending journal, never admission.
        if os.write(self._journal_fd, raw) != len(raw):
            raise HostSecretAdmissionError()
        os.fsync(self._journal_fd)

    def require_active(self, target: str) -> None:
        if not self._active or self._finished or self.target != target:
            raise HostSecretAdmissionError()
        os.fstat(self._journal_fd)

    @property
    def mutation_started(self) -> bool:
        return self._mutation_started

    @property
    def completed_result(self) -> str | None:
        return self._completed_result

    @property
    def completed_source(self) -> str | None:
        return self._completed_source

    def prepare_mutation(self) -> None:
        """Persist before the first remote effect; caller already holds the host lock."""
        if (self.reconciliation_only or self.kind == "check"
                or (self.kind == "token-push" and not self._prepared)):
            raise HostSecretAdmissionError()
        if self._deferred_prepared:
            self._record("prepared")
            self._deferred_prepared = False
        self._record("sent")
        self._mutation_started = True

    def prepare_token_push(self, prior_generation: str | None) -> None:
        """Record the prior encrypted source before resolving or sending a token."""
        if self.kind != "token-push" or self._prepared:
            raise HostSecretAdmissionError()
        if prior_generation is not None and str(UUID(prior_generation)) != prior_generation:
            raise HostSecretAdmissionError()
        self.prior_generation = prior_generation
        self._prepared = True
        self._record("prepared")

    def finish(self, evidence: TerminalEvidence) -> None:
        if not self._active or self._finished:
            raise HostSecretAdmissionError()
        valid_source = (
            evidence.source == _TERMINAL_SOURCES.get(self.kind)
            and evidence.result != _OPERATOR_UNKNOWN_CLEANUP_RESULT
        )
        if (
            self.kind == "operator-identity-restoration"
            and evidence.result == _OPERATOR_UNKNOWN_CLEANUP_RESULT
            and evidence.source == _OPERATOR_UNKNOWN_CLEANUP_SOURCE
            and self._mutation_started
        ):
            valid_source = True
        if (
            self.kind == "deploy"
            and evidence.result == _OPERATOR_UNKNOWN_CLEANUP_RESULT
            and evidence.source == _DEPLOY_UNKNOWN_FENCE_SOURCE
            and self.allow_bootstrap is False
            and (
                self._mutation_started
                or (
                    self._completed_result == _OPERATOR_UNKNOWN_CLEANUP_RESULT
                    and self._completed_source == _DEPLOY_UNKNOWN_FENCE_SOURCE
                )
            )
        ):
            valid_source = True
        if (
            self.kind in {"source-persistence", "source-diagnostic"}
            and evidence.result == "failed"
            and evidence.source == _SOURCE_PERSISTENCE_ABSENCE_SOURCE
            and (
                self._prepared
                or (
                    self._completed_result == "failed"
                    and self._completed_source == _SOURCE_PERSISTENCE_ABSENCE_SOURCE
                )
            )
        ):
            valid_source = True
        if (
            self.kind == "token-push"
            and evidence.result == "aborted"
            and evidence.source == _TOKEN_PUSH_LOCAL_ABORT_SOURCE
            and not self._mutation_started
        ):
            valid_source = True
        if (
            evidence.operation_id != self.operation_id
            or evidence.kind != self.kind
            or evidence.target != self.target
            or evidence.result not in {
                "committed", "aborted", "failed", _OPERATOR_UNKNOWN_CLEANUP_RESULT,
            }
            or (
                evidence.result == _OPERATOR_UNKNOWN_CLEANUP_RESULT
                and self.kind not in {"operator-identity-restoration", "deploy"}
            )
            or (
                evidence.result == _OPERATOR_UNKNOWN_CLEANUP_RESULT
                and self.kind == "deploy" and self.allow_bootstrap is not False
            )
            or (
                evidence.result == "failed"
                and (
                    self.kind not in {"deploy", "source-persistence", "source-diagnostic", "operator-identity-restoration"}
                    or self.kind == "deploy" and self.allow_bootstrap is not False
                )
            )
            or not valid_source
        ):
            raise HostSecretAdmissionError()
        if self._completed_result is not None:
            if evidence.result != self._completed_result:
                raise HostSecretAdmissionError()
        else:
            self._record(evidence.result, evidence.source)
        self._finished = True


class HostSecretController:
    """One stable lock and append-only value-free journal, outside Git/iCloud.

    `directory` is for isolated fixture controllers. Production uses one fixed
    per-owner state path; downstream entrypoints must share this controller.
    """

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or Path.home() / ".local/state/yggdrasil/secret-controller"

    @contextmanager
    def _locked_journal(self, *, wait: bool = False) -> Iterator[int]:
        directory_fd = lock_fd = journal_fd = None
        try:
            path = self.directory
            if not path.is_absolute() or any(
                part in {"Mobile Documents", "CloudStorage", ".git"} for part in path.parts
            ):
                raise HostSecretAdmissionError()
            # Reject symlinked ancestry and every repository, even untracked subdirectories.
            for parent in (path, *path.parents):
                if parent.is_symlink() or (parent / ".git").exists():
                    raise HostSecretAdmissionError()
            directory_fd = self._durable_directory(path)
            info = os.fstat(directory_fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise HostSecretAdmissionError()
            lock_fd = self._open_file(directory_fd, "operation.lock")
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
            except BlockingIOError:
                raise HostSecretAdmissionError() from None
            journal_fd = self._open_file(directory_fd, "operations.jsonl")
            os.fsync(directory_fd)
            yield journal_fd
        except HostSecretAdmissionError:
            raise
        except PreserveJournalBodyError:
            raise
        except Exception:
            raise HostSecretAdmissionError() from None
        finally:
            for descriptor in (journal_fd, lock_fd, directory_fd):
                if descriptor is not None:
                    os.close(descriptor)

    @staticmethod
    def _durable_directory(path: Path) -> int:
        """Persist every directory entry before the journal can authorize a send.

        Traversal uses directory descriptors and refuses symlinks. Fsync even
        existing entries: another first-use caller may just have created them.
        """
        descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in path.parts[1:]:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                try:
                    os.fsync(child)
                    os.fsync(descriptor)
                except BaseException:
                    os.close(child)
                    raise
                os.close(descriptor)
                descriptor = child
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _open_file(directory_fd: int, name: str) -> int:
        descriptor = os.open(
            name,
            os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=directory_fd,
        )
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            os.close(descriptor)
            raise HostSecretAdmissionError()
        return descriptor

    @staticmethod
    def _pending(descriptor: int) -> dict[str, str | bool | None] | None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        with os.fdopen(os.dup(descriptor), "r", encoding="utf-8") as source:
            pending = None
            seen: set[str] = set()
            for line in source:
                if not line.endswith("\n"):
                    raise HostSecretAdmissionError()
                record = json.loads(line)
                if (
                    not isinstance(record, dict)
                    or not {"operation_id", "kind", "target", "stage", "source"} <= set(record)
                    or record["kind"] not in _KINDS
                    or record["target"] not in _TARGETS
                    or (
                        record["kind"] == "operator-identity-restoration"
                        and record["target"] != "dev"
                    )
                    or str(UUID(record["operation_id"])) != record["operation_id"]
                ):
                    raise HostSecretAdmissionError()
                if record["kind"] == "token-push":
                    if (
                        set(record) != {
                            "operation_id", "kind", "target", "stage", "source", "prior_generation"
                        }
                        or (
                            record["prior_generation"] is not None
                            and str(UUID(record["prior_generation"])) != record["prior_generation"]
                        )
                    ):
                        raise HostSecretAdmissionError()
                elif record["kind"] == "deploy":
                    base_fields = {"operation_id", "kind", "target", "stage", "source"}
                    if frozenset(record) not in {
                        frozenset(base_fields), frozenset(base_fields | {"allow_bootstrap"}),
                        frozenset(base_fields | {"allow_bootstrap", "deploy_image_binding"}),
                    }:
                        raise HostSecretAdmissionError()
                    if "allow_bootstrap" in record and type(record["allow_bootstrap"]) is not bool:
                        raise HostSecretAdmissionError()
                    if "deploy_image_binding" in record:
                        _validate_deploy_image_binding(record["deploy_image_binding"], record["target"])
                elif record["kind"] in {"source-persistence", "source-diagnostic"}:
                    base_fields = {"operation_id", "kind", "target", "stage", "source"}
                    binding_fields = {"source_image_binding"} if "source_image_binding" in record else set()
                    if (binding_fields and record["kind"] != "source-persistence"):
                        raise HostSecretAdmissionError()
                    if binding_fields:
                        _validate_source_image_binding(record["source_image_binding"], record["target"])
                    if frozenset(set(record) - binding_fields) not in {
                        frozenset(base_fields), frozenset(base_fields | {"producer_kind"}),
                        frozenset(base_fields | {"producer_kind", "source_mode", "source_request_fingerprint"}),
                        frozenset(base_fields | {"source_mode", "source_request_fingerprint"}),
                    } or (
                        "producer_kind" in record and record["producer_kind"] != "registry"
                    ) or (
                        "source_mode" in record and (
                            record["source_mode"] != "current-state"
                            or not isinstance(record['source_request_fingerprint'], str)
                            or re.fullmatch(r'[0-9a-f]{64}', record['source_request_fingerprint']) is None
                            or record["target"] not in {"dev", "test"}
                            or (record["kind"] == "source-persistence"
                                and record.get("producer_kind") != "registry")
                        )
                    ) or (
                        record["kind"] == "source-diagnostic"
                        and (record.get("source_mode") != "current-state" or "producer_kind" in record)
                    ):
                        raise HostSecretAdmissionError()
                elif set(record) != {"operation_id", "kind", "target", "stage", "source"}:
                    raise HostSecretAdmissionError()
                if record["stage"] == _DEPLOY_ABSENCE_STAGE:
                    if (
                        record["kind"] != "deploy"
                        or record["target"] not in {"dev", "test"}
                        or record.get("allow_bootstrap") is not False
                        or record["source"] != _DEPLOY_ABSENCE_SOURCE
                        or record["operation_id"] in seen
                    ):
                        raise HostSecretAdmissionError()
                    seen.add(record["operation_id"])
                    continue
                if record["stage"] == "prepared":
                    if (
                        pending is not None
                        or record["operation_id"] in seen
                        or record["source"] is not None
                    ):
                        raise HostSecretAdmissionError()
                    seen.add(record["operation_id"])
                    pending = record
                else:
                    if pending is None or any(
                        record[k] != pending[k] for k in ("operation_id", "kind", "target")
                    ):
                        raise HostSecretAdmissionError()
                    if record["kind"] == "token-push" and record["prior_generation"] != pending["prior_generation"]:
                        raise HostSecretAdmissionError()
                    if record["kind"] == "deploy" and record.get("allow_bootstrap") != pending.get("allow_bootstrap"):
                        raise HostSecretAdmissionError()
                    if (record["kind"] == "deploy"
                            and record.get("deploy_image_binding") != pending.get("deploy_image_binding")):
                        raise HostSecretAdmissionError()
                    if (
                        record["kind"] in {"source-persistence", "source-diagnostic"}
                        and (record.get("producer_kind") != pending.get("producer_kind")
                             or record.get("source_mode") != pending.get("source_mode")
                             or record.get('source_request_fingerprint') != pending.get('source_request_fingerprint')
                             or record.get('source_image_binding') != pending.get('source_image_binding'))
                    ):
                        raise HostSecretAdmissionError()
                    if record["stage"] == "failed" and (
                        record["kind"] not in {
                            "deploy", "source-persistence", "source-diagnostic", "operator-identity-restoration",
                        }
                        or record["kind"] == "deploy" and pending.get("allow_bootstrap") is not False
                    ):
                        raise HostSecretAdmissionError()
                    if (
                        record["stage"] == "sent"
                        and record["source"] is None
                        and record["kind"] != "check"
                    ):
                        pending = record
                        continue
                    terminal_stages = {"committed", "aborted"}
                    if record["kind"] in {
                        "deploy", "source-persistence", "source-diagnostic", "operator-identity-restoration",
                    }:
                        terminal_stages.add("failed")
                    if record["kind"] == "operator-identity-restoration":
                        terminal_stages.add(_OPERATOR_UNKNOWN_CLEANUP_RESULT)
                    if record["kind"] == "deploy":
                        terminal_stages.add(_OPERATOR_UNKNOWN_CLEANUP_RESULT)
                    if (
                        record["stage"] not in terminal_stages
                        or not (
                            (
                                record["source"] == _TERMINAL_SOURCES[record["kind"]]
                                and record["stage"] != _OPERATOR_UNKNOWN_CLEANUP_RESULT
                            )
                            or (
                                record["kind"] == "operator-identity-restoration"
                                and record["stage"] == _OPERATOR_UNKNOWN_CLEANUP_RESULT
                                and pending["stage"] == "sent"
                                and record["source"] == _OPERATOR_UNKNOWN_CLEANUP_SOURCE
                            )
                            or (
                                record["kind"] == "deploy"
                                and record["stage"] == _OPERATOR_UNKNOWN_CLEANUP_RESULT
                                and pending["stage"] == "sent"
                                and pending.get("allow_bootstrap") is False
                                and record.get("allow_bootstrap") is False
                                and record["source"] == _DEPLOY_UNKNOWN_FENCE_SOURCE
                            )
                            or (
                                record["kind"] in {"source-persistence", "source-diagnostic"}
                                and record["stage"] == "failed"
                                and pending["stage"] in {"prepared", "sent"}
                                and record["source"] == _SOURCE_PERSISTENCE_ABSENCE_SOURCE
                            )
                            or (
                                record["kind"] == "token-push"
                                and record["stage"] == "aborted"
                                and pending["stage"] == "prepared"
                                and record["source"] == _TOKEN_PUSH_LOCAL_ABORT_SOURCE
                            )
                        )
                    ):
                        raise HostSecretAdmissionError()
                    pending = None
            return pending

    @contextmanager
    def admit(self, kind: str, target: str) -> Iterator[HostSecretOperation]:
        if (
            kind not in _KINDS
            or target not in _TARGETS
            or kind == "token-push"
            or (kind == "operator-identity-restoration" and target != "dev")
            or (target == "shared" and kind not in {"check", "import"})
            or (target == "bob-1" and kind not in {"check", "import", "deploy"})
        ):
            raise HostSecretAdmissionError()
        with self._locked_journal() as descriptor:
            if self._pending(descriptor) is not None:
                raise HostSecretAdmissionError()
            operation = HostSecretOperation(descriptor, str(uuid4()), kind, target)
            operation._record("prepared")
            try:
                yield operation
            finally:
                # Never clear a pending operation merely because the process unwound.
                operation._active = False

    def reconcile(
        self,
        readback: Callable[[str, str, str], TerminalEvidence],
        *,
        expected: tuple[str, str, bool | None] | None = None,
        expected_deploy_image_binding: str | None = None,
    ) -> None:
        """Read authoritative operation-specific terminal evidence under the host lock.

        Downstream adapters own authentication, durable receipt and provider terminality
        checks. No public CLI accepts caller assertions as terminal evidence.
        """
        with self._locked_journal() as descriptor:
            pending = self._pending(descriptor)
            if pending is None:
                raise HostSecretAdmissionError()
            if expected is not None and (
                pending["kind"], pending["target"], pending.get("allow_bootstrap")
            ) != expected:
                raise HostSecretAdmissionError()
            if (pending["kind"] == "deploy" and pending.get("deploy_image_binding") is not None
                    and pending.get("deploy_image_binding") != expected_deploy_image_binding):
                raise HostSecretAdmissionError()
            prior_generation = pending.get("prior_generation")
            allow_bootstrap = pending.get("allow_bootstrap")
            if prior_generation is not None and not isinstance(prior_generation, str):
                raise HostSecretAdmissionError()
            if allow_bootstrap is not None and not isinstance(allow_bootstrap, bool):
                raise HostSecretAdmissionError()
            source_fields: dict[str, str | None] = {}
            for key in (
                "producer_kind", "source_mode", "source_request_fingerprint",
                "source_image_binding", "deploy_image_binding",
            ):
                value = pending.get(key)
                if value is not None and not isinstance(value, str):
                    raise HostSecretAdmissionError()
                source_fields[key] = value
            operation = HostSecretOperation(
                descriptor,
                str(pending["operation_id"]),
                str(pending["kind"]),
                str(pending["target"]),
                prior_generation=prior_generation,
                allow_bootstrap=allow_bootstrap,
                prepared=pending["kind"] == "token-push",
                mutation_started=pending["stage"] == "sent",
                producer_kind=source_fields["producer_kind"],
                source_mode=source_fields["source_mode"],
                source_request_fingerprint=source_fields["source_request_fingerprint"],
                source_image_binding=source_fields["source_image_binding"],
                deploy_image_binding=source_fields["deploy_image_binding"],
            )
            try:
                evidence = readback(operation.operation_id, operation.kind, operation.target)
                operation.finish(evidence)
            finally:
                operation._active = False

    def prove_deploy_absence(
        self,
        operation_id: str,
        target: str,
        readback: Callable[[], dict[str, str | bool]],
    ) -> dict[str, str | bool]:
        """Prove that one automatic deploy ID never entered host admission.

        The downstream readback runs while the shared host journal lock is held,
        so another cooperating entrypoint cannot admit the ID between the host
        history check and the remote fixed-field observation.  No journal record
        is appended by this read-only path.
        """
        if (
            target not in {"dev", "test"}
            or not isinstance(operation_id, str)
            or str(UUID(operation_id)) != operation_id
        ):
            raise HostSecretAdmissionError()
        with self._locked_journal(wait=True) as descriptor:
            self._pending(descriptor)  # Validate the complete append-only history.
            os.lseek(descriptor, 0, os.SEEK_SET)
            with os.fdopen(os.dup(descriptor), "r", encoding="utf-8") as source:
                records = [json.loads(line) for line in source]
            matches = [record for record in records if record["operation_id"] == operation_id]
            retired = len(matches) == 1 and matches[0] == {
                "operation_id": operation_id,
                "kind": "deploy",
                "target": target,
                "stage": _DEPLOY_ABSENCE_STAGE,
                "source": _DEPLOY_ABSENCE_SOURCE,
                "allow_bootstrap": False,
            }
            if matches and not retired:
                raise HostSecretAdmissionError()
            result = readback()
            if (
                not isinstance(result, dict)
                or result.get("operation_id") != operation_id
                or result.get("channel") != target
                or result.get("native_operation_absent") is not True
                or result.get("native_worker_absent") is not True
                or result.get("native_lock_absent") is not True
                or result.get("native_request_absent") is not True
            ):
                raise HostSecretAdmissionError()
            if not retired:
                record = {
                    "operation_id": operation_id,
                    "kind": "deploy",
                    "target": target,
                    "stage": _DEPLOY_ABSENCE_STAGE,
                    "source": _DEPLOY_ABSENCE_SOURCE,
                    "allow_bootstrap": False,
                }
                raw = (json.dumps(record, sort_keys=True) + "\n").encode()
                if os.write(descriptor, raw) != len(raw):
                    raise HostSecretAdmissionError()
                os.fsync(descriptor)
            return {
                **result,
                "host_operation_absent": True,
                "host_operation_retired": True,
            }

    @contextmanager
    def token_push_operation(
        self, target: str
    ) -> Iterator[tuple[HostSecretOperation, dict[str, str | bool | None] | None]]:
        """Start or resume one same-ID VM token push under the shared host lock."""
        if target not in _TARGETS - {"shared", "bob-1"}:
            raise HostSecretAdmissionError()
        with self._locked_journal(wait=True) as descriptor:
            pending = self._pending(descriptor)
            if pending and (pending["kind"] != "token-push" or pending["target"] != target):
                raise HostSecretAdmissionError()
            prior_generation = pending.get("prior_generation") if pending else None
            if prior_generation is not None and not isinstance(prior_generation, str):
                raise HostSecretAdmissionError()
            operation = HostSecretOperation(
                descriptor,
                str(pending["operation_id"]) if pending else str(uuid4()),
                "token-push",
                target,
                prior_generation=prior_generation,
                prepared=bool(pending),
                mutation_started=bool(pending and pending["stage"] == "sent"),
            )
            try:
                yield operation, pending
            finally:
                operation._active = False

    @contextmanager
    def import_operation(self, target: str) -> Iterator[tuple[HostSecretOperation, bool]]:
        """Admit or resume import under the same lock; the admin must prove terminality.

        Resumption does not clear admission or attest a provider outcome. The import
        implementation reads its durable per-send history before any new provider call.
        All other callers continue to refuse the pending operation.
        """
        if target not in _TARGETS:
            raise HostSecretAdmissionError()
        with self._locked_journal() as descriptor:
            pending = self._pending(descriptor)
            if pending and (pending["kind"] != "import" or pending["target"] != target):
                raise HostSecretAdmissionError()
            operation = HostSecretOperation(
                descriptor, str(pending["operation_id"]) if pending else str(uuid4()),
                "import", target,
            )
            if not pending:
                operation._record("prepared")
            try:
                yield operation, bool(pending and pending["stage"] == "sent")
            finally:
                operation._active = False

    @contextmanager
    def source_persistence_operation(
        self, target: str, *, operation_id: str,
        producer_kind: str = "vault-alpha",
        current_state: bool = False,
        request_fingerprint: str | None = None,
        source_image_binding: str | None = None,
        reconciliation_only: bool = False,
        allow_legacy_cleanup: bool = False,
    ) -> Iterator[tuple[HostSecretOperation, bool]]:
        """Admit one DEV/TEST ordinary-producer operation under the host lock."""
        with self._source_operation(
            target, operation_id=operation_id, producer_kind=producer_kind,
            current_state=current_state, diagnostic=False,
            request_fingerprint=request_fingerprint, source_image_binding=source_image_binding,
            reconciliation_only=reconciliation_only, allow_legacy_cleanup=allow_legacy_cleanup,
        ) as result:
            yield result

    @contextmanager
    def source_diagnostic_operation(
        self, target: str, *, operation_id: str, request_fingerprint: str | None = None,
    ) -> Iterator[tuple[HostSecretOperation, bool]]:
        """Serialize a distinct read-only diagnostic, never a source producer."""
        with self._source_operation(
            target, operation_id=operation_id, producer_kind="vault-alpha",
            current_state=True, diagnostic=True,
            request_fingerprint=request_fingerprint,
            source_image_binding=None,
            reconciliation_only=False, allow_legacy_cleanup=False,
        ) as result:
            yield result

    @contextmanager
    def _source_operation(
        self, target: str, *, operation_id: str, producer_kind: str,
        current_state: bool, diagnostic: bool,
        request_fingerprint: str | None, source_image_binding: str | None,
        reconciliation_only: bool, allow_legacy_cleanup: bool,
    ) -> Iterator[tuple[HostSecretOperation, bool]]:
        if target not in {"dev", "test"}:
            raise HostSecretAdmissionError()
        if (type(reconciliation_only) is not bool or type(allow_legacy_cleanup) is not bool
                or (allow_legacy_cleanup and diagnostic)):
            raise HostSecretAdmissionError()
        if (producer_kind not in {"vault-alpha", "registry"}
            or type(current_state) is not bool
            or (current_state and not diagnostic and producer_kind != "registry")
            or (current_state and (not isinstance(request_fingerprint, str)
                                  or re.fullmatch(r'[0-9a-f]{64}', request_fingerprint) is None))
            or (not current_state and request_fingerprint is not None)):
            raise HostSecretAdmissionError()
        kind = "source-diagnostic" if diagnostic else "source-persistence"
        if source_image_binding is not None:
            if diagnostic:
                raise HostSecretAdmissionError()
            _validate_source_image_binding(source_image_binding, target)
        mode = "current-state" if current_state else None
        try:
            if str(UUID(operation_id)) != operation_id:
                raise HostSecretAdmissionError()
        except (ValueError, TypeError, AttributeError):
            raise HostSecretAdmissionError() from None
        with self._locked_journal(wait=True) as descriptor:
            pending = self._pending(descriptor)
            if pending is not None and (
                pending.get("operation_id") != operation_id
                or pending.get("kind") != kind
                or pending.get("target") != target
                or pending.get("producer_kind")
                != ("registry" if producer_kind == "registry" else None)
                or pending.get("source_mode") != mode
                or pending.get('source_request_fingerprint') != request_fingerprint
                or (pending.get('source_image_binding') != source_image_binding
                    and not (pending.get('source_image_binding') is None
                             and (reconciliation_only or allow_legacy_cleanup))
                    and not (reconciliation_only and source_image_binding is None))
            ):
                raise HostSecretAdmissionError()
            completed = None
            completed_source = None
            if pending is None:
                os.lseek(descriptor, 0, os.SEEK_SET)
                with os.fdopen(os.dup(descriptor), "r", encoding="utf-8") as source:
                    matches = [
                        record for record in map(json.loads, source)
                        if record["operation_id"] == operation_id
                    ]
                if matches:
                    last = matches[-1]
                    if (
                        last["kind"] != kind
                        or last["target"] != target
                        or last["stage"] not in {"committed", "failed"}
                        or last["source"] not in {
                            "remote-terminal", _SOURCE_PERSISTENCE_ABSENCE_SOURCE,
                        }
                        or last.get("producer_kind")
                        != ("registry" if producer_kind == "registry" else None)
                        or last.get("source_mode") != mode
                        or last.get('source_request_fingerprint') != request_fingerprint
                        or (last.get('source_image_binding') != source_image_binding
                            and not (last.get('source_image_binding') is None
                                     and (reconciliation_only or allow_legacy_cleanup))
                            and not (reconciliation_only and source_image_binding is None))
                    ):
                        raise HostSecretAdmissionError()
                    completed = str(last["stage"])
                    completed_source = str(last["source"])
            stored_binding = (pending.get("source_image_binding") if pending else
                              last.get("source_image_binding") if completed is not None else source_image_binding)
            if stored_binding is not None and not isinstance(stored_binding, str):
                raise HostSecretAdmissionError()
            legacy_cleanup = stored_binding is None and source_image_binding is not None and (pending or completed)
            operation = HostSecretOperation(
                descriptor, operation_id, kind, target,
                prepared=pending is not None,
                mutation_started=pending is not None and pending.get("stage") == "sent",
                completed_result=completed,
                completed_source=completed_source,
                producer_kind=("registry" if producer_kind == "registry" else None),
                source_mode=mode,
                source_request_fingerprint=request_fingerprint,
                source_image_binding=stored_binding,
                reconciliation_only=reconciliation_only or bool(legacy_cleanup),
            )
            resumed = pending is not None or completed is not None
            if not resumed:
                operation._deferred_prepared = True
            try:
                yield operation, resumed
            finally:
                operation._active = False

    def source_persistence_preflight(self, target: str) -> dict[str, str | bool | None]:
        """Read exact value-free host admission state before a caller allocates an ID."""
        if target not in {"dev", "test"}:
            raise HostSecretAdmissionError()
        with self._locked_journal(wait=True) as descriptor:
            pending = self._pending(descriptor)
        return {
            "contract": "host-source-persistence-admission.v1",
            "target": target,
            "ready": pending is None,
            "pending_operation_id": None if pending is None else str(pending["operation_id"]),
            "pending_kind": None if pending is None else str(pending["kind"]),
            "pending_target": None if pending is None else str(pending["target"]),
            "pending_stage": None if pending is None else str(pending["stage"]),
        }

    @contextmanager
    def operator_identity_restoration_operation(
        self, target: str, *, operation_id: str,
    ) -> Iterator[tuple[HostSecretOperation, bool]]:
        """Admit only the separately reviewed DEV operator restoration."""
        if target != "dev":
            raise HostSecretAdmissionError()
        try:
            if str(UUID(operation_id)) != operation_id:
                raise HostSecretAdmissionError()
        except (ValueError, TypeError, AttributeError):
            raise HostSecretAdmissionError() from None
        with self._locked_journal(wait=True) as descriptor:
            pending = self._pending(descriptor)
            if pending is not None and (
                pending.get("operation_id") != operation_id
                or pending.get("kind") != "operator-identity-restoration"
                or pending.get("target") != target
            ):
                raise HostSecretAdmissionError()
            completed = None
            completed_source = None
            if pending is None:
                os.lseek(descriptor, 0, os.SEEK_SET)
                with os.fdopen(os.dup(descriptor), "r", encoding="utf-8") as source:
                    matches = [
                        record for record in map(json.loads, source)
                        if record["operation_id"] == operation_id
                    ]
                if matches:
                    last = matches[-1]
                    if (
                        last["kind"] != "operator-identity-restoration"
                        or last["target"] != "dev"
                        or last["stage"] not in {
                            "committed", "failed", _OPERATOR_UNKNOWN_CLEANUP_RESULT,
                        }
                        or not (
                            (
                                last["source"] == "remote-terminal"
                                and last["stage"] != _OPERATOR_UNKNOWN_CLEANUP_RESULT
                            )
                            or (
                                last["stage"] == _OPERATOR_UNKNOWN_CLEANUP_RESULT
                                and last["source"] == _OPERATOR_UNKNOWN_CLEANUP_SOURCE
                            )
                        )
                    ):
                        raise HostSecretAdmissionError()
                    completed = str(last["stage"])
                    completed_source = str(last["source"])
            operation = HostSecretOperation(
                descriptor, operation_id, "operator-identity-restoration", target,
                prepared=pending is not None,
                mutation_started=pending is not None and pending.get("stage") == "sent",
                completed_result=completed,
                completed_source=completed_source,
            )
            resumed = pending is not None or completed is not None
            if not resumed:
                operation._deferred_prepared = True
            try:
                yield operation, resumed
            finally:
                operation._active = False


    @contextmanager
    def deploy_operation(
        self, target: str, *, allow_bootstrap: bool | None = None, operation_id: str | None = None,
        deploy_image_binding: str | None = None,
        reconciliation_only: bool = False, allow_legacy_terminal: bool = False,
    ) -> Iterator[tuple[HostSecretOperation, bool]]:
        """Resume only the same channel/ID; the remote receipt remains authority."""
        if (type(reconciliation_only) is not bool or type(allow_legacy_terminal) is not bool
            or target not in _TARGETS - {"shared"} or (
            allow_bootstrap is not None and type(allow_bootstrap) is not bool
        )):
            raise HostSecretAdmissionError()
        if operation_id is not None and (
            target not in {'dev', 'test'} or allow_bootstrap is not False
            or str(UUID(operation_id)) != operation_id
        ):
            raise HostSecretAdmissionError()
        if deploy_image_binding is not None:
            if allow_bootstrap is None:
                raise HostSecretAdmissionError()
            _validate_deploy_image_binding(deploy_image_binding, target)
        with self._locked_journal(wait=True) as descriptor:
            pending = self._pending(descriptor)
            if pending and (pending["kind"] != "deploy" or pending["target"] != target):
                raise HostSecretAdmissionError()
            if pending and pending.get("allow_bootstrap") != allow_bootstrap:
                # Legacy pending deployment records have no mode. Reconcile their
                # matching remote receipt before a new request can adopt the ID.
                raise HostSecretAdmissionError()
            if pending and pending.get("deploy_image_binding") != deploy_image_binding:
                if not (reconciliation_only and pending.get("deploy_image_binding") is None):
                    raise HostSecretAdmissionError()
            if pending and operation_id is not None and pending['operation_id'] != operation_id:
                raise HostSecretAdmissionError()
            completed = None
            completed_source = None
            if operation_id is not None and pending is None:
                # _pending has validated the entire durable history. An exact
                # terminal ID is read-only; it cannot append another prepared or
                # sent record. The caller must still bind and read the VM receipt.
                os.lseek(descriptor, 0, os.SEEK_SET)
                with os.fdopen(os.dup(descriptor), 'r') as source:
                    records = [json.loads(line) for line in source]
                matches = [record for record in records if record['operation_id'] == operation_id]
                if matches:
                    last = matches[-1]
                    terminal_matches = (
                        last['stage'] in {'committed', 'aborted', 'failed'}
                        and last['source'] == 'remote-terminal'
                    ) or (
                        target in {'dev', 'test'}
                        and last['stage'] == _OPERATOR_UNKNOWN_CLEANUP_RESULT
                        and last['source'] == _DEPLOY_UNKNOWN_FENCE_SOURCE
                    )
                    legacy_terminal = (last.get('deploy_image_binding') is None
                                       and (reconciliation_only or allow_legacy_terminal))
                    if (last['kind'] != 'deploy' or last['target'] != target
                        or last.get('allow_bootstrap') is not False
                        or (last.get('deploy_image_binding') != deploy_image_binding and not legacy_terminal)
                        or not terminal_matches):
                        raise HostSecretAdmissionError()
                    completed = str(last['stage'])
                    completed_source = str(last['source'])
            stored_binding = (pending.get("deploy_image_binding") if pending else
                              last.get("deploy_image_binding") if completed is not None else deploy_image_binding)
            if stored_binding is not None and not isinstance(stored_binding, str):
                raise HostSecretAdmissionError()
            operation = HostSecretOperation(descriptor,
                str(pending["operation_id"]) if pending else operation_id or str(uuid4()), "deploy", target,
                allow_bootstrap=allow_bootstrap,
                deploy_image_binding=stored_binding,
                reconciliation_only=(reconciliation_only or (completed is not None and stored_binding is None
                                                               and deploy_image_binding is not None)),
                mutation_started=bool(pending and pending.get('stage') == 'sent'),
                completed_result=completed, completed_source=completed_source)
            # Read-only host preflight holds the same lock but does not leave a
            # pending mutation that would prevent importing a missing value.
            # prepare_mutation persists prepared + sent before the first RPC.
            operation._deferred_prepared = not bool(pending) and completed is None
            try:
                yield operation, bool(pending) or completed is not None
            finally:
                operation._active = False
