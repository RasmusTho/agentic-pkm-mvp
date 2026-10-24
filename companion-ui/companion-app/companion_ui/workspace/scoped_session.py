"""Ephemeral browser carrier for the existing Companion picker.

The cookie contains only the opaque API capability, never a path or identity.
It is translated at the same-origin transport boundary and is never healed.
"""
from __future__ import annotations

from http.cookies import CookieError, SimpleCookie

SESSION_COOKIE = "companion_context_session"
# Authenticated discovery lists folder names for explicit picker intent. It
# never reads vault content or selects a context and must remain usable after
# a stale content selection, as the existing selector bridge does.
PICKER_DISCOVERY_PATHS = frozenset({"/api/companion/vault/browse"})
SELECTOR_PATHS = frozenset({
    "/api/companion/vault/select",
    "/api/companion/vault/initialize",
    "/api/companion/vault/initialize/bootstrap",
    "/api/companion/vault/reload",
})
COMPATIBILITY_PATHS = frozenset({
    "/api/companion/capture/compatibility",
    "/api/companion/note/save/compatibility",
})


def session_cookie(value: str) -> str:
    cookie = SimpleCookie()
    cookie[SESSION_COOKIE] = value
    cookie[SESSION_COOKIE]["path"] = "/"
    cookie[SESSION_COOKIE]["httponly"] = True
    cookie[SESSION_COOKIE]["samesite"] = "Strict"
    return cookie.output(header="").strip()


def session_from_cookie(value: str) -> str | None:
    if SESSION_COOKIE not in value:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(value)
    except CookieError:
        return "invalid-session-cookie"
    item = cookie.get(SESSION_COOKIE)
    # A malformed/blank explicit carrier stays explicit and fails at the API.
    return item.value if item is not None and item.value else "invalid-session-cookie"


def scoped_session_script() -> str:
    return r"""
<script>
/* companion-scoped-session: request intent survives navigation in an HttpOnly session cookie. */
(function() {
  var send = window.fetch.bind(window);
  var bootstrap = Object.create(null);
  var reselectionRequired = false;
  function reselection(response) {
    if (response.ok) return Promise.resolve(response);
    return response.clone().text().then(function(text) {
      if (text.indexOf('reselection_required') === -1) return response;
      if (reselectionRequired) return response;
      reselectionRequired = true;
      // Reuse the shipped picker. No read, retry, default resolution or mint
      // happens in response to a stale bearer.
      var host = document.querySelector('[data-testid="vault-switch-host"]');
      if (host) { host.hidden = false; host.setAttribute('data-open', 'true'); }
      var error = document.querySelector('[data-testid="vault-picker-select-error"]');
      if (error) { error.hidden = false; error.textContent = 'Choose a vault again to continue.'; }
      else if (window.alert) { window.alert('Choose a vault again to continue.'); }
      return response;
    });
  }
  function jsonOptions(options, body) {
    return Object.assign({}, options, {body: JSON.stringify(body)});
  }
  window.fetch = function(input, options) {
    options = options || {};
    var url = new URL(typeof input === 'string' ? input : input.url, window.location.href);
    if (url.origin !== window.location.origin) return send(input, options);
    var path = url.pathname;
    var method = (options.method || 'GET').toUpperCase();
    if (method === 'POST' && path === '/api/companion/vault/select') {
      var selected = JSON.parse(options.body || '{}');
      selected.scoped_selection = true;
      return send(input, jsonOptions(options, selected)).then(function(response) {
        if (response.ok) reselectionRequired = false;
        return reselection(response);
      });
    }
    if (method === 'POST' && path === '/api/companion/vault/initialize') {
      var body = JSON.parse(options.body || '{}');
      body.scoped_selection = true;
      var key = JSON.stringify([body.path, body.machine_role, body.machineRole, body.vault_name]);
      if (bootstrap[key]) { body.confirm = true; body.bootstrap_token = bootstrap[key]; }
      return send(input, jsonOptions(options, body)).then(function(response) {
        if (response.ok) { delete bootstrap[key]; reselectionRequired = false; return response; }
        return response.clone().json().then(function(data) {
          if (!data.detail || data.detail.error !== 'vault_init_bootstrap_required') return response;
          if (!body.confirm) {
            return new Response(JSON.stringify({detail: {
              error: 'vault_init_confirmation_required',
              message: 'Confirm initialization of this folder as your first vault.'
            }}), {status: 409, headers: {'Content-Type': 'application/json'}});
          }
          return send('/api/companion/vault/initialize/bootstrap', jsonOptions(options, body))
            .then(function(issued) {
              if (!issued.ok) return issued;
              return issued.json().then(function(token) {
                bootstrap[key] = token.bootstrap_token;
                body.bootstrap_token = token.bootstrap_token;
                // One execution, never an automatic retry after a failed effect
                // or lost response. An explicit retry reuses this exact token.
                return send(input, jsonOptions(options, body)).then(function(result) {
                  if (result.ok) { delete bootstrap[key]; reselectionRequired = false; }
                  return result;
                });
              });
            });
        });
      }).then(reselection);
    }
    if (reselectionRequired && path !== '/api/companion/vault/browse') {
      return Promise.resolve(new Response(JSON.stringify({detail:'reselection_required'}), {
        status:401, headers:{'Content-Type':'application/json'}
      }));
    }
    if (method === 'POST' && (path === '/api/companion/capture' || path === '/api/companion/note/save')) {
      return send('/api/companion/vault/notes/scoped', {method: 'GET'})
        .then(function(read) {
          if (!read.ok) return read;
          var proof = read.headers.get('X-Compatibility-Write-Precondition');
          if (!proof) return new Response(JSON.stringify({detail: {error: 'capability_not_ready'}}), {status: 409});
          var headers = new Headers(options.headers || {});
          headers.set('X-Compatibility-Write-Precondition', proof);
          return send(path + '/compatibility', Object.assign({}, options, {headers: headers}));
        }).then(reselection);
    }
    return send(input, options).then(reselection);
  };
})();
</script>
"""
