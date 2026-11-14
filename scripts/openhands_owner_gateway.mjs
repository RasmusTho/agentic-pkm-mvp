/** Tailnet owner admission. Keys are injected upstream, never into Canvas HTML. */
import { createServer, request } from 'node:http';
import { openSync, readFileSync, fstatSync, closeSync, constants } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';

export function privateKey(path) {
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const s = fstatSync(fd);
    if (!s.isFile() || s.uid !== process.getuid() || (s.mode & 0o077)) throw Error('private key required');
    const key = readFileSync(fd, 'utf8').trim().replace(/^OH_SESSION_API_KEYS_0=/, '');
    if (!key || key.length > 4096 || /[\r\n\x00]/.test(key)) throw Error('invalid key');
    return key;
  } finally { closeSync(fd); }
}

export function admitted(req, config, websocket = false) {
  // Only loopback Tailscale Serve is admitted. No direct LAN/tailnet listener exists here.
  if (!['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(req.socket.remoteAddress)) return false;
  if (typeof config.ownerLogin !== 'string' || !config.ownerLogin ||
      !req.headers['tailscale-user-login'] || req.headers['tailscale-user-login'] !== config.ownerLogin) return false;
  const origin = new URL(config.publicOrigin);
  if (req.headers.host !== origin.host) return false;
  if (req.headers.origin && req.headers.origin !== origin.origin) return false;
  if ((websocket || !['GET', 'HEAD'].includes(req.method)) && req.headers.origin !== origin.origin) return false;
  if (req.headers['sec-fetch-site'] === 'cross-site') return false;
  let url;
  try { url = new URL(req.url, origin); } catch { return false; }
  if (url.origin !== origin.origin || url.searchParams.has('session_api_key')) return false;
  return true;
}

export function allowed(method, path, config, websocket = false) {
  const id = config.conversationId;
  if (websocket) return path === `/sockets/events/${id}` || path === `/sockets/session/${id}`;
  if (['GET', 'HEAD'].includes(method)) {
    if (!path.startsWith('/api/') && !path.startsWith('/sockets/') &&
        !/^\/(settings|agent-profiles|server_info|alive|health|ready)(\/|$)/.test(path)) return true;
    return /^\/(server_info|alive|health|ready)$/.test(path) ||
      /^\/api\/(settings|agent-profiles)$/.test(path) ||
      /^\/api\/agent-profiles\/([0-9a-f-]{36}|default|bob-owner)$/.test(path) ||
      /^\/api\/(profiles|meta-profiles|skills|workspaces|file\/home|llm\/models\/verified|canvas-extensions\/installed)$/.test(path) ||
      path === '/api/conversations' ||
      /^\/api\/conversations\/(search|count)$/.test(path) ||
      new RegExp(`^/api/conversations/${id}(/(events(/(search|count|[0-9a-f-]{36}))?|children|runtime|agent_final_response))?$`).test(path);
  }
  if (method === 'PATCH' && path === '/api/settings') return true;
  return method === 'POST' && new RegExp(`^/api/conversations/${id}/(events|run|pause|interrupt)$`).test(path);
}

// Hold the existing exact-assignment lifecycle/port locks until TCP connection is bound.
// The private pipe is consumed only by this process; it is never logged or returned to Canvas.
let nativeEndpointQueue = Promise.resolve();
export async function endpoint(config) {
  if (!config.sandbox) return {config, release:()=>{}};
  // Canvas fetches metadata concurrently. Queue this gateway's brief lock holds rather than
  // turning harmless sibling requests into LifecycleBusy failures or polling another worker.
  const previous = nativeEndpointQueue;
  let unlock;
  nativeEndpointQueue = new Promise(resolve=>{unlock=resolve;});
  await previous;
  const code = `import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from app.builderops import epic_workspace as e
e.OPENHANDS_PORT_RANGE=range(18840,18848)
l=e.Layout(Path(sys.argv[2]),int(sys.argv[3]))
m=e._load_state(l)['issue_mappings'][sys.argv[3]]
c=m.get('conversation',{})
if m.get('worker')!='owner-sandbox' or c.get('status')!='created' or c.get('engine')!='codex' or c.get('model')!='gpt-6.1-terra': raise ValueError('sandbox binding unavailable')
with e._endpoint_session(l,'owner-sandbox',int(sys.argv[3]),m,e.subprocess.run) as (port,key):
 if e._load_state(l)['issue_mappings'][sys.argv[3]].get('conversation')!=c: raise ValueError('conversation changed')
 if not 18840<=port<=18847: raise ValueError('sandbox port unavailable')
 print(json.dumps({'port':port,'key':key,'cid':c['id']}),flush=True)
 sys.stdin.buffer.read(1)
`;
  return new Promise((resolve,reject) => {
    const child=spawn('python3',['-c',code,config.runner,config.root,String(config.sandboxEpic)],{stdio:['pipe','pipe','ignore']});
    let buffer='', settled=false, released=false, lost=false, onLost=()=>{};
    const timer=setTimeout(()=>{child.kill();if(!settled){settled=true;reject(Error('sandbox busy'));}},10000);
    child.stdout.on('data',chunk=>{
      buffer+=chunk.toString();
      if(buffer.length>8192){child.kill();return;}
      if(!settled && buffer.includes('\n')) {
        try {
          const d=JSON.parse(buffer.slice(0,buffer.indexOf('\n')));
          if(!/^[0-9a-f-]{36}$/.test(d.cid) || typeof d.key!=='string')throw Error('invalid endpoint');
          settled=true;clearTimeout(timer);
          resolve({config:{...config,backend:`http://127.0.0.1:${d.port}`,conversationId:d.cid},key:d.key,
            release:()=>{if(!released){released=true;child.stdin.end();}},
            onLost:callback=>{onLost=callback;if(lost)callback();}});
        }catch{child.kill();}
      }
    });
    child.stdin.on('error',()=>{});
    child.on('error',()=>{unlock();clearTimeout(timer);if(!settled){settled=true;reject(Error('sandbox unavailable'));}});
    child.on('close',()=>{unlock();clearTimeout(timer);if(!released){lost=true;onLost();}if(!settled){settled=true;reject(Error('sandbox unavailable'));}});
  });
}

export function start(config) {
  if (typeof config.ownerLogin !== 'string' || !config.ownerLogin ||
      new URL(config.publicOrigin).protocol !== 'https:' || !/^[0-9a-f-]{36}$/.test(config.conversationId)) throw Error('owner identity, HTTPS origin and conversation are required');
  for (const endpoint of [config.backend, config.canvas]) {
    const url = new URL(endpoint);
    if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.username || url.password || url.pathname !== '/') throw Error('loopback target required');
  }
  const deny = res => { res.writeHead(403, {'Content-Type':'application/json', 'Cache-Control':'no-store'}); res.end('{"detail":"Owner route does not support this request"}'); };
  const server = createServer(async (req, res) => {
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    let path, current, binding;
    try { path = new URL(req.url, config.publicOrigin).pathname; } catch { return deny(res); }
    if (!admitted(req, config)) return deny(res);
    let preferenceBody;
    if (req.method === 'PATCH') {
      try {
        const chunks=[];let size=0;
        for await (const chunk of req) {size+=chunk.length;if(size>1024)throw Error('oversize');chunks.push(chunk);}
        const value=JSON.parse(Buffer.concat(chunks).toString());
        const expected={misc_settings_diff:{app_preferences:{user_consents_to_analytics:false}}};
        if (JSON.stringify(value)!==JSON.stringify(expected)) throw Error('unsupported preference');
        preferenceBody=Buffer.from(JSON.stringify(expected));
      } catch {return deny(res);}
    }
    const backend = /^\/(api|settings|agent-profiles|server_info|alive|health|ready)(\/|$)/.test(path);
    try { binding = backend ? await endpoint(config) : {config,release:()=>{}}; current=binding.config; } catch { res.writeHead(503); res.end('Sandbox stopped or not verified. Return to owner access and request sandbox status.'); return; }
    if (!allowed(req.method, path, current)) { binding.release(); return deny(res); }
    if (path === '/api/conversations') {
      const ids=new URL(req.url,config.publicOrigin).searchParams.getAll('ids');
      if(ids.length!==1 || ids[0]!==current.conversationId){binding.release();return deny(res);}
    }

    try {
      delete req.headers.authorization;
      delete req.headers['x-session-api-key'];
      if (backend) req.headers['x-session-api-key'] = binding.key ?? privateKey(config.keyFile);
      if (preferenceBody) req.headers['content-length']=String(preferenceBody.length);
      const target = new URL(backend ? current.backend : config.canvas);
      const upstream = request({hostname:target.hostname,port:target.port,path:req.url,method:req.method,headers:req.headers}, reply => {
        res.writeHead(reply.statusCode, {...reply.headers, 'referrer-policy':'no-referrer','cache-control':'no-store'});
        reply.on('aborted',()=>res.destroy());
        reply.on('error',()=>res.destroy());
        reply.pipe(res);
      });
      res.on('close',()=>upstream.destroy());
      binding.onLost?.(()=>upstream.destroy());
      upstream.on('socket',sock=>{if(sock.connecting)sock.once('connect',binding.release);else binding.release();});
      upstream.on('error', () => { binding.release(); if (!res.headersSent) res.writeHead(503); res.end('Owner service unavailable'); });
      upstream.setTimeout(120000, () => upstream.destroy());
      req.on('aborted', () => upstream.destroy());
      if (preferenceBody) upstream.end(preferenceBody); else req.pipe(upstream);
    } catch { binding.release(); if (!res.headersSent) res.writeHead(503); res.end('Owner service unavailable'); }
  });
  server.on('upgrade', async (req, socket, head) => {
    let path, current, binding;
    try { path = new URL(req.url, config.publicOrigin).pathname; } catch { socket.destroy(); return; }
    if (!admitted(req, config, true)) { socket.destroy(); return; }
    try { binding=await endpoint(config);current=binding.config; } catch { socket.destroy(); return; }
    if (!allowed('GET', path, current, true)) {
      binding.release();socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n'); return;
    }
    try {
      delete req.headers.authorization;
      req.headers['x-session-api-key'] = binding.key ?? privateKey(config.keyFile);
      const target = new URL(current.backend);
      const upstream = request({hostname:target.hostname,port:target.port,path:req.url,headers:req.headers});
      binding.onLost?.(()=>upstream.destroy());
      upstream.on('socket',sock=>{if(sock.connecting)sock.once('connect',binding.release);else binding.release();});
      upstream.on('upgrade', (reply, peer, peerHead) => {
        socket.write(`HTTP/1.1 ${reply.statusCode} Switching Protocols\r\n` +
          Object.entries(reply.headers).map(([k,v]) => `${k}: ${v}\r\n`).join('') + '\r\n');
        if (peerHead.length) socket.write(peerHead);
        if (head.length) peer.write(head);
        socket.pipe(peer); peer.pipe(socket);
        socket.on('error', () => peer.destroy()); peer.on('error', () => socket.destroy());
        socket.on('close', () => peer.destroy()); peer.on('close', () => socket.destroy());
      });
      upstream.on('response', reply => { reply.resume(); socket.end(`HTTP/1.1 ${reply.statusCode} Refused\r\nConnection: close\r\n\r\n`); });
      upstream.on('error', () => {binding.release();socket.destroy();});
      upstream.end();
    } catch { binding.release();socket.destroy(); }
  });
  server.listen(config.port, '127.0.0.1');
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  start(JSON.parse(readFileSync(process.argv[2], 'utf8')));
}
