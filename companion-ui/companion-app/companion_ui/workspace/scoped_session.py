"""Ephemeral selection transport for the existing Companion picker.

The bearer stays HttpOnly. A non-authority intent cookie makes a lost or
mismatched handoff an explicit refusal instead of a new default journey.
"""
from __future__ import annotations

import hashlib
import hmac
from http.cookies import CookieError, SimpleCookie
import json
import re

SESSION_COOKIE = "companion_context_session"
INTENT_COOKIE = "companion_context_intent"
HANDOFF_DIGEST_HEADER = "X-Companion-Scoped-Handoff"
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


def session_transport_digest(value: str) -> str:
    """Correlate transported bytes only; this digest grants no API authority."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def session_from_cookie(value: str) -> str | None:
    if SESSION_COOKIE not in value and INTENT_COOKIE not in value:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(value)
    except CookieError:
        return ""
    session = cookie.get(SESSION_COOKIE)
    intent = cookie.get(INTENT_COOKIE)
    if INTENT_COOKIE in value:
        # Pending, malformed, missing, and old retained bearer bytes are all
        # explicit intent. An empty carrier reaches the API's typed refusal.
        if intent is None or not re.fullmatch(r"[a-f0-9]{64}", intent.value):
            return ""
        if session is None or not session.value:
            return ""
        if not hmac.compare_digest(session_transport_digest(session.value), intent.value):
            return ""
    return session.value if session is not None and session.value else ""


def scoped_session_script(compatibility_precondition: str | None = None, *, scoped_document: bool = False) -> str:
    script = r"""
<script>
/* companion-scoped-session: explicit intent survives navigation; write proof belongs to this document. */
(function() {
  var send = window.fetch.bind(window);
  var bootstrap = Object.create(null);
  var reselectionRequired = false;
  var handoffPending = false;
  var documentWriteProof = __DOCUMENT_WRITE_PROOF__;
  var scopedDocument = __SCOPED_DOCUMENT__;
  function refusal(message, status) {
    return new Response(JSON.stringify({detail:{error:'reselection_required',message:message}}), {
      status:status || 409, headers:{'Content-Type':'application/json'}
    });
  }
  function reselection(response) {
    if (response.ok) return Promise.resolve(response);
    return response.clone().text().then(function(text) {
      if (text.indexOf('reselection_required') === -1 || reselectionRequired) return response;
      reselectionRequired = true;
      var host = document.querySelector('[data-testid="vault-switch-host"]');
      if (host) { host.hidden = false; host.setAttribute('data-open', 'true'); }
      var error = document.querySelector('[data-testid="vault-picker-select-error"]');
      if (error) { error.hidden = false; error.textContent = 'Choose a vault again to continue.'; }
      else if (window.alert) { window.alert('Choose a vault again to continue.'); }
      return response;
    });
  }
  function setIntent(value) {
    try {
      document.cookie = 'companion_context_intent=' + value + '; Path=/; SameSite=Strict';
      return String(document.cookie || '').split(';').some(function(item) {
        return item.trim() === 'companion_context_intent=' + value;
      });
    } catch (e) { return false; }
  }
  function beginHandoff() {
    handoffPending = true;
    return setIntent('pending');
  }
  function acceptHandoff(response) {
    if (!response.ok) return Promise.resolve(response);
    var expected = response.headers.get('X-Companion-Scoped-Handoff') || '';
    if (!/^[a-f0-9]{64}$/.test(expected) || !setIntent(expected)) {
      return Promise.resolve(refusal('The scoped selection handoff was not established. Choose a vault again.'));
    }
    // The gateway compares the expected transport digest with the HttpOnly
    // cookie. This strict read then validates the actual capability at the API.
    return send('/api/companion/vault/notes/scoped', {method:'GET'}).then(function(read) {
      if (!read.ok) return read;
      handoffPending = false;
      reselectionRequired = false;
      // Never replace documentWriteProof with the new selection's proof. The
      // picker controller reloads the document after this verified handoff.
      return response;
    });
  }
  function jsonOptions(options, body) {
    return Object.assign({}, options, {body:JSON.stringify(body)});
  }
  window.fetch = function(input, options) {
    options = options || {};
    var url = new URL(typeof input === 'string' ? input : input.url, window.location.href);
    if (url.origin !== window.location.origin) return send(input, options);
    var path = url.pathname;
    var method = (options.method || 'GET').toUpperCase();
    if (method === 'POST' && path === '/api/companion/vault/select') {
      if (!beginHandoff()) return reselection(refusal('Scoped browser session storage is unavailable.'));
      var selected = JSON.parse(options.body || '{}');
      selected.scoped_selection = true;
      return send(input, jsonOptions(options, selected)).then(acceptHandoff).then(reselection);
    }
    if (method === 'POST' && path === '/api/companion/vault/initialize') {
      if (!beginHandoff()) return reselection(refusal('Scoped browser session storage is unavailable.'));
      var body = JSON.parse(options.body || '{}');
      body.scoped_selection = true;
      var key = JSON.stringify([body.path,body.machine_role,body.machineRole,body.vault_name]);
      if (bootstrap[key]) { body.confirm = true; body.bootstrap_token = bootstrap[key]; }
      function finish(response) {
        return acceptHandoff(response).then(function(verified) {
          if (verified.ok) delete bootstrap[key];
          return verified;
        });
      }
      return send(input, jsonOptions(options, body)).then(function(response) {
        if (response.ok) return finish(response);
        return response.clone().json().then(function(data) {
          if (!data.detail || data.detail.error !== 'vault_init_bootstrap_required') return response;
          if (!body.confirm) {
            return new Response(JSON.stringify({detail:{
              error:'vault_init_confirmation_required',
              message:'Confirm initialization of this folder as your first vault.'
            }}), {status:409,headers:{'Content-Type':'application/json'}});
          }
          return send('/api/companion/vault/initialize/bootstrap', jsonOptions(options, body))
            .then(function(issued) {
              if (!issued.ok) return issued;
              return issued.json().then(function(token) {
                bootstrap[key] = token.bootstrap_token;
                body.bootstrap_token = token.bootstrap_token;
                // Exactly one execution. Explicit retries retain this token
                // until the server-owned handoff has been verified.
                return send(input, jsonOptions(options, body)).then(finish);
              });
            });
        });
      }).then(reselection);
    }
    if ((reselectionRequired || handoffPending) && path !== '/api/companion/vault/browse') {
      return Promise.resolve(refusal('Choose a vault again to continue.', 401));
    }
    if (method === 'POST' && (path === '/api/companion/capture' || path === '/api/companion/note/save')) {
      if (!documentWriteProof) return reselection(refusal('Reload or reselect the vault before writing.'));
      // Validate current session liveness without acquiring a replacement write
      // proof. A stale rendered A document must never obtain B write intent.
      return send(scopedDocument ? '/api/companion/active-context/selection' : '/api/companion/vault/notes', {method:'GET'}).then(function(inspected) {
        if (!inspected.ok) return inspected;
        var headers = new Headers(options.headers || {});
        headers.set('X-Compatibility-Write-Precondition', documentWriteProof);
        return send(path + '/compatibility', Object.assign({}, options, {headers:headers}));
      }).then(reselection);
    }
    return send(input, options).then(reselection);
  };
})();
</script>
"""
    encoded = json.dumps(compatibility_precondition, ensure_ascii=True).replace("<", chr(92) + "u003c")
    return script.replace("__DOCUMENT_WRITE_PROOF__", encoded).replace("__SCOPED_DOCUMENT__", json.dumps(scoped_document))
