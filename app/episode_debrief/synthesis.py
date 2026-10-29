"""DEBRIEF-02: adapt a closure trigger to the existing, proposal-only Create engine.

The event is the intent. Retrieval admits only active bound artifacts; Create
owns citations, proposal construction, durable draft publication and receipts.
The only Episode mutation is a versioned, additive debrief_ref patch.
"""
from __future__ import annotations

from contextlib import nullcontext
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

import yaml

from app.activation import expansion_records
from app.activation.gate import ActivationPosture
from app.episode_debrief import store
from app.episode_debrief.trigger import (
    _assert_selected_vault_owns_path, _is_configured_scalar_root,
    debrief_id_for_episode,
)
from app.episodes.notes import parse_episode_note_document
from app.expansion import create
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.instance.scalar_binding_runtime import resolve_scalar_binding_runtime
from app.knowledge.write_ops import read_note_text_with_version, write_note_from_absolute
from app.reasoning.multi import ReasoningSourceInput, materialize_reasoning_inputs
from app.retrieval.capability import RetrievalHit, RetrievalRequest, retrieve
from app.receipts.decision_receipt_log import iter_decision_receipts
from app.workers.outbox_binding_gate import current_binding_effect_window
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
from scripts.yaml_roundtrip import load_frontmatter

_LOG = logging.getLogger(__name__)
WRITE_ACTION = "episode_debrief.synthesize"
SECTIONS = ("decisions", "commitments", "open_loops", "key_captures")


class DebriefSynthesisError(ValueError):
    """Typed, retryable refusal; never acknowledge an unlinked draft as success."""


def append_debrief_ref_text(raw: str, *, episode_id: str, scope: str, debrief_id: str) -> str:
    """Patch one YAML value, preserving every unrelated byte (including CRLF)."""
    fields, _ = parse_episode_note_document(raw)
    if fields.get("episode_id") != episode_id or fields.get("scope") != scope or not fields["time"]["closed"]:
        _LOG.warning("debrief_ref append refused: Episode identity/scope/closure changed")
        raise DebriefSynthesisError("Episode identity, scope or closure changed")
    if debrief_id != debrief_id_for_episode(episode_id):
        raise DebriefSynthesisError("debrief identity does not belong to this Episode")
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", raw, re.S)
    if match is None:
        raise DebriefSynthesisError("Episode frontmatter cannot be patched")
    if any(isinstance(token, yaml.tokens.AliasToken) for token in yaml.scan(match.group(1))):
        raise DebriefSynthesisError("aliased Episode fields cannot be patched safely")
    document = yaml.compose(match.group(1))
    if not isinstance(document, yaml.MappingNode):
        raise DebriefSynthesisError("Episode frontmatter must be a mapping")
    keys = [key.value for key, _ in document.value]
    if len(keys) != len(set(keys)):
        raise DebriefSynthesisError("duplicate Episode fields are ambiguous")
    refs = fields.get("debrief_ref", [])
    if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
        raise DebriefSynthesisError("debrief_ref must be an identity list")
    if debrief_id in refs:
        return raw
    def checked(result: str) -> str:
        after, after_body = parse_episode_note_document(result)
        before_without_ref = {key: value for key, value in fields.items() if key != "debrief_ref"}
        after_without_ref = {key: value for key, value in after.items() if key != "debrief_ref"}
        if before_without_ref != after_without_ref or parse_episode_note_document(raw)[1] != after_body:
            raise DebriefSynthesisError("debrief patch attempted to change protected Episode content")
        return result
    value = json.dumps([*refs, debrief_id], ensure_ascii=False)
    for key, node in document.value:
        if key.value == "debrief_ref":
            start = match.start(1) + node.start_mark.index
            end = match.start(1) + node.end_mark.index
            # Block sequences consume the following newline; restore it exactly.
            suffix = raw[end:]
            if raw[start:end].endswith(("\n", "\r")):
                value += "\r\n" if "\r\n" in raw[start:end] else "\n"
            return checked(raw[:start] + value + suffix)
    newline = "\r\n" if raw.startswith("---\r\n") else "\n"
    offset = match.end(1)
    return checked(raw[:offset] + newline + "debrief_ref: " + value + raw[offset:])


