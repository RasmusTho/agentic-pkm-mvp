"""One fixed TEST-only consumer of the shipped journaling acceptance wrapper.

This is not another native-web pilot, a provider substitute, or parent acceptance.
The trusted native runner owns image/resources, transport and cleanup.
"""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import FrameType
from typing import Any

from app.ops import pg_acceptance
from app.ops.native_web_acceptance import NativeWebRefusal, hash_json

PROFILE = 'native-journaling.v1'
WRAPPER = 'tests/journaling/test_conversational_journaling_live_acceptance.py::test_conversational_journaling_live_acceptance'
SCENARIOS = ('preflight', 'day_context', 'conversation', 'transcript', 'primary_candidate',
             'synthetic_acceptance', 'canonical_materialization', 'second_conversation',
             'addendum_candidate', 'never_overwrite')
EFFECTS = {'conversation_sessions': 2, 'candidate_writes': 2, 'actor_checkbox_writes': 1, 'canonical_accepts': 1}
ACTOR = 'synthetic-journaling-acceptance-v1'
DEADLINE = 1800
EVIDENCE = Path('/scratch/journaling-evidence')
VAULT = Path('/scratch/vault')
MANIFEST = Path('/scratch/journaling-manifest.json')
SELECTION_HASH = hash_json([PROFILE, WRAPPER, SCENARIOS, EFFECTS, ACTOR, DEADLINE])


def identity(sha: str, digest: str, channel: str, operation_id: str) -> dict[str, str]:
    base = pg_acceptance.identity(sha, digest, channel, operation_id)
    if channel != 'test':
        raise NativeWebRefusal('fixed_test_journaling_invocation_required')
    return {**base, 'profile_version': PROFILE, 'selection_hash': SELECTION_HASH}


