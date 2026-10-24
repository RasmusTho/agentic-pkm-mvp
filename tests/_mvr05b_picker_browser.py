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
def picker_browser(monkeypatch, *, cookie=""):
    api = TestClient(app, raise_server_exceptions=False, client=("127.0.0.1", 40000))
    calls = []

    def request(method, url, **kwargs):
        path = urlparse(url).path
        kwargs.pop("timeout", None)
        calls.append((method, path, dict(kwargs.get("headers") or {}), kwargs.get("json")))
        return api.request(method, path, **kwargs)

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
var cookie = INITIAL_COOKIE, reloads = 0, clickHandler, reloadResolve, handoffs = [];
var visible = {hidden:true, textContent:''};
var picker = {querySelector:()=>null, addEventListener:(kind,fn)=>{if(kind==='click')clickHandler=fn;}, getAttribute:()=>null};
globalThis.window = globalThis;
globalThis.location = {href:ORIGIN+'/', origin:ORIGIN, reload:()=>{reloads++; if(reloadResolve)reloadResolve();}};
globalThis.document = {querySelector:(selector)=>selector==='[data-testid="vault-picker"]'?picker:selector==='[data-testid="vault-picker-select-error"]'?visible:null};
globalThis.fetch = async function(input, options={}) {
  var headers = new Headers(options.headers||{});
  if(cookie)headers.set('Cookie',cookie);
  var response = await nativeFetch(new URL(input,ORIGIN), Object.assign({}, options,{headers}));
  var setCookie = response.headers.get('set-cookie');
  if(setCookie){cookie=setCookie.split(';')[0];handoffs.push({headers:setCookie,body:await response.clone().json()});}
  return response;
};
function button(path) {var attrs={'data-vault-path':path}; return {getAttribute:k=>attrs[k],setAttribute:(k,v)=>attrs[k]=v,removeAttribute:k=>delete attrs[k],attrs};}
async function choose(path) {
  var b=button(path);
  var done=new Promise(resolve=>reloadResolve=resolve);
  clickHandler({target:{closest:selector=>selector==='[data-testid="vault-picker-row-select"]'?b:null}});
  await Promise.race([done,new Promise((_,reject)=>setTimeout(()=>reject(new Error('picker selection failed: '+JSON.stringify(b.attrs))),4000))]);
}
async function initialize(path) {
  var b=button(path);
  function click(){clickHandler({target:{closest:selector=>selector==='.vault-picker-initialize-button'?b:null}});}
  click();
  for(var i=0;i<100 && b.attrs['data-affordance-status']!=='confirm-required';i++)await new Promise(r=>setTimeout(r,10));
  if(b.attrs['data-affordance-status']!=='confirm-required')throw new Error('no initialize confirmation: '+JSON.stringify(b.attrs));
  var done=new Promise(resolve=>reloadResolve=resolve);
  click();
  await Promise.race([done,new Promise((_,reject)=>setTimeout(()=>reject(new Error('initialize failed: '+JSON.stringify(b.attrs))),4000))]);
}
'''.replace('INITIAL_COOKIE', json.dumps(cookie)).replace('ORIGIN', json.dumps(origin))

    def run(body):
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("Node is required to verify the production picker controller")
        program = setup + '\n' + '\n'.join(scripts) + '\n(async()=>{'+body+'\n})().catch(e=>{console.error(e);process.exitCode=1;});'
        result = subprocess.run([node, '-e', program], capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    try:
        yield run, calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        api.close()
