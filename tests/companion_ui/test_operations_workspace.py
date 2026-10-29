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
        preflight_count=len([c for c in client.calls if c[1]=='/api/operations/preconditions'])
        page.keyboard.press('Escape')
        page.get_by_test_id('operations-workspace').wait_for(state='hidden')
        opener.focus()
        page.keyboard.press('Enter')
        assert page.locator('#operations-preview-region').evaluate('(e)=>e===document.activeElement')
        assert page.locator('#operations-confirm').is_enabled()
        assert len([c for c in client.calls if c[1]=='/api/operations/preconditions'])==preflight_count
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


def retained_snapshot(*, state='pending', cancelled=False):
    """Server-shaped retained batch fixture for transport-ordering UI proofs."""
    terminal=state=='succeeded'
    outcome={'request_id':'receipt-A','operation_id':'artifact.update','status':'succeeded',
             'receipt':{'receipt_id':'native-A'},'convergence':{'source_effect':'committed','store':'converged','index':'converged','link':'converged'}}
    return {'batch_id':'retained-A','status':'cancelled' if cancelled else 'succeeded' if terminal else 'pending',
            'current_admission':'original','cancel_requested':cancelled,
            'counts':{'completed':2 if terminal else 1,'pending':0 if terminal or cancelled else 1,'recoverable':0,'cancelled':1 if cancelled else 0},
            'items':[{'request_id':'receipt-A','artifact_id':'target-A','state':'terminal','outcome':outcome},
                     {'request_id':'receipt-B','artifact_id':'target-B','state':'cancelled' if cancelled else 'terminal' if terminal else state,
                      'outcome':outcome|{'request_id':'receipt-B'} if terminal else None}]}


def install_retained_transport(page, initial):
    state={'snapshot':initial,'reads':0,'execute':[],'cancel':[]}
    def route_retained(route):
        request=route.request
        if request.method=='GET':
            state['reads']+=1
            if state.get('unavailable'):
                route.fulfill(status=503,json={'detail':'operation_readback_unavailable'})
            else:
                route.fulfill(json=state['snapshot'])
        elif request.url.endswith('/execute'):
            state['execute'].append(route)
        elif request.url.endswith('/cancel'):
            state['cancel'].append(route)
        else:
            route.abort()
    page.route('**/api/operations/batches/retained-*',route_retained)
    page.route('**/api/operations/batches/retained-*/execute',route_retained)
    page.route('**/api/operations/batches/retained-*/cancel',route_retained)
    page.get_by_text('Reopen an operation after interruption',exact=True).click()
    page.locator('#operations-reference').fill('retained-A')
    page.locator('#operations-digest').fill('a'*64)
    page.locator('#operations-reopen').click()
    page.get_by_text('Runtime status: pending',exact=True).wait_for()
    return state


@pytest.mark.parametrize('cancel_first',[True,False])
def test_late_mutation_response_cannot_regress_cancellation_or_change_reference(tmp_path,monkeypatch,cancel_first):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page)
        pending=retained_snapshot()
        transport=install_retained_transport(page,pending)
        with page.expect_request('**/retained-A/execute'):
            page.locator('#operations-resume').click()
        page.wait_for_timeout(50)
        with page.expect_request('**/retained-A/cancel'):
            page.locator('#operations-cancel').click()
        page.wait_for_timeout(50)
        cancelled=retained_snapshot(cancelled=True)
        if cancel_first:
            transport['snapshot']=cancelled
            transport['cancel'][0].fulfill(json=cancelled)
            page.get_by_text('Runtime status: cancelled',exact=True).wait_for()
            transport['execute'][0].fulfill(json=pending)
        else:
            transport['execute'][0].fulfill(json=pending)
            page.wait_for_timeout(100)
            # Cancellation still owns A; changing the reference cannot cross that in-flight boundary.
            page.locator('#operations-reference').fill('retained-B')
            page.locator('#operations-digest').fill('b'*64)
            assert page.locator('#operations-reopen').is_disabled()
            page.evaluate("document.querySelector('#operations-reopen').onclick()")
            assert parse_qs(urlparse(page.url).query)['operation_request']==['retained-A']
            transport['snapshot']=cancelled
            transport['cancel'][0].fulfill(json=cancelled)
        page.get_by_text('Runtime status: cancelled',exact=True).wait_for()
        page.wait_for_timeout(50)
        assert 'Cancellation requested: true' in page.locator('#operations-progress').text_content()
        assert page.locator('#operations-resume').is_hidden()
        assert parse_qs(urlparse(page.url).query)['operation_request']==['retained-A']
        # Settled ACKs preserve a user's intervening focus inside the current modal.
        assert page.locator('#operations-results' if cancel_first else '#operations-digest').evaluate('(e)=>e===document.activeElement')
        evidence(page,'ordered-cancel-'+str(cancel_first),external,errors)
        assert host.note.read_text().endswith('Original.\n')
        assert errors==[] and external==[]


