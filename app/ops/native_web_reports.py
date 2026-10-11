"""Admit the two original finite pilot reports and their actual artifacts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Any

from app.ops.native_web_acceptance import CONTEXT_PATH, REPORT_DIRECTORY, EFFECT_LIMITS, NativeWebRefusal, SCENARIOS, WRAPPERS, hash_json


def report_binding(manifest: dict[str, Any], start: dict[str, Any]) -> dict[str, Any]:
    fixture = start['api']['fixture']
    identity = {key: manifest[key] for key in ('source_sha', 'image_digest', 'channel', 'operation_id',
                                             'resource_generation', 'resource_tree', 'app_image_id')}
    harness = {name: manifest['files'].get('tests/companion_ui/' + name)
               for name in ('live_deep_review.py', 'live_core_flow.py')}
    if any(not isinstance(value, str) for value in harness.values()):
        raise NativeWebRefusal('original_report_producer_missing')
    binding = {'source_sha': manifest['source_sha'], 'image_digest': manifest['image_digest'], 'channel': manifest['channel'],
            'harness_hashes': harness, 'configuration_hashes': {'runtime': start['configuration_hash'], 'vault': fixture['settings_hash']},
            'run_id': manifest['resource_generation'], 'resource_version': manifest['resource_tree'],
            'native_boundary_ref': hash_json({'native_identity': identity, 'start': start}),
            'fixture_metadata_sha256': hash_json(fixture), 'local_instance_id': fixture['local_clone_id']}
    # Preserve the original producer's sorted-json serialization for the exact
    # fixed input manifest; the pilot adapter must hash this admitted input.
    binding['manifest_sha256'] = hashlib.sha256(json.dumps(pilot_manifest('deep-review', binding), sort_keys=True).encode()).hexdigest()
    return binding


def pilot_manifest(pilot: str, binding: dict[str, Any]) -> dict[str, Any]:
    return {'schema': 'native-web-pilot-manifest.v1', 'pilot': pilot, 'native_context': str(CONTEXT_PATH),
            'output_dir': str(REPORT_DIRECTORY / pilot),
            'report_binding': {key: value for key, value in binding.items() if key != 'manifest_sha256'}}


def _deep_proof(row: dict[str, Any], report: dict[str, Any]) -> bool:
    proof = row.get('proof')
    if not isinstance(proof, dict) or proof.get('source') != 'served_product':
        return False
    name = row['id']
    if name == 'native_admission':
        native = proof.get('native') or {}
        return (all(native.get(key) is True for key in ('gateway_upstream_verified', 'synthetic_fixture_verified',
                'native_lock_verified', 'first_contact_navigation_safe'))
                and native.get('image_digest') == report['expected_image_digest']
                and native.get('test_resource_version') == report['test_resource_version']
                and bool(native.get('configuration_hashes')) and proof.get('served_sha') == report['expected_sha'])
    if name == 'a1_overlay_selection_continuity':
        return proof.get('cycles') == 2 and bool(proof.get('selection'))
    if name == 'a1_runtime_resume_position':
        prior, restored, leave = (proof.get(key) or {} for key in ('prior_view', 'restored', 'runtime_leave_point'))
        return (leave.get('status') == 'present' and bool(restored)
                and leave.get('artifact_ref', {}).get('artifact_uuid') == prior.get('artifact_id')
                and leave.get('artifact_ref', {}).get('logical_ref') == prior.get('note_path')
                and all(restored.get(k) == prior.get(k) for k in ('start', 'end', 'editor_scroll', 'reading_scroll')))
    if name == 'b4_all_overlay_focus_escape_return':
        overlays = proof.get('overlays') or {}
        return set(overlays) == {'cmd', 'capture', 'receipts', 'settings', 'memory', 'map'} and all(
            value == {'focus_trap': True, 'escape': True, 'focus_return': True} for value in overlays.values())
    if name == 'populated_vault_list_and_inspector':
        return bool(proof.get('note_uuid')) and proof.get('list_count', 0) > 0 and proof.get('inspector') is True
    if name == 'populated_governed_apply_exact_receipt':
        ack = proof.get('confirmation') or {}
        return (ack.get('status') == 'executed' and ack.get('outcome') == 'success'
                and bool(ack.get('receipt', {}).get('receipt_id'))
                and proof.get('exact_persisted_readback') is True and proof.get('receipt_history') is True)
    if name.startswith('populated_memory_'):
        action = name.removeprefix('populated_memory_')
        expected = {'accept': 'accepted', 'reject': 'rejected', 'revise': 'revised', 'defer': 'deferred'}[action]
        return (proof.get('decision', {}).get('status') == expected
                and isinstance(proof.get('actual_pending_ids'), list) and bool(proof.get('server_authority')))
    if name == 'populated_capture_confirmation_and_caret':
        ack = proof.get('capture') or {}
        return (ack.get('outcome') == 'written' and bool(ack.get('trace_id'))
                and proof.get('source_readback') is True and proof.get('selection_restored') is True)
    if name == 'public_copy_populated_and_entry':
        return set(proof.get('surfaces', [])) == {'shell', 'entry', 'cmd', 'memory', 'receipts', 'settings', 'map'} and proof.get('public_copy_clean') is True
    return (name == 'public_copy_degraded' and row.get('kind') == 'browser_fault_injection'
            and proof.get('kind') == 'browser_fault_injection' and proof.get('calm_unavailable') is True)


def require_original_reports(reports: dict[str, Any], binding: dict[str, Any]) -> None:
    for pilot, report in reports.items():
        if (report.get('channel') != binding['channel'] or report.get('channel') != 'test'
            or report.get('expected_sha') != binding['source_sha']
            or report.get('run_id') != binding['run_id']):
            raise NativeWebRefusal('original_report_run_identity_mismatch')
        if pilot == 'deep-review':
            if (report.get('schema') != 'companion_ui_deep_review_execution.v1'
                or report.get('execution_kind') != 'live' or report.get('identity_verified') is not True
                or report.get('expected_image_digest') != binding['image_digest']
                or report.get('test_resource_version') != binding['resource_version']
                or report.get('qualification_ref') != binding['native_boundary_ref']
                or report.get('fixture_metadata_sha256') != binding['fixture_metadata_sha256']
                or report.get('local_instance_id') != binding['local_instance_id']
                or report.get('harness_hashes') != binding['harness_hashes']
                or report.get('manifest_sha256') != binding['manifest_sha256']
                or report.get('required_scenarios') != list(SCENARIOS[pilot])
                or report.get('refused_requests') != [] or report.get('effect_budget') != EFFECT_LIMITS[pilot]
                or report.get('artifacts', {}).get('trace') != 'trace.zip'
                or report.get('artifacts', {}).get('junit') != 'junit.xml'
                or any(report['effects'][key] != 1 for key in EFFECT_LIMITS[pilot])
                or not all(_deep_proof(row, report) for row in report['scenarios'])):
                raise NativeWebRefusal('original_deep_report_proof_incomplete')
            acknowledgements = report.get('backend_acknowledgements') or {}
            by_id = {row['id']: row['proof'] for row in report['scenarios']}
            if (acknowledgements.get('panel_confirm') != by_id['populated_governed_apply_exact_receipt']['confirmation']
                or acknowledgements.get('capture') != by_id['populated_capture_confirmation_and_caret']['capture']
                or report.get('actual_proof', {}).get('native') != by_id['native_admission']['native']
                or by_id['native_admission']['native'].get('configuration_hashes') != binding['configuration_hashes']):
                raise NativeWebRefusal('original_deep_acknowledgement_mismatch')
        else:
            audio = report.get('diagnostics', {}).get('audio') or {}
            segments = audio.get('segments') or []
            if (report.get('schema') != 'daily_briefing_live_acceptance.v1'
                or report.get('execution_kind') != 'actual_native_browser'
                or report.get('expected_digest') != binding['image_digest']
                or report.get('resource_version') != binding['resource_version']
                or report.get('native_boundary_ref') != binding['native_boundary_ref']
                or report.get('fixture_restored') is not True or report.get('trace') != 'trace.zip'
                or report.get('junit') != 'junit.xml'
                or any(row.get('kind') != ('browser_local_failure' if row['id'] == 'text_only_degradation' else 'actual')
                       for row in report['scenarios'])
                or any(report['effects_consumed'][key] != EFFECT_LIMITS[pilot][key] for key in EFFECT_LIMITS[pilot])
                or audio.get('playback_observed') is not True or type(audio.get('frames')) is not int or audio['frames'] <= 0
                or type(audio.get('sample_rate')) is not int or audio['sample_rate'] <= 0
                or any(re.fullmatch(r'[0-9a-f]{64}', str(audio.get(k))) is None for k in ('audio_sha256', 'source_text_sha256', 'cache_key'))
                or not segments or {(x.get('language'), x.get('provider'), x.get('voice_id')) for x in segments} != {
                    ('sv-SE', 'piper', 'sv_SE-lisa-medium'), ('en-US', 'kokoro', 'bf_isabella')}):
                raise NativeWebRefusal('original_daily_report_proof_incomplete')


def require_artifacts(pilot: str, directory: Path) -> None:
    try:
        xml = (directory / 'junit.xml').read_bytes()
        if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:
            raise ValueError()
        root = ET.fromstring(xml)
        cases = list(root.iter('testcase'))
        names = [case.get('name') for case in cases]
        wrapper = WRAPPERS[0 if pilot == 'deep-review' else 1]
        test_file, function = wrapper.split('::')
        exact_wrapper = (len(cases) == 1 and names == [function]
                         and cases[0].get('classname') == test_file.removesuffix('.py').replace('/', '.'))
        if (root.tag not in {'testsuite', 'testsuites'}
            or names != list(SCENARIOS[pilot]) and not exact_wrapper
            or any(list(case) for case in cases)):
            raise ValueError()
        with zipfile.ZipFile(directory / 'trace.zip') as archive:
            members = archive.infolist()
            if (len(members) > 4096 or sum(member.file_size for member in members) > 128 * 1024 * 1024
                or any(Path(m.filename).is_absolute() or '..' in Path(m.filename).parts for m in members)
                or archive.testzip() is not None):
                raise ValueError()
            events = [json.loads(line) for name in archive.namelist() if name.endswith('.trace')
                      for line in archive.read(name).splitlines() if line]
            before = {event.get('callId') for event in events if event.get('type') == 'before'}
            after = {event.get('callId') for event in events if event.get('type') == 'after' and not event.get('error')}
            if (not any(event.get('type') == 'context-options' for event in events)
                or len(before & after) < len(SCENARIOS[pilot]) or None in before
                or not any(event.get('type') == 'before' and event.get('params', {}).get('url', '').rstrip('/')
                           == 'http://127.0.0.1:8090' for event in events)):
                raise ValueError()
    except Exception:
        raise NativeWebRefusal('original_pilot_artifact_unusable') from None