def _read_episode(path: Path, episode_id: str, scope: str) -> tuple[str, str, dict[str, Any]]:
    raw, version = read_note_text_with_version(path)
    fields, _ = parse_episode_note_document(raw)
    # The patcher validates identity/closure even when the ref is already present.
    append_debrief_ref_text(raw, episode_id=episode_id, scope=scope,
                            debrief_id=debrief_id_for_episode(episode_id))
    return raw, version, fields


def _sources(
    members: tuple[tuple[str, str], ...], *, scope: str, root: Path,
    source_binding_id: str, effect_binding_id: str, episode_id: str, episode_fields: Mapping[str, Any],
) -> tuple[tuple[create.SourceInput, ...], tuple[tuple[str, tuple[str, ...]], ...]]:
    if not members or any(member_scope != scope for _, member_scope in members):
        raise DebriefSynthesisError("cross_scope_no_flow: active binding scope differs from trigger")
    from datetime import datetime
    times = episode_fields["time"]
    start = datetime.fromisoformat(str(times["start"]).replace("Z", "+00:00"))
    end = datetime.fromisoformat(str(times["end"]).replace("Z", "+00:00")) if times.get("end") else None
    observations = tuple(store.resolve_synthesis_artifact(ref, vault_binding_id=source_binding_id, vault_root=root) for ref, _ in members)
    # Multiple active activity refs can describe one logical source. Choose its
    # latest in-interval observation, not a stale pre-assignment duplicate.
    grouped: dict[str, list[store.SynthesisArtifact]] = {}
    for observation in observations:
        grouped.setdefault(observation.identity, []).append(observation)
    artifacts = tuple(max((item for item in items if item.observed_at is not None
        and item.observed_at >= start.timestamp() and (end is None or item.observed_at <= end.timestamp())),
        key=lambda item: (item.observed_at or 0, item.provenance_ref), default=items[0])
        for items in grouped.values())
    identities = tuple(item.identity for item in artifacts)
    response = retrieve(RetrievalRequest(
        query=episode_id, scope=scope, domain=scope, k=len(identities),
        artifact_episode_id=episode_id, artifact_ids=identities, artifact_binding_ids=(source_binding_id,) if source_binding_id != COMPATIBILITY_BINDING_ID else None,
    ))
    by_identity: dict[str, RetrievalHit] = {}
    for hit in response.hits:
        payload = hit.payload
        # Exact scope is stricter than the ordinary retrieval bridge prefilter.
        if (payload.get("domain") or payload.get("scope_id")) != scope:
            raise DebriefSynthesisError("cross_scope_no_flow: retrieved source differs from trigger")
        if hit.evidence_role_in_context not in {"reference", "background", "evidence"}:
            raise DebriefSynthesisError("source evidence role does not admit cited synthesis")
        for identity in (hit.object_id, hit.source_ref, payload.get("provenance_ref")):
            if identity in identities:
                if identity in by_identity and by_identity[identity] != hit:
                    raise create.UnresolvableCitationError("ambiguous bound source identity")
                by_identity[identity] = hit
    if set(by_identity) != set(identities):
        raise create.UnresolvableCitationError("one or more bound citations cannot be resolved in scope")
    receipts_by_object: dict[str, list[dict[str, Any]]] = {}
    for record in iter_decision_receipts(root):
        if record.get("object_id") not in {hit.object_id for hit in response.hits}:
            continue
        try:
            at = datetime.fromisoformat(str(record["created_at"]).replace("Z", "+00:00"))
            if at < start or (end is not None and at > end):
                continue
        except (KeyError, ValueError, TypeError) as exc:
            raise create.UnresolvableCitationError("bound decision receipt has no resolvable time") from exc
        receipts_by_object.setdefault(record["object_id"], []).append(record)
    selected: list[tuple[RetrievalHit, str, str, str | None, str]] = []
    sections: dict[str, list[int]] = {name: [] for name in SECTIONS}
    for index, identity in enumerate(identities):
        hit = by_identity[identity]
        heimdal_observation = hit.payload.get("heimdal_observation")
        if heimdal_observation is not None:
            at = datetime.fromisoformat(str(heimdal_observation["observed_at_start"]).replace("Z", "+00:00"))
            if at < start or (end is not None and at > end):
                raise create.UnresolvableCitationError("bound Heimdal observation is outside Episode bounds")
            raw_observation = json.dumps(heimdal_observation, sort_keys=True, ensure_ascii=False)
            sections["key_captures"].append(len(selected))
            selected.append((hit, raw_observation, hit.text, None, identity))
            continue
        note_path = hit.payload.get("note_path") or hit.payload.get("path")
        if not isinstance(note_path, str):
            raise create.UnresolvableCitationError("bound source has no retained note path")
        path = root / note_path
        _assert_selected_vault_owns_path(root, path.resolve(), "debrief source")
        raw, _ = read_note_text_with_version(path)
        fields, body = load_frontmatter(raw)
        if fields.get("uuid") is not None and store.canonical_note_identity(str(fields["uuid"]), vault_binding_id=source_binding_id) != hit.object_id:
            raise create.UnresolvableCitationError("retained source identity differs from the scoped canonical identity")
        source_scopes = [fields[key] for key in ("scope", "domain") if fields.get(key) is not None]
        if any(source_scope != scope for source_scope in source_scopes):
            raise DebriefSynthesisError("cross_scope_no_flow: retained note differs from trigger")
        from app.agents.panel.filters import strip_ai_panels
        from app.agents.panel.writeback import strip_ai_status_block
        source_text = strip_ai_status_block(strip_ai_panels(body)).strip()
        if not source_text or source_text != hit.text.strip():
            raise create.UnresolvableCitationError("retained citation differs from canonical ingest source text")
        selected.append((hit, raw, source_text, note_path, artifacts[index].provenance_ref))
        commitment = fields.get("commitment")
        commitment = commitment if isinstance(commitment, dict) else {}
        kind = fields.get("kind")
        decisions = receipts_by_object.get(hit.object_id, [])
        is_decision = kind in {"decision", "decision_receipt"} or bool(decisions)
        if is_decision and not decisions:
            raise create.UnresolvableCitationError("decision has no resolvable receipt within Episode bounds")
        is_commitment = bool(commitment) or kind == "commitment" or "commitment_id" in fields
        if is_commitment:
            sections["commitments"].append(index)
        state = commitment.get("state") or fields.get("commitment_state") or fields.get("state") or fields.get("status")
        if is_commitment or state in {"in-progress", "in_progress"}:
            # Commitment kind persists across completion: it cannot override state.
            # A closure-time state claim requires the immutable watcher observation
            # admitted by the Episode binding, not today's mutable note alone.
            artifact = artifacts[index]
            digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            from app.episode_debrief.evidence import commitment_content_fingerprint
            state_matches = (artifact.content_fingerprint == commitment_content_fingerprint(fields, body)) if artifact.content_fingerprint else (artifact.content_hash == digest)
            if not state_matches or artifact.observed_at is None:
                raise create.UnresolvableCitationError("closure-time commitment state has no matching bound observation")
            from datetime import timezone
            observed = datetime.fromtimestamp(artifact.observed_at, timezone.utc)
            if observed < start or (end is not None and observed > end):
                raise create.UnresolvableCitationError("commitment observation is outside Episode bounds")
        if state in {"next", "next_action", "waiting", "in-progress", "in_progress"}:
            sections["open_loops"].append(index)
        if not is_decision and not is_commitment and index not in sections["open_loops"]:
            sections["key_captures"].append(index)
    # Receipts inherit only the already-admitted bound object's scope/role. Their
    # exact immutable JSON is cited, not silently replaced by the source summary.
    for hit, _, _, note_path, _ in tuple(selected):
        for record in receipts_by_object.get(hit.object_id, []):
            text = json.dumps(record, sort_keys=True, ensure_ascii=False)
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            sections["decisions"].append(len(selected))
            selected.append((hit, text, text, note_path, "decision-receipt:sha256:" + digest))
    inputs = materialize_reasoning_inputs([
        ReasoningSourceInput(source_id=f"{identity}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}", text=body)
        for _, raw, body, _, identity in selected
    ], namespace_key=f"episode-debrief:{effect_binding_id}:{episode_id}", vault_binding_id=effect_binding_id)
    sources = tuple(create.SourceInput(
        object_id=item.object_id, note_path=note_path, text=body, quoted_spans=(body,),
        review_state=hit.payload.get("review_state"), provenance_ref=identity, raw_bytes=raw.encode("utf-8"),
        evidence_role=hit.evidence_role_in_context,
    ) for item, (hit, raw, body, note_path, identity) in zip(inputs, selected, strict=True))
    return sources, tuple((name, tuple(sources[i].object_id for i in indexes)) for name, indexes in sections.items())