@pytest.mark.parametrize('lost_response',[False,True])
def test_pending_restart_and_lost_response_keep_passive_observation(tmp_path,monkeypatch,lost_response):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page)
        transport=install_retained_transport(page,retained_snapshot())
        if lost_response:
            with page.expect_request('**/retained-A/execute'):
                page.locator('#operations-resume').click()
            page.wait_for_timeout(50)
            transport['execute'][0].abort()
            page.wait_for_function("!document.querySelector('#operations-resume').disabled")
        initial_reads=transport['reads']
        transport['snapshot']=retained_snapshot(state='succeeded')
        page.get_by_text('Runtime status: succeeded',exact=True).wait_for()
        assert transport['reads']>initial_reads
        assert len(transport['execute'])==int(lost_response)
        assert not [c for c in client.calls if c[1].endswith('/execute')]
        evidence(page,'pending-observed-'+str(lost_response),external,errors)
        assert errors==[] and external==[]


def test_progress_preserves_disclosure_focus_and_deduplicates_item_announcements(tmp_path,monkeypatch):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page)
        transport=install_retained_transport(page,retained_snapshot())
        assert page.locator('#operations-results').evaluate('(e)=>e===document.activeElement')
        disclosure=page.locator('section[aria-label="Result target-A"] details').last
        disclosure.locator('summary').click()
        assert disclosure.evaluate('(e)=>e.open')
        transport['snapshot']=retained_snapshot(state='started')
        page.get_by_text('target-B · started',exact=True).wait_for()
        assert disclosure.evaluate('(e)=>e.open')
        assert disclosure.locator('summary').evaluate('(e)=>e===document.activeElement')
        announcement=page.locator('#operations-state').text_content()
        assert 'target-B: started' in announcement
        reads=transport['reads']
        page.wait_for_timeout(1200)
        assert transport['reads']>reads
        assert page.locator('#operations-state').text_content()==announcement
        assert disclosure.evaluate('(e)=>e.open')
        assert disclosure.locator('summary').evaluate('(e)=>e===document.activeElement')
        transport['unavailable']=True
        page.locator('#operations-inspect').click()
        page.get_by_text('Current readback unavailable;',exact=False).wait_for()
        assert page.locator('#operations-resume').is_hidden()
        assert disclosure.evaluate('(e)=>e.open')
        transport['unavailable']=False
        page.locator('#operations-inspect').click()
        page.get_by_text('Durable readback restored.',exact=False).wait_for()
        assert page.locator('#operations-resume').is_visible()
        assert disclosure.evaluate('(e)=>e.open')
        evidence(page,'focused-disclosure-live-item',external,errors)
        assert errors==[] and external==[]


def test_reopens_a_native_receipt_with_a_colon_identity(tmp_path,monkeypatch):
    host=production_operation_host(tmp_path,monkeypatch)
    response=host.client.post('/api/operations',headers=host.headers,
        json=host.command(request_id='retained:external'))
    assert response.status_code==200
    with browser(host) as (page,client,external,errors):
        open_workspace(page)
        page.get_by_text('Reopen an operation after interruption',exact=True).click()
        page.locator('#operations-reference').fill('retained:external')
        page.locator('#operations-reopen').click()
        page.get_by_text('Source effect: committed',exact=False).wait_for()
        assert any(c[0]=='GET' and c[1]=='/api/operations/receipts/retained:external' for c in client.calls)
        assert errors==[] and external==[]


def test_newer_cancellation_readback_survives_a_late_execute_acknowledgement(tmp_path,monkeypatch):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page)
        transport=install_retained_transport(page,retained_snapshot())
        with page.expect_request('**/retained-A/execute'):
            page.locator('#operations-resume').click()
        page.wait_for_timeout(50)
        recovery=retained_snapshot()
        recovery.update(status='recovery_required',cancel_requested=True)
        recovery['counts'].update(pending=0,recoverable=1)
        recovery['items'][1].update(state='recoverable',outcome={
            'request_id':'receipt-B','status':'recovery_required','operation_id':'artifact.update',
            'convergence':{'source_effect':'unknown','index':'pending'}})
        transport['snapshot']=recovery
        page.locator('#operations-inspect').click()
        page.get_by_text('Runtime status: recovery_required',exact=True).wait_for()
        assert 'Cancellation requested: true' in page.locator('#operations-progress').text_content()
        assert page.locator('#operations-resume').is_hidden()
        stale=json.loads(json.dumps(recovery));stale['cancel_requested']=False
        reads=transport['reads']
        transport['execute'][0].fulfill(json=stale)
        page.wait_for_function("!document.querySelector('#operations-resume').disabled")
        assert transport['reads']>reads
        assert 'Cancellation requested: true' in page.locator('#operations-progress').text_content()
        assert page.locator('#operations-resume').is_hidden()
        assert not transport['cancel']
        evidence(page,'cancellation-from-readback',external,errors)
        assert errors==[] and external==[]


def test_slow_passive_read_is_not_superseded_by_the_polling_interval(tmp_path,monkeypatch):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page)
        install_retained_transport(page,retained_snapshot())
        held=[]
        def slow_read(route):
            assert route.request.method=='GET'
            held.append(route)
        page.route('**/api/operations/batches/retained-*',slow_read)
        page.wait_for_timeout(1200)
        assert len(held)==1
        page.wait_for_timeout(1600)
        assert len(held)==1, 'A passive read must settle before another starts'
        held[0].fulfill(json=retained_snapshot(state='succeeded'))
        page.get_by_text('Runtime status: succeeded',exact=True).wait_for()
        page.wait_for_timeout(1200)
        assert len(held)==1
        evidence(page,'slow-read-terminal',external,errors)
        assert not [c for c in client.calls if c[1].endswith('/execute')]
        assert errors==[] and external==[]


