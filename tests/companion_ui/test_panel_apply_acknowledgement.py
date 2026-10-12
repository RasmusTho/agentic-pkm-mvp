"""Actual proxy/JS boundary proof; synthetic acknowledgements are not live acceptance."""
from __future__ import annotations

from copy import deepcopy
import io
import json
import subprocess
from urllib.parse import unquote
import xml.etree.ElementTree as ET

import pytest

from companion_ui.workspace.serve_dev_page import _panel_apply_script, _render_panel_confirm_response, make_handler


HEADER = "X-Companion-Panel-Confirmation"


def _ack(proposal: str = "proposal-1", status: str = "executed") -> dict:
    return {"proposal_id": proposal, "artifact_id": "synthetic-artifact", "status": status,
            "outcome": "success" if status == "executed" else status,
            "idempotency_key": "key-" + proposal[-1],
            "receipt": {"receipt_id": "receipt-" + proposal, "outcome": "success" if status == "executed" else status,
                        "timestamp": "2026-10-12T00:00:00Z"} if status in {"executed", "logged"} else None}


def _proxy_reply(ack: dict, *, request: dict | None = None) -> dict:
    payload = request or {"proposal_id": ack["proposal_id"], "artifact_id": ack["artifact_id"],
                          "action": "confirm", "idempotency_key": ack["idempotency_key"]}
    calls = []

    class Client:
        def post(self, path, **kwargs):
            calls.append((path, kwargs))
            return ack

    handler_class = make_handler(client=Client(), api_base_url="http://127.0.0.1:18002")
    handler = handler_class.__new__(handler_class)
    raw = json.dumps(payload).encode()
    handler.path = "/api/panel/confirm"
    handler.headers = {"Content-Length": str(len(raw))}
    handler.rfile = io.BytesIO(raw)
    handler.wfile = io.BytesIO()
    headers = {}
    status = []
    handler.send_response = status.append
    handler.send_header = headers.__setitem__
    handler.end_headers = lambda: None
    handler.do_POST()
    assert status == [200] and calls == [("/api/panel/confirm", {"json": payload})]
    assert handler.wfile.getvalue() == json.dumps(ack).encode(), "native-observed JSON bytes changed"
    return {"ack": ack, "header": headers.get(HEADER)}