def private_json(path: Path, value: Any) -> None:
    """Durable complete-before-publication, atomic no-overwrite, or absent."""
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name + '.')
    temporary = Path(temporary_name)
    staged = None
    try:
        with os.fdopen(descriptor, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link publication is atomic and refuses an existing final name.
        staged = temporary.lstat()
        os.link(temporary, path, follow_symlinks=False)
        temporary.unlink()
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except BaseException:
        try:
            if staged is not None:
                # Only the exact link just published can be invalidated on a
                # failed acknowledgement; never remove a replaced/foreign file.
                try:
                    named = path.lstat()
                except FileNotFoundError:
                    named = None
                if named is not None and (named.st_dev, named.st_ino) == (staged.st_dev, staged.st_ino):
                    path.unlink()
                    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        os.fsync(parent)
                    finally:
                        os.close(parent)
        finally:
            temporary.unlink(missing_ok=True)
        raise


def file_hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise NativeWebRefusal('journaling_artifact_missing')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_report(report: Any, binding: dict[str, Any]) -> None:
    if not isinstance(report, dict):
        raise NativeWebRefusal('journaling_report_missing')
    expected = {'schema': 'conversational_journaling_execution.v1', 'channel': 'test',
                'run_id': binding['resource_generation'], 'fixture_id': 'jrnl-' + binding['resource_generation'],
                'actor_id': ACTOR, 'expected_sha': binding['source_sha'], 'observed_sha': binding['source_sha'],
                'expected_image_digest': binding['image_digest'], 'observed_image_digest': binding['image_digest']}
    rows = report.get('scenarios')
    if (any(report.get(key) != value for key, value in expected.items())
        or report.get('feature_acceptance') != 'PASS' or report.get('limitation') is not None
        or not isinstance(rows, list) or len(rows) != len(SCENARIOS)
        or any(not isinstance(row, dict) or row.get('outcome') != 'passed' for row in rows)
        or [row.get('name') for row in rows] != list(SCENARIOS)
        or report.get('effects') != EFFECTS
        or any(type(value) is not int for value in report.get('effects', {}).values())):
        raise NativeWebRefusal('journaling_scenarios_or_effects_incomplete')
    artifacts = report.get('artifacts')
    hashes = ('primary_transcript_sha256', 'second_transcript_sha256', 'primary_candidate_sha256',
              'addendum_candidate_sha256', 'canonical_before_sha256', 'canonical_after_sha256')
    if (not isinstance(artifacts, dict) or set(artifacts) != set(hashes) | {'acceptance_receipt_id'}
        or any(re.fullmatch(r'[0-9a-f]{64}', str(artifacts.get(key))) is None for key in hashes)
        or not artifacts.get('acceptance_receipt_id')
        or artifacts['canonical_before_sha256'] != artifacts['canonical_after_sha256']):
        raise NativeWebRefusal('journaling_artifact_inventory_incomplete')


def require_result(result: Any, binding: dict[str, Any]) -> None:
    if (not isinstance(result, dict) or result.get('result') != 'passed'
        or any(result.get(key) != binding[key] for key in (
            'profile_version', 'selection_hash', 'source_sha', 'image_digest', 'channel',
            'operation_id', 'resource_generation', 'resource_tree', 'app_image_id'))
        or result.get('wrapper') != WRAPPER or result.get('report_hash') != hash_json(result.get('report'))):
        raise NativeWebRefusal('journaling_result_identity_mismatch')
    require_report(result.get('report'), binding)
    observer = result.get('effect_observer')
    rows = observer.get('observed') if isinstance(observer, dict) else None
    if (not isinstance(observer, dict) or observer.get('effects') != EFFECTS
        or observer.get('order') != list(EffectObserver.ORDER) or not isinstance(rows, list)
        or len(rows) != 6 or any(not isinstance(row, dict) for row in rows)
        or [row.get('effect') for row in rows] != list(EffectObserver.ORDER)):
        raise NativeWebRefusal('journaling_observed_effects_incomplete')
    artifacts = result['report']['artifacts']
    if (rows[0].get('session_id') == rows[4].get('session_id') or not rows[0].get('session_id')
        or not rows[4].get('session_id') or rows[1].get('path') == rows[5].get('path')
        or rows[1].get('is_addendum') is not False or rows[5].get('is_addendum') is not True
        or not rows[1].get('candidate_uuid') or rows[1].get('candidate_uuid') == rows[5].get('candidate_uuid')
        or any(rows[index].get('authority_state') != 'proposal' or rows[index].get('derived_by') != 'conversation'
               for index in (1, 5))
        or any(not isinstance(rows[index].get('cognition'), dict)
               or rows[index]['cognition'].get('degraded') is not False
               or rows[index]['cognition'].get('outcome') in {'provider_failure', 'missing_input', 'empty_output'}
               for index in (1, 5))
        or rows[2].get('path') != rows[1].get('path') or rows[2].get('actor_id') != ACTOR
        or rows[1].get('sha256') != artifacts['primary_candidate_sha256']
        or rows[5].get('sha256') != artifacts['addendum_candidate_sha256']
        or rows[3].get('sha256') != artifacts['canonical_before_sha256']
        or rows[3].get('receipt_id') != artifacts['acceptance_receipt_id']
        or any(not isinstance(row.get('path'), str) or Path(row['path']).is_absolute()
               or '..' in Path(row['path']).parts or not row['path'] for row in rows)
        or any(re.fullmatch(r'[0-9a-f]{64}', str(row.get('sha256'))) is None for row in rows)):
        raise NativeWebRefusal('journaling_observed_artifacts_mismatch')
    fixture = result.get('fixture')
    if (not isinstance(fixture, dict) or fixture.get('run_id') != binding['resource_generation']
        or fixture.get('fixture_id') != result['report']['fixture_id'] or fixture.get('actor_id') != ACTOR
        or not fixture.get('logical_vault_id') or not fixture.get('local_clone_id')
        or not isinstance(fixture.get('sources'), dict) or len(fixture['sources']) < 3
        or any(re.fullmatch(r'[0-9a-f]{64}', str(value)) is None for value in fixture['sources'].values())):
        raise NativeWebRefusal('journaling_fixture_identity_unknown')
    provider = result.get('provider')
    if (not isinstance(provider, dict) or provider.get('execution_host_profile') != 'profile.codex_remote_host'
        or provider.get('provider') in {None, '', 'mock'} or provider.get('model') in {None, '', 'mock-chat'}):
        raise NativeWebRefusal('actual_product_provider_unavailable')
    calls = observer.get('provider_calls')
    if any(type(row['cognition'].get('source_count')) is not int
           or not 4 <= row['cognition']['source_count'] <= 8 for row in (rows[1], rows[5])):
        raise NativeWebRefusal('actual_drafting_provider_inventory_invalid')
    expected_calls = 6 + sum(row['cognition'].get('source_count', 0) for row in (rows[1], rows[5]))
    if (not isinstance(calls, list) or len(calls) != expected_calls or not 8 <= expected_calls <= 32
        or any(not isinstance(call, dict) or call.get('execution_host_profile') != 'profile.codex_remote_host'
               or call.get('provider') in {None, '', 'mock'} or not call.get('model')
               or call.get('degraded') is not False or call.get('preflight_status') != 'passed' for call in calls)):
        raise NativeWebRefusal('actual_product_provider_calls_incomplete')
    if (result.get('producer_pid') != 1 or result.get('producer_module') != '/app/app/ops/native_journaling_acceptance.py'
        or result.get('configuration_hash') != fixture.get('configuration_hash')
        or re.fullmatch(r'[0-9a-f]{64}', str(result.get('configuration_hash'))) is None
        or result.get('guarded_receipt', {}).get('event_id') != artifacts['acceptance_receipt_id']
        or result.get('guarded_receipt', {}).get('event') != 'journal.entry.accepted'
        or re.fullmatch(r'[0-9a-f]{64}', str(result.get('guarded_receipt', {}).get('sha256'))) is None):
        raise NativeWebRefusal('journaling_producer_or_guarded_receipt_unknown')


def bootstrap(binding: dict[str, Any]) -> dict[str, Any]:
    """Canonical source producers, using their ordinary guards, never fake results."""
    from app.domain.commitments import CommitmentRecord
    from app.knowledge.write_ops import write_note_relative
    from app.knowledge_acquisition.candidate_writeback import Candidate, write_candidate_note
    from app.receipts.decision_receipt_log import append_decision_receipt
    from app.services.commitment_persistence import persist_commitment
    from app.vault.manager import get_vault_manager
    from app.journaling.day_context import assemble_day_context

    if VAULT.exists() and any(VAULT.iterdir()):
        raise NativeWebRefusal('journaling_fixture_not_fresh')
    EVIDENCE.mkdir(mode=0o700)
    manager = get_vault_manager()
    manager.initialize_vault(VAULT, vault_name='Synthetic native journaling', machine_role='testNode')
    context = manager.select_vault(VAULT)
    if context.status != 'selected' or not context.active_vault_id or not context.local_instance_id:
        raise NativeWebRefusal('canonical_vault_initialization_unavailable')
    generation = binding['resource_generation']
    anchor = 'Notes/native-journaling.md'
    write_note_relative(anchor, '---\nuuid: 60500000-0000-4000-8000-000000000001\n'
                        'title: Synthetic evening\n---\nDisposable synthetic reflection.\n',
                        vault_root=VAULT, writer_identity=ACTOR, create_once=True)
    persist_commitment(CommitmentRecord('native-journaling-' + generation, 'next_action', 'done',
                       summary='Finished the synthetic task'), vault_context=context)
    now = datetime.now(UTC)
    append_decision_receipt(object_id='native-journaling-' + generation, key='review', value={},
                           trace_id=generation, created_at=now, vault_root=VAULT,
                           vault_uuid=context.active_vault_id)
    capture = write_candidate_note(Candidate(
        content_identity='sha256:' + hashlib.sha256(generation.encode()).hexdigest(),
        source_kind='synthetic', item_ref='native-journaling-' + generation,
        url='https://example.test/native-journaling', title='Synthetic day capture', creator=ACTOR,
        published=now.isoformat(), acquisition_method='synthetic-test-actor',
        transcript_available=False, extractions=(),
    ), vault_context=context)
    if capture.status != 'written':
        raise NativeWebRefusal('canonical_capture_unavailable')
    bundle = assemble_day_context(vault_context=context, for_date=date.today())
    if any(section.status != 'available' or not section.items for section in bundle.sections.values()):
        raise NativeWebRefusal('heterogeneous_journaling_sources_incomplete')
    sources = {}
    for item in bundle.included:
        if not isinstance(item.path, str) or not item.path:
            raise NativeWebRefusal('heterogeneous_journaling_source_identity_missing')
        sources[item.path] = file_hash(VAULT / item.path)
    marker = {'run_id': generation, 'fixture_id': 'jrnl-' + generation, 'actor_id': ACTOR,
              'channel': 'test', 'for_date': date.today().isoformat()}
    private_json(VAULT / '.journal-acceptance-fixture.json', marker)
    manifest = {**marker, 'expected_sha': binding['source_sha'], 'observed_sha': binding['source_sha'],
                'expected_image_digest': binding['image_digest'], 'observed_image_digest': binding['image_digest'],
                'vault_root': str(VAULT), 'anchor_note': anchor, 'output_dir': str(EVIDENCE),
                'outbox_path': str(EVIDENCE / 'journal-review-outbox.jsonl'), 'effect_budget': EFFECTS}
    private_json(MANIFEST, manifest)
    return {'logical_vault_id': context.active_vault_id, 'local_clone_id': context.local_instance_id,
            'sources': sources, 'anchor_sha256': file_hash(VAULT / anchor), **marker}


class RequiredJournalingResults:
    def __init__(self) -> None:
        self.passed = False
        self.bad = False

    def pytest_collection_finish(self, session: Any) -> None:
        import pytest
        if [item.nodeid for item in session.items] != [WRAPPER]:
            raise pytest.UsageError('fixed journaling wrapper missing')

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.skipped or report.failed or hasattr(report, 'wasxfail'):
            self.bad = True
        if report.when == 'call' and report.passed:
            if self.passed or report.nodeid != WRAPPER:
                self.bad = True
            self.passed = True

    def require_complete(self, status: int) -> None:
        if status != 0 or self.bad or not self.passed:
            raise NativeWebRefusal('journaling_wrapper_execution_incomplete')


class EffectObserver:
    """Observe original Product calls/returns; never replace any implementation."""
    ORDER = ('conversation', 'draft', 'actor', 'review', 'conversation', 'draft')

    def __init__(self, *, root: Path = Path('/app')) -> None:
        from app.journaling.draft import draft_journal_entry
        from app.journaling.review import process_journal_reviews_tick
        from tests.journaling.live_journaling_acceptance import _check_primary_accept
        self.functions = {'draft': draft_journal_entry,
                          'actor': _check_primary_accept, 'review': process_journal_reviews_tick}
        self.codes = {function.__code__: name for name, function in self.functions.items()}
        self.order: list[str] = []
        self.observed: list[dict[str, Any]] = []
        self.primary: Path | None = None
        self.canonical: Path | None = None
        self.canonical_hash: str | None = None
        self.root = root
        from app.components.llm.fabric import ChatClient
        self.chat_code = ChatClient.chat.__code__
        self.provider_calls: list[dict[str, Any]] = []
        self.provider_started = 0
        self.provider_active: set[int] = set()

    def profile(self, frame: FrameType, event: str, value: Any) -> None:
        if frame.f_code is self.chat_code and event == 'call':
            if Path(frame.f_code.co_filename).resolve() != self.root / 'app/components/llm/fabric.py':
                raise NativeWebRefusal('actual_product_provider_call_origin_invalid')
            self.provider_started += 1
            if self.provider_started > 32:
                raise NativeWebRefusal('actual_product_provider_calls_over_budget')
            self.provider_active.add(id(frame))
            return
        if frame.f_code is self.chat_code and event == 'return':
            if id(frame) not in self.provider_active:
                raise NativeWebRefusal('actual_product_provider_call_unobserved')
            self.provider_active.remove(id(frame))
            route = frame.f_locals['self'].model_access_route
            if (Path(frame.f_code.co_filename).resolve() != self.root / 'app/components/llm/fabric.py'
                or route is None or route.execution_host_profile != 'profile.codex_remote_host'
                or route.provider == 'mock' or route.degraded or route.preflight_status != 'passed'
                or not isinstance(value, str) or not value.strip()):
                raise NativeWebRefusal('actual_product_provider_call_unavailable')
            self.provider_calls.append({'execution_host_profile': route.execution_host_profile,
                                        'provider': route.provider, 'model': route.model, 'degraded': route.degraded,
                                        'preflight_status': route.preflight_status})
            if len(self.provider_calls) > 32:
                raise NativeWebRefusal('actual_product_provider_calls_over_budget')
            return
        name = self.codes.get(frame.f_code)
        # Native governance observes the fixed interaction producer passively;
        # it must not import or invoke a protected interaction-layer surface.
        if frame.f_code.co_qualname == 'ReflectionConversationService.start':
            if Path(frame.f_code.co_filename).resolve() != self.root / 'app/chat/reflection_conversation.py':
                raise NativeWebRefusal('journaling_effect_order_or_origin_invalid')
            name = 'conversation'
        if name is None:
            return
        if event == 'call':
            if (len(self.order) >= len(self.ORDER) or name != self.ORDER[len(self.order)]
                or not Path(frame.f_code.co_filename).resolve().is_relative_to(self.root)):
                raise NativeWebRefusal('journaling_effect_order_or_origin_invalid')
            if name == 'actor' and frame.f_locals.get('path') != self.primary:
                raise NativeWebRefusal('synthetic_actor_target_mismatch')
            self.order.append(name)
        elif event == 'return':
            row: dict[str, Any] = {'effect': name}
            if name == 'conversation':
                session = value.session
                row.update(session_id=session.session_id, path=session.log_path.relative_to(VAULT).as_posix(),
                           sha256=file_hash(session.log_path))
            elif name == 'draft':
                from scripts.yaml_roundtrip import load_frontmatter
                path = VAULT / value.path
                frontmatter, _body = load_frontmatter(path.read_text())
                row.update(path=value.path, sha256=file_hash(path), is_addendum=value.is_addendum)
                row.update(candidate_uuid=frontmatter.get('uuid'), authority_state=frontmatter.get('authority_state'),
                           derived_by=frontmatter.get('derived_by'))
                if frontmatter.get('authority_state') != 'proposal' or frontmatter.get('derived_by') != 'conversation':
                    raise NativeWebRefusal('journaling_candidate_provenance_invalid')
                cognition = frontmatter.get('proposed_by', {}).get('cognition', {})
                if (not isinstance(cognition, dict) or cognition.get('degraded') is not False
                    or cognition.get('outcome') in {'provider_failure', 'missing_input', 'empty_output'}
                    or not isinstance(cognition.get('object_ids'), list) or not cognition['object_ids']):
                    raise NativeWebRefusal('actual_drafting_provider_unavailable')
                row['cognition'] = {'outcome': cognition.get('outcome'), 'degraded': cognition['degraded'],
                                    'source_count': len(cognition['object_ids'])}
                if value.is_addendum is False:
                    if self.primary is not None:
                        raise NativeWebRefusal('duplicate_primary_candidate')
                    self.primary = path
                elif self.primary == path or self.canonical is None or file_hash(self.canonical) != self.canonical_hash:
                    raise NativeWebRefusal('accepted_primary_changed_or_addendum_missing')
            elif name == 'actor':
                if self.primary is None:
                    raise NativeWebRefusal('synthetic_actor_target_mismatch')
                row.update(path=self.primary.relative_to(VAULT).as_posix(), sha256=file_hash(self.primary), actor_id=ACTOR)
            elif name == 'review':
                from app.journaling.review import JournalReviewState
                if value.errors or len(value.results) != 1:
                    raise NativeWebRefusal('guarded_materialization_incomplete')
                accepted = value.results[0]
                if (accepted.state is not JournalReviewState.FULLY_MATERIALIZED or accepted.action != 'accept'
                    or not accepted.canonical_path or not accepted.receipt_id):
                    raise NativeWebRefusal('guarded_materialization_incomplete')
                canonical = VAULT / accepted.canonical_path
                self.canonical, self.canonical_hash = canonical, file_hash(canonical)
                row.update(path=accepted.canonical_path, sha256=self.canonical_hash, receipt_id=accepted.receipt_id)
            self.observed.append(row)

    def require_complete(self, report: dict[str, Any]) -> dict[str, Any]:
        if self.provider_active or self.provider_started != len(self.provider_calls):
            raise NativeWebRefusal('actual_product_provider_calls_incomplete')
        if self.order != list(self.ORDER) or [row['effect'] for row in self.observed] != list(self.ORDER):
            raise NativeWebRefusal('journaling_observed_effects_incomplete')
        artifacts = report['artifacts']
        rows = self.observed
        if (rows[0]['session_id'] == rows[4]['session_id'] or rows[1]['path'] == rows[5]['path']
            or rows[0]['sha256'] == rows[4]['sha256']
            or rows[1]['sha256'] != artifacts['primary_candidate_sha256']
            or rows[3]['sha256'] != artifacts['canonical_before_sha256']
            or rows[3]['receipt_id'] != artifacts['acceptance_receipt_id']
            or rows[5]['sha256'] != artifacts['addendum_candidate_sha256']
            or self.canonical is None or file_hash(self.canonical) != artifacts['canonical_after_sha256']):
            raise NativeWebRefusal('journaling_observed_artifacts_mismatch')
        # Transcript hash in the wrapper includes owner turns after start returns;
        # bind it to the exact session path rather than a fabricated success count.
        for index, field in ((0, 'primary_transcript_sha256'), (4, 'second_transcript_sha256')):
            if file_hash(VAULT / rows[index]['path']) != artifacts[field]:
                raise NativeWebRefusal('journaling_transcript_drift')
        return {'order': list(self.order), 'observed': rows, 'effects': dict(EFFECTS),
                'provider_calls': self.provider_calls}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args(argv)
    result: dict[str, Any] = {'profile_version': PROFILE, 'result': 'refused', 'reason': 'unknown'}
    try:
        binding = json.loads(args.manifest.read_text())
        expected = identity(binding['source_sha'], binding['image_digest'], binding['channel'], binding['operation_id'])
        result.update(expected, resource_generation=binding['resource_generation'])
        if any(binding.get(key) != value for key, value in expected.items()):
            raise NativeWebRefusal('journaling_resource_identity_mismatch')
        pg_binding = {**binding, 'profile_version': pg_acceptance.PROFILE_VERSION,
                      'selection_hash': pg_acceptance.SELECTION_HASH}
        pg_acceptance.verify_resources(pg_binding)
        if WRAPPER.split('::')[0] not in binding['files']:
            raise NativeWebRefusal('journaling_wrapper_missing')
        subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], check=True, timeout=120,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        fixture = bootstrap(binding)
        # The runtime tmpfs is intentionally empty. Produce and ingest settings
        # canonically before any model consumer; ambient/mock routing is not used.
        from app.settings.compiler import RUNTIME, compile_all
        from app.settings.runtime import reload_settings_bundle
        compile_all(vault_root=VAULT, auto_heal=False)
        reload_settings_bundle(notify=False)
        configuration_hash = hash_json({path.relative_to(RUNTIME).as_posix(): file_hash(path)
                                        for path in sorted(RUNTIME.rglob('*')) if path.is_file()})
        fixture['configuration_hash'] = configuration_hash
        # Actual Product routing must be remote, never mock or another in-memory factory.
        from app.components.llm.fabric import get_chat_client
        from app.components.llm.router import LLMTaskIntent
        try:
            client = get_chat_client(LLMTaskIntent(task_kind='reflection'))
        except Exception:
            raise NativeWebRefusal('actual_product_provider_unavailable') from None
        route = client.model_access_route
        if route is None or route.execution_host_profile != 'profile.codex_remote_host':
            raise NativeWebRefusal('actual_product_provider_unavailable')
        os.environ['JOURNALING_ACCEPTANCE_MANIFEST'] = str(MANIFEST)
        plugin = RequiredJournalingResults()
        observer = EffectObserver()
        import pytest
        if sys.getprofile() is not None:
            raise NativeWebRefusal('foreign_journaling_observer')
        sys.setprofile(observer.profile)
        try:
            status = pytest.main(['-q', '--noconftest', WRAPPER, '--junitxml=' + str(EVIDENCE / 'junit.xml'),
                                  '-o', 'cache_dir=/tmp/journaling-pytest-cache'], plugins=[plugin])
        finally:
            sys.setprofile(None)
        plugin.require_complete(status)
        report = json.loads((EVIDENCE / (binding['resource_generation'] + '.json')).read_text())
        require_report(report, binding)
        effects = observer.require_complete(report)
        receipt_path = EVIDENCE / 'journal-review-outbox.jsonl'
        receipt_rows = [json.loads(line) for line in receipt_path.read_text().splitlines() if line.strip()]
        if (len(receipt_rows) != 1 or receipt_rows[0].get('event') != 'journal.entry.accepted'
            or receipt_rows[0].get('event_id') != report['artifacts']['acceptance_receipt_id']):
            raise NativeWebRefusal('guarded_journaling_receipt_incomplete')
        if any(file_hash(VAULT / path) != value for path, value in fixture['sources'].items()):
            raise NativeWebRefusal('journaling_source_drift')
        if configuration_hash != hash_json({path.relative_to(RUNTIME).as_posix(): file_hash(path)
                                            for path in sorted(RUNTIME.rglob('*')) if path.is_file()}):
            raise NativeWebRefusal('journaling_configuration_drift')
        pg_acceptance.verify_resources(pg_binding)
        result.update(result='passed', resource_tree=binding['resource_tree'], app_image_id=binding['app_image_id'],
                      wrapper=WRAPPER, report=report, report_hash=hash_json(report), fixture=fixture,
                      effect_observer=effects,
                      guarded_receipt={'event': 'journal.entry.accepted',
                                       'event_id': receipt_rows[0]['event_id'], 'sha256': file_hash(receipt_path)},
                      producer_pid=os.getpid(), producer_module=str(Path(__file__).resolve()),
                      configuration_hash=configuration_hash,
                      provider={'execution_host_profile': route.execution_host_profile,
                                'provider': route.provider, 'model': route.model})
    except NativeWebRefusal as exc:
        result.update(result='refused', reason=exc.reason)
    except Exception:
        result.update(result='refused', reason='journaling_initialization_or_execution_unavailable')
    print('YGGDRASIL_NATIVE_JOURNALING=' + json.dumps(result, sort_keys=True))
    return 0 if result['result'] == 'passed' else 78


if __name__ == '__main__':
    sys.exit(main())
