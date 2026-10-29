"""Real browser -> Companion gateway -> installed operations runtime proofs."""
from __future__ import annotations

from contextlib import contextmanager
from email.message import Message
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import json
import pytest

from companion_ui.workspace.operations_client import operations_route_allowed
from companion_ui.workspace.serve_dev_page import make_handler, render_index_html
from companion_ui.workspace.workspace_http_client import WorkspaceClientHTTPError
from tests._production_operation_harness import production_operation_host
from tests.companion_ui.browser_runtime_harness import companion_workspace_fields


class RuntimeClient:
    """Only the HTTP transport is substituted; the runtime/kernel/native owners are real."""
    def __init__(self, host, headers=None, calls=None):
        self.host = host
        self.headers = headers or {}
        self.calls = calls if calls is not None else []

    def with_context_headers(self, headers):
        return RuntimeClient(self.host, headers, self.calls)

    def _request(self, method, url, *, headers=None, **kwargs):
        self.calls.append((method, url, kwargs.get('json'), {**self.headers, **(headers or {})}))
        response = self.host.client.request(method, url, headers={**self.headers, **(headers or {})}, **kwargs)
        if response.status_code >= 400:
            raise WorkspaceClientHTTPError(response.status_code, response.text)
        return response.json()

    def get(self, url, *, params=None, headers=None):
        return self._request('GET', url, params=params, headers=headers)

    def post(self, url, *, json, headers=None, timeout=None):
        return self._request('POST', url, json=json, headers=headers)


@contextmanager
def gateway(host):
    client = RuntimeClient(host)
    fields = companion_workspace_fields(body='Original.') | {'artifact_id': host.artifact_id}
    html = render_index_html(api_base_url='http://127.0.0.1:18001', fields=fields).encode()
    handler = make_handler(client=client, api_base_url='http://127.0.0.1:18001', production_profile=True)

    class Handler(handler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if urlparse(self.path).path == '/':
                self._send_html(200, html.decode())
            else:
                super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', client
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


@contextmanager
def browser(host, *, viewport=None, javascript_enabled=True):
    if os.environ.get('COMPANION_UI_BROWSER_TESTS') != '1':
        pytest.skip('Set COMPANION_UI_BROWSER_TESTS=1 for real Chromium interaction proof')
    from playwright.sync_api import sync_playwright
    with gateway(host) as (url, client), sync_playwright() as pw:
        engine = pw.chromium.launch()
        context = engine.new_context(viewport=viewport or {'width': 1440, 'height': 1000}, java_script_enabled=javascript_enabled)
        context.add_cookies([{'name': 'companion_context_session', 'value': host.selection['context_selection_id'],
                             'url': url, 'httpOnly': True, 'sameSite': 'Strict'}])
        page = context.new_page()
        external = []
        errors = []
        page.on('request', lambda request: external.append(request.url) if not request.url.startswith(url) else None)
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            page.goto(url, wait_until='domcontentloaded')
            yield page, client, external, errors
        finally:
            context.close()
            engine.close()


def evidence(page, name, external, errors):
    destination = os.environ.get('OPERATIONS_EVIDENCE_DIR')
    if not destination:
        return
    folder=Path(destination)
    folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder/(name+'.png')))
    (folder/(name+'.json')).write_text(json.dumps({'external_requests':external,'page_errors':errors,
        'viewport':page.viewport_size,'aria':page.get_by_role('dialog',name='Operations',exact=True).aria_snapshot()},indent=2))


def open_workspace(page):
    page.get_by_test_id('operations-open').click()
    page.locator('#operations-kind option[value="artifact.update"]:enabled').wait_for(state='attached')
    page.locator('#operations-resources input[type=checkbox]:enabled').first.wait_for()


def choose(page, kind='artifact.update', text='Updated in Companion.\n'):
    page.locator('#operations-resources input[type=checkbox]:enabled').first.check()
    page.locator('#operations-kind').select_option(kind)
    page.locator('[data-argument]').first.fill(text)