def test_initial_unavailable_retained_read_exposes_safe_reset_and_focus(tmp_path,monkeypatch):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        page.route('**/api/operations/batches/retained-unavailable*',
            lambda route:route.fulfill(status=503,json={'detail':'batch_state_unavailable'}))
        page.goto(page.url+'?operation_request=retained-unavailable&operation_digest='+'f'*64)
        page.get_by_test_id('operations-open').click()
        page.get_by_text('Current readback unavailable;',exact=False).wait_for()
        assert page.locator('#operations-results').is_visible()
        assert page.locator('#operations-results').evaluate('(e)=>e===document.activeElement')
        assert page.locator('#operations-new').is_visible()
        assert page.locator('#operations-inspect').is_visible()
        assert page.locator('#operations-cancel').is_hidden() and page.locator('#operations-resume').is_hidden()
        evidence(page,'initial-unavailable-recovery',external,errors)
        page.locator('#operations-new').click()
        page.locator('#operations-resources input[type=checkbox]:enabled').first.wait_for()
        assert page.locator('#operations-discover').is_enabled()
        assert page.locator('#operations-intent').is_enabled()
        assert 'operation_request' not in parse_qs(urlparse(page.url).query)
        assert not [c for c in client.calls if c[1].endswith('/execute')]
        assert host.note.read_text().endswith('Original.\n')
        assert errors==[] and external==[]


@pytest.mark.parametrize('mutation',['execute','cancel'])
def test_overlapping_mutation_ack_reads_fresh_state_before_rendering(tmp_path,monkeypatch,mutation):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page)
        transport=install_retained_transport(page,retained_snapshot())
        button='resume' if mutation=='execute' else 'cancel'
        with page.expect_request('**/retained-A/'+mutation):
            page.locator('#operations-'+button).click()
        page.wait_for_timeout(50)
        held=[]
        page.route('**/api/operations/batches/retained-*',lambda route:held.append(route))
        page.locator('#operations-inspect').click()
        page.wait_for_timeout(50)
        assert len(held)==1
        old=retained_snapshot()
        if mutation=='cancel':old['cancel_requested']=True
        transport[mutation][0].fulfill(json=old)
        page.wait_for_timeout(50)
        assert len(held)==2, 'Overlapping mutation acknowledgement must request fresh authoritative readback'
        latest=retained_snapshot(state='succeeded')
        if mutation=='cancel':latest['cancel_requested']=True
        held[1].fulfill(json=latest)
        page.get_by_text('Runtime status: succeeded',exact=True).wait_for()
        held[0].fulfill(json=retained_snapshot())
        page.wait_for_timeout(50)
        assert page.get_by_text('Runtime status: succeeded',exact=True).is_visible()
        assert page.locator('#operations-resume').is_hidden()
        if mutation=='cancel':assert 'Cancellation requested: true' in page.locator('#operations-progress').text_content()
        evidence(page,'overlapping-ack-'+mutation,external,errors)
        assert errors==[] and external==[]


def test_scope_replacement_clears_old_effect_controls_before_readback(tmp_path,monkeypatch):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page)
        transport=install_retained_transport(page,retained_snapshot())
        held=[]
        page.route('**/api/operations/batches/retained-B*',lambda route:held.append(route))
        page.locator('#operations-reference').fill('retained-B')
        page.locator('#operations-digest').fill('b'*64)
        page.locator('#operations-reopen').click()
        page.get_by_text('Loading durable state for retained-B',exact=False).wait_for()
        assert page.locator('#operations-progress').text_content()==''
        assert page.locator('#operations-cancel').is_hidden() and page.locator('#operations-resume').is_hidden()
        assert page.locator('#operations-results').evaluate('(e)=>e===document.activeElement')
        page.evaluate("document.querySelector('#operations-cancel').onclick()")
        assert not transport['cancel']
        page.wait_for_timeout(50)
        assert len(held)==1
        held[0].fulfill(status=503,json={'detail':'batch_state_unavailable'})
        page.get_by_text('Current readback unavailable;',exact=False).wait_for()
        assert page.locator('#operations-new').is_visible()
        assert 'target-A' not in page.locator('#operations-progress').text_content()
        evidence(page,'scope-replacement-loading',external,errors)
        assert errors==[] and external==[]


def test_a_superseded_read_does_not_block_the_new_reference_observer(tmp_path,monkeypatch):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page)
        install_retained_transport(page,retained_snapshot())
        old=[]
        page.route('**/api/operations/batches/retained-A?*',lambda route:old.append(route))
        page.locator('#operations-inspect').click()
        page.wait_for_timeout(50)
        assert len(old)==1
        state={'snapshot':retained_snapshot()|{'batch_id':'retained-B'}}
        page.route('**/api/operations/batches/retained-B?*',lambda route:route.fulfill(json=state['snapshot']))
        page.locator('#operations-reference').fill('retained-B')
        page.locator('#operations-digest').fill('b'*64)
        page.locator('#operations-reopen').click()
        page.get_by_text('Runtime status: pending',exact=True).wait_for()
        state['snapshot']=retained_snapshot(state='succeeded')|{'batch_id':'retained-B'}
        page.get_by_text('Runtime status: succeeded',exact=True).wait_for()
        old[0].fulfill(json=retained_snapshot())
        page.wait_for_timeout(50)
        assert page.get_by_text('Runtime status: succeeded',exact=True).is_visible()
        assert parse_qs(urlparse(page.url).query)['operation_request']==['retained-B']
        evidence(page,'superseded-read-new-view',external,errors)
        assert errors==[] and external==[]


