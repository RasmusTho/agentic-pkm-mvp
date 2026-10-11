"""Fixed disposable Product web qualification; never channel/PG acceptance.

This module runs inside the admitted image. Native ownership, Docker and source
objects stay in the trusted runner. Candidate callers cannot choose a command,
profile, persistent data source or ingress.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from uuid import UUID

from app.ops import pg_acceptance

WEB_PROFILE = 'native-web-pilots.v1'
WEB_DEADLINE = 1800
WRAPPERS = (
    'tests/companion_ui/test_companion_ui_live_deep_review.py::test_deep_review_live_acceptance',
    'tests/companion_ui/test_companion_ui_live_daily_briefing.py::test_daily_briefing_live_acceptance',
)
SCENARIOS = {
    'deep-review': ('native_admission', 'a1_overlay_selection_continuity', 'a1_runtime_resume_position',
                    'b4_all_overlay_focus_escape_return', 'populated_vault_list_and_inspector',
                    'populated_governed_apply_exact_receipt', 'populated_memory_accept',
                    'populated_memory_reject', 'populated_memory_revise', 'populated_memory_defer',
                    'populated_capture_confirmation_and_caret', 'public_copy_populated_and_entry',
                    'public_copy_degraded'),
    'daily-briefing': ('preflight', 'generation_and_provenance', 'daily_trigger_idempotence', 'one_read_only_card',
                       'mixed_audio_playback', 'partial_source', 'text_only_degradation', 'fixture_restored'),
}
EFFECT_LIMITS = {
    'deep-review': dict.fromkeys(('queue_review', 'panel_confirm', 'memory_accept', 'memory_reject',
                                  'memory_revise', 'memory_defer', 'capture'), 1),
    'daily-briefing': {'first_contact': 2, 'navigation': 4, 'tts_plan': 1, 'tts_synthesis': 1,
                       'degrade_source': 1, 'restore_source': 1},
}
CONTEXT_PATH = Path('/scratch/native-web-context.json')
REPORT_DIRECTORY = Path('/scratch/native-web-reports')
API_URL = 'http://127.0.0.1:8000'
UI_URL = 'http://127.0.0.1:8090'
CALDAV_URL = 'http://127.0.0.1:8870'
WEB_SELECTION_HASH = hashlib.sha256(json.dumps(
    [WEB_PROFILE, WRAPPERS, SCENARIOS, EFFECT_LIMITS, WEB_DEADLINE, API_URL, UI_URL, CALDAV_URL],
    separators=(',', ':'),
).encode()).hexdigest()


class NativeWebRefusal(RuntimeError):
    """Bounded cause only: transport exceptions and credentials never escape."""
    def __init__(self, reason: str) -> None:
        super().__init__('isolated web qualification refused: ' + reason)
        self.reason = reason


def web_identity(sha: str, digest: str, channel: str, operation_id: str) -> dict[str, str]:
    base = pg_acceptance.identity(sha, digest, channel, operation_id)
    return {**base, 'profile_version': WEB_PROFILE, 'selection_hash': WEB_SELECTION_HASH}


def hash_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def require_reports(reports: Any, binding: dict[str, Any] | None = None) -> None:
    if not isinstance(reports, dict) or set(reports) != set(SCENARIOS):
        raise NativeWebRefusal('pilot_reports_incomplete')
    for pilot, inventory in SCENARIOS.items():
        report = reports[pilot]
        scenarios = report.get('scenarios') if isinstance(report, dict) else None
        effects = report.get('effects' if pilot == 'deep-review' else 'effects_consumed') if isinstance(report, dict) else None
        if (not isinstance(scenarios, list) or len(scenarios) != len(inventory)
            or any(not isinstance(row, dict) or row.get('status') != 'passed' for row in scenarios)
            or [row.get('id') for row in scenarios] != list(inventory) or report.get('passed') is not True
            or not isinstance(effects, dict) or set(effects) != set(EFFECT_LIMITS[pilot])
            or any(type(count) is not int or count < 0 or count > EFFECT_LIMITS[pilot][key]
                   for key, count in effects.items())):
            raise NativeWebRefusal('pilot_outcomes_incomplete')
    if binding is None:
        raise NativeWebRefusal('original_report_context_missing')
    from app.ops.native_web_reports import require_original_reports
    require_original_reports(reports, binding)


def require_wrappers(manifest: dict[str, Any], *, root: Path = Path('/app')) -> None:
    for selector in WRAPPERS:
        name, function = selector.split('::')
        if name not in manifest['files'] or not (root / name).is_file():
            raise NativeWebRefusal('required_wrapper_missing')
        # Collection later proves this function actually executes. A filename
        # in a source manifest alone cannot qualify a scenario.
        if not function:
            raise NativeWebRefusal('required_wrapper_missing')


def verify_resources(manifest: dict[str, Any], *, root: Path = Path('/app')) -> None:
    expected = web_identity(manifest['source_sha'], manifest['image_digest'],
                            manifest['channel'], manifest['operation_id'])
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise NativeWebRefusal('resource_identity_mismatch')
    # Reuse exact-SHA blob verification and baked-import origin checks. The
    # manifest contains every web asset as well as PG's existing resources.
    pg_acceptance.verify_resources({**manifest, 'profile_version': pg_acceptance.PROFILE_VERSION,
                                    'selection_hash': pg_acceptance.SELECTION_HASH}, root=root)
    require_wrappers(manifest, root=root)


class RequiredWebResults:
    def __init__(self, wrapper: str | None = None) -> None:
        if wrapper is not None and wrapper not in WRAPPERS:
            raise NativeWebRefusal('unknown_pilot_wrapper')
        self.required = {wrapper} if wrapper is not None else set(WRAPPERS)
        self.passed: set[str] = set()
        self.bad = False

    def pytest_collection_finish(self, session: Any) -> None:
        import pytest
        nodes = [item.nodeid for item in session.items]
        if set(nodes) != self.required or len(nodes) != len(self.required):
            raise pytest.UsageError('fixed web wrapper inventory is incomplete')

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.skipped or report.failed or hasattr(report, 'wasxfail'):
            self.bad = True
        if report.when == 'call' and report.passed:
            if report.nodeid in self.passed:
                self.bad = True
            self.passed.add(report.nodeid)

    def require_complete(self, exit_status: int) -> None:
        if exit_status != 0 or self.bad or self.passed != self.required:
            raise NativeWebRefusal('wrapper_execution_incomplete')


def require_result(result: Any, expected: dict[str, str], manifest: dict[str, Any]) -> None:
    if (not isinstance(result, dict) or any(result.get(k) != v for k, v in expected.items())
        or result.get('result') != 'passed' or result.get('cleanup') != 'confirmed'
        or result.get('resource_tree') != manifest['resource_tree']
        or result.get('app_image_id') != manifest['app_image_id']
        or str(UUID(str(result.get('resource_generation')))) != result.get('resource_generation')
        or result.get('resource_generation') != manifest['resource_generation']
        or not isinstance(result.get('start'), dict) or result.get('start') != result.get('end')
        or result.get('wrappers') != list(WRAPPERS)
        or re.fullmatch(r'[0-9a-f]{64}', str(result.get('report_hash'))) is None
        or result.get('report_hash') != hash_json(result.get('pilots'))):
        raise NativeWebRefusal('web_result_identity_mismatch')
    start = result['start']
    api = start.get('api')
    fixture = api.get('fixture') if isinstance(api, dict) else None
    if (not isinstance(api, dict) or not isinstance(fixture, dict)
        or any(api.get(key) != manifest[key] for key in (
            'source_sha', 'image_digest', 'app_image_id', 'resource_tree', 'resource_generation'))
        or api.get('api_module') != '/app/app/main.py'
        or type(api.get('api_pid')) is not int or api['api_pid'] <= 0
        or type(start.get('ui_pid')) is not int or start['ui_pid'] <= 0 or start['ui_pid'] == api['api_pid']
        or start.get('ui_program_sha256') != manifest['files'].get(
            'companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py')
        or re.fullmatch(r'[0-9a-f]{64}', str(start.get('configuration_hash'))) is None
        or api.get('browser_audio_assets_hash') != hash_json(manifest['prerequisites'])
        or fixture.get('resource_generation') != manifest['resource_generation']
        or re.fullmatch(r'[0-9a-f]{64}', str(fixture.get('note_sha256'))) is None
        or re.fullmatch(r'[0-9a-f]{64}', str(fixture.get('settings_hash'))) is None
        or not isinstance(fixture.get('candidate_ids'), list) or len(set(fixture['candidate_ids'])) != 4
        or not fixture.get('logical_vault_id') or not fixture.get('local_clone_id')
        or not fixture.get('note_uuid') or not fixture.get('note_path')):
        raise NativeWebRefusal('web_service_or_fixture_identity_unknown')
    from app.ops.native_web_reports import report_binding
    require_reports(result.get('pilots'), report_binding(manifest, start))
    # Bind the original pilot acknowledgement to the API observer's exact
    # guarded response and declared source transition, not just a report flag.
    acknowledgements = result.get('guarded_acknowledgements')
    versions = result.get('mutable_versions')
    sources = fixture.get('controlled_mutable_sources')
    if (not isinstance(acknowledgements, dict) or set(acknowledgements) != {'capture', 'panel_confirm'}
        or not isinstance(versions, dict) or not isinstance(sources, list) or len(sources) != 2
        or {source.get('effect') for source in sources} != {'capture', 'panel_confirm'}
        or set(versions) != {source.get('note_path') for source in sources}):
        raise NativeWebRefusal('original_guarded_acknowledgement_missing')
    original = result['pilots']['deep-review']['backend_acknowledgements']
    for source in sources:
        effect, path = source['effect'], source['note_path']
        ack = acknowledgements.get(effect)
        if (not isinstance(ack, dict) or ack.get('target') != path or ack.get('source_uuid') != source['note_uuid']
            or ack.get('pre_sha256') != source['seed_sha256'] or ack.get('post_sha256') != versions.get(path)
            or re.fullmatch(r'[0-9a-f]{64}', str(ack.get('post_sha256'))) is None
            or ack.get('response_sha256') != hash_json(original[effect])):
            raise NativeWebRefusal('original_guarded_acknowledgement_mismatch')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args(argv)
    result: dict[str, Any] = {'profile_version': WEB_PROFILE, 'result': 'refused', 'reason': 'unknown'}
    try:
        manifest = json.loads(args.manifest.read_text())
        expected = web_identity(manifest['source_sha'], manifest['image_digest'],
                                manifest['channel'], manifest['operation_id'])
        result.update(expected, resource_generation=manifest['resource_generation'])
        verify_resources(manifest)
        from app.ops.native_web_runtime import qualify
        result = {**result, **qualify(manifest)}
        verify_resources(manifest)
        result.update(result='passed', resource_tree=manifest['resource_tree'],
                      app_image_id=manifest['app_image_id'])
        # Native cleanup is checked and attached by the trusted worker after
        # the candidate process has exited. It cannot self-certify host cleanup.
        print('YGGDRASIL_NATIVE_WEB=' + json.dumps(result, sort_keys=True))
        return 0
    except NativeWebRefusal as exc:
        result.update(result='refused', reason=exc.reason)
    except Exception:
        result.update(result='refused', reason='source_initialization_or_execution_unavailable')
    print('YGGDRASIL_NATIVE_WEB=' + json.dumps(result, sort_keys=True))
    return 78


if __name__ == '__main__':
    raise SystemExit(main())
