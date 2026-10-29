"""Capability-derived wire contracts and real external SDK compatibility."""
from __future__ import annotations

import json

import jsonschema
import pytest

from app.api.operation_schemas import OperationCommand, operation_transport_schemas
from tests._production_operation_harness import production_operation_host
from tests.operations._surface_harness import ExternalMcpClient, SIDECAR, runtime_http

pytestmark = pytest.mark.usefixtures("product_model_access_gateway")


@pytest.fixture(autouse=True)
def sidecar_source_path(monkeypatch):
    monkeypatch.syspath_prepend(str(SIDECAR))


def test_v2_tools_are_capability_derived_and_exclude_raw_filesystem_write(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    observed = host.client.get('/api/operations/capabilities', headers=host.headers)
    assert observed.status_code == 200, observed.text
    discovery = observed.json()
    capabilities = {item['resource_id']: item['payload'] for item in discovery['items']}
    assert discovery['extensions']['transport_schemas'] == operation_transport_schemas()
    command_schema = OperationCommand.model_json_schema()
    for kind, capability in capabilities.items():
        jsonschema.Draft202012Validator.check_schema(capability['input_schema'])
        assert capability['operation_version'] == 'ygg.operation.v1'
        if kind not in {'operation.batch', 'operation.discovery'}:
            assert capability['input_schema']['properties']['arguments'] == command_schema['properties']['arguments']
            assert capability['input_schema']['properties']['operation_id'] == {'type': 'string', 'const': kind}
    with runtime_http(host) as (url, calls, _), ExternalMcpClient(url, host.headers) as client:
        tools = {tool.name: tool for tool in client.tools()}
        supported = {kind for kind, cap in capabilities.items() if cap['support'] == 'supported'}
        assert supported >= {'artifact.list', 'artifact.read', 'artifact.search', 'artifact.related',
                             'artifact.capture', 'artifact.update', 'artifact.move', 'artifact.rename', 'operation.batch'}
        for kind in supported - {'operation.batch'}:
            tool = tools['mimer.v2.' + kind]
            assert tool.inputSchema == capabilities[kind]['input_schema']
            assert tool.meta['authority_class'] == capabilities[kind]['authority_class']
            assert tool.meta['maturity'] == 'active'
        for kind, cap in capabilities.items():
            if cap['support'] != 'supported':
                assert 'mimer.v2.' + kind not in tools
        assert {'mimer.v2.batch.preview', 'mimer.v2.batch.inspect', 'mimer.v2.batch.execute',
                'mimer.v2.batch.cancel', 'mimer.v2.operation.preconditions', 'mimer.v2.operation.receipt'} <= tools.keys()
        before = list(calls)
        refused = client.call('mimer.v2.vault.write', {'path': 'Notes/human.md', 'body': 'forbidden'})
        assert refused.isError
        assert all(path.startswith('/api/operations') for _, path in calls)
        assert not any(method == 'POST' for method, _ in calls[len(before):])
        assert host.note.read_text().endswith('Original.\n')


def test_v1_compatibility_and_v2_operation_parity(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    from mimer_mcp_sidecar.semantic import MimerMcpServer
    expected = [tool.as_dict() for tool in MimerMcpServer.for_loopback().list_tools()]
    with runtime_http(host) as (url, calls, _):
        with ExternalMcpClient(url, host.headers, profile='v1') as v1:
            assert [tool.model_dump(exclude_none=True) for tool in v1.tools()] == expected
            health = v1.call('mimer.health')
            assert not health.isError and isinstance(json.loads(health.content[0].text)['result'], dict)
            assert v1.call('mimer.v2.operation.receipt', {'request_id': 'anything'}).isError
        with ExternalMcpClient(url, host.headers) as v2:
            command = host.command('artifact.capture', request_id='v2-compatible-capture', targets=[],
                                   arguments={'text': 'Captured exactly once through the native owner.'}, expected_version=None)
            result = v2.payload('mimer.v2.artifact.capture', command)
            assert result['convergence']['source_effect'] == 'committed'
            assert result['receipt']['extensions']['write']['source_receipt']['operation'] == 'append_note'
            assert v2.payload('mimer.v2.operation.receipt', {'request_id': command['request_id']}) == result
        assert calls.count(('POST', '/api/operations')) == 1
        captured = ''.join(note.read_text() for note in host.root.rglob('*.md'))
        assert captured.count('Captured exactly once through the native owner.') == 1


@pytest.mark.parametrize('case', ['missing', 'unknown', 'wrong-instance', 'wrong-principal', 'expired', 'override', 'empty-override', 'read-only', 'injection'])
def test_v2_request_metadata_never_supplies_host_authority(tmp_path, monkeypatch, case):
    host = production_operation_host(tmp_path, monkeypatch)
    original = host.note.read_bytes()
    with runtime_http(host) as (url, calls, _), ExternalMcpClient(url, host.headers) as client:
        command = host.command(request_id='metadata-refusal')
        if case == 'missing':
            client.meta = {}
        elif case == 'unknown':
            client.meta = {'mimer/active-context-session': 'not-a-selection'}
        elif case in {'wrong-instance', 'wrong-principal'}:
            from app.api.routes.active_context_selection import get_selection_store
            store = get_selection_store()
            record = next(iter(store._records.values()))
            from dataclasses import replace
            store._records[host.headers['X-Active-Context-Session']] = (replace(record, instance_identity='another-instance')
                if case == 'wrong-instance' else replace(record, principal=replace(record.principal, principal_id='another-principal')))
        elif case == 'expired':
            from app.api.routes.active_context_selection import get_selection_store
            monkeypatch.setattr(get_selection_store(), '_clock', lambda: 4102444800)
        elif case in {'override', 'empty-override'}:
            client.meta['mimer/active-context-override'] = 'stale-override' if case == 'override' else ''
        elif case == 'read-only':
            # The MVR-05B snapshot/context identity is not its raw WSP bearer
            # and cannot authorize a governed effect.
            client.meta = {'mimer/active-context-session': host.selection['context']['context_id']}
        else:
            command['arguments']['delegation'] = {'authority_class': 'governed_effect'}
        result = client.call('mimer.v2.artifact.update', command)
        assert result.isError
        assert host.note.read_bytes() == original
        if case != 'injection':
            assert not any(method == 'POST' for method, _ in calls)


def test_v2_incomplete_native_schema_is_a_typed_refusal_before_dispatch(tmp_path, monkeypatch):
    from copy import deepcopy
    import httpx
    from mimer_mcp_sidecar.v2 import MimerMcpV2Server
    host = production_operation_host(tmp_path, monkeypatch)
    payload = deepcopy(host.client.get('/api/operations/capabilities', headers=host.headers).json())
    del payload['extensions']['transport_schemas']['preconditions']
    calls = []
    def transport(request):
        calls.append(request.method)
        assert request.method == 'GET'
        return httpx.Response(200, json=payload)
    server = MimerMcpV2Server(httpx.Client(base_url='http://127.0.0.1', transport=httpx.MockTransport(transport)))
    assert [tool.name for tool in server.list_tools()] == ['mimer.v2.operation.discovery']
    result = server.call_tool('mimer.v2.artifact.update', host.command())
    assert result.is_error and result.error['error'] == 'operation_discovery_contract_incomplete'
    assert calls == ['GET', 'GET']
    assert host.note.read_text().endswith('Original.\n')


def test_v2_carriers_are_request_scoped_and_forged_headers_never_reach_native_identity(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    with runtime_http(host) as (url, calls, _), ExternalMcpClient(url, host.headers) as client:
        client.meta.update({"X-API-Key": "forged", "X-Forwarded-For": "203.0.113.7",
            "principal": "human", "mimer/identity": "forged"})
        first = client.payload('mimer.v2.operation.discovery')
        assert first['status'] == 'succeeded'
        assert host.headers['X-Active-Context-Session'] not in str(first)
        client.meta = {}
        second = client.call('mimer.v2.operation.discovery')
        assert second.isError and '401' in second.content[0].text
        assert not any(method == 'POST' for method, _ in calls)


@pytest.mark.parametrize('reference', ['colon:1', '.', '..', 'safe.dot'])
def test_v2_receipt_identifiers_remain_opaque_path_segments(tmp_path, monkeypatch, reference):
    host = production_operation_host(tmp_path, monkeypatch)
    with runtime_http(host) as (url, calls, _), ExternalMcpClient(url, host.headers) as client:
        outcome = client.payload('mimer.v2.artifact.update', host.command(request_id=reference))
        assert client.payload('mimer.v2.operation.receipt', {'request_id': reference}) == outcome
        assert all(path.startswith('/api/operations') for _, path in calls)


def test_v2_sdk_validation_http_errors_and_debug_logs_do_not_expose_carriers(tmp_path, monkeypatch):
    import os
    from pathlib import Path
    import subprocess
    import sys
    from tests.mcp.test_mimer_server_transport import _notify, _request
    host = production_operation_host(tmp_path, monkeypatch)
    session = host.headers['X-Active-Context-Session']
    override = 'synthetic-private-override-marker'
    sidecar = Path(__file__).resolve().parents[2] / 'mimer-mcp-sidecar'
    with runtime_http(host) as (url, _, _):
        process = subprocess.Popen([sys.executable, '-c',
            'import logging; logging.basicConfig(level=logging.DEBUG); '
            'from mimer_mcp_sidecar.transport import main; raise SystemExit(main())',
            '--profile', 'v2', '--base-url', url], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env={**os.environ, 'PYTHONPATH': str(sidecar)})
        outputs = []
        try:
            outputs.append(_request(process, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                'params': {'protocolVersion': '2025-11-25', 'capabilities': {},
                    'clientInfo': {'name': 'carrier-privacy', 'version': '1'}}}))
            _notify(process, {'jsonrpc': '2.0', 'method': 'notifications/initialized'})
            # Real SDK validation before the tool handler must not log metadata.
            outputs.append(_request(process, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                'params': {'name': 7, '_meta': {'mimer/active-context-session': session,
                                             'mimer/active-context-override': override}}}))
            assert outputs[-1]['error']['code'] == -32602
            # Native HTTP rejection and adapter header validation are also opaque.
            for index, value in enumerate((override, override + '\n'), start=3):
                outputs.append(_request(process, {'jsonrpc': '2.0', 'id': index, 'method': 'tools/call',
                    'params': {'name': 'mimer.v2.operation.discovery', 'arguments': {},
                        '_meta': {'mimer/active-context-session': session,
                                  'mimer/active-context-override': value}}}))
                assert outputs[-1]['result']['isError']
            process.stdin.close()
            process.wait(10)
            diagnostics = process.stderr.read()
            assert process.returncode == 0
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(10)
        for value in (session, override):
            assert value not in diagnostics and value not in json.dumps(outputs)