def test_operations_work_without_secure_context_random_uuid(tmp_path,monkeypatch):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        page.evaluate("Object.defineProperty(window.crypto,'randomUUID',{value:undefined,configurable:true})")
        open_workspace(page)
        choose(page)
        page.locator('#operations-preview').click()
        page.locator('#operations-confirm:enabled').wait_for()
        page.locator('#operations-confirm').click()
        page.get_by_text('Source effect: committed',exact=False).wait_for()
        assert host.note.read_text().endswith('Updated in Companion.\n')
        effects=[c for c in client.calls if c[0]=='POST' and c[1]=='/api/operations' and c[2]['operation_id']=='artifact.update']
        assert len(effects)==1
        assert effects[0][2]['request_id'].startswith('companion-')
        assert errors==[] and external==[]


@pytest.mark.parametrize('mutation',['execute','cancel'])
@pytest.mark.parametrize('late_error',[False,True])
def test_settled_mutation_does_not_wait_for_superseded_read_before_scope_reset(tmp_path,monkeypatch,mutation,late_error):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page)
        transport=install_retained_transport(page,retained_snapshot())
        with page.expect_request('**/retained-A/'+mutation):
            page.locator('#operations-'+('resume' if mutation=='execute' else 'cancel')).click()
        page.wait_for_timeout(40)
        held=[]
        page.route('**/api/operations/batches/retained-*',lambda route:held.append(route))
        page.locator('#operations-inspect').click()
        page.wait_for_timeout(40)
        transport[mutation][0].fulfill(json=retained_snapshot(cancelled=mutation=='cancel'))
        page.wait_for_timeout(40)
        assert len(held)==2
        assert page.locator('#operations-new').is_enabled()
        assert page.locator('#operations-resume').is_hidden() and page.locator('#operations-cancel').is_hidden()
        page.locator('#operations-inspect').click()
        page.wait_for_timeout(40)
        assert len(held)==3
        held[2].fulfill(json=retained_snapshot(state='succeeded'))
        page.get_by_text('Runtime status: succeeded',exact=True).wait_for()
        # G0/G1 remain lost while reset must actually work; no replay of the settled effect.
        page.locator('#operations-new').click()
        page.locator('#operations-resources input[type=checkbox]:enabled').first.wait_for()
        assert 'operation_request' not in parse_qs(urlparse(page.url).query)
        page.locator('#operations-reference').fill('retained-B')
        page.locator('#operations-digest').fill('b'*64)
        page.locator('#operations-reopen').click()
        page.wait_for_timeout(40)
        held[3].fulfill(json=retained_snapshot(state='succeeded')|{'batch_id':'retained-B'})
        page.get_by_text('Runtime status: succeeded',exact=True).wait_for()
        if late_error:
            held[0].abort();held[1].fulfill(status=503,json={'detail':'obsolete'})
        else:
            held[0].fulfill(json=retained_snapshot());held[1].fulfill(json=retained_snapshot())
        page.wait_for_timeout(60)
        assert parse_qs(urlparse(page.url).query)['operation_request']==['retained-B']
        assert page.get_by_text('Runtime status: succeeded',exact=True).is_visible()
        assert len(transport[mutation])==1
        evidence(page,'settled-guard-'+mutation+'-'+str(late_error),external,errors)
        assert errors==[] and external==[]