def _consume(replies: list[dict], *, latest: dict | None = None, repeat: bool = False, base_url: str | None = None) -> dict:
    fragments = [_render_panel_confirm_response(row["ack"]) for row in replies]
    latest_html = _render_panel_confirm_response(latest or replies[-1]["ack"])
    documents = {}
    for html in fragments + [latest_html] + [unquote(r["header"]) for r in replies if r["header"]]:
        try:
            root = ET.fromstring(html)
        except ET.ParseError:
            continue
        documents[html] = [{"attrs": e.attrib} for e in root.iter()]
    data = {"replies": replies, "latest": latest_html, "documents": documents, "repeat": repeat, "base_url": base_url}
    script = _panel_apply_script().removeprefix("\n  <script>").removesuffix("\n  </script>")
    setup = "const input=" + json.dumps(data) + ";" + r"""
const calls=[]; let key=0;
function matches(attrs, selector) {
 return selector.split(',').some(part => {
  const attrsWanted=[...part.matchAll(/\[([^=\]]+)(?:="([^"]*)")?\]/g)];
  return attrsWanted.length && attrsWanted.every(m => m[2]===undefined ? m[1] in attrs : attrs[m[1]]===m[2]); });
}
function node(html, index) {
 const spec=input.documents[html][index];
 return {html,getAttribute:n=>spec.attrs[n]??null,
  querySelector:s=>input.documents[html].map((x,i)=>({x,i})).filter(v=>v.i!==index&&matches(v.x.attrs,s)).map(v=>node(html,v.i))[0]||null,
  querySelectorAll:s=>input.documents[html].map((x,i)=>({x,i})).filter(v=>v.i!==index&&matches(v.x.attrs,s)).map(v=>node(html,v.i))};
}
global.DOMParser=class {parseFromString(html) {
 return {querySelector:s=>input.documents[html].map((x,i)=>({x,i})).filter(v=>matches(v.x.attrs,s)).map(v=>node(html,v.i))[0]||null,
 querySelectorAll:s=>input.documents[html].map((x,i)=>({x,i})).filter(v=>matches(v.x.attrs,s)).map(v=>node(html,v.i))}; }};
const surfaces={rail:{},palette:{}};
const rows=input.replies.flatMap(reply=>['rail','palette'].map(surface=> {
 const attrs={'data-proposal-id':reply.ack.proposal_id,'data-artifact-id':reply.ack.artifact_id,
 'data-panel-action':'confirm','data-api-path':'/api/panel/confirm'};
 const row={id:reply.ack.proposal_id,surface,html:null,status:null,
 getAttribute:n=>n==='data-proposal-id'?row.id:null,querySelector:()=>row.status,closest:()=>surfaces[surface],
 querySelectorAll:()=>[row.button],appendChild:e=>{row.status=e;},replaceWith:n=>{row.html=n.html;}};
 row.button={getAttribute:n=>attrs[n]??null,setAttribute:(n,v)=>{attrs[n]=v;},
 removeAttribute:n=>{delete attrs[n];},closest:()=>row};row.attrs=attrs;return row;
}));
const rail={scrollTop:7};
global.window={crypto:{randomUUID:()=> 'key-'+(++key)}};
global.document={getElementById:()=>({getAttribute:()=> 'note.md'}),querySelector:()=>rail,
 querySelectorAll:s=>s.includes('workspace-panel-confirm-response')?rows.filter(r=>r.html):rows.filter(r=>!r.html),
 importNode:n=>n,addEventListener:()=>{},
 createElement:()=>({setAttribute:()=>{},textContent:''})};
const realFetch=global.fetch;
global.fetch=async(path,options)=> {
 calls.push({path,options});
 if(input.base_url) return realFetch(input.base_url+path,options);
 if(options.method==='POST') {
  const body=JSON.parse(options.body),reply=input.replies.find(r=>r.ack.proposal_id===body.proposal_id);
  if(reply.network) throw new Error('private unknown transport');
  return {ok:reply.ok!==false,headers:{get:()=>reply.header},json:async()=>reply.ack};
 }
 return {ok:true,text:async()=>input.latest};
};
"""
    finish = r"""
(async()=>{
 await Promise.all(rows.filter(r=>r.surface==='rail').map(r=>window.panelActions.submit(r.button)));
 if(input.repeat) await window.panelActions.submit(rows.find(r=>r.surface==='palette').button);
 console.log(JSON.stringify({calls,rows:rows.map(r=>({id:r.id,surface:r.surface,html:r.html,
  disabled:r.attrs['aria-disabled'],state:r.attrs['data-action-state'],copy:r.status&&r.status.textContent})),scroll:rail.scrollTop}));
})();"""
    p = subprocess.run(["node", "-e", setup + script + finish], check=True, capture_output=True, text=True, timeout=10)
    return json.loads(p.stdout)


@pytest.mark.parametrize("status", ["executed", "logged", "blocked", "rejected"])
def test_proxy_keeps_ack_bytes_and_binds_server_fragment(status: str) -> None:
    ack = _ack(status=status)
    reply = _proxy_reply(ack)
    assert reply["header"] and reply["header"].isascii()
    html = unquote(reply["header"])
    root = ET.fromstring(html)
    assert root.get("data-proposal-id") == ack["proposal_id"]
    assert root.get("data-artifact-id") == ack["artifact_id"]
    assert root.get("data-idempotency-key") == ack["idempotency_key"]
    assert ('data-receipt-state="applied"' in html) is (status == "executed")


def test_concurrent_same_artifact_apply_retains_each_own_post_fragment() -> None:
    replies = [_proxy_reply(_ack("proposal-1")), _proxy_reply(_ack("proposal-2", "logged"))]
    observed = _consume(replies)
    for row in observed["rows"]:
        ack = next(r["ack"] for r in replies if r["ack"]["proposal_id"] == row["id"])
        assert row["html"] == _render_panel_confirm_response(ack)
    assert sum(c["options"]["method"] == "POST" for c in observed["calls"]) == 2
    assert observed["scroll"] == 7


