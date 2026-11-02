"""One owner-native corpus through direct, HTTP, Companion and external MCP."""
from __future__ import annotations

from contextlib import ExitStack
import os
from urllib.parse import quote

import pytest

from tests._production_batch_harness import batch_command, production_batch_host
from tests.operations import _surface_harness
from tests.operations._surface_harness import ExternalMcpClient, SurfaceCalls, companion_http, direct, runtime_http

pytestmark = pytest.mark.usefixtures('product_model_access_gateway')


def _command(host, kind, request_id, arguments=None, targets=None):
    return dict(operation_id=kind, request_id=request_id,
        active_context_ref=host.selection['context']['context_id'],
        vault_generation=str(host.selection['context']['generation']),
        target_binding_id=host.binding_id,
        targets=[{'artifact_id': host.artifact_id}] if targets is None else targets,
        arguments=arguments or {})


def test_cross_surface_watchdog_preserves_request_limit(monkeypatch):
    marks = getattr(test_all_operation_families_share_owner_native_semantics, 'pytestmark', [])
    assert [mark.args for mark in marks if mark.name == 'timeout'] == [(300,)]

    waits = []

    class NeverCompletes:
        def result(self, timeout):
            waits.append(timeout)
            raise TimeoutError('request did not complete')

    monkeypatch.setattr(_surface_harness, 'Future', NeverCompletes)
    client = ExternalMcpClient('http://127.0.0.1', {})
    with pytest.raises(TimeoutError, match='request did not complete'):
        client._request('call', 'example', {})
    assert waits == [30]


@pytest.mark.timeout(300)
@pytest.mark.parametrize('initiator', ['direct', 'http', 'companion', 'mcp'])
def test_all_operation_families_share_owner_native_semantics(tmp_path, monkeypatch, initiator):
    host, sources = production_batch_host(tmp_path, monkeypatch)
    with ExitStack() as stack:
        url, _, _ = stack.enter_context(runtime_http(host))
        mcp = stack.enter_context(ExternalMcpClient(url, host.headers))
        companion, _ = stack.enter_context(companion_http(host))

        def invoke(surface, command):
            if surface == 'direct':
                return direct(host, command)
            if surface == 'mcp':
                return mcp.payload('mimer.v2.' + command['operation_id'], command)
            response = (host.client.post('/api/operations', headers=host.headers, json=command)
                        if surface == 'http' else companion.post('/api/operations', json=command))
            assert response.status_code == 200, response.text
            return response.json()

        for kind, args, targets in [
            ('artifact.list', {}, []), ('artifact.read', {}, None),
            ('artifact.search', {'query': 'Original'}, []), ('artifact.related', {}, None),
            ('artifact.create', {}, []), ('artifact.classify', {}, None),
            ('artifact.tags.add', {}, None), ('artifact.tags.remove', {}, None),
            ('collection.reorder', {}, None), ('artifact.archive', {}, None), ('artifact.restore', {}, None),
        ]:
            command = _command(host, kind, 'corpus-' + kind, args, targets)
            observed = [invoke(surface, command) for surface in ('direct', 'http', 'companion', 'mcp')]
            assert all(result == observed[0] for result in observed[1:]), kind
            if kind in {'artifact.list', 'artifact.read', 'artifact.related'}:
                assert observed[0]['status'] == 'succeeded', observed[0]
            elif kind not in {'artifact.search'}:
                assert observed[0]['status'] == 'not_supported', observed[0]

        for kind, args, targets in [
            ('artifact.capture', {'text': 'A shared native capture.'}, []),
            ('artifact.update', {'body': 'A shared native edit.\n'}, None),
            ('artifact.move', {'destination': 'Notes/moved.md'}, None),
            ('artifact.rename', {'name': 'renamed.md'}, None),
        ]:
            command = _command(host, kind, initiator + '-' + kind, args, targets)
            preconditions = mcp.payload('mimer.v2.operation.preconditions', command)
            assert preconditions['status'] == 'observed', preconditions
            command.update(expected_version=preconditions['expected_version'], arguments=preconditions['arguments'])
            result = invoke(initiator, command)
            assert result['status'] == 'convergence_pending', result
            assert result['convergence']['source_effect'] == 'committed'
            assert result['receipt']['status'] == 'committed'
            native = result['receipt']['extensions']
            assert native.get('write', native.get('placement'))
            receipt = {'request_id': command['request_id']}
            assert mcp.payload('mimer.v2.operation.receipt', receipt) == result
            assert host.client.get('/api/operations/receipts/' + command['request_id'], headers=host.headers).json() == result
            assert companion.get('/api/operations/receipts/' + command['request_id']).json() == result
            if kind == 'artifact.move':
                host.note = host.root / 'Notes/moved.md'
            elif kind == 'artifact.rename':
                host.note = host.root / 'Notes/renamed.md'
        assert host.artifact_id in host.note.read_text()
        assert host.note.read_text().endswith('A shared native edit.\n')

        sources[0] = (host.artifact_id, host.note)
        surface = SurfaceCalls(host, companion, mcp, initiator)
        preview = surface.batch('preview', batch_command(host, sources, batch_id='complete-' + initiator))
        assert preview['status'] == 'pending' and preview['cardinality'] == 2
        reference = {'batch_id': preview['batch_id'], 'expected_digest': preview['digest']}
        batch = surface.batch('execute', reference)
        assert batch['status'] == 'convergence_pending' and batch['counts']['completed'] == 2
        for item in batch['items']:
            assert item['outcome']['receipt']['extensions']['write']['authority_receipt']['receipt_id']
        assert mcp.payload('mimer.v2.batch.inspect', reference)['items'] == batch['items']
        assert companion.get('/api/operations/batches/' + reference['batch_id'],
            params={'expected_digest': reference['expected_digest']}).json()['items'] == batch['items']