@pytest.mark.parametrize('mutation',['execute','cancel'])
@pytest.mark.parametrize('failure',['abort','http','nonjson'])
def test_failed_mutation_forces_post_settlement_read_without_stale_effect_eligibility(tmp_path,monkeypatch,mutation,failure):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page)
        transport=install_retained_transport(page,retained_snapshot())
        with page.expect_request('**/retained-A/'+mutation):
            page.locator('#operations-'+('resume' if mutation=='execute' else 'cancel')).click()
        page.wait_for_timeout(40)
        held=[]
        page.route('**/api/operations/batches/retained-*',lambda route:held.append(route))
        page.locator('#operations-inspect').click()
        page.wait_for_timeout(40)
        if failure=='abort':transport[mutation][0].abort()
        elif failure=='http':transport[mutation][0].fulfill(status=503,json={'detail':'lost response'})
        else:transport[mutation][0].fulfill(status=200,content_type='text/plain',body='not json')
        page.wait_for_timeout(80)
        assert len(held)==2, 'A pre-settlement observation cannot replace post-settlement readback'
        held[0].fulfill(json=retained_snapshot())
        page.wait_for_timeout(40)
        assert page.locator('#operations-resume').is_hidden() and page.locator('#operations-cancel').is_hidden()
        assert page.locator('#operations-new').is_enabled()
        summary=page.locator('section[aria-label="Result target-A"] details').last.locator('summary')
        summary.click()
        page.evaluate("window.liveUpdates=[];new MutationObserver(()=>liveUpdates.push(document.querySelector('#operations-state').textContent)).observe(document.querySelector('#operations-state'),{childList:true,subtree:true,characterData:true})")
        held[1].fulfill(json=retained_snapshot())
        page.locator('#operations-resume:enabled').wait_for()
        assert page.locator('#operations-state').text_content().startswith('Operation pending')
        assert len(page.evaluate('liveUpdates'))==1
        assert summary.evaluate('(e)=>e===document.activeElement && e.parentElement.open')
        page.locator('#operations-inspect').click();page.wait_for_timeout(40)
        assert len(held)==3
        held[2].fulfill(json=retained_snapshot());page.wait_for_timeout(40)
        assert len(page.evaluate('liveUpdates'))==1, 'Identical inspection after settlement remains silent'
        page.wait_for_timeout(1100)
        assert len(held)==4, 'Fresh pending readback restores one passive observer'
        held[3].fulfill(json=retained_snapshot(state='succeeded'))
        page.get_by_text('Runtime status: succeeded',exact=True).wait_for()
        assert len(transport[mutation])==1
        evidence(page,'failed-guard-'+mutation+'-'+failure,external,errors)
        assert errors==[] and external==[]


@pytest.mark.parametrize('mutation',['execute','cancel'])
def test_only_unsettled_http_request_fences_reference_replacement(tmp_path,monkeypatch,mutation):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page)
        transport=install_retained_transport(page,retained_snapshot())
        action='resume' if mutation=='execute' else 'cancel'
        with page.expect_request('**/retained-A/'+mutation):page.locator('#operations-'+action).click()
        transport['snapshot']=retained_snapshot(state='succeeded')
        page.locator('#operations-inspect').click()
        page.get_by_text('Runtime status: succeeded',exact=True).wait_for()
        assert page.locator('#operations-new').is_disabled() and page.locator('#operations-reopen').is_disabled()
        page.evaluate("document.querySelector('#operations-new').onclick();document.querySelector('#operations-reopen').onclick();document.querySelector('#operations-"+action+"').onclick()")
        page.wait_for_timeout(40)
        assert parse_qs(urlparse(page.url).query)['operation_request']==['retained-A']
        assert len(transport[mutation])==1
        held=[]
        page.route('**/api/operations/batches/retained-*',lambda route:held.append(route))
        transport[mutation][0].fulfill(json=retained_snapshot())
        page.locator('#operations-new:enabled').wait_for()
        assert len(held)==1
        page.locator('#operations-new').click()
        page.locator('#operations-resources input[type=checkbox]:enabled').first.wait_for()
        assert 'operation_request' not in parse_qs(urlparse(page.url).query)
        assert len(transport[mutation])==1
        assert errors==[] and external==[]


@pytest.mark.parametrize('focus',['cancel','resume','disclosure'])
def test_passive_read_failure_preserves_or_rehomes_focus_and_restores_once(tmp_path,monkeypatch,focus):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page)
        transport=install_retained_transport(page,retained_snapshot())
        summary=page.locator('section[aria-label="Result target-A"] details').last.locator('summary')
        if focus=='disclosure':summary.click()
        else:page.locator('#operations-'+focus).focus()
        transport['unavailable']=True
        page.get_by_text('Current readback unavailable;',exact=False).wait_for()
        if focus=='disclosure':
            assert summary.evaluate('(e)=>e===document.activeElement && e.parentElement.open')
        else:assert page.locator('#operations-results').evaluate('(e)=>e===document.activeElement')
        assert page.locator('#operations-resume').is_hidden() and page.locator('#operations-cancel').is_hidden()
        page.evaluate("window.liveUpdates=[];new MutationObserver(()=>liveUpdates.push(document.querySelector('#operations-state').textContent)).observe(document.querySelector('#operations-state'),{childList:true,subtree:true,characterData:true})")
        transport['unavailable']=False
        page.locator('#operations-inspect').focus();page.keyboard.press('Enter')
        page.get_by_text('Durable readback restored.',exact=False).wait_for()
        assert len(page.evaluate('liveUpdates'))==1
        page.locator('#operations-inspect').click();page.wait_for_timeout(60)
        assert len(page.evaluate('liveUpdates'))==1
        evidence(page,'passive-focus-'+focus,external,errors)
        assert errors==[] and external==[]


