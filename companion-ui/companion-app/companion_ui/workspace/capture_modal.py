"""⌘N capture modal for the Companion UI shell (SEP-08b, issue #1791).

Implements the UI half of ``docs/SYSTEM_ENTRY_POINT/CAPTURE_TO_VAULT_INBOX.md``
against the normative invariants in
``companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md`` §Resolved Q17: friction-free
intake of "things I need to take care of" as a commitment to future-self
appended to the vault inbox — never an app-owned task.

The surface is a top modal mounted on the shared overlay host (#1785,
``overlay_host.py``), opened by ``⌘N`` / ``capture.open``:

- a textarea (``data-region="capture-input"``) and a "Capture to inbox"
  action (``capture.save``) that posts to the shipped governed endpoint
  (``POST /api/companion/capture``, #1790) — no direct vault I/O from the UI;
- a session-capture list showing this session's captures with their
  written / not-yet-written state. **A write is claimed only on the runtime
  acknowledgement** (the endpoint surfaces the deterministic writer's
  ``WriteReceipt`` verbatim); the UI never fabricates one. If the runtime
  reports that the vault write happened but its AuthorityReceipt was not
  persisted, the item is shown as written with acknowledgement pending, never
  as retryable not-yet-written.
- **Offline honesty:** when the runtime is unreachable the composer stays
  usable, each unwritten capture is plainly labeled not yet written with its
  full text kept visible in the session list, and text is never silently
  dropped.
- Dismissal routes through the overlay host back to the document anchor;
  unsent draft text is preserved for the session (the modal only hides).
- No due-date field and no app task states exist anywhere on the surface
  (spec §Resolved Q17); resurfacing is by relevance, like any vault material.

Like ``overlay_host.py`` and ``entry_state.py``, the pure model in this
module is the contract the in-page controller (:func:`capture_modal_script`)
mirrors; tests assert both. Nothing here performs I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from companion_ui.workspace.guidance_layer import (
    guidance_callout_markup,
    guidance_toggle_markup,
)

# The overlay-host id this surface occupies (declared in
# overlay_host.DECLARED_OVERLAYS; shipped via SHIPPED_OVERLAY_OCCUPANTS).
CAPTURE_OVERLAY_ID = "capture"

# The shipped governed endpoint (#1790) — policy → validation → deterministic
# writer; the response is the runtime acknowledgement.
CAPTURE_ENDPOINT = "/api/companion/capture"

# Session-capture states. A capture is `written` only when the runtime
# acknowledged it. `written_unacknowledged` is the explicit post-write failure
# state for "vault write happened, AuthorityReceipt persistence failed".
WRITTEN = "written"
WRITTEN_UNACKNOWLEDGED = "written_unacknowledged"
NOT_YET_WRITTEN = "not_yet_written"
CAPTURE_STATES: tuple[str, ...] = (
    WRITTEN,
    WRITTEN_UNACKNOWLEDGED,
    NOT_YET_WRITTEN,
)


@dataclass(frozen=True)
class CaptureAck:
    """The runtime acknowledgement of a written capture.

    Mirrors the shipped endpoint's response model
    (``app/api/routes/capture.py::CaptureResponse``): the deterministic
    writer's receipt surfaced verbatim. The UI only ever builds this from an
    actual runtime response — never locally.
    """

    note_path: str
    operation: str
    adapter: str
    captured_at: str
    trace_id: str


@dataclass(frozen=True)
class SessionCapture:
    """One capture in this session's list.

    The written claim is bound to the acknowledgement by construction: a
    ``written`` capture without an ack — or a ``not_yet_written`` capture
    carrying a fabricated one — cannot exist.
    """

    text: str
    state: str
    ack: CaptureAck | None = None

    def __post_init__(self) -> None:
        if self.state not in CAPTURE_STATES:
            raise ValueError(
                f"unknown capture state {self.state!r}; allowed: {CAPTURE_STATES}"
            )
        if self.state == WRITTEN and self.ack is None:
            raise ValueError(
                "a write is never claimed without the runtime acknowledgement"
            )
        if self.state != WRITTEN and self.ack is not None:
            raise ValueError(
                "only a runtime-acknowledged written capture can carry an "
                "acknowledgement reference"
            )


@dataclass(frozen=True)
class CaptureSessionState:
    """The capture surface's session state: the draft and this session's list.

    Session-honest, not an offline-first store: the list lives for the
    session only (spec: durable offline queueing is out of scope).
    """

    draft: str = ""
    captures: tuple[SessionCapture, ...] = field(default=())


def edit_draft(state: CaptureSessionState, text: str) -> CaptureSessionState:
    """Replace the composer draft; the session list is untouched."""
    return replace(state, draft=text)


def submit_draft(
    state: CaptureSessionState, *, ack: CaptureAck | None
) -> CaptureSessionState:
    """``capture.save`` — record the draft in the session list.

    With a runtime acknowledgement the capture is ``written`` and carries the
    acknowledgement reference. Without one (runtime unreachable, blocked, or
    any non-acknowledged response) it is honestly ``not_yet_written`` with
    its text preserved verbatim — never silently dropped. Either way the
    composer clears and stays usable for the next thought.

    A whitespace-only draft is a no-op, mirroring the endpoint's explicit
    empty-capture rejection: nothing fake enters the session list.
    """
    if not state.draft.strip():
        return state
    entry = SessionCapture(
        text=state.draft,
        state=WRITTEN if ack is not None else NOT_YET_WRITTEN,
        ack=ack,
    )
    return CaptureSessionState(draft="", captures=state.captures + (entry,))


def dismiss_modal(state: CaptureSessionState) -> CaptureSessionState:
    """Dismiss-to-anchor preserves the session state by construction.

    The overlay host owns the dismissal itself (Esc / scrim / close → back to
    the document anchor, no route reset). This surface's contract is that
    dismissal never touches the unsent draft or the session-capture list —
    the identity function, kept explicit so tests can pin it.
    """
    return state


def capture_modal_markup() -> str:
    """The top-modal markup (and its scoped styles) for the capture surface.

    Hidden until the overlay host mounts the ``capture`` occupant (``⌘N`` /
    ``capture.open``). The host scrim sits underneath; the panel renders as a
    top modal above it. Deliberately absent: any due-date field, any task
    state, any checkbox — a capture is vault intake, not a task.
    """
    return """
  <!-- Capture modal (#1791, SEP-08b) — friction-free intake appended to the
       vault inbox through the governed endpoint (#1790). A write is claimed
       only on the runtime acknowledgement; offline captures are plainly
       labeled not yet written and their text stays visible. -->
  <style>
    .capture-modal {
      align-items: flex-start;
      display: flex;
      inset: 0;
      justify-content: center;
      padding: 56px 16px 0;
      pointer-events: none;
      position: fixed;
      z-index: 1010;
    }
    .capture-modal[hidden] { display: none; }
    .capture-modal-panel {
      background: var(--bg-surface);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-lg);
      box-shadow: 0 18px 48px rgba(0, 0, 0, 0.5);
      display: flex;
      flex-direction: column;
      gap: 10px;
      max-height: 72vh;
      max-width: 560px;
      overflow: hidden;
      padding: 18px 20px;
      pointer-events: auto;
      width: 100%;
    }
    .capture-modal-header {
      align-items: center;
      display: flex;
      justify-content: space-between;
    }
    .capture-modal-title {
      color: var(--fg-1);
      font-family: var(--font-ui);
      font-size: var(--text-sm);
      font-weight: 600;
    }
    .capture-modal-close {
      background: transparent;
      border: none;
      color: var(--fg-2);
      cursor: pointer;
      font-size: 1.2rem;
      line-height: 1;
      padding: 0 4px;
    }
    .capture-input {
      background: var(--bg-raised);
      border: 1px solid var(--border-strong);
      border-radius: 8px;
      color: var(--fg-1);
      font-family: var(--font-ui);
      font-size: var(--text-sm);
      min-height: 84px;
      padding: 10px 12px;
      resize: vertical;
    }
    .capture-actions { display: flex; justify-content: flex-end; }
    .capture-save {
      background: var(--accent);
      border: none;
      border-radius: 8px;
      color: #0a0e16;
      cursor: pointer;
      font-family: var(--font-ui);
      font-size: var(--text-sm);
      font-weight: 600;
      padding: 8px 14px;
    }
    .capture-status {
      color: var(--fg-3);
      font-family: var(--font-ui);
      font-size: var(--text-xs);
      min-height: 1em;
    }
    .capture-session-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
      list-style: none;
      margin: 0;
      overflow-y: auto;
      padding: 0;
    }
    .capture-session-item {
      border: 1px solid var(--border);
      border-radius: 8px;
      display: flex;
      flex-direction: column;
      gap: 2px;
      padding: 8px 10px;
    }
    .capture-session-text {
      color: var(--fg-1);
      font-family: var(--font-ui);
      font-size: var(--text-sm);
      white-space: pre-wrap;
    }
    .capture-session-state {
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }
    .capture-session-item[data-capture-state="not_yet_written"]
      .capture-session-state {
      color: var(--accent);
    }
    .capture-session-item[data-capture-state="written_unacknowledged"]
      .capture-session-state {
      color: var(--warning, var(--accent));
    }
  </style>
  <div class="capture-modal" id="capture-modal" data-testid="capture-modal"
       data-region="capture-modal" role="dialog" aria-modal="true"
       aria-label="Capture to inbox" hidden>
    <div class="capture-modal-panel">
      <div class="capture-modal-header">
        <span class="capture-modal-title">Capture</span>
        """ + guidance_toggle_markup("capture") + """
        <button class="capture-modal-close" data-testid="capture-close"
                onclick="overlayHost.dismiss()" aria-label="Close">&times;</button>
      </div>
      """ + guidance_callout_markup("capture") + """
      <textarea class="capture-input" id="capture-input"
                data-testid="capture-input" data-region="capture-input"
                rows="4" placeholder="What needs taking care of?"
                autocomplete="off"></textarea>
      <div class="capture-actions">
        <button class="capture-save" id="capture-save" data-testid="capture-save"
                data-intent="capture.save"
                onclick="captureModal.save()">Capture to inbox</button>
      </div>
      <div class="capture-status" id="capture-status" data-testid="capture-status"
           role="status" aria-live="polite"></div>
      <ul class="capture-session-list" id="capture-session-list"
          data-testid="capture-session-list" data-region="capture-session-list"
          aria-label="Captures from this session"></ul>
    </div>
  </div>
  <!-- /capture-modal -->"""


def capture_modal_script() -> str:
    """The in-page capture controller mirroring the pure model above.

    Must be emitted after :func:`overlay_host.overlay_host_script` so
    ``window.overlayHost`` exists: the controller registers the ``capture``
    occupant, which makes the host's ``⌘N`` wiring (already routed to
    ``capture.open`` since #1785) mount this surface instead of staying inert.
    """
    return """
  <script>
  /* capture-modal-controller */
  (function() {
    var modal = document.getElementById('capture-modal');
    if (!modal) { return; }
    var input = document.getElementById('capture-input');
    var list = document.getElementById('capture-session-list');
    var statusLine = document.getElementById('capture-status');

    function setStatus(msg) { statusLine.textContent = msg || ''; }

    function addEntry(text, state, ack) {
      // Session-capture list entry. The full text always lands here via
      // textContent — visible and intact, never silently dropped.
      var li = document.createElement('li');
      li.className = 'capture-session-item';
      li.setAttribute('data-capture-state', state);
      var textSpan = document.createElement('span');
      textSpan.className = 'capture-session-text';
      textSpan.textContent = text;
      var stateSpan = document.createElement('span');
      stateSpan.className = 'capture-session-state';
      if (state === 'written') {
        // Written entries carry the runtime acknowledgement reference.
        li.setAttribute('data-ack-note-path', ack.note_path || '');
        li.setAttribute('data-ack-trace-id', ack.trace_id || '');
        li.setAttribute('data-ack-captured-at', ack.captured_at || '');
        stateSpan.textContent = 'written \\u00b7 ' + (ack.note_path || '');
      } else if (state === 'written_unacknowledged') {
        stateSpan.textContent = 'written \\u00b7 acknowledgement pending';
      } else {
        stateSpan.textContent = 'not yet written';
      }
      li.appendChild(textSpan);
      li.appendChild(stateSpan);
      list.insertBefore(li, list.firstChild);
    }

    function clearComposerIfUnchanged(text) {
      // Clear only what was just recorded; anything typed mid-flight stays.
      if (input.value === text) { input.value = ''; }
    }

    function onWritten(text, ack) {
      // The written claim is made only here, from the runtime
      // acknowledgement payload — never locally.
      addEntry(text, 'written', ack);
      clearComposerIfUnchanged(text);
      setStatus('');
    }

    function onNotWritten(text, reason) {
      // Offline honesty: the capture stays visible with its full text and a
      // plain not-yet-written label; the composer stays usable; no
      // acknowledgement is fabricated on this path.
      addEntry(text, 'not_yet_written', null);
      clearComposerIfUnchanged(text);
      setStatus(reason);
    }

    function onWrittenUnacknowledged(text, reason) {
      // The runtime reported a post-write acknowledgement failure. Do not
      // invite a retry that would duplicate the vault entry.
      addEntry(text, 'written_unacknowledged', null);
      clearComposerIfUnchanged(text);
      setStatus(reason);
    }

    window.captureModal = {
      open: function() {
        modal.removeAttribute('hidden');
        if (input) { input.focus(); }
      },
      close: function() {
        modal.setAttribute('hidden', '');
      },
      save: function() {
        var text = input.value;
        if (!text || !text.replace(/\\s+/g, '').length) {
          setStatus('Nothing to capture yet.');
          return;
        }
        fetch('/api/companion/capture', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({text: text})
        }).then(function(resp) {
          if (resp.ok) {
            return resp.json().then(function(ack) { onWritten(text, ack); });
          }
          return resp.json().catch(function() { return null; }).then(function(body) {
            var detail = body && body.detail ? body.detail : null;
            var msg = (detail && detail.message)
              ? body.detail.message
              : 'The runtime did not acknowledge the capture (HTTP ' + resp.status + ').';
            if (detail && detail.state === 'not_acknowledged') {
              onWrittenUnacknowledged(text, msg);
              return;
            }
            onNotWritten(text, msg);
          });
        }).catch(function() {
          onNotWritten(text, 'Runtime unreachable \\u2014 this capture is not yet written.');
        });
      }
    };

    // Register as the overlay host's `capture` occupant: ⌘N / capture.open
    // mounts this modal; Esc and the scrim dismiss it back to the document
    // anchor. The close path only hides the panel, so unsent draft text and
    // the session-capture list survive for the session.
    if (window.overlayHost) {
      window.overlayHost.register('capture', {
        open: function() { window.captureModal.open(); },
        close: function() { window.captureModal.close(); }
      });
    }
  })();
  /* /capture-modal-controller */
  </script>"""


__all__ = [
    "CAPTURE_ENDPOINT",
    "CAPTURE_OVERLAY_ID",
    "CAPTURE_STATES",
    "NOT_YET_WRITTEN",
    "WRITTEN",
    "WRITTEN_UNACKNOWLEDGED",
    "CaptureAck",
    "CaptureSessionState",
    "SessionCapture",
    "capture_modal_markup",
    "capture_modal_script",
    "dismiss_modal",
    "edit_draft",
    "submit_draft",
]
