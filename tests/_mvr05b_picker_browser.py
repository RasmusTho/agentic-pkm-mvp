"""Run shipped picker JavaScript against the real same-origin gateway and API.

Only the DOM and the API network hop are adapted: requests cross a real UI
HTTP socket, WorkspaceHttpClient, and the production FastAPI route graph.
"""
from __future__ import annotations

from contextlib import contextmanager
from http.server import ThreadingHTTPServer
import json
import shutil
import subprocess
import threading
from urllib.parse import urlparse

import httpx
from fastapi.testclient import TestClient

from app.api.app import app
from companion_ui.workspace.serve_dev_page import make_handler, _render_vault_picker_script
from companion_ui.workspace.scoped_session import scoped_session_script
from companion_ui.workspace.workspace_http_client import WorkspaceHttpClient


@contextmanager
def picker_browser(monkeypatch, *, cookie="", response_filter=None, before_request=None, raise_server_exceptions=False):
    api = TestClient(app, raise_server_exceptions=raise_server_exceptions, client=("127.0.0.1", 40000))
    calls = []

    def request(method, url, **kwargs):
        path = urlparse(url).path
        kwargs.pop("timeout", None)
        calls.append((method, path, dict(kwargs.get("headers") or {}), kwargs.get("json")))
        if before_request is not None:
            before_request(method, path)
        response = api.request(method, path, **kwargs)
        return response_filter(method, path, response) if response_filter is not None else response

    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: request("GET", url, **kwargs))
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: request("POST", url, **kwargs))
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(
        client=WorkspaceHttpClient("http://runtime"), api_base_url="http://runtime",
    ))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    scripts = [scoped_session_script(), _render_vault_picker_script()]
    scripts = [script[script.index('<script>') + 8:script.rindex('</script>')] for script in scripts]
    setup = r'''
const nativeFetch = globalThis.fetch;
var cookie = INITIAL_COOKIE, reloads = 0, clickHandler, reloadResolve, reloadReject, handoffs = [], gatewayResponses = [], lastDocumentHtml = "";
var dropHandoffCookie = false, dropHandoffAck = false;
function storeCookie(raw) {
  var pair=raw.split(';')[0], name=pair.split('=')[0];
  var parts=cookie?cookie.split('; ').filter(item=>item.split('=')[0]!==name):[];
  parts.push(pair);cookie=parts.join('; ');
}
var visible = {hidden:true, textContent:''};
function element() {
  var attrs={}, children=[];
  var el={attrs,children,hidden:false,setAttribute:(k,v)=>attrs[k]=v,getAttribute:k=>attrs[k],removeAttribute:k=>delete attrs[k],appendChild:item=>children.push(item),querySelector:()=>null,querySelectorAll:()=>children};
  Object.defineProperty(el,'innerHTML',{get:()=>el.markup||'',set:value=>{el.markup=value;children.length=0;}});
  return el;
}
var fsMode=element(), fsList=element(), fsError=element(), recentsMode=element();
fsError.hidden=true;
fsMode.querySelector=selector=>selector==='[data-testid="vault-picker-fs-list"]'?fsList:selector==='[data-testid="vault-picker-fs-error"]'?fsError:null;
var picker=element();
picker.querySelector=selector=>selector==='[data-testid="vault-picker-fs-mode"]'?fsMode:selector==='[data-testid="vault-picker-recents-mode"]'?recentsMode:selector==='[data-testid="vault-picker-select-error"]'?visible:selector==='[data-testid="vault-picker-fs-error"]'?fsError:null;
picker.addEventListener=(kind,fn)=>{if(kind==='click')clickHandler=fn;};
globalThis.window = globalThis;
globalThis.location = {href:ORIGIN+'/', origin:ORIGIN, reload:()=>{
  reloads++;
  bootDocument().then(()=>{if(reloadResolve)reloadResolve();}).catch(error=>{if(reloadReject)reloadReject(error);});
}};
globalThis.document = {createElement:element,querySelector:(selector)=>selector==='[data-testid="vault-picker"]'?picker:selector==='[data-testid="vault-picker-select-error"]'?visible:null};
Object.defineProperty(document,'cookie',{
  get:()=>cookie.split('; ').filter(item=>item.split('=')[0]!=='companion_context_session').join('; '),
  set:storeCookie
});
var browserFetch = async function(input, options={}) {
  var headers = new Headers(options.headers||{});
  if(cookie)headers.set('Cookie',cookie);
  var response = await nativeFetch(new URL(input,ORIGIN), Object.assign({}, options,{headers}));
  if(['/api/companion/vault/select','/api/companion/vault/initialize'].includes(new URL(input,ORIGIN).pathname))gatewayResponses.push({status:response.status,body:await response.clone().json()});
  var setCookie = response.headers.get('set-cookie');
  if(setCookie){
    if(!dropHandoffCookie)storeCookie(setCookie);
    handoffs.push({headers:setCookie,digest:response.headers.get('X-Companion-Scoped-Handoff'),body:await response.clone().json()});
  }
  if(dropHandoffAck && response.headers.has('X-Companion-Scoped-Handoff')){
    var altered=new Headers(response.headers);altered.delete('X-Companion-Scoped-Handoff');
    response=new Response(await response.arrayBuffer(),{status:response.status,headers:altered});
  }
  return response;
};
globalThis.fetch=browserFetch;
async function bootDocument(path='/workspace') {
  var response=await browserFetch(path);
  var html=await response.text();
  lastDocumentHtml=html;
  var match=html.match(/<script>\s*\/\* companion-scoped-session[\s\S]*?<\/script>/);
  if(!response.ok || !match)throw new Error('document reload did not contain the production scoped controller');
  // A navigation installs a new document-local closure from the actual server
  // response, including the write proof captured while that page was read.
  globalThis.fetch=browserFetch;
  (0,eval)(match[0].replace(/^<script>/,'').replace(/<\/script>$/,''));
  return html;
}
function button(path) {var attrs={'data-vault-path':path}; return {getAttribute:k=>attrs[k],setAttribute:(k,v)=>attrs[k]=v,removeAttribute:k=>delete attrs[k],attrs};}
// Wait on the controller's own terminal signals, never a wall-clock budget: the
// reload it triggers settles `done`, and leaving its in-flight state without a
// reload (e.g. data-affordance-status=blocked) fails with the controller attrs.
// A real hang is bounded by the Node subprocess timeout.
function untilReloaded(done, el, label) {
  return new Promise((resolve,reject)=>{
    var poll=setInterval(()=>{if(el.attrs['data-submitting']!=='true'){clearInterval(poll);reject(new Error(label+': '+JSON.stringify(el.attrs)));}},10);
    done.then(value=>{clearInterval(poll);resolve(value);},error=>{clearInterval(poll);reject(error);});
  });
}
async function whileAttr(el, name, value) {
  while(el.attrs[name]===value)await new Promise(r=>setTimeout(r,10));
}
async function choose(path) {
  var b=button(path);
  var done=new Promise((resolve,reject)=>{reloadResolve=resolve;reloadReject=reject;});
  clickHandler({target:{closest:selector=>selector==='[data-testid="vault-picker-row-select"]'?b:null}});
  await untilReloaded(done,b,'picker selection failed');
}
async function browseChoose(path) {
  var browse=element();
  clickHandler({preventDefault:()=>{},target:{closest:selector=>selector==='[data-testid="vault-picker-browse"]'?browse:null}});
  await whileAttr(fsMode,'data-loading','true');
  if(fsMode.hidden || !fsError.hidden)throw new Error('picker discovery failed: '+fsError.textContent);
  var row=fsList.children.find(item=>item.attrs['data-fs-path']===path);
  if(!row || row.innerHTML.indexOf('data-testid="vault-picker-fs-open"')===-1)throw new Error('sibling vault action missing: '+path);
  var open=element();open.attrs['data-fs-path']=row.attrs['data-fs-path'];
  var done=new Promise((resolve,reject)=>{reloadResolve=resolve;reloadReject=reject;});
  clickHandler({target:{closest:selector=>selector==='[data-testid="vault-picker-fs-open"]'?open:null}});
  await untilReloaded(done,open,'picker discovered selection failed');
}
async function initialize(path) {
  var b=button(path);
  function click(){clickHandler({target:{closest:selector=>selector==='.vault-picker-initialize-button'?b:null}});}
  // A reload before the confirm round-trip is also terminal, not a wait.
  var reloaded=false;
  new Promise((resolve,reject)=>{reloadResolve=resolve;reloadReject=reject;}).then(()=>reloaded=true,()=>reloaded=true);
  click();
  while(b.attrs['data-submitting']==='true' && !reloaded)await new Promise(r=>setTimeout(r,10));
  if(b.attrs['data-affordance-status']!=='confirm-required')throw new Error('no initialize confirmation: '+JSON.stringify(b.attrs));
  var done=new Promise((resolve,reject)=>{reloadResolve=resolve;reloadReject=reject;});
  click();
  await untilReloaded(done,b,'initialize failed');
}
'''.replace('INITIAL_COOKIE', json.dumps(cookie)).replace('ORIGIN', json.dumps(origin))

    def run(body):
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("Node is required to verify the production picker controller")
        program = setup + '\n' + '\n'.join(scripts) + '\n(async()=>{'+body+'\n})().catch(e=>{console.error(e);process.exitCode=1;});'
        # Hang guard only: the in-program waits are signal-driven, so this bounds a
        # stuck controller rather than budgeting a slow but progressing one.
        result = subprocess.run([node, '-e', program], capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    try:
        yield run, calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        api.close()