@pytest.mark.parametrize('state',['pending','recovery','terminal','unavailable'])
def test_retained_overlay_reopen_replaces_lost_reads_and_focuses_labelled_results(tmp_path,monkeypatch,state):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page)
        transport=install_retained_transport(page,retained_snapshot())
        snapshot=retained_snapshot(state='succeeded') if state=='terminal' else retained_snapshot()
        if state=='recovery':snapshot.update(status='recovery_required',counts={'pending':0,'recoverable':1})
        transport['snapshot']=snapshot
        transport['unavailable']=state=='unavailable'
        page.locator('#operations-inspect').click();page.wait_for_timeout(60)
        held=[]
        page.route('**/api/operations/batches/retained-*',lambda route:held.append(route))
        page.locator('#operations-inspect').click();page.wait_for_timeout(40)
        for _ in range(3):
            count=len(held)
            page.keyboard.press('Escape')
            page.get_by_test_id('operations-workspace').wait_for(state='hidden')
            page.wait_for_timeout(50)
            assert page.get_by_test_id('operations-open').evaluate('(e)=>e===document.activeElement')
            page.get_by_test_id('operations-open').click()
            assert page.locator('#operations-results').evaluate('(e)=>e===document.activeElement')
            page.wait_for_timeout(50)
            assert len(held)==count+1
        assert len(held)==4
        # Settling an obsolete read cannot clear ownership of the newest held one.
        held[0].abort();held[1].fulfill(json=retained_snapshot(state='succeeded'))
        page.wait_for_timeout(1200)
        assert len(held)==4
        if state=='unavailable':held[-1].fulfill(status=503,json={'detail':'unavailable'})
        else:held[-1].fulfill(json=snapshot)
        page.wait_for_timeout(70)
        assert page.locator('#operations-results').evaluate('(e)=>e===document.activeElement')
        assert not transport['execute'] and not transport['cancel']
        evidence(page,'retained-reopen-'+state,external,errors)
        assert errors==[] and external==[]


@pytest.mark.parametrize('replacement',['other-id','other-digest','roundtrip'])
def test_reference_generation_rejects_old_success_and_failure(tmp_path,monkeypatch,replacement):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page)
        install_retained_transport(page,retained_snapshot())
        held=[]
        page.route('**/api/operations/batches/retained-*',lambda route:held.append(route))
        page.locator('#operations-inspect').click();page.wait_for_timeout(40)
        new_id='retained-A' if replacement=='other-digest' else 'retained-B'
        page.locator('#operations-reference').fill(new_id);page.locator('#operations-digest').fill('b'*64)
        page.locator('#operations-reopen').click();page.wait_for_timeout(40)
        assert page.locator('#operations-progress').text_content()==''
        if replacement=='roundtrip':
            page.locator('#operations-reference').fill('retained-A');page.locator('#operations-digest').fill('a'*64)
            page.locator('#operations-reopen').click();page.wait_for_timeout(40)
            held[1].fulfill(status=503,json={'detail':'old B'})
        held[-1].fulfill(json=retained_snapshot(state='succeeded')|{'batch_id':'retained-A' if replacement=='roundtrip' else new_id})
        page.get_by_text('Runtime status: succeeded',exact=True).wait_for()
        held[0].fulfill(json=retained_snapshot())
        page.wait_for_timeout(60)
        expected_id='retained-A' if replacement=='roundtrip' else new_id
        assert parse_qs(urlparse(page.url).query)['operation_request']==[expected_id]
        assert page.get_by_text('Runtime status: succeeded',exact=True).is_visible()
        assert errors==[] and external==[]


@pytest.mark.parametrize('pending',[True,False])
def test_named_phase_announcements_match_visible_facts_and_identical_reads_are_silent(tmp_path,monkeypatch,pending):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page)
        snapshot=retained_snapshot()
        if not pending:snapshot.update(status='recovery_required',counts={'pending':0,'recoverable':1})
        outcome=snapshot['items'][0]['outcome']
        outcome['convergence'].update(store='pending',index='pending',link='pending')
        outcome['receipt']={'status':'pending'}
        transport=install_retained_transport(page,retained_snapshot())
        transport['snapshot']=snapshot
        page.locator('#operations-inspect').click();page.wait_for_timeout(60)
        assert 'Receipt: not declared · Receipt status: pending' in page.locator('#operations-progress').text_content()
        page.evaluate("window.liveUpdates=[];new MutationObserver(()=>liveUpdates.push(document.querySelector('#operations-state').textContent)).observe(document.querySelector('#operations-state'),{childList:true,subtree:true,characterData:true})")
        phases=[('store',lambda:outcome['convergence'].update(store='converged')),
                ('index',lambda:outcome['convergence'].update(index='converged')),
                ('links',lambda:outcome['convergence'].update(link='converged')),
                ('receipt status',lambda:outcome['receipt'].update(status='failed')),
                ('receipt identity',lambda:outcome['receipt'].update(receipt_id='native-new',status='committed')),
                ('recovery action',lambda:outcome.update(recovery={'action':'inspect_receipt','instructions':'Inspect native receipt'})),
                ('recovery instructions',lambda:outcome['recovery'].update(instructions='Verify through runtime')),
                ('recovery action',lambda:outcome.update(recovery=None)),
                ('cancellation requested: true',lambda:snapshot.update(cancel_requested=True)),
                ('admission: refused',lambda:snapshot.update(current_admission='refused'))]
        for fact,change in phases:
            before=len(page.evaluate('liveUpdates'));change()
            if not pending:page.locator('#operations-inspect').click()
            page.wait_for_function("n=>window.liveUpdates.length>n",arg=before)
            live=page.locator('#operations-state').text_content()
            assert fact in live
            assert len(page.evaluate('liveUpdates'))==before+1
            page.locator('#operations-inspect').click();page.wait_for_timeout(50)
            assert len(page.evaluate('liveUpdates'))==before+1
        evidence(page,'named-phases-'+str(pending),external,errors)
        assert not transport['execute'] and not transport['cancel']
        assert errors==[] and external==[]


