"""Bounded HKA semantic edits over existing human notes; no runtime installation.

The trusted composition supplies an applicable human semantic approval. This
owner validates its concrete intent, preserves source representation outside
the selected fields, and uses the existing GOV window and rewritten-note CAS.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping, cast
from uuid import UUID

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from app.events.schema import make_outbox_event
from app.governance.governed_write import (
    GovernedWriteAdapter,
    GovernedWriteGrant,
    InvalidDecisionTokenError,
)
from app.instance.context_bound_read import ContextBoundReadError
from app.instance.context_bound_write import context_bound_write_window
from app.instance.errors import RegistryError
from app.instance.vault_registry import VaultRegistryStore
from app.knowledge import make_note_locator
from app.knowledge.contracts import WriteReceipt
from app.knowledge.errors import (
    KnowledgeAtomicExchangeNotApplied,
    KnowledgeCapabilityError,
    KnowledgeWriteConflict,
)
from app.knowledge.multiwriter import (
    NoteClass,
    WriteOperation,
    classify_note_in_vault,
    is_conflict_artifact,
)
from app.knowledge.write_ops import read_note_text_with_version, write_note_from_absolute
from app.services.artifact_identity import resolve_note_artifact_identity
from app.services.outbox import append_jsonl_outbox_event
from app.vault.active_context_v1 import ActiveContextError, ActiveContextSetV1
from app.vault.manager import nearest_enclosing_vault_root
from app.vault.path_overlap import (
    VaultPathOverlapError,
    assert_targets_do_not_overlap_capture_note,
    vault_path_is_within,
)
from app.vault.paths import get_vault_sources_dir_rel, get_vault_system_dir_rel
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError

CLASSIFY = "artifact.classify"
TAGS_ADD = "artifact.tags.add"
TAGS_REMOVE = "artifact.tags.remove"
REORDER = "collection.reorder"
SEMANTIC_OPERATIONS = frozenset({CLASSIFY, TAGS_ADD, TAGS_REMOVE, REORDER})
# ARTIFACT_METADATA_CONTRACT §5; these are HK classes, never AM/BA/MM/CN.
HUMAN_CLASSES = frozenset(
    {
        "human_knowledge",
        "fleeting_capture",
        "daily_log",
        "shopping_list",
        "checklist",
        "project_note",
        "area_dashboard",
        "source_note",
        "literature_note",
        "media_note",
        "screenshot_note",
        "scan_or_receipt_note",
        "email_summary",
        "youtube_source_note",
        "contact_note",
        "decision_record",
        "reflection_note",
        "evergreen_note",
        "synthesis_note",
    }
)
# Only the already documented HK subdivisions are admitted in this slice.
HUMAN_TYPES = frozenset({"concept_note", "photo"})
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)^---(?:\r?\n|\Z)", re.MULTILINE | re.DOTALL)


class SemanticValidationError(ValueError):
    """An admitted semantic request or source has an invalid representation."""


class _UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader: _UniqueLoader, node: yaml.MappingNode, deep: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result or key == "<<":
            raise SemanticValidationError("frontmatter requires unique string keys without merges")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _metadata(text: str) -> tuple[dict[str, Any], re.Match[str]]:
    match = _FRONTMATTER.match(text)
    if match is None:
        raise SemanticValidationError("a complete frontmatter mapping is required")
    try:
        # Aliases could make an apparently local field edit change unrelated
        # metadata semantics. Refuse rather than rewrite shared YAML structure.
        if any(
            isinstance(token, (yaml.AliasToken, yaml.AnchorToken)) for token in yaml.scan(match[1])
        ):
            raise SemanticValidationError("frontmatter anchors and aliases require explicit repair")
        value = yaml.load(match[1], Loader=_UniqueLoader)
    except yaml.YAMLError as exc:
        raise SemanticValidationError("source frontmatter is malformed") from exc
    if not isinstance(value, dict):
        raise SemanticValidationError("source frontmatter must be a mapping")
    return value, match


def _uuid(value: Any) -> str:
    if not isinstance(value, str):
        raise SemanticValidationError("artifact identities must be UUID strings")
    try:
        return str(UUID(value.strip()))
    except ValueError as exc:
        raise SemanticValidationError("artifact identity is not a UUID") from exc


def _declared_identities(node: Node | None) -> set[str]:
    """Probe UUID declarations without collapsing duplicate keys or YAML merges.

    This is candidate discovery only. Any matching candidate must still pass
    the strict metadata/identity decoder before supplying authority or meaning.
    """
    identities: set[str] = set()
    visited: set[int] = set()

    def values(value: Node) -> None:
        if id(value) in visited:
            return
        visited.add(id(value))
        if isinstance(value, ScalarNode):
            try:
                identities.add(_uuid(value.value))
            except SemanticValidationError:
                pass
        elif isinstance(value, SequenceNode):
            for child in value.value:
                values(child)
        elif isinstance(value, MappingNode):
            for _, child in value.value:
                values(child)

    def declarations(value: Node | None) -> None:
        if value is None or id(value) in visited:
            return
        visited.add(id(value))
        if isinstance(value, MappingNode):
            for key, child in value.value:
                if isinstance(key, ScalarNode) and key.value == "uuid":
                    values(child)
                elif isinstance(key, ScalarNode) and key.value == "<<":
                    declarations(child)
        elif isinstance(value, SequenceNode):
            for child in value.value:
                declarations(child)

    declarations(node)
    return identities


def _vocabulary(value: Any) -> str:
    if not isinstance(value, str):
        raise SemanticValidationError("classification values must be strings")
    return value.strip().lower()


def _tags(value: Any) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise SemanticValidationError("tags must be a list of strings")
    normalized = [item.strip().lstrip("#").lower() for item in value]
    if any(
        not item or any(char.isspace() or ord(char) < 32 for char in item) for item in normalized
    ):
        raise SemanticValidationError("tags require nonempty names without whitespace or controls")
    return sorted(set(normalized))


def _members(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise SemanticValidationError("member_order must be an explicitly authored UUID list")
    result = [_uuid(item) for item in value]
    if len(result) != len(set(result)):
        raise SemanticValidationError("member_order contains duplicate identities")
    return result


def _replace_fields(text: str, patch: Mapping[str, Any]) -> str:
    """Splice only selected YAML values; retain body and unrelated source bytes."""
    original, match = _metadata(text)
    block = match[1]
    node = yaml.compose(block)
    if not isinstance(node, MappingNode) or node.flow_style:
        raise SemanticValidationError("semantic writes require a block frontmatter mapping")
    values = {key.value: value for key, value in node.value}
    replacements: list[tuple[int, int, str]] = []
    for field, value in patch.items():
        rendered = (
            yaml.safe_dump(value, default_flow_style=True, width=100000)
            .removesuffix("...\n")
            .strip()
        )
        if field in values:
            old = values[field]
            suffix = (
                "\r\n"
                if block[old.start_mark.index : old.end_mark.index].endswith("\r\n")
                else "\n"
                if block[old.start_mark.index : old.end_mark.index].endswith("\n")
                else ""
            )
            replacements.append((old.start_mark.index, old.end_mark.index, rendered + suffix))
        else:
            newline = "\r\n" if "\r\n" in block else "\n"
            prefix = "" if block.endswith("\n") else newline
            replacements.append((len(block), len(block), f"{prefix}{field}: {rendered}{newline}"))
    for start, end, value in sorted(replacements, reverse=True):
        block = block[:start] + value + block[end:]
    result = text[: match.start(1)] + block + text[match.end(1) :]
    updated, _ = _metadata(result)
    if updated != {**original, **patch}:
        raise SemanticValidationError("source metadata cannot be preserved by this representation")
    return result


@dataclass(frozen=True)
class SemanticIntent:
    request_id: str
    operation: str
    artifact_id: str
    expected_version: str
    changes: Mapping[str, Any]
    resource: str
    context_ref: str
    vault_generation: str


@dataclass(frozen=True)
class SemanticResult:
    status: str
    source_effect: str = "not_applied"
    receipt: Mapping[str, Any] | None = None
    reason: str | None = None


class KnowledgeSemanticOwner:
    """Direct composition only; caller admission cannot manufacture semantic approval.

    ``authorize_semantic`` resolves the exact normalized intent to an existing
    applicable human decision; ``authority_is_current`` checks that same approval
    again at the CAS seam. Both ports are required, with no allow-by-default path.
    """

    def __init__(
        self,
        *,
        vault_root: Path,
        active_context: ActiveContextSetV1,
        target_binding_id: str,
        registry_store: VaultRegistryStore,
        context_is_current: Callable[[], bool],
        authorize_semantic: Callable[[SemanticIntent], GovernedWriteGrant | None],
        authority_is_current: Callable[[SemanticIntent, GovernedWriteGrant], bool],
        receipt_path: Path,
        write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
        reconcile_projection: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.root = Path(os.path.abspath(vault_root))
        if self.root.resolve() != self.root:
            raise KnowledgeCapabilityError("semantic source root must be canonical")
        if not all(
            callable(port)
            for port in (context_is_current, authorize_semantic, authority_is_current)
        ):
            raise KnowledgeCapabilityError(
                "semantic composition requires explicit context and approval ports"
            )
        self.active_context = active_context
        self.target_binding_id = target_binding_id
        self.registry_store = registry_store
        self.context_is_current = context_is_current
        self.authorize_semantic = authorize_semantic
        self.authority_is_current = authority_is_current
        self.receipt_path = receipt_path
        self.write_guard = write_guard
        self.reconcile_projection = reconcile_projection

    @property
    def actor(self) -> str:
        return self.active_context.principal_context.principal_id

    def _context(self) -> None:
        configured = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
        if (
            not configured
            or Path(configured).resolve() != self.registry_store.path.resolve()
            or self.target_binding_id not in self.active_context.binding_ids
        ):
            raise InvalidDecisionTokenError("semantic source context is unavailable or mismatched")
        snapshot = self.registry_store.read_existing()
        registration = snapshot.registrations.get(self.target_binding_id)
        if (
            snapshot.app_install_id != self.active_context.instance_identity
            or registration is None
            or Path(registration.path).resolve() != self.root
        ):
            raise InvalidDecisionTokenError("semantic root differs from the selected binding")
        # Registry/path reads above may block. Observe current selection and
        # lifetime after them; the GOV seam repeats expiry after approval too.
        if not self.context_is_current() or (
            self.active_context.expires_at is not None
            and self.active_context.expires_at <= time.time()
        ):
            raise InvalidDecisionTokenError("semantic source context is unavailable or expired")

    def _path(self, path: Path, *, mutable: bool) -> str:
        relative = path.relative_to(self.root).as_posix()
        if (
            path.resolve() != path
            or any(part.startswith(".") for part in path.relative_to(self.root).parts)
            or nearest_enclosing_vault_root(path, search_root=self.root) != self.root
            or vault_path_is_within(
                relative, get_vault_system_dir_rel(self.root), vault_root=self.root
            )
            or path.name.endswith(".meta.md")
            or is_conflict_artifact(relative)
        ):
            raise SemanticValidationError(
                "source is aliased, system-owned, or outside the selected vault"
            )
        if mutable:
            assert_targets_do_not_overlap_capture_note([relative], vault_root=self.root)
            if (
                classify_note_in_vault(
                    relative,
                    WriteOperation.WRITE,
                    vault_root=self.root,
                    sources_root_rel=get_vault_sources_dir_rel(self.root),
                )
                is not NoteClass.REWRITTEN
            ):
                raise SemanticValidationError(
                    "semantic writes require an existing rewritten human note"
                )
        locator = make_note_locator(relative, vault=self.target_binding_id)
        if locator.path != relative:
            raise SemanticValidationError("source locator spelling must already be canonical")
        return locator.path

    def _resolve_many(
        self, artifact_ids: set[str]
    ) -> dict[str, tuple[Path, str, str, dict[str, Any]]]:
        matches: dict[str, tuple[Path, str, str, dict[str, Any]]] = {}
        # UUIDs are read from actual authorized sources, never DB membership,
        # rendered Panel order, search results, or the current folder order.
        for directory, folders, files in os.walk(self.root, followlinks=False):
            parent = Path(directory)
            folders[:] = [
                name
                for name in folders
                if not name.startswith(".")
                and not (parent / name).is_symlink()
                and nearest_enclosing_vault_root(parent / name, search_root=self.root) == self.root
            ]
            for name in files:
                path = parent / name
                if path.suffix.lower() != ".md":
                    continue
                try:
                    relative = self._path(path, mutable=False)
                except SemanticValidationError:
                    continue
                text, version = read_note_text_with_version(path)
                if not _FRONTMATTER.match(text):
                    continue
                block = _FRONTMATTER.match(text)
                assert block is not None
                # Locate candidates without imposing this command's metadata
                # preconditions on every unrelated human note in the vault.
                # A matching candidate is then decoded strictly before it can
                # supply identity, membership or mutation content.
                try:
                    candidate_ids = _declared_identities(
                        yaml.compose(block[1], Loader=yaml.SafeLoader)
                    )
                except yaml.YAMLError:
                    flattened = block[1].lower().replace("-", "")
                    if any(identity.replace("-", "") in flattened for identity in artifact_ids):
                        raise SemanticValidationError(
                            "a matching source candidate has malformed frontmatter"
                        )
                    continue
                if not candidate_ids.intersection(artifact_ids):
                    continue
                metadata, _ = _metadata(text)
                identity = _uuid(metadata.get("uuid"))
                if identity in artifact_ids:
                    resolved = resolve_note_artifact_identity(
                        artifact_path=path,
                        vault_root=self.root,
                        safe_note_path=relative,
                        body=text,
                        heal_missing_uuid=False,
                    )
                    if not resolved.owns_identity or resolved.artifact_kind != "human_note":
                        raise SemanticValidationError("member identity is not a human note")
                    if identity in matches:
                        raise SemanticValidationError(
                            "source UUID is ambiguous in the selected vault"
                        )
                    matches[identity] = (path, text, version, metadata)
        if set(matches) != artifact_ids:
            raise SemanticValidationError(
                "source UUID is unresolved or ambiguous in the selected vault"
            )
        return matches

    def _resolve(self, artifact_id: str) -> tuple[Path, str, str, dict[str, Any]]:
        return self._resolve_many({artifact_id})[artifact_id]

    def _changes(
        self, operation: str, arguments: Mapping[str, Any], metadata: Mapping[str, Any]
    ) -> dict[str, Any]:
        current_class = _vocabulary(metadata.get("artifact_class", "human_knowledge"))
        if current_class not in HUMAN_CLASSES or metadata.get("authority_state") == "proposal":
            raise SemanticValidationError(
                "semantic edits cannot promote a non-human artifact family"
            )
        if operation == CLASSIFY:
            if not arguments or set(arguments) - {"artifact_class", "artifact_type"}:
                raise SemanticValidationError(
                    "classify admits only artifact_class and artifact_type"
                )
            patch = {key: _vocabulary(value) for key, value in arguments.items()}
            selected = patch.get("artifact_class", current_class)
            if selected not in HUMAN_CLASSES or (
                "artifact_type" in patch and patch["artifact_type"] not in HUMAN_TYPES
            ):
                raise SemanticValidationError(
                    "classification vocabulary or subdivision is not admitted"
                )
            return patch
        if operation in {TAGS_ADD, TAGS_REMOVE}:
            if set(arguments) != {"tags"} or "tag" in metadata:
                raise SemanticValidationError("tag edits require only the canonical tags field")
            requested = set(_tags(arguments["tags"]))
            existing = set(_tags(metadata.get("tags", [])))
            return {
                "tags": sorted(
                    existing | requested if operation == TAGS_ADD else existing - requested
                )
            }
        if (
            operation != REORDER
            or set(arguments) != {"ordered_ids"}
            or "member_order" not in metadata
        ):
            raise SemanticValidationError("reorder requires an already authored member_order list")
        source_members, proposed = (
            _members(metadata["member_order"]),
            _members(arguments["ordered_ids"]),
        )
        if set(source_members) != set(proposed):
            raise SemanticValidationError(
                "ordered_ids must be a complete permutation of source membership"
            )
        self._resolve_many(set(source_members))
        return {"member_order": proposed}

    def apply(
        self,
        *,
        request_id: str,
        operation: str,
        artifact_id: str,
        expected_version: str,
        arguments: Mapping[str, Any],
    ) -> SemanticResult:
        source: WriteReceipt | None = None
        receipt: dict[str, Any] | None = None
        source_started = False
        try:
            self._context()
            if operation not in SEMANTIC_OPERATIONS or not request_id or not expected_version:
                return SemanticResult(
                    "invalid", reason="semantic operation, request and source version are required"
                )
            identity = _uuid(artifact_id)
            # The read window admits source reads before proposal validation;
            # the subsequent write window revalidates the exact full selection.
            from app.instance.context_bound_read import context_bound_read_window

            with context_bound_read_window(self.active_context, registry_store=self.registry_store):
                path, text, version, metadata = self._resolve(identity)
                resource = self._path(path, mutable=True)
                if version != expected_version:
                    return SemanticResult(
                        "conflicted", reason="expected raw-byte source version is stale"
                    )
                patch = self._changes(operation, arguments, metadata)
                content = _replace_fields(text, patch)
            intent = SemanticIntent(
                request_id,
                operation,
                identity,
                version,
                patch,
                resource,
                self.active_context.context_id,
                str(self.active_context.generation),
            )
            grant = self.authorize_semantic(intent)
            gov = GovernedWriteAdapter()
            binding = {
                "action": f"operation.{operation}",
                "write_class": "vault_semantic_edit",
                "actor": self.actor,
                "resource": resource,
            }

            def check() -> None:
                # Source and health checks can block. Complete them before
                # observing the final current context and semantic approval.
                if operation == REORDER:
                    self._resolve_many(set(patch["member_order"]))
                self.write_guard.assert_writes_allowed(binding["action"])
                self._context()
                if (
                    not isinstance(grant, GovernedWriteGrant)
                    or grant.policy_decision.source != "human_review"
                    or grant.policy_decision.decision_id != grant.decision_token.decision_id
                    or any(
                        getattr(grant.policy_decision, key) != value
                        for key, value in binding.items()
                    )
                    or not self.authority_is_current(intent, grant)
                ):
                    raise InvalidDecisionTokenError(
                        "applicable explicit semantic approval is required"
                    )
                gov.validate_decision_token(decision_token=grant.decision_token, **binding)
                gov.validate_context(
                    grant.decision_token,
                    context=self.active_context,
                    target_binding_id=self.target_binding_id,
                )

            check()
            assert grant is not None
            with context_bound_write_window(
                self.active_context,
                target_binding_id=self.target_binding_id,
                token=grant.decision_token,
                registry_store=self.registry_store,
                effect_check=check,
                **binding,
            ) as selected_root:
                if selected_root != self.root:
                    raise InvalidDecisionTokenError("selected semantic source root changed")
                check()
                source_started = True
                try:
                    source = write_note_from_absolute(
                        path,
                        content,
                        vault_root=self.root,
                        action=binding["action"],
                        write_guard=self.write_guard,
                        expected_version=version,
                        writer_identity=self.actor,
                        vault=self.target_binding_id,
                    )
                except KnowledgeWriteConflict as exc:
                    if exc.receipt is None or exc.receipt.outcome != "conflict_staged":
                        raise
                    source = exc.receipt
                receipt = cast(
                    dict[str, Any],
                    json.loads(
                        json.dumps(
                            {
                                "owner": "knowledge.semantic",
                                "request_id": request_id,
                                "operation": operation,
                                "artifact_id": identity,
                                "input_version": version,
                                "resulting_version": sha256(content.encode()).hexdigest(),
                                "changes": patch,
                                "source_receipt": asdict(source),
                                "policy_decision": asdict(grant.policy_decision),
                                "decision_token": asdict(grant.decision_token),
                                "projection_repair": ["store", "index", "link"]
                                if source.outcome == "written"
                                else [],
                                "effect_state": "source_applied"
                                if source.outcome == "written"
                                else "source_conflict_staged",
                            }
                        )
                    ),
                )
                authority = gov.record_authority_receipt(
                    decision_token=grant.decision_token,
                    mutation_receipt=cast(Any, source),
                    state_owner="knowledge",
                    trace_id=request_id,
                    effect_id=request_id,
                    outcome="failed" if source.outcome == "conflict_staged" else "applied",
                )
                receipt["authority_receipt"] = json.loads(json.dumps(asdict(authority)))
                receipt["receipt_id"] = authority.receipt_id
                event = make_outbox_event(
                    event="governance.authority_receipt.recorded",
                    source="operations.semantic",
                    trace_id=request_id,
                    payload=receipt,
                )
                if not append_jsonl_outbox_event(
                    self.receipt_path, event, default_source="operations.semantic"
                ):
                    raise RuntimeError("semantic AuthorityReceipt persistence failed")
            if source.outcome == "conflict_staged":
                return SemanticResult(
                    "conflicted",
                    receipt=receipt,
                    reason="HKA staged the proposal; source is unchanged",
                )
            if self.reconcile_projection is not None:
                try:
                    self.reconcile_projection(receipt)
                except Exception:
                    return SemanticResult(
                        "convergence_pending",
                        "committed",
                        receipt,
                        "source is receipted; projection repair is required",
                    )
                return SemanticResult("succeeded", "committed", receipt)
            return SemanticResult(
                "convergence_pending",
                "committed",
                receipt,
                "source is receipted; rebuild Store/index/link from source",
            )
        except (SemanticValidationError, VaultPathOverlapError, yaml.YAMLError) as exc:
            return SemanticResult("invalid", reason=str(exc))
        except (
            InvalidDecisionTokenError,
            ContextBoundReadError,
            ActiveContextError,
            RegistryError,
            WritesBlockedError,
        ) as exc:
            if source is not None:
                effect = "committed" if source.outcome == "written" else "not_applied"
                return SemanticResult(
                    "recovery_required",
                    effect,
                    receipt or {"source_receipt": asdict(source)},
                    str(exc),
                )
            return SemanticResult("rejected", reason=str(exc))
        except KnowledgeAtomicExchangeNotApplied as exc:
            return SemanticResult("not_supported", reason=str(exc))
        except KnowledgeCapabilityError as exc:
            if not source_started:
                return SemanticResult("not_supported", reason=str(exc))
            return SemanticResult(
                "recovery_required",
                "committed" if source is not None and source.outcome == "written" else "unknown",
                receipt or ({"source_receipt": asdict(source)} if source is not None else None),
                str(exc),
            )
        except Exception as exc:
            effect = (
                "committed"
                if source is not None and source.outcome == "written"
                else "unknown"
                if source_started
                else "not_applied"
            )
            if receipt is None and source is not None:
                receipt = {"source_receipt": asdict(source), "request_id": request_id}
            return SemanticResult(
                "recovery_required",
                effect,
                receipt,
                f"reconcile source and receipts before retry ({type(exc).__name__})",
            )


__all__ = ["KnowledgeSemanticOwner", "SemanticIntent", "SemanticResult", "SEMANTIC_OPERATIONS"]