@pytest.mark.parametrize("fault", ["missing", "malformed", "oversized", "wrong_proposal", "wrong_artifact", "wrong_key", "wrong_receipt", "unknown_status", "unknown_ack_status", "receipt_error", "network"])
def test_unacknowledged_apply_stays_held_across_clones_without_second_contact(fault: str) -> None:
    ack = _ack()
    reply = _proxy_reply(ack)
    if fault == "wrong_receipt":
        bad = deepcopy(ack)
        bad["receipt"]["receipt_id"] = "another-receipt"
        reply["header"] = _proxy_reply(bad)["header"]
    elif fault == "unknown_ack_status":
        reply["ack"] = {**ack, "status": "unexpected"}
    elif fault in {"wrong_proposal", "wrong_artifact", "wrong_key", "unknown_status"}:
        bad = deepcopy(ack)
        field = {"wrong_proposal": "proposal_id", "wrong_artifact": "artifact_id", "wrong_key": "idempotency_key", "unknown_status": "status"}[fault]
        bad[field] = "unexpected"
        reply = {"ack": ack, "header": _proxy_reply(bad)["header"]}
    elif fault == "missing":
        reply["header"] = None
    elif fault == "malformed":
        reply["header"] = "%not-valid"
    elif fault == "oversized":
        reply["header"] = "a" * 8193
    elif fault == "receipt_error":
        reply["ok"] = False
        reply["ack"] = {**ack, "detail": {"error": "authority_receipt_persistence_failed", "state": "not_acknowledged"}}
    else:
        reply["network"] = True
    observed = _consume([reply], repeat=True)
    assert sum(c["options"]["method"] == "POST" for c in observed["calls"]) == 1
    assert all(row["disabled"] == "true" for row in observed["rows"])
    assert all(row["html"] is None for row in observed["rows"])
    assert not any(c["options"]["method"] == "GET" for c in observed["calls"])


def test_missing_proposal_time_is_not_fabricated_from_render_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    from companion_ui.workspace import serve_dev_page

    class ForbiddenClock:
        @classmethod
        def now(cls):
            raise AssertionError("render clock fabricated proposal freshness")

    monkeypatch.setattr(serve_dev_page, "datetime", ForbiddenClock)
    html = serve_dev_page._render_panel_proposal_rows([{
        "proposal_id": "proposal-1", "artifact_id": "art-1137", "status": "staged",
        "description": "Synthetic", "affordances": {"confirm": True},
    }], writeguard_blocked=False)
    assert 'data-testid="workspace-panel-provenance"' in html


def test_presentation_is_bounded_escaped_and_never_changes_ack_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    from companion_ui.workspace import serve_dev_page

    ack = _ack(status="logged")
    ack["receipt"]["message"] = '<script>private</script> · "quoted"'
    header = _proxy_reply(ack)["header"]
    assert header.isascii() and len(header) <= 8192
    html = unquote(header)
    assert "<script>" not in html and "&lt;script&gt;" in html
    ack["receipt"]["message"] = "x" * 9000
    assert _proxy_reply(ack)["header"] is None

    def unavailable(_):
        raise RuntimeError("presentation failed after acknowledgement")

    monkeypatch.setattr(serve_dev_page, "_render_panel_confirm_response", unavailable)
    assert _proxy_reply(_ack())["header"] is None


@pytest.mark.parametrize("status", [[], {}])
def test_unhashable_optional_status_preserves_proxy_ack_and_holds_ui(status) -> None:
    """The confirmed malformed shape cannot withhold an already returned ack."""
    ack = _ack(status="blocked")
    ack["status"] = status
    reply = _proxy_reply(ack)
    assert reply["header"] is None
    observed = _consume([reply], repeat=True)
    assert sum(c["options"]["method"] == "POST" for c in observed["calls"]) == 1
    assert all(row["disabled"] == "true" and row["html"] is None for row in observed["rows"])