def synthesize_debrief(
    payload: Mapping[str, Any], *, vault_root: Path | str,
    vault_binding_id: str = COMPATIBILITY_BINDING_ID,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    activation_posture: ActivationPosture | None = None,
) -> dict[str, Any]:
    """Consume one trigger; blocked/refused work must not be acknowledged."""
    episode_id, debrief_id, scope = (payload.get(key) for key in ("episode_id", "debrief_id", "scope"))
    if not all(isinstance(value, str) and value for value in (episode_id, debrief_id, scope)):
        raise DebriefSynthesisError("invalid debrief trigger")
    assert isinstance(episode_id, str) and isinstance(debrief_id, str) and isinstance(scope, str)
    if debrief_id != debrief_id_for_episode(episode_id):
        raise DebriefSynthesisError("invalid debrief trigger identity")
    root = Path(vault_root).expanduser().resolve(strict=True)
    runtime = resolve_scalar_binding_runtime(requested_binding_id=vault_binding_id, vault_root=root)
    binding = runtime.vault_binding_id if runtime is not None else vault_binding_id
    projection_ids: tuple[str, ...] = (binding,)
    if binding != COMPATIBILITY_BINDING_ID and _is_configured_scalar_root(root):
        projection_ids = (binding, COMPATIBILITY_BINDING_ID)
    write_guard.assert_writes_allowed(WRITE_ACTION)
    with current_binding_effect_window(runtime) if runtime is not None else nullcontext():
        row, members, source_binding = store.synthesis_inputs(episode_id, projection_binding_ids=projection_ids)
        path = root / row.note_path
        _assert_selected_vault_owns_path(root, path.resolve(), "Episode note")
        decision = expansion_records.evaluate_synthesis_note_proposal_activation(
            [ref for ref, _ in members], posture=activation_posture,
        )
        if not decision.activatable:
            return {"status": "blocked", "reasons": list(decision.blocked_reasons)}
        draft_path = root / "_system/episode-debriefs" / f"{debrief_id}.md"
        activation_path = root / "_system/episode-debriefs/activation.jsonl"
        outbox_path = root / "_system/episode-debriefs/outbox.jsonl"
        # Validate each resolved leaf before the first effect, including lock
        # sidecars; containment of the directory or draft is not sufficient.
        destinations = [draft_path, activation_path, outbox_path, create._draft_integrity_path(draft_path),
            draft_path.with_name(f".{draft_path.name}.publication.lock"),
            path.with_name(f".{path.name}.publication.lock"),
            outbox_path.with_name(f".{outbox_path.name}.append.lock")]
        # Reused append/publication helpers derive locks after resolving aliases.
        # A same-vault leaf alias can therefore select a different lock filename.
        for target, suffix in ((draft_path, "publication"), (path, "publication"), (outbox_path, "append")):
            canonical = target.resolve()
            destinations.append(canonical.with_name(f".{canonical.name}.{suffix}.lock"))
        for destination in destinations:
            _assert_selected_vault_owns_path(root, destination.resolve(), "debrief destination")
        receipt_id = str(uuid5(NAMESPACE_URL, f"episode-debrief:{binding}:{debrief_id}"))
        with create._draft_publication_lock(path):
            raw, version, fields = _read_episode(path, episode_id, scope)
            if not (draft_path.exists() and debrief_id in fields.get("debrief_ref", [])):
                expansion_records.emit_expansion_gate_receipt(decision, receipt_path=activation_path)
            source_request = None
            if not draft_path.exists() or debrief_id not in fields.get("debrief_ref", []):
                sources, sections = _sources(members, scope=scope, root=root,
                    source_binding_id=source_binding, effect_binding_id=binding, episode_id=episode_id, episode_fields=fields)
                source_request = create.CreateRequest(kind=create.OutputKind.EPISODE_DEBRIEF,
                    title=f"Episode debrief: {fields['title']}", sources=sources, debrief_sections=sections, reasoning_binding_id=binding)
            if draft_path.exists():
                metadata, _ = load_frontmatter(draft_path.read_text(encoding="utf-8"))
                expected_fingerprint = create._request_fingerprint(source_request) if source_request is not None else metadata.get("request_fingerprint", "")
                retained = create._replay_draft_metadata(draft_path, request_fingerprint=expected_fingerprint, draft_id=debrief_id)
                assert retained is not None
                if metadata.get("episode_id") != episode_id or metadata.get("scope") != scope:
                    raise DebriefSynthesisError("existing draft belongs to another Episode or scope")
                receipt = create._existing_receipt(outbox_path, create.CREATE_PROPOSED_EVENT, receipt_id)
                expected_receipt = {
                    "draft_id": debrief_id, "kind": create.OutputKind.EPISODE_DEBRIEF.value,
                    "sources": metadata.get("sources", []),
                    "cognition_metadata": metadata.get("proposed_by", {}).get("cognition", {}),
                    "draft_path": str(draft_path.relative_to(root)),
                    "language": metadata.get("language"), "language_rule": metadata.get("language_rule"),
                    "request_fingerprint": metadata.get("request_fingerprint"), "draft_sha256": retained[1],
                }
                if receipt is not None and receipt.get("payload") != expected_receipt:
                    raise create.CreateIdempotencyConflictError("debrief receipt does not match retained draft")
                if receipt is None:
                    # Re-enter Create to recover an artifact-before-receipt interruption.
                    report = None
                else:
                    report = {"draft": str(draft_path.relative_to(root))}
            else:
                report = None
            if report is None:
                assert source_request is not None
                created = create.run_create_pass(source_request,
                    vault_root=root, outbox_path=outbox_path, write_guard=write_guard,
                    draft_id=debrief_id, receipt_id=receipt_id,
                    draft_frontmatter_enricher=lambda draft: {"episode_id": episode_id, "scope": scope,
                        "debrief_source_refs": [ref.model_dump(exclude_none=True) for ref in draft.source_refs]},
                )
                if not created.activatable:
                    return {"status": "blocked", "reasons": list(created.blocked_reasons)}
            if debrief_id not in fields.get("debrief_ref", []):
                _, current_members, current_binding = store.synthesis_inputs(episode_id, projection_binding_ids=projection_ids)
                if (current_members, current_binding) != (members, source_binding):
                    raise DebriefSynthesisError("Episode membership changed before linking")
                current_sources, current_sections = _sources(current_members, scope=scope, root=root,
                    source_binding_id=current_binding, effect_binding_id=binding, episode_id=episode_id, episode_fields=fields)
                current_request = create.CreateRequest(kind=create.OutputKind.EPISODE_DEBRIEF,
                    title=f"Episode debrief: {fields['title']}", sources=current_sources,
                    debrief_sections=current_sections, reasoning_binding_id=binding)
                assert source_request is not None
                if create._request_fingerprint(current_request) != create._request_fingerprint(source_request):
                    raise create.UnresolvableCitationError("Episode evidence changed before linking")
            patched = append_debrief_ref_text(raw, episode_id=episode_id, scope=scope, debrief_id=debrief_id)
            changed = patched != raw
            if changed:
                write_note_from_absolute(path, patched, vault_root=root, write_guard=write_guard,
                                         action=WRITE_ACTION, expected_version=version)
            return {"status": "created" if changed else "already_debriefed", "kind": create.OutputKind.EPISODE_DEBRIEF.value,
                    "draft": str(draft_path.relative_to(root)), "episode_note_updated": changed}



def synthesize_episode(episode_id: str, *, vault_root: Path | str) -> dict[str, Any]:
    root = Path(vault_root).expanduser().resolve(strict=True)
    runtime = resolve_scalar_binding_runtime(vault_root=root)
    binding = runtime.vault_binding_id if runtime is not None else COMPATIBILITY_BINDING_ID
    return synthesize_debrief(store.trigger_for_episode(episode_id, vault_binding_id=binding),
                              vault_root=root, vault_binding_id=COMPATIBILITY_BINDING_ID)