def test_explicit_scope_reset_does_not_reimport_an_old_history_reference(tmp_path,monkeypatch):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        reads=[]
        def unavailable(route):
            reads.append(route.request.url);route.fulfill(status=503,json={'detail':'unavailable'})
        page.route('**/api/operations/batches/retained-history*',unavailable)
        page.goto(page.url+'?operation_request=retained-history&operation_digest='+'f'*64)
        page.get_by_test_id('operations-open').click()
        page.get_by_text('Current readback unavailable;',exact=False).wait_for()
        page.locator('#operations-new').click()
        page.locator('#operations-resources input[type=checkbox]:enabled').first.wait_for()
        page.keyboard.press('Escape');page.get_by_test_id('operations-workspace').wait_for(state='hidden');page.wait_for_timeout(80)
        page.get_by_test_id('operations-open').click()
        page.locator('#operations-resources input[type=checkbox]:enabled').first.wait_for()
        assert 'operation_request' not in parse_qs(urlparse(page.url).query)
        page.go_back();page.get_by_test_id('operations-workspace').wait_for(state='hidden')
        page.go_forward();page.get_by_test_id('operations-workspace').wait_for(state='visible')
        assert 'operation_request' not in parse_qs(urlparse(page.url).query)
        assert page.locator('#operations-results').is_hidden()
        assert len(reads)==1
        assert errors==[] and external==[]


@pytest.mark.parametrize('old_read',['preconditions','list','capabilities'])
def test_reference_replacement_invalidates_old_preparation_and_discovery(tmp_path,monkeypatch,old_read):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page)
        choose(page)
        held=[]
        route_url='**/api/operations'+('/'+old_read if old_read!='list' else '')
        def hold(route):
            if old_read=='list' and route.request.post_data_json.get('operation_id')!='artifact.list':route.fallback();return
            response=route.fetch();held.append((route,response.json()))
        page.route(route_url,hold)
        page.locator('#operations-'+{'preconditions':'preview','list':'list','capabilities':'discover'}[old_read]).click()
        # The real gateway/native read can finish after the route event itself.
        for _ in range(100):
            page.wait_for_timeout(20)
            if held:break
        assert len(held)==1
        page.route('**/api/operations/batches/retained-B*',lambda route:route.fulfill(json=retained_snapshot(state='succeeded')|{'batch_id':'retained-B'}))
        page.get_by_text('Reopen an operation after interruption',exact=True).click()
        page.locator('#operations-reference').fill('retained-B');page.locator('#operations-digest').fill('b'*64)
        page.locator('#operations-reopen').click()
        page.get_by_text('Runtime status: succeeded',exact=True).wait_for()
        state=page.locator('#operations-state').text_content()
        assert page.locator('#operations-preview-region').is_hidden()
        assert page.locator('#operations-confirm').is_disabled()
        held[0][0].fulfill(json=held[0][1]);page.wait_for_timeout(80)
        assert page.locator('#operations-preview-region').is_hidden()
        assert page.locator('#operations-confirm').is_disabled()
        assert page.locator('#operations-selection').get_attribute('disabled') is not None
        assert page.locator('#operations-state').text_content()==state
        assert parse_qs(urlparse(page.url).query)['operation_request']==['retained-B']
        assert not [c for c in client.calls if c[1].endswith('/execute')]
        assert host.note.read_text().endswith('Original.\n')
        assert errors==[] and external==[]


@pytest.mark.parametrize('completion',['read','execute','cancel'])
def test_async_completion_respects_topmost_focus_and_closed_observer(tmp_path,monkeypatch,completion):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page)
        transport=install_retained_transport(page,retained_snapshot())
        held=[]
        page.route('**/api/operations/batches/retained-*',lambda route:held.append(route))
        if completion=='read':
            page.locator('#operations-inspect').click();page.wait_for_timeout(40)
        else:
            with page.expect_request('**/retained-A/'+completion):
                page.locator('#operations-'+('resume' if completion=='execute' else 'cancel')).click()
            page.wait_for_timeout(40)
        # Real shared overlay/frame, including a focusable invoker-independent close control.
        page.evaluate("overlayHost.mount('receipts');document.querySelector('#receipts-history-modal button').focus()")
        focus=page.evaluate('document.activeElement.outerHTML')
        if completion=='read':held[0].fulfill(json=retained_snapshot(state='succeeded'))
        else:transport[completion][0].fulfill(json=retained_snapshot(state='succeeded'))
        page.wait_for_timeout(80)
        assert page.evaluate('overlayHost.topmost()')=='receipts'
        assert page.evaluate('document.activeElement.outerHTML')==focus
        page.keyboard.press('Escape');page.wait_for_timeout(80)
        assert page.evaluate('overlayHost.topmost()')=='operations'
        # An obsolete read finishing after close must not repaint or recreate its observer.
        page.locator('#operations-inspect').click();page.wait_for_timeout(40)
        count=len(held)
        page.keyboard.press('Escape');page.get_by_test_id('operations-workspace').wait_for(state='hidden');page.wait_for_timeout(80)
        held[-1].fulfill(json=retained_snapshot())
        page.wait_for_timeout(1200)
        assert len(held)==count
        assert page.get_by_test_id('operations-workspace').is_hidden()
        assert errors==[] and external==[]