def test_gateway_preserves_auth_context_refusals_and_finite_route_allowlist(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    with gateway(host) as (url, client), httpx.Client(base_url=url) as request:
        assert request.get('/api/operations/capabilities').status_code == 401
        request.cookies.set('companion_context_session', host.selection['context_selection_id'])
        discovered = request.get('/api/operations/capabilities')
        assert discovered.status_code == 200
        assert discovered.json()['context']['active_context_ref'] == host.selection['context']['context_id']
        assert client.calls[-1][3]['X-Forwarded-For'] == '127.0.0.1'
        command = host.command(request_id='gateway-owner')
        command.pop('expected_version')
        observed = request.post('/api/operations/preconditions', json=command)
        assert observed.status_code == 200, observed.text
        assert observed.json()['expected_version']
        assert host.note.read_text().endswith('Original.\n')
        command.update(expected_version=observed.json()['expected_version'], arguments=observed.json()['arguments'])
        result = request.post('/api/operations', json=command)
        assert result.status_code == 200, result.text
        assert result.json()['convergence']['source_effect'] == 'committed'
        assert request.get('/api/operations/receipts/gateway-owner').json() == result.json()
        assert host.note.read_text().endswith('Updated body.\n')
        for path in ['/api/operations/anything', '/api/operations/batches/a/recover',
                     '/api/operations/receipts/a/child', '/api/operations/batches/a/execute/child']:
            assert request.get(path).status_code == 404
            assert request.post(path, json={}).status_code == 404
        host.clear_selection()
        refused = request.post('/api/operations', json=command)
        assert refused.status_code == 401
        assert refused.json() == {'detail': 'reselection_required'}

    handler = make_handler(client=RuntimeClient(host), api_base_url="http://127.0.0.1:18001")
    instance = handler.__new__(handler)
    instance.client_address = ('203.0.113.7', 4000)
    instance.headers = Message()
    instance.headers['X-API-Key'] = 'test-api-key'
    for path in ['/api/operations', '/api/operations/receipts/single-1',
                 '/api/operations/batches/batch-1', '/api/operations/batches/batch-1/execute']:
        headers = instance._forwarded_client_headers(path)
        assert headers['X-Forwarded-For'] == '203.0.113.7'
        assert headers['X-API-Key'] == 'test-api-key'
        assert operations_route_allowed(path)


def test_renders_capability_driven_operation_actions(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    with browser(host) as (page, client, external, errors):
        open_workspace(page)
        for kind in ['artifact.capture', 'artifact.update', 'artifact.move', 'artifact.rename']:
            assert page.locator(f'#operations-kind option[value="{kind}"]').is_enabled()
        for kind in ['artifact.create', 'artifact.classify', 'artifact.tags.add', 'artifact.tags.remove',
                     'collection.reorder', 'artifact.archive', 'artifact.restore']:
            assert page.locator(f'#operations-kind option[value="{kind}"]').is_disabled()
        assert 'semantic approval owner unavailable' in page.locator('#operations-capabilities').text_content()
        assert host.artifact_id in page.locator('#operations-resources').text_content()
        assert 'Notes/human.md' in page.locator('#operations-resources').text_content()
        choose(page)
        page.locator('#operations-preview').click()
        page.locator('#operations-confirm:enabled').wait_for()
        assert host.note.read_text().endswith('Original.\n')
        evidence(page,'single-preview',external,errors)
        page.locator('#operations-confirm').dblclick()
        page.get_by_text('Source effect: committed', exact=False).wait_for()
        assert host.note.read_text().endswith('Updated in Companion.\n')
        assert len([c for c in client.calls if c[0]=='POST' and c[1]=='/api/operations' and c[2]['operation_id']=='artifact.update']) == 1
        page.reload()
        page.get_by_test_id('operations-open').click()
        page.get_by_text('Source effect: committed', exact=False).wait_for()
        assert len([c for c in client.calls if c[0]=='POST' and c[1]=='/api/operations' and c[2]['operation_id']=='artifact.update']) == 1
        evidence(page,'single-restart',external,errors)
        assert external == [] and errors == []


def add_second(host):
    identity = str(uuid4())
    (host.root/'Notes'/'second.md').write_text(f'---\nuuid: {identity}\nartifact_class: human_knowledge\ntrust: human\n---\nSecond.\n')
    return identity


def batch_preview(page, host):
    open_workspace(page)
    for check in page.locator('#operations-resources input[type=checkbox]:enabled').all():
        check.check()
    page.locator('#operations-kind').select_option('artifact.update')
    for index, field in enumerate(page.locator('[data-argument]').all()):
        field.fill(f'Batch item {index}.\n')
    page.locator('#operations-preview').click()
    page.locator('#operations-confirm:enabled').wait_for()


def test_confirms_bounded_scope_once_before_execution(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    second = add_second(host)
    with browser(host) as (page, client, external, errors):
        batch_preview(page, host)
        scope = page.locator('#operations-scope')
        assert 'Cardinality: 2' in scope.text_content()
        assert 'Maximum count: 2' in scope.text_content()
        assert host.artifact_id in scope.text_content() and second in scope.text_content()
        assert 'expected_version' in scope.text_content() and 'expires_at' in scope.text_content()
        assert 'allowed_effects' in scope.text_content() and 'independent' in scope.text_content()
        assert host.note.read_text().endswith('Original.\n')
        page.locator('#operations-confirm').click()
        page.get_by_text('Runtime status: convergence_pending', exact=True).wait_for()
        effects=[c for c in client.calls if c[0]=='POST' and c[1].endswith('/execute')]
        assert len(effects) == 1 and set(effects[0][2]) == {'expected_digest'}
        assert not [c for c in client.calls if c[0]=='POST' and c[1]=='/api/operations' and c[2]['operation_id']=='artifact.update']
        assert external == [] and errors == []


def test_renders_truthful_progress_receipts_and_recovery(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    add_second(host)
    with browser(host) as (page, client, external, errors):
        batch_preview(page, host)
        # Freeze actual owner-native versions, then race a real edit before execution.
        host.note.write_text(host.note.read_text()+'Concurrent newer body.\n')
        page.locator('#operations-confirm').click()
        page.get_by_text('Runtime status: partial', exact=True).wait_for()
        progress=page.locator('#operations-progress').text_content()
        assert 'conflicted' in progress and 'convergence_pending' in progress
        assert 'Source effect: committed' in progress and 'index rebuild_required' in progress
        assert 'Receipt:' in progress and 'provenance' in progress
        evidence(page,'partial-conflict',external,errors)
        assert host.note.read_text().endswith('Concurrent newer body.\n')
        assert page.locator('#operations-resume').is_hidden()
        page.reload()
        page.get_by_test_id('operations-open').click()
        page.get_by_text('Runtime status: partial', exact=True).wait_for()
        assert 'conflicted' in page.locator('#operations-progress').text_content()
        assert external == [] and errors == []


@pytest.mark.parametrize('state', ['rejected', 'recovery_required', 'cancelled'])
def test_server_declared_failure_states_never_imply_retry_or_success(tmp_path, monkeypatch, state):
    host = production_operation_host(tmp_path, monkeypatch)
    with browser(host) as (page, client, external, errors):
        open_workspace(page)
        # Only outcome transport is injected; no client inference from an HTTP 200.
        body={'request_id':'retained-'+state,'operation_id':'artifact.update','status':state,
              'convergence':{'source_effect':'unknown','index':'pending','store':'pending','link':'pending'},
              'warnings':['owner proof unavailable'],'recovery':{'resume_allowed':False}}
        page.route('**/api/operations/receipts/retained-*',lambda route:route.fulfill(json=body))
        page.get_by_text('Reopen an operation after interruption', exact=True).click()
        page.locator('#operations-reference').fill('retained-'+state)
        page.locator('#operations-reopen').click()
        page.get_by_text('Runtime status: '+state, exact=True).wait_for()
        assert 'Source effect: unknown' in page.locator('#operations-progress').text_content()
        assert page.locator('#operations-resume').is_hidden()
        assert not [c for c in client.calls if c[1].endswith('/execute')]
        assert host.note.read_text().endswith('Original.\n')
        assert errors == [] and external == []


def test_supports_keyboard_focus_labels_and_responsive_layout(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    with browser(host,viewport={'width':390,'height':844}) as (page, client, external, errors):
        opener=page.get_by_test_id('operations-open')
        opener.focus()
        page.keyboard.press('Enter')
        page.locator('#operations-resources input[type=checkbox]:enabled').first.wait_for()
        assert page.locator('#operations-discover').evaluate('(e)=>e===document.activeElement')
        choose(page)
        page.locator('#operations-preview').focus()
        page.keyboard.press('Enter')
        page.locator('#operations-confirm:enabled').wait_for()
        assert page.locator('#operations-preview-region').evaluate('(e)=>e===document.activeElement')
        page.keyboard.press('Tab')
        assert page.locator('#operations-preview-region').evaluate('(e)=>e.contains(document.activeElement)')
        page.locator('#operations-back').click()
        assert page.locator('#operations-preview').evaluate('(e)=>e===document.activeElement')
        for width in [1440,720,390,195]:
            page.set_viewport_size({'width':width,'height':900})
            assert page.locator('.operations-panel').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
            assert page.locator('.operations-body').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
            evidence(page,'width-'+str(width),external,errors)
        page.set_viewport_size({'width':1440,'height':1000})
        page.evaluate("document.documentElement.style.zoom='2'")
        assert page.locator('.operations-body').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
        assert page.locator('.operations-panel').bounding_box()['width'] <= 1440
        evidence(page,'zoom-200',external,errors)
        page.evaluate("document.documentElement.style.zoom='1'")
        snapshot=page.get_by_role('dialog',name='Operations',exact=True).aria_snapshot()
        assert 'Select resources' in snapshot and 'Choose an outcome' in snapshot and 'Operation' in snapshot
        assert page.locator('#operations-state').get_attribute('aria-live')=='polite'
        page.emulate_media(media='print')
        assert page.get_by_role('dialog',name='Operations',exact=True).is_visible()
        evidence(page,'print',external,errors)
        page.emulate_media(media='screen')
        page.keyboard.press('Escape')
        page.get_by_test_id('operations-workspace').wait_for(state='hidden')
        assert opener.evaluate('(e)=>e===document.activeElement')
        assert errors==[] and external==[]


def test_cancellation_uses_retained_server_scope(tmp_path, monkeypatch):
    host=production_operation_host(tmp_path,monkeypatch)
    add_second(host)
    with browser(host) as (page, client, external, errors):
        batch_preview(page,host)
        def delayed_execute(route):
            query=parse_qs(urlparse(page.url).query)
            identity=query['operation_request'][0]
            digest=query['operation_digest'][0]
            pending=host.client.get('/api/operations/batches/'+identity,params={'expected_digest':digest},headers=host.headers)
            assert pending.status_code==200
            route.fulfill(json=pending.json())
        page.route('**/api/operations/batches/*/execute',delayed_execute)
        page.locator('#operations-confirm').click()
        page.locator('#operations-cancel:visible').wait_for()
        page.locator('#operations-cancel').click()
        page.get_by_text('Runtime status: cancelled',exact=True).wait_for()
        assert 'Cancellation requested: true' in page.locator('#operations-progress').text_content()
        assert page.locator('#operations-resume').is_hidden()
        assert host.note.read_text().endswith('Original.\n')
        evidence(page,'cancelled',external,errors)
        page.reload()
        page.get_by_test_id('operations-open').click()
        page.get_by_text('Runtime status: cancelled',exact=True).wait_for()
        assert errors==[] and external==[]


def test_lost_effect_response_reads_receipt_without_retry(tmp_path, monkeypatch):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page, client, external, errors):
        open_workspace(page)
        choose(page)
        page.locator('#operations-preview').click()
        page.locator('#operations-confirm:enabled').wait_for()
        def lose_response(route):
            response=route.fetch()
            assert response.status==200
            route.abort()
        page.route('**/api/operations',lose_response)
        page.locator('#operations-confirm').click()
        page.get_by_text('Source effect: committed',exact=False).wait_for()
        assert host.note.read_text().endswith('Updated in Companion.\n')
        assert len([c for c in client.calls if c[0]=='POST' and c[1]=='/api/operations' and c[2]['operation_id']=='artifact.update'])==1
        assert errors==[] and external==[]


def test_empty_discovery_and_javascript_off_are_truthful(tmp_path, monkeypatch):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page, client, external, errors):
        open_workspace(page)
        page.locator('#operations-filter').fill('no-such-title-5339')
        page.locator('#operations-list').click()
        page.get_by_text('No resources match this filter.',exact=True).wait_for()
        assert page.locator('#operations-resources input[type=checkbox]').count()==0
        evidence(page,'empty',external,errors)
        assert errors==[] and external==[]
    with browser(host,javascript_enabled=False) as (page, client, external, errors):
        assert page.get_by_text('Operations requires JavaScript. No operation has been submitted.',exact=True).first.is_visible()
        assert not [c for c in client.calls if c[1].startswith('/api/operations')]
        destination=os.environ.get('OPERATIONS_EVIDENCE_DIR')
        if destination:page.screenshot(path=str(Path(destination)/'javascript-off.png'))
        assert errors==[] and external==[]