@pytest.mark.browser_runtime
@pytest.mark.skipif(os.environ.get("COMPANION_UI_BROWSER_TESTS") != "1",
                   reason="Composed human/agent proof executes in the blocking browser lane")
def test_human_and_agent_flows_share_authority_and_recovery_semantics(tmp_path, monkeypatch):
    """A served human write is one original agent-readable native receipt.

    A genuine temporary WSP process-store replacement invalidates both old
    carriers. A fresh native read selection recovers the same durable receipts
    through browser and official SDK, and cannot refresh the frozen write grant.
    """
    from playwright.sync_api import sync_playwright
    from app.api.routes import active_context_selection
    from app.ops.operations_acceptance import file_hash
    from tests.companion_ui.test_live_operations_acceptance import served_journey
    from tests.operations.live_operations_acceptance import OfficialClient
    with served_journey(tmp_path, monkeypatch) as (host, run, calls):
        originals = dict(run.outcomes)
        assert len(originals) == 3
        before = {str(path): file_hash(path) for path in host.root.rglob("*.md")}
        writes = sum(method == 'POST' and path == '/api/operations' for method, path in calls)
        python = run.binding["identity"]["sidecar"]["runtime"]["executable"]
        old = run.bearer
        active_context_selection.reset_selection_store_for_tests()
        assert host.client.get('/api/operations/capabilities', headers=host.headers).status_code == 401
        with OfficialClient(run.api_url, old, python) as sdk:
            assert sdk.call('mimer.v2.operation.discovery').isError
        issued = host.client.post('/api/companion/active-context/selection',
                                  json={'vault_binding_ids': [host.binding_id]})
        assert issued.status_code == 201
        fresh = issued.json()
        assert fresh['context']['principal_id'] == run.binding['principal_id']
        assert fresh['context']['instance_identity'] == run.binding['instance_identity']
        headers = {'X-Active-Context-Session': fresh['context_selection_id']}
        with OfficialClient(run.api_url, fresh['context_selection_id'], python) as sdk:
            for request_id, original in originals.items():
                assert sdk.payload('mimer.v2.operation.receipt', {'request_id': request_id}) == original
                assert host.client.get('/api/operations/receipts/' + quote(request_id, safe=''), headers=headers).json() == original
        request_id = next(iter(originals))
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context()
            context.add_cookies([{'name': 'companion_context_session', 'value': fresh['context_selection_id'],
                'url': run.ui_url, 'httpOnly': True, 'sameSite': 'Strict'}])
            page = context.new_page()
            page.goto(run.ui_url + '/?operation_request=' + quote(request_id, safe=''), wait_until='domcontentloaded')
            page.get_by_test_id('operations-open').click()
            page.get_by_text('Source effect: committed', exact=False).wait_for()
            context.close()
            browser.close()
        command = run.command('lost-ack')
        command.update(active_context_ref=fresh['context']['context_id'], vault_generation=str(fresh['context']['generation']))
        refused = host.client.post('/api/operations', json=command, headers=headers)
        assert refused.status_code == 200 and refused.json()['status'] == 'rejected'
        assert host.client.post('/api/operations', json=command,
            headers={'Principal':'forged','X-API-Key':'forged'}).status_code == 401
        assert writes == sum(method == 'POST' and path == '/api/operations' for method, path in calls)
        assert before == {str(path): file_hash(path) for path in host.root.rglob('*.md')}
