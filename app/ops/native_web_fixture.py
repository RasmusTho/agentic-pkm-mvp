"""Finite synthetic source bootstrap in the actual Product API process.

These are input artifacts, not fabricated Product results. Every write uses
its existing producer and normal guard; unsupported initialization is refused.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from app.agent_memory.review_queue import MemoryCandidateReviewQueue
from app.ops.native_web_acceptance import NativeWebRefusal, hash_json

NOTE_UUID = '59690000-0000-4000-8000-000000000001'
NOTE_PATH = 'Projects/native-web-acceptance.md'
REVIEW_NOTE_UUID = '59690000-0000-4000-8000-000000000004'
REVIEW_NOTE_PATH = 'Projects/native-web-review.md'
CAPTURE_NOTE_UUID = '59690000-0000-4000-8000-000000000005'
CAPTURE_NOTE_PATH = 'Inbox/native-web-capture.md'
SCOPE_ID = 'work'
CANDIDATE_IDS = tuple('native-web-' + name for name in ('promote', 'reject', 'defer', 'revise'))


def bootstrap_fixture(vault_root: Path, generation: str, *, review_queue: MemoryCandidateReviewQueue) -> dict[str, Any]:
    from app.agent_memory.candidate import MemoryCandidate, MemoryType
    from app.agent_memory.companion_aware import SynthesisCompanion, discover_candidates_from_companions
    from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
    from app.domain.commitments import CommitmentRecord
    from app.episodes.notes import render_episode_note
    from app.knowledge.write_ops import write_note_relative
    from app.relevance.materialization import materialize_moment
    from app.relevance.schema import Moment, MomentNeed, MomentProvenance, MomentTrigger, MomentUrgency, SurfacedRef
    from app.services.commitment_persistence import persist_commitment
    from app.vault.manager import get_vault_manager

    if (str(UUID(generation)) != generation or vault_root.is_symlink()
        or (vault_root.exists() and any(vault_root.iterdir()))
        or review_queue.pending()
        or review_queue.decided()):
        raise NativeWebRefusal('fixture_not_fresh')
    manager = get_vault_manager()
    manager.initialize_vault(vault_root, vault_name='Synthetic native web acceptance', machine_role='testNode')
    context = manager.select_vault(vault_root)
    if context.status != 'selected' or not context.active_vault_id or not context.local_instance_id:
        raise NativeWebRefusal('canonical_vault_initialization_unavailable')
    now = datetime.now(UTC)
    content = ('---\nuuid: ' + NOTE_UUID + '\ntitle: Synthetic native acceptance\n'
               'scope: ' + SCOPE_ID + '\n---\n# Synthetic native acceptance\n'
               'This source is disposable and belongs to operation generation ' + generation + '.\n')
    write_note_relative(NOTE_PATH, content, vault_root=vault_root, writer_identity='synthetic.native-web', create_once=True)
    mutable = []
    from app.vault.paths import get_vault_capture_note_rel
    capture_path = get_vault_capture_note_rel(vault_root)
    for note_uuid, path, effect in ((REVIEW_NOTE_UUID, REVIEW_NOTE_PATH, 'panel_confirm'),
                                     (CAPTURE_NOTE_UUID, capture_path, 'capture')):
        write_note_relative(path, content.replace(NOTE_UUID, note_uuid), vault_root=vault_root,
                            writer_identity='synthetic.native-web', create_once=True)
        mutable.append({'note_uuid': note_uuid, 'note_path': path, 'effect': effect,
                        'seed_sha256': hashlib.sha256((vault_root / path).read_bytes()).hexdigest()})
    ref = 'vault://' + REVIEW_NOTE_PATH
    for kind in ('next_action', 'waiting', 'review_return'):
        persist_commitment(CommitmentRecord(
            commitment_id='native-web-' + kind, commitment_kind=kind,  # type: ignore[arg-type]
            state='waiting' if kind == 'waiting' else 'next', target_ref=ref,
            summary='Synthetic ' + kind, waiting_on='Synthetic calendar' if kind == 'waiting' else None,
            review_cadence='daily' if kind == 'review_return' else None,
        ), vault_context=context)
    moment = materialize_moment(Moment(
        uuid='59690000-0000-4000-8000-000000000002', created=now.isoformat(),
        trigger=MomentTrigger(kind='synthetic-source', source_ref=ref),
        need=MomentNeed(basis='reorientation', summary='Revisit the synthetic project'),
        surfaced_refs=[SurfacedRef(ref=ref, uuid=NOTE_UUID, why='Synthetic source')],
        urgency=MomentUrgency(band='timely', basis='Synthetic fixture', evaluator='native-web-fixture'),
        provenance=MomentProvenance(produced_by='synthetic.native-web', inputs_digest=hashlib.sha256(content.encode()).hexdigest()),
    ), vault_context=context)
    if moment.status != 'materialized':
        raise NativeWebRefusal('canonical_moment_materialization_unavailable')
    episode_id = 'ep-59690000-0000-4000-8000-000000000003'
    write_note_relative('episodes/' + episode_id + '.md', render_episode_note({
        'episode_id': episode_id, 'scope': SCOPE_ID, 'title': 'Synthetic work session',
        'time': {'start': now.isoformat(), 'closed': False}, 'space': [], 'protagonists': [],
        'goal': [], 'causation': [], 'parent_episode': None, 'segmentation': 'proposed', 'derived_from': [ref],
    }), vault_root=vault_root, writer_identity='synthetic.native-web', create_once=True)
    candidates = {candidate_id: MemoryCandidate(
        candidate_id=candidate_id, title='Synthetic ' + candidate_id, memory_type=MemoryType.SEMANTIC_MEMORY,
        source_refs=[ref], derived_from=REVIEW_NOTE_UUID, generated_by='synthetic.native-web',
        scope_id=SCOPE_ID, content='A synthetic proposal awaiting explicit review.',
    ) for candidate_id in CANDIDATE_IDS}
    queue = review_queue
    discovered = discover_candidates_from_companions([SynthesisCompanion(
        companion_for=REVIEW_NOTE_UUID, target_path=REVIEW_NOTE_PATH, candidates=candidates,
        generated_by='synthetic.native-web',
    )], queue, binding=COMPATIBILITY_BINDING_ID)
    if discovered is not queue or {entry.candidate_id for entry in queue.pending()} != set(CANDIDATE_IDS):
        raise NativeWebRefusal('api_process_memory_queue_unavailable')
    return {
        'scope_id': SCOPE_ID, 'note_uuid': NOTE_UUID, 'note_path': NOTE_PATH,
        'note_sha256': hashlib.sha256((vault_root / NOTE_PATH).read_bytes()).hexdigest(),
        'logical_vault_id': context.active_vault_id, 'local_clone_id': context.local_instance_id,
        'candidate_ids': list(CANDIDATE_IDS), 'resource_generation': generation,
        'controlled_mutable_sources': mutable,
        'review_note_uuid': REVIEW_NOTE_UUID, 'review_note_path': REVIEW_NOTE_PATH,
        'capture_note_uuid': CAPTURE_NOTE_UUID, 'capture_note_path': capture_path,
        'source_configuration': 'canonical-vault-commitments-moments-decisions-episodes-caldav',
    }


def _daily_helper() -> Any:
    # The helper is an exact-SHA read-only test resource, with Product imports
    # still baked. Missing delivered helper remains a recovery fact.
    from importlib import import_module
    try:
        helper = import_module('tests.companion_ui.live_daily_briefing')
    except ImportError:
        raise NativeWebRefusal('daily_source_helper_missing') from None
    if not isinstance(helper.__file__, str) or Path(helper.__file__).resolve() != Path('/app/tests/companion_ui/live_daily_briefing.py'):
        raise NativeWebRefusal('daily_source_helper_origin_mismatch')
    return helper


def prepare_daily_sources(fixture: dict[str, Any], resource_version: str) -> dict[str, Any]:
    from app.vault.manager import get_vault_manager
    from app.receipts.decision_receipt_log import append_decision_receipt, decisions_receipts_dir
    context = get_vault_manager().context
    root = Path(context.active_vault_path or '').resolve(strict=True)
    marker_relative = 'fixtures/native-web-daily.json'
    marker = root / marker_relative
    marker.parent.mkdir()
    admission = {'schema': 'daily-briefing-synthetic-fixture.v1', 'synthetic': True,
                 'run_id': fixture['resource_generation'], 'resource_version': resource_version,
                 'vault_id': context.active_vault_id, 'vault_path': str(root)}
    descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(admission, stream, sort_keys=True)
    # The original helper's previous-day monthly log must be absent. It runs
    # first at the actual fixture day; native's own normal append follows.
    from app.briefing.config import BRIEFING_TIMEZONE
    for_date = datetime.now(ZoneInfo(BRIEFING_TIMEZONE)).date()
    result = _daily_helper().prepare_sources(vault_context=context,
                 for_date=for_date,
                 run_id=fixture['resource_generation'], marker_path=marker_relative)
    now = datetime.now(UTC)
    shard = decisions_receipts_dir(root) / ('decisions-' + now.strftime('%Y%m') + '.jsonl')
    prior = shard.read_bytes() if shard.exists() else b''
    receipt = append_decision_receipt(object_id=NOTE_UUID, key='review', value={
        'actor': 'synthetic.native-web', 'source': 'vault://' + REVIEW_NOTE_PATH, 'scope_id': SCOPE_ID,
    }, trace_id=fixture['resource_generation'], created_at=now, vault_root=root, vault_uuid=context.active_vault_id)
    current = shard.read_bytes()
    if not current.startswith(prior) or json.loads(current[len(prior):]) != receipt:
        raise NativeWebRefusal('native_seed_receipt_append_unknown')
    # Only this observed canonical bootstrap append advances its initial hash;
    # every other original helper inventory entry stays byte-exact.
    result['source_files'][shard.relative_to(root).as_posix()] = hashlib.sha256(current).hexdigest()
    fixture['native_seed_receipt'] = receipt
    from app.briefing.compose import briefing_note_path
    result.update(date=for_date.isoformat(), briefing_path=briefing_note_path(vault_context=context, for_date=for_date).relative_to(root).as_posix())
    return result


def fixture_readback(vault_root: Path, fixture: dict[str, Any]) -> dict[str, Any]:
    from app.vault.markdown_settings import MarkdownSettingsStore
    from app.vault.manager import get_vault_manager
    context = get_vault_manager().validate_vault(vault_root)
    note = vault_root / fixture['note_path']
    settings = vault_root / 'settings'
    if not note.is_file() or note.is_symlink() or context.status != 'selected':
        raise NativeWebRefusal('fixture_identity_unknown')
    settings_hashes = {}
    for path in sorted(settings.rglob('*')):
        if path.is_symlink():
            raise NativeWebRefusal('fixture_configuration_drift')
        if path.is_file():
            settings_hashes[path.relative_to(settings).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    mutable = {}
    for source in fixture['controlled_mutable_sources']:
        path = vault_root / source['note_path']
        if path.is_symlink() or not path.is_file() or MarkdownSettingsStore().read(path).frontmatter.get('uuid') != source['note_uuid']:
            raise NativeWebRefusal('mutable_fixture_identity_drift')
        mutable[source['note_path']] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {**fixture, 'note_sha256': hashlib.sha256(note.read_bytes()).hexdigest(),
            'logical_vault_id': context.active_vault_id, 'local_clone_id': context.local_instance_id,
            'settings_hash': hash_json(settings_hashes), 'mutable_readback': mutable}
