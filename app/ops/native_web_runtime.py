"""Image-owned API/UI startup and fixed pilot consumer, without host access."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import sysconfig
from threading import Thread
import time
from typing import Any, Iterator
from urllib.parse import urlencode
from urllib.request import urlopen
from xml.sax.saxutils import escape

from app.ops.native_web_acceptance import (
    API_URL, CALDAV_URL, CONTEXT_PATH, EFFECT_LIMITS, NativeWebRefusal, REPORT_DIRECTORY,
    RequiredWebResults, UI_URL, WRAPPERS, hash_json, require_reports, verify_resources,
)
from app.ops.native_web_fixture import SCOPE_ID, bootstrap_fixture, fixture_readback, prepare_daily_sources
from app.ops.native_web_reports import pilot_manifest, report_binding


class AcknowledgedFixtureState:
    """Read-only observer of actual guarded Product acknowledgements.

    A requested effect never licenses drift. Only the successful normal
    response, its original receipt, exact target and measured post-write bytes
    can advance the permitted version of a declared mutable synthetic note.
    """
    def __init__(self, vault: Path, fixture: dict[str, Any], effects: dict[str, dict[str, int]]) -> None:
        self.vault, self.fixture, self.effects = vault, fixture, effects
        self.versions = {source['note_path']: source['seed_sha256'] for source in fixture['controlled_mutable_sources']}
        self.acknowledgements: dict[str, Any] = {}
        self.grants: dict[str, str] = {}
        self.requests: dict[str, dict[str, Any]] = {}

    def require_current(self, mutable: dict[str, str]) -> None:
        if mutable != self.versions:
            raise NativeWebRefusal('unacknowledged_fixture_state_change')

    def grant(self, effect: str) -> None:
        targets = {'panel_confirm': self.fixture['review_note_path'], 'capture': self.fixture['capture_note_path']}
        if effect not in targets:
            return
        if effect in self.grants or effect in self.acknowledgements:
            raise NativeWebRefusal('duplicate_mutable_effect_grant')
        path = targets[effect]
        current = hashlib.sha256((self.vault / path).read_bytes()).hexdigest()
        if current != self.versions[path]:
            raise NativeWebRefusal('hook_fixture_prestate_drift')
        self.grants[effect] = current

    def begin_request(self, route: str, payload: dict[str, Any]) -> dict[str, Any]:
        effect = 'capture' if route == '/api/companion/capture' else 'panel_confirm'
        path = self.fixture['capture_note_path' if effect == 'capture' else 'review_note_path']
        if (effect not in self.grants or effect in self.requests or effect in self.acknowledgements
            or self.effects['deep-review'][effect] != 1):
            raise NativeWebRefusal('normal_request_without_single_grant')
        raw = (self.vault / path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.grants[effect] or self.versions[path] != self.grants[effect]:
            raise NativeWebRefusal('normal_request_prestate_drift')
        target = None
        if effect == 'capture':
            if set(payload) != {'text'} or not isinstance(payload['text'], str) or not payload['text'].strip():
                raise NativeWebRefusal('normal_capture_request_unknown')
        else:
            if (set(payload) != {'proposal_id', 'artifact_id', 'action', 'idempotency_key'}
                or payload['action'] != 'confirm' or payload['artifact_id'] != self.fixture['review_note_uuid']
                or not isinstance(payload['idempotency_key'], str) or not payload['idempotency_key']):
                raise NativeWebRefusal('normal_panel_request_target_mismatch')
            target = self.panel_target(payload)
            if (target is None or target['note_uuid'] != self.fixture['review_note_uuid']
                or target['note_path'] != path):
                raise NativeWebRefusal('normal_panel_request_target_mismatch')
        admitted = {'effect': effect, 'route': route, 'payload': dict(payload), 'target': target,
                    'path': path, 'pre_bytes': raw, 'pre_sha256': self.grants[effect], 'started': datetime.now(UTC)}
        self.requests[effect] = admitted
        return admitted

    def _expected_panel(self, admitted: dict[str, Any], timestamp: str) -> set[str]:
        from app.agents.panel.writeback import annotate_action_ids, remove_actions_from_markdown, stable_action_id, write_receipts
        from app.agents.panel.parser import parse_panel
        updated = remove_actions_from_markdown(annotate_action_ids(admitted['pre_bytes'].decode()),
                                                {stable_action_id('Queue for review')})
        parsed = parse_panel(updated)
        preferred = parsed.spans[-1][1] + 1 if parsed.spans else None
        end = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).astimezone(UTC)
        current = admitted['started'].replace(second=0, microsecond=0)
        if end < admitted['started'] or end - admitted['started'] > timedelta(minutes=10):
            raise NativeWebRefusal('normal_acknowledgement_time_unknown')
        expected = set()
        while current <= end:
            text = write_receipts(updated, ['✅ Queue for review (' + current.strftime('%Y-%m-%d %H:%M') + ')'],
                                  preferred_index=preferred)
            expected.add(hashlib.sha256(text.encode()).hexdigest())
            current += timedelta(minutes=1)
        return expected

    def observe(self, route: str, response: dict[str, Any], admitted: dict[str, Any] | None = None) -> None:
        if (admitted is None or self.requests.get(admitted['effect']) is not admitted
            or admitted['route'] != route or admitted['effect'] in self.acknowledgements):
            raise NativeWebRefusal('normal_acknowledgement_without_prestate')
        if route == '/api/panel/confirm':
            from app.panel import confirmation
            receipt = response.get('receipt', {})
            if (response.get('status') not in {'executed', 'logged'} or not receipt.get('receipt_id')
                or receipt.get('action_taken') != 'confirm' or receipt.get('outcome') not in {'success', 'logged'}):
                return
            panel_target = admitted['target']
            if panel_target is None or panel_target['proposal_id'] != response.get('proposal_id'):
                raise NativeWebRefusal('normal_panel_receipt_target_unknown')
            if panel_target['note_uuid'] != self.fixture['review_note_uuid'] or panel_target['note_path'] != self.fixture['review_note_path']:
                raise NativeWebRefusal('normal_panel_receipt_target_mismatch')
            cached = confirmation._idempotency_store.get(response.get('idempotency_key', ''))
            if cached is None or cached.model_dump(mode='json') != response:
                raise NativeWebRefusal('normal_panel_acknowledgement_unknown')
            effect = 'panel_confirm'
            note_path = self.fixture['review_note_path']
            expected = self._expected_panel(admitted, receipt['timestamp'])
        elif route == '/api/companion/capture':
            receipt = response.get('governed_write', {}).get('authority_receipt', {})
            if (response.get('outcome') != 'written' or response.get('operation') != 'append_note'
                or response.get('adapter') != 'fs_vault' or not receipt.get('receipt_id')
                or response.get('note_path') != self.fixture['capture_note_path']
                or receipt.get('resource') != self.fixture['capture_note_path']
                or receipt.get('outcome') != 'applied' or receipt.get('operation') != 'append_note'):
                raise NativeWebRefusal('normal_capture_receipt_target_mismatch')
            effect = 'capture'
            note_path = self.fixture['capture_note_path']
            from app.api.routes.capture import _compose_entry
            text = admitted['payload']['text'].strip('\n').strip()
            prefix = admitted['pre_bytes']
            append = (b'\n' if prefix and not prefix.endswith(b'\n') else b'')
            append += _compose_entry(text, response['captured_at']).encode()
            expected = {hashlib.sha256(prefix + append).hexdigest()}
        else:
            return
        if self.effects['deep-review'][effect] != 1 or effect in self.acknowledgements:
            raise NativeWebRefusal('normal_acknowledgement_without_budget')
        path = self.vault / note_path
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest not in expected:
            raise NativeWebRefusal('normal_acknowledgement_poststate_drift')
        self.versions[note_path] = digest
        self.acknowledgements[effect] = {'target': note_path, 'source_uuid': self.fixture[
            'review_note_uuid' if effect == 'panel_confirm' else 'capture_note_uuid'],
            'receipt': receipt, 'response_sha256': hash_json(response), 'pre_sha256': admitted['pre_sha256'],
            'request_sha256': hash_json(admitted['payload']), 'post_sha256': digest}

    def panel_target(self, request: dict[str, Any]) -> dict[str, str] | None:
        from app.panel import confirmation
        proposal = confirmation._proposal_store.get(request.get('proposal_id', ''))
        if proposal is None:
            return None
        note = proposal.intent_event.payload.note
        actions = proposal.intent_event.payload.actions
        if (len(actions) != 1 or not actions[0].checked or actions[0].label != 'Queue for review'
            or actions[0].mapping is None or actions[0].mapping.id != 'queue_review'):
            raise NativeWebRefusal('normal_panel_action_outside_fixed_fixture')
        if not isinstance(note.path, str) or not isinstance(note.uuid, str):
            raise NativeWebRefusal('normal_panel_receipt_target_unknown')
        path = Path(note.path)
        if path.is_absolute():
            path = path.relative_to(self.vault)
        return {'proposal_id': request['proposal_id'], 'note_uuid': note.uuid, 'note_path': path.as_posix()}


class DailySourceFault:
    """Two fixed, guarded synthetic-fixture writes; no arbitrary target/input."""
    def __init__(self, vault: Path, daily: dict[str, Any], effects: dict[str, dict[str, int]],
                 deep: AcknowledgedFixtureState | None = None) -> None:
        self.vault, self.daily, self.effects = vault, daily, effects
        self.acknowledgements: dict[str, Any] = {}
        self.versions = dict(daily['source_files'])
        self.deep = deep
        self.deep_paths = set(deep.versions) if deep is not None else set()
        if deep is not None and any(name not in self.versions or self.versions[name] != deep.versions[name] for name in self.deep_paths):
            raise NativeWebRefusal('source_version_ownership_mismatch')
        path = Path(daily['moment_path'])
        if (path.is_absolute() or '..' in path.parts or path.as_posix() not in self.versions
            or path.as_posix() in self.deep_paths):
            raise NativeWebRefusal('daily_fixture_source_target_unknown')
        self.path = path.as_posix()

    def require_current(self) -> None:
        for name, expected in self.expected_versions().items():
            path = self.vault / name
            if (Path(name).is_absolute() or '..' in Path(name).parts or path.is_symlink()
                or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
                raise NativeWebRefusal('daily_fixture_source_drift')

    def expected_versions(self) -> dict[str, str]:
        return {**self.versions, **(self.deep.versions if self.deep is not None else {})}

    def require_restored(self) -> None:
        self.require_current()
        if any(self.versions[name] != expected for name, expected in self.daily['source_files'].items()
               if name not in self.deep_paths):
            raise NativeWebRefusal('daily_fixture_restore_incomplete')

    def write(self, restore: bool) -> dict[str, Any]:
        from dataclasses import asdict
        from app.knowledge.write_ops import write_note_relative
        effect = 'restore_source' if restore else 'degrade_source'
        if self.effects['daily-briefing'][effect] != 1 or effect in self.acknowledgements:
            raise NativeWebRefusal('daily_source_fault_without_budget')
        if restore and 'degrade_source' not in self.acknowledgements:
            raise NativeWebRefusal('daily_source_restore_without_owned_fault')
        self.require_current()
        content = self.daily['moment_full_text'] if restore else '---\ninvalid: [\n---\nSynthetic unavailable source.\n'
        receipt = write_note_relative(self.path, content, vault_root=self.vault,
                                      expected_version=self.versions[self.path], writer_identity='synthetic.native-web')
        if receipt.outcome != 'written' or receipt.locator.path != self.path:
            raise NativeWebRefusal('daily_source_fault_not_acknowledged')
        digest = hashlib.sha256((self.vault / self.path).read_bytes()).hexdigest()
        self.versions[self.path] = digest
        self.acknowledgements[effect] = {'target': self.path, 'receipt': asdict(receipt), 'post_sha256': digest}
        return self.acknowledgements[effect]


def _asset_readback(manifest: dict[str, Any]) -> dict[str, str]:
    prerequisites = manifest.get('prerequisites')
    if (not isinstance(prerequisites, dict) or prerequisites.get('playwright') != '1.63.0'
        or prerequisites.get('chromium_revision') != '1243' or not prerequisites.get('files')):
        raise NativeWebRefusal('browser_audio_prerequisites_unqualified')
    if prerequisites['native_runtime'].get('python_abi') != sysconfig.get_config_var('SOABI'):
        raise NativeWebRefusal('candidate_browser_abi_mismatch')
    for name, expected in prerequisites['files'].items():
        path = Path('/web-assets') / name
        if Path(name).is_absolute() or '..' in Path(name).parts or path.is_symlink() or not path.is_file():
            raise NativeWebRefusal('browser_audio_prerequisite_unknown')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise NativeWebRefusal('browser_audio_prerequisite_drift')
    return {'browser_audio_assets_hash': hash_json(prerequisites)}


def _private_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, sort_keys=True)


def _get_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=5) as response:
        value = json.loads(response.read(1024 * 1024))
    if not isinstance(value, dict):
        raise NativeWebRefusal('service_readback_unknown')
    return value


def before_effect(pilot: str, effect: str) -> None:
    """Pilot hook: a real API-process readback before each finite browser effect."""
    if pilot not in EFFECT_LIMITS or effect not in EFFECT_LIMITS[pilot]:
        raise NativeWebRefusal('unknown_browser_effect')
    context = json.loads(CONTEXT_PATH.read_text())
    observed = _get_json(API_URL + '/__native_web_identity?' + urlencode({'pilot': pilot, 'effect': effect}))
    if observed['identity'] != context['start']['api']:
        raise NativeWebRefusal('before_effect_identity_drift')


def _api_app(manifest: dict[str, Any]) -> Any:
    # Source initialization and queue production occur here, in the process
    # which will actually serve app.main:app, before its normal lifespan.
    verify_resources(manifest)
    _asset_readback(manifest)
    vault = Path('/scratch/vault')
    fixture = bootstrap_fixture(vault, manifest['resource_generation'])
    fixture['daily'] = prepare_daily_sources(fixture, manifest['resource_tree'])
    from app.main import app
    baseline = fixture_readback(vault, fixture)
    baseline.pop('mutable_readback')
    effects = {pilot: dict.fromkeys(limits, 0) for pilot, limits in EFFECT_LIMITS.items()}
    acknowledged = AcknowledgedFixtureState(vault, fixture, effects)
    daily_fault = DailySourceFault(vault, fixture['daily'], effects, acknowledged)

    @app.middleware('http')
    async def observe_guarded_acknowledgement(request: Any, call_next: Any) -> Any:
        admitted = None
        if request.method == 'POST' and request.url.path in {'/api/panel/confirm', '/api/companion/capture'}:
            admitted = acknowledged.begin_request(request.url.path, await request.json())
        response = await call_next(request)
        if request.method != 'POST' or request.url.path not in {'/api/panel/confirm', '/api/companion/capture'} or response.status_code != 200:
            return response
        from starlette.responses import Response
        chunks = [chunk async for chunk in response.body_iterator]
        raw = b''.join(chunks)
        if len(raw) > 1024 * 1024:
            raise NativeWebRefusal('normal_acknowledgement_over_budget')
        acknowledged.observe(request.url.path, json.loads(raw), admitted)
        # Forward the exact Product bytes/status/headers/background unchanged;
        # this observer neither creates a receipt nor fabricates an ack.
        return Response(raw, status_code=response.status_code, headers=dict(response.headers), background=response.background)

    def readback() -> dict[str, Any]:
        from app.tts.config import load_tts_config
        from app.tts.providers import resolve_voice
        tts = load_tts_config()
        voices = [resolve_voice(tts, language) for language in ('sv-SE', 'en-US')]
        if (not tts.enabled or not tts.local_only or tts.allow_browser_fallback or tts.allow_cloud_fallback
            or any(not voice.available for voice in voices)
            or [(voice.provider, voice.voice_id) for voice in voices] != [('piper', 'sv_SE-lisa-medium'), ('kokoro', 'bf_isabella')]):
            raise NativeWebRefusal('selected_real_local_tts_unavailable')
        verify_resources(manifest)
        current = fixture_readback(vault, fixture)
        mutable = current.pop('mutable_readback')
        acknowledged.require_current(mutable)
        daily_fault.require_current()
        module_path = sys.modules['app.main'].__file__
        if not isinstance(module_path, str):
            raise NativeWebRefusal('actual_api_module_unknown')
        return {
            'source_sha': manifest['source_sha'], 'image_digest': manifest['image_digest'],
            'app_image_id': manifest['app_image_id'], 'resource_tree': manifest['resource_tree'],
            'resource_generation': manifest['resource_generation'], 'api_pid': os.getpid(),
            'api_module': str(Path(module_path).resolve()),
            'fixture': current, **_asset_readback(manifest),
            'selected_tts': [(voice.provider, voice.language, voice.voice_id) for voice in voices],
        }

    @app.get('/__native_web_identity', include_in_schema=False)
    def native_identity(pilot: str | None = None, effect: str | None = None) -> dict[str, Any]:
        from fastapi import HTTPException
        observed = readback()
        if observed['fixture'] != baseline:
            raise HTTPException(409, 'synthetic fixture identity drift')
        if pilot is not None or effect is not None:
            if pilot not in effects or effect not in effects[pilot]:
                raise HTTPException(409, 'unknown fixed effect')
            if effects[pilot][effect] >= EFFECT_LIMITS[pilot][effect]:
                raise HTTPException(409, 'fixed browser effect budget exhausted')
            effects[pilot][effect] += 1
            if pilot == 'deep-review':
                acknowledged.grant(effect)
        return {'identity': observed, 'effects': effects, 'acknowledgements': acknowledged.acknowledgements,
                'mutable_versions': acknowledged.versions, 'daily_source_versions': daily_fault.expected_versions(),
                'daily_source_acknowledgements': daily_fault.acknowledgements}

    @app.post('/__native_web_fixture/degrade-source', include_in_schema=False)
    def degrade_source() -> dict[str, Any]:
        return daily_fault.write(False)

    @app.post('/__native_web_fixture/restore-source', include_in_schema=False)
    def restore_source() -> dict[str, Any]:
        return daily_fault.write(True)

    return app


@contextmanager
def _caldav() -> Iterator[dict[str, Any]]:
    now = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    ics = ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:native-web-calendar\r\n'
           'DTSTART:' + now.strftime('%Y%m%dT%H%M%SZ') + '\r\nDTEND:' + (now + timedelta(hours=1)).strftime('%Y%m%dT%H%M%SZ') +
           '\r\nSUMMARY:Synthetic native calendar\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n')
    identity: dict[str, Any] = {'calendar_uid': 'native-web-calendar', 'calendar_etag': 'native-web-etag',
                'calendar_ics': ics, 'calendar_ics_hash': hashlib.sha256(ics.encode()).hexdigest(), 'report_count': 0}
    class Handler(BaseHTTPRequestHandler):
        def do_REPORT(self) -> None:
            if self.path != '/calendar/' or int(self.headers.get('Content-Length', '0')) > 16384:
                self.send_error(404)
                return
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            if b'calendar-query' not in body:
                self.send_error(400)
                return
            identity['report_count'] += 1
            if Path('/scratch/calendar-unavailable').exists():
                self.send_error(503)
                return
            content = ('<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:response>'
                       '<D:href>/calendar/native-web.ics</D:href><D:propstat><D:prop><D:getetag>' +
                       escape(identity['calendar_etag']) + '</D:getetag>'
                       '<C:calendar-data>' + escape(identity['calendar_ics']) + '</C:calendar-data></D:prop>'
                       '<D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response></D:multistatus>').encode()
            self.send_response(207)
            self.send_header('Content-Type', 'application/xml')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, _format: str, *args: Any) -> None:
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 8870), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield identity
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        if thread.is_alive():
            raise NativeWebRefusal('private_calendar_cleanup_unknown')


@contextmanager
def _service(command: list[str], environment: dict[str, str]) -> Iterator[subprocess.Popen[bytes]]:
    process = subprocess.Popen(command, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        yield process
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _wait_service(url: str, process: subprocess.Popen[bytes]) -> None:
    for _ in range(60):
        if process.poll() is not None:
            raise NativeWebRefusal('actual_product_service_unavailable')
        try:
            with urlopen(url, timeout=1):
                return
        except Exception:
            time.sleep(1)
    raise NativeWebRefusal('actual_product_service_unavailable')


def _observations(manifest: dict[str, Any], api: subprocess.Popen[bytes], ui: subprocess.Popen[bytes]) -> dict[str, Any]:
    if api.poll() is not None or ui.poll() is not None:
        raise NativeWebRefusal('actual_product_service_stopped')
    identity = _get_json(API_URL + '/__native_web_identity')['identity']
    if identity['api_pid'] != api.pid:
        raise NativeWebRefusal('actual_api_process_mismatch')
    version = _get_json(API_URL + '/version')
    if version.get('git_sha') != manifest['source_sha']:
        raise NativeWebRefusal('actual_server_version_mismatch')
    with urlopen(UI_URL, timeout=5) as response:
        html = response.read(8 * 1024 * 1024).decode()
    scripts = re.findall(r'<script\b[^>]*>(.*?)</script>', html, re.DOTALL)
    if not scripts:
        raise NativeWebRefusal('actual_ui_assets_unavailable')
    # The served executable scripts, not substituted cards, bind the UI asset
    # identity; fixture state is read independently from the real API process.
    program = 'companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py'
    if program not in manifest['files']:
        raise NativeWebRefusal('actual_ui_program_identity_unknown')
    return {'api': identity, 'ui_pid': ui.pid, 'ui_program_sha256': manifest['files'][program],
            'configuration_hash': hash_json({key: os.environ.get(key) for key in (
                'STORE_BACKEND', 'PKM_ENVIRONMENT', 'TTS_MODEL_DIR', 'TTS_LOCAL_ONLY',
                'TTS_ALLOW_BROWSER_FALLBACK', 'TTS_ALLOW_CLOUD_FALLBACK', 'CALDAV_URL', 'CALDAV_SCOPE',
            )})}


def qualify(manifest: dict[str, Any]) -> dict[str, Any]:
    import pytest
    _asset_readback(manifest)
    environment = dict(os.environ)  # Native runner already supplied env -i.
    environment.update(CALDAV_URL=CALDAV_URL, CALDAV_USERNAME='synthetic', CALDAV_APP_PASSWORD='synthetic',
                       CALDAV_CALENDAR_PATH='/calendar/', CALDAV_SCOPE=SCOPE_ID)
    # Actual migrations prepare only the disposable database, just as the
    # existing native PG service preconditions do. No fake store/schema state.
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env=environment,
                   check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with _caldav() as calendar, _service([
        sys.executable, '-m', 'app.ops.native_web_runtime', '--api-process', '--manifest', '/native-web-manifest.json',
    ], environment) as api, _service([
        sys.executable, '-m', 'companion_ui.workspace.serve_dev_page',
    ], {**environment, 'HOST': '127.0.0.1', 'PORT': '8090', 'COMPANION_API_BASE_URL': API_URL}) as ui:
        _wait_service(API_URL + '/__native_web_identity', api)
        _wait_service(UI_URL + '/healthz', ui)
        daily_sources = _get_json(API_URL + '/__native_web_identity')['identity']['fixture']['daily']
        calendar.update({key: daily_sources[key] for key in ('calendar_uid', 'calendar_etag', 'calendar_ics')})
        calendar['calendar_ics_hash'] = hashlib.sha256(calendar['calendar_ics'].encode()).hexdigest()
        from playwright.sync_api import sync_playwright
        # This is a real launch with actual OS libraries, not payload existence.
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                browser.close()
        except Exception:
            raise NativeWebRefusal('actual_browser_launch_unavailable') from None
        start = _observations(manifest, api, ui)
        binding = report_binding(manifest, start)
        context = {'schema': 'native-web-context.v1', 'report_binding': binding, 'native_identity': {
            key: manifest[key] for key in ('source_sha', 'image_digest', 'channel', 'operation_id',
                                          'resource_generation', 'resource_tree', 'app_image_id')},
            'api_url': API_URL, 'ui_url': UI_URL, 'caldav_url': CALDAV_URL,
            'fixture': start['api']['fixture'], 'calendar': calendar, 'start': start,
            'reports': {pilot: str(REPORT_DIRECTORY / pilot / 'report.json') for pilot in EFFECT_LIMITS},
            'calendar_unavailable_marker': '/scratch/calendar-unavailable'}
        _private_json(CONTEXT_PATH, context)
        for pilot, variable in (('deep-review', 'COMPANION_UI_DEEP_REVIEW_MANIFEST'),
                                ('daily-briefing', 'COMPANION_UI_DAILY_BRIEFING_MANIFEST')):
            path = Path('/scratch') / (pilot + '-manifest.json')
            _private_json(path, pilot_manifest(pilot, binding))
            os.environ[variable] = str(path)
        for pilot, wrapper in zip(EFFECT_LIMITS, WRAPPERS, strict=True):
            if pilot == 'daily-briefing':
                probe = _get_json(API_URL + '/__native_web_identity')
                # Original all-vault inventory at Daily's actual start: only
                # explicitly owned Deep targets advance to acknowledged bytes.
                daily_sources = {**daily_sources, 'source_files': probe['daily_source_versions']}
                context['daily_start_sources'] = daily_sources
                # Atomic replacement changes no authority-bearing input; the
                # normal API readback remains the source/version authority.
                temporary = CONTEXT_PATH.with_suffix('.next')
                _private_json(temporary, context)
                os.replace(temporary, CONTEXT_PATH)
            output = REPORT_DIRECTORY / pilot
            plugin = RequiredWebResults(wrapper)
            caller_junit = output / 'caller-junit.xml'
            status = int(pytest.main(['-vv', wrapper, '-p', 'timeout', '--timeout=600', '--timeout-method=thread',
                                     '--junitxml=' + str(caller_junit), '-o', 'cache_dir=/tmp/native-web-cache'], plugins=[plugin]))
            plugin.require_complete(status)
            if not (output / 'junit.xml').exists():
                os.rename(caller_junit, output / 'junit.xml')
        reports = {pilot: json.loads(Path(path).read_text()) for pilot, path in context['reports'].items()}
        require_reports(reports, binding)
        end = _observations(manifest, api, ui)
        if start != end or calendar['report_count'] == 0 or Path('/scratch/calendar-unavailable').exists():
            raise NativeWebRefusal('service_assets_or_fixture_drift')
        final_probe = _get_json(API_URL + '/__native_web_identity')
        observed_effects = final_probe['effects']
        if any(reports[pilot]['effects' if pilot == 'deep-review' else 'effects_consumed'] != observed_effects[pilot]
               for pilot in reports):
            raise NativeWebRefusal('before_effect_inventory_incomplete')
        final_source_versions = final_probe['daily_source_versions']
        if final_source_versions != daily_sources['source_files']:
            raise NativeWebRefusal('daily_fixture_restore_incomplete')
        return {'start': start, 'end': end, 'wrappers': list(WRAPPERS), 'pilots': reports,
                'report_hash': hash_json(reports), 'calendar_reports': calendar['report_count'],
                'guarded_acknowledgements': final_probe['acknowledgements'],
                'mutable_versions': final_probe['mutable_versions'],
                'daily_source_acknowledgements': final_probe['daily_source_acknowledgements']}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--api-process', action='store_true', required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args(argv)
    import uvicorn
    uvicorn.run(_api_app(json.loads(args.manifest.read_text())), host='127.0.0.1', port=8000, log_level='warning')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
