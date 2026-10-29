"""Public same-origin operations transport. The runtime owns admission and effects."""

import re


def operations_route_allowed(path: str) -> bool:
    """Finite consumed route set, also used to retain real-client admission."""
    return path in {
        "/api/operations", "/api/operations/capabilities", "/api/operations/preconditions",
        "/api/operations/batches/preview",
    } or re.fullmatch(r"/api/operations/receipts/[A-Za-z0-9_.:-]{1,256}", path) is not None or re.fullmatch(
        r"/api/operations/batches/[A-Za-z0-9_.:-]{1,200}(?:/(?:execute|cancel))?", path,
    ) is not None


def operations_client_script() -> str:
    return r"""<script>
(function() {
  'use strict';
  function identity(value) {
    if (typeof value !== 'string' || !/^[A-Za-z0-9_.:-]{1,256}$/.test(value)) {
      throw new Error('Invalid operation reference');
    }
    // The admitted alphabet is already path-segment safe, including literal colons.
    return value;
  }
  async function request(path, body) {
    var response = await fetch(path, body === undefined ? {method:'GET', cache:'no-store'} : {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
    });
    var payload;
    try { payload = await response.json(); }
    catch (_) { throw new Error('Operation readback unavailable; outcome unknown'); }
    if (!response.ok) {
      var error = new Error(typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload));
      error.payload = payload; error.status = response.status; throw error;
    }
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      throw new Error('Operation response unavailable; outcome unknown');
    }
    return payload;
  }
  window.operationsClient = Object.freeze({
    capabilities: function() { return request('/api/operations/capabilities'); },
    preconditions: function(intent) { return request('/api/operations/preconditions', intent); },
    invoke: function(intent) { return request('/api/operations', intent); },
    receipt: function(id) { return request('/api/operations/receipts/' + identity(id)); },
    previewBatch: function(intent) { return request('/api/operations/batches/preview', intent); },
    inspectBatch: function(id, digest) {
      return request('/api/operations/batches/' + identity(id) + '?expected_digest=' + encodeURIComponent(digest));
    },
    executeBatch: function(id, digest) {
      return request('/api/operations/batches/' + identity(id) + '/execute', {expected_digest:digest});
    },
    cancelBatch: function(id, digest) {
      return request('/api/operations/batches/' + identity(id) + '/cancel', {expected_digest:digest});
    }
  });
})();
</script>"""
