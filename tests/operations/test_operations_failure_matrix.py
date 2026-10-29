"""Native failure/restart truth survives all four operation adapters."""
from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.api.app import _create_app
from app.api.routes import active_context_selection
from app.operations.execution_kernel import JsonReceiptStore
from tests._production_batch_harness import batch_command, production_batch_host
from tests.operations._surface_harness import ExternalMcpClient, SurfaceCalls, companion_http, runtime_http

pytestmark = pytest.mark.usefixtures('product_model_access_gateway')


@pytest.mark.parametrize('initiator', ['direct', 'http', 'companion', 'mcp'])
def test_operations_failure_matrix_is_fail_closed_and_recoverable(tmp_path, monkeypatch, initiator):
    host, sources = production_batch_host(tmp_path, monkeypatch)
    with runtime_http(host) as (url, _, _), ExternalMcpClient(url, host.headers) as mcp, companion_http(host) as (companion, _):
        surface = SurfaceCalls(host, companion, mcp, initiator)
        command = host.command(request_id='stale-' + initiator)
        host.note.write_text(host.note.read_text().replace('Original.', 'Human edit after observation.'))
        before = host.note.read_bytes()
        conflict = surface.operation(command)
        assert conflict['status'] == 'conflicted', conflict
        assert host.note.read_bytes() == before

        lagged = surface.operation(host.command(request_id='lag-' + initiator))
        assert lagged['status'] == 'convergence_pending'
        assert lagged['convergence']['source_effect'] == 'committed'
        assert lagged['convergence']['index'] in {'pending', 'rebuild_required'}
        assert lagged['receipt']['extensions']['write']['authority_receipt']['receipt_id']

        preview = surface.batch('preview', batch_command(host, sources, batch_id='partial-' + initiator))
        assert preview['status'] == 'pending'
        sources[1][1].write_text(sources[1][1].read_text().replace('Original', 'Newer human edit'))
        reference = {'batch_id': preview['batch_id'], 'expected_digest': preview['digest']}
        partial = surface.batch('execute', reference)
        assert partial['status'] == 'partial', partial
        assert partial['counts']['completed'] == 1 and partial['counts']['conflicted'] == 1
        assert partial['items'][0]['outcome']['receipt']['status'] == 'committed'
        assert 'Newer human edit' in sources[1][1].read_text()
        assert mcp.payload('mimer.v2.batch.inspect', reference)['items'] == partial['items']
        assert surface.batch('cancel', reference)['items'] == partial['items']

        finalize = JsonReceiptStore.finalize
        def lost_ack(store, request_id, *args, **kwargs):
            if request_id == 'lost-ack-' + initiator:
                raise ConnectionError('kernel reply lost after durable native receipt')
            return finalize(store, request_id, *args, **kwargs)
        monkeypatch.setattr(JsonReceiptStore, 'finalize', lost_ack)
        request = host.command(request_id='lost-ack-' + initiator, arguments={'body': 'Native committed once.\n'})
        unknown = surface.operation(request)
        assert unknown['status'] == 'recovery_required'
        assert unknown['convergence']['source_effect'] == 'committed'
        assert unknown['extensions']['owner_readback']['effect_receipt_ref']
        after = host.note.read_bytes()
        monkeypatch.setattr(JsonReceiptStore, 'finalize', finalize)
        # A component restart reopens the real durable journal and native owners.
        host.client = TestClient(_create_app())
        observed = mcp.payload('mimer.v2.operation.receipt', {'request_id': request['request_id']})
        assert observed['status'] == 'recovery_required'
        assert host.note.read_bytes() == after
        assert surface.operation(request)['status'] == 'recovery_required'
        assert host.note.read_bytes() == after

        # Full WSP restart invalidates old authority, then a newly selected actor
        # may inspect retained receipts without replaying a consumed effect.
        active_context_selection.reset_selection_store_for_tests()
        host.client = TestClient(_create_app())
        assert mcp.call('mimer.v2.operation.receipt', {'request_id': request['request_id']}).isError
        selection = host.client.post('/api/companion/active-context/selection',
            json={'vault_binding_ids': [host.binding_id]})
        assert selection.status_code == 201
        host.selection = selection.json()
        host.headers = {'X-Active-Context-Session': host.selection['context_selection_id']}
        mcp.meta = {'mimer/active-context-session': host.selection['context_selection_id']}
        readback = mcp.payload('mimer.v2.operation.receipt', {'request_id': request['request_id']})
        assert readback['receipt'] == observed['receipt']
        assert host.note.read_bytes() == after


def test_real_mcp_disconnect_after_write_requires_durable_readback_without_replay(tmp_path, monkeypatch):
    host, _ = production_batch_host(tmp_path, monkeypatch)
    with runtime_http(host) as (url, calls, disconnect):
        with ExternalMcpClient(url, host.headers) as first:
            command = host.command(request_id='external-lost-reply')
            disconnect.append('/api/operations')
            result = first.call('mimer.v2.artifact.update', command)
            assert result.isError
            assert 'operation_not_acknowledged' in result.content[0].text
        after = host.note.read_bytes()
        assert after.endswith(b'Updated body.\n')
        with ExternalMcpClient(url, host.headers) as restarted:
            receipt = restarted.payload('mimer.v2.operation.receipt', {'request_id': command['request_id']})
            assert receipt['status'] == 'convergence_pending'
            assert receipt['receipt']['extensions']['write']['authority_receipt']['receipt_id']
        assert calls.count(('POST', '/api/operations')) == 1
        assert host.note.read_bytes() == after