def test_retained_reference_replaces_an_unconfirmed_preview_without_dead_controls(tmp_path,monkeypatch):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page);choose(page)
        page.locator('#operations-preview').click();page.locator('#operations-confirm:enabled').wait_for()
        held=[]
        page.route('**/api/operations/batches/retained-B*',lambda route:held.append(route))
        page.get_by_text('Reopen an operation after interruption',exact=True).click()
        page.locator('#operations-reference').fill('retained-B');page.locator('#operations-digest').fill('b'*64)
        page.locator('#operations-reopen').click();page.wait_for_timeout(50)
        assert page.locator('#operations-preview-region').is_hidden() and page.locator('#operations-confirm').is_disabled()
        assert page.locator('#operations-selection').get_attribute('disabled') is not None
        page.evaluate("document.querySelector('#operations-back').onclick();document.querySelector('#operations-confirm').onclick()")
        page.wait_for_timeout(40)
        assert page.locator('#operations-selection').get_attribute('disabled') is not None
        assert len(held)==1
        held[0].fulfill(status=503,json={'detail':'unavailable'})
        page.get_by_text('Current readback unavailable;',exact=False).wait_for()
        assert page.locator('#operations-results').evaluate('(e)=>e===document.activeElement')
        assert host.note.read_text().endswith('Original.\n')
        assert not [c for c in client.calls if c[1].endswith('/execute') or c[1]=='/api/operations' and c[2]['operation_id']=='artifact.update']
        assert errors==[] and external==[]


def test_superseded_read_finally_and_removed_disclosure_preserve_current_ownership(tmp_path,monkeypatch):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page);install_retained_transport(page,retained_snapshot())
        summary=page.locator('section[aria-label="Result target-A"] details').last.locator('summary')
        summary.click()
        held=[]
        page.route('**/api/operations/batches/retained-*',lambda route:held.append(route))
        # Invoke the existing explicit control without changing the focused disclosure.
        page.evaluate("document.querySelector('#operations-inspect').onclick()")
        page.wait_for_timeout(40)
        page.evaluate("document.querySelector('#operations-inspect').onclick()")
        page.wait_for_timeout(40)
        assert len(held)==2
        held[0].abort();page.wait_for_timeout(1200)
        assert len(held)==2
        latest=retained_snapshot(state='succeeded');latest['items']=latest['items'][1:]
        held[1].fulfill(json=latest)
        page.get_by_text('Runtime status: succeeded',exact=True).wait_for()
        assert page.locator('#operations-results').evaluate('(e)=>e===document.activeElement')
        assert page.locator('section[aria-label="Result target-A"]').count()==0
        assert errors==[] and external==[]


def test_successful_resume_with_unchanged_nonpending_result_settles_live_status_once(tmp_path,monkeypatch):
    host=production_operation_host(tmp_path,monkeypatch)
    with browser(host) as (page,client,external,errors):
        open_workspace(page)
        transport=install_retained_transport(page,retained_snapshot())
        recovery=retained_snapshot()
        recovery.update(status='recovery_required',counts={'pending':0,'recoverable':1})
        recovery['items'][1].update(state='recoverable',outcome={'request_id':'receipt-B','status':'recovery_required',
            'operation_id':'artifact.update','recovery':{'action':'inspect_receipt','instructions':'Inspect retained native evidence'},
            'convergence':{'source_effect':'unknown','store':'pending'}})
        transport['snapshot']=recovery
        page.locator('#operations-inspect').click()
        page.get_by_text('Runtime status: recovery_required',exact=True).wait_for()
        reads=transport['reads']
        with page.expect_request('**/retained-A/execute'):page.locator('#operations-resume').click()
        page.wait_for_timeout(40)
        assert 'Awaiting owner receipt' in page.locator('#operations-state').text_content()
        summary=page.locator('section[aria-label="Result target-A"] details').last.locator('summary')
        summary.click()
        page.evaluate("window.liveUpdates=[];new MutationObserver(()=>liveUpdates.push(document.querySelector('#operations-state').textContent)).observe(document.querySelector('#operations-state'),{childList:true,subtree:true,characterData:true})")
        transport['execute'][0].fulfill(json=recovery)
        page.locator('#operations-new:enabled').wait_for()
        assert page.locator('#operations-state').text_content().startswith('Operation recovery_required')
        assert len(page.evaluate('liveUpdates'))==1
        assert summary.evaluate('(e)=>e===document.activeElement && e.parentElement.open')
        assert transport['reads']==reads, 'Nonpending ACK requires no invented observer or retry'
        for _ in range(2):
            page.locator('#operations-inspect').click();page.wait_for_timeout(50)
            assert len(page.evaluate('liveUpdates'))==1
            assert summary.evaluate('(e)=>e.parentElement.open')
        assert len(transport['execute'])==1 and not transport['cancel']
        evidence(page,'unchanged-nonpending-settlement',external,errors)
        page.locator('#operations-new').click()
        page.locator('#operations-resources input[type=checkbox]:enabled').first.wait_for()
        assert 'operation_request' not in parse_qs(urlparse(page.url).query)
        assert errors==[] and external==[]
