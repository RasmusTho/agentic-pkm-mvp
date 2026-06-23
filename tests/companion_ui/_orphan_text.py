"""Orphan text-node detector for Companion UI rendered HTML.

Implements the build-time check described in issue #1343 / design §11.1
closing rule.  A text node is "orphan" when none of its ancestors in the
document body carry a ``data-testid`` or ``class`` attribute that belongs to
the whitelist of known design-system containers.

This is a pytest helper — import and call ``assert_no_orphan_text(html)``
from companion-UI workspace tests.
"""
from __future__ import annotations

from html.parser import HTMLParser

# Whitelist of ``data-testid`` values that legitimately host text content.
# Extend this list when new design-system containers ship.
CONTAINER_TESTIDS: frozenset[str] = frozenset(
    {
        # Header strip (§7.2 / #1336)
        "workspace-wordmark",
        "workspace-vault-chip",
        "workspace-runtime-status",
        "workspace-runtime-pill",
        "workspace-runtime-human-label",
        "workspace-freshness",
        "workspace-dev-ribbon",
        "workspace-quick-open",
        "workspace-browse-vault",
        "workspace-header-row",
        # CUIDR-04 (#2447): Capture is the single topbar launcher; the operator
        # telemetry region holds the relocated runtime disclosure; the composed
        # bottom bar holds the Map + Help wayfinding controls.
        "workspace-surface-icon-capture",
        "workspace-surface-icon-vault-settings",
        "workspace-operator-telemetry-region",
        "workspace-bottom-bar",
        "workspace-surface-icon-map",
        # Runtime status popover rows
        "workspace-runtime-status-popover",
        "workspace-runtime-channel",
        "workspace-runtime-channel-api",
        "workspace-vault-identity",
        "workspace-vault-channel",
        "workspace-vault-provenance",
        "workspace-writeguard-state",
        "workspace-canvas-enabled-state",
        "workspace-update-flow-state",
        "workspace-update-flow-state-detail",
        "workspace-update-flow-availability",
        "workspace-update-flow-scope",
        "workspace-update-flow-reason",
        "workspace-update-flow-config-mode",
        "workspace-update-governance-state",
        "workspace-guard-degraded-state",
        "workspace-runtime-trace-id",
        # Legacy primary posture (pre-#1336 baseline on origin/main)
        "workspace-primary-posture",
        "workspace-primary-posture-identity",
        "workspace-primary-posture-trace",
        # Note header / breadcrumb
        "workspace-note-header",
        "workspace-note-breadcrumb",
        "workspace-breadcrumb",
        "workspace-note-title",
        "workspace-properties-disclosure",
        "workspace-note-frontmatter",
        # Note body
        "workspace-note-body",
        # Outline
        "note-outline",
        "note-outline-link",
        # Panel / agent rail
        "workspace-agent-rail",
        "workspace-panel-empty",
        "workspace-panel-header",
        "workspace-panel-section",
        "workspace-reorient-strip",
        "workspace-reorient-disclosure",
        "workspace-canvas-session",
        "workspace-suggestions",
        "workspace-find-section",
        "workspace-resurface-section",
        # Banners
        "workspace-vault-unreachable-banner",
        "workspace-session-persistence",
        "workspace-session-persistence-notice",
        # Vault browser (left pane + overlay)
        "vault-browser-overlay",
        "vault-browser-row",
        "vault-browser-empty",
        "vault-browser-header",
        "vault-browser-search",
        "vault-browser-path",
        "vault-browser-section",
        "workspace-vault-browser-toggle",
        "workspace-vault-browser-active-identity",
        "workspace-vault-browser-read-only",
        "workspace-vault-browser-provenance",
        "workspace-vault-browser-state-identity-unavailable",
        "vault-browse-button",
        # Vault browser density: folder group headers (§6 / #1400)
        "workspace-vault-browser-group",
        # Body edit panel
        "workspace-body-edit-submit",
        "workspace-body-edit-reset",
        # Properties panel
        "workspace-note-properties",
        "vault-properties-label",
        "vault-properties-mode",
        "vault-property-value",
        "vault-property-key",
        # Responsive collapse elements (§7.5 / #1342)
        "workspace-outline-ribbon",
        "workspace-outline-sheet-trigger",
        "workspace-panel-sheet-trigger",
        "workspace-sheet-triggers",
        # Adaptive left context panel modes (§4 / #1399)
        "workspace-left-panel-mode-switcher",
        "workspace-left-panel-tab-browse",
        "workspace-left-panel-tab-outline",
        "workspace-left-panel-tab-context",
        "workspace-left-panel-collapse",
        "workspace-left-panel-reopen",
        "workspace-left-panel-context",
        "workspace-left-panel-mode-browse",
        "workspace-left-panel-mode-outline",
        "workspace-left-panel-mode-context",
        # Dev controls disclosure (#1361)
        "workspace-dev-controls-toggle",
        # Memory candidate review drawer (#1793, SEP-09b) — overlay-host
        # occupant; all drawer text lives inside this container.
        "memory-review-drawer",
        # Receipts history modal (#1794, SEP-10) — overlay-host occupant;
        # all modal text lives inside this container.
        "receipts-history-modal",
        # Settings drawer (#1789, SEP-07) — overlay-host occupant; all
        # drawer text lives inside this container. The local-only render
        # badge is a shell chip outside the drawer.
        "settings-drawer",
        "settings-local-only-badge",
        # System map overlay (#1787, SEP-05) — overlay-host occupant; all
        # map text (center node, surface nodes, parked note) lives inside
        # this container.
        "system-map-overlay",
        # Vault settings panel (vault-selector / settings work) — all labels,
        # status copy, action buttons, and setting rows live inside this
        # section; child testids are dynamic (vault-permission-{key},
        # vault-setting-save-{key}, etc.) so the outer container is registered.
        "vault-settings-panel",
    }
)

# Whitelist of CSS class name tokens — any element whose ``class`` attribute
# contains at least one of these is a legitimate text host.
CONTAINER_CLASSES: frozenset[str] = frozenset(
    {
        "vault-markdown-rendered",
        "panel-section",
        "primary-posture",
        "safety-item",          # legacy runtime-safety-strip rows (pre-#1336)
        "workspace-runtime-popover-row",
        "workspace-runtime-popover-key",
        "workspace-session-persistence",
        "note-heading",
        "note-subheading",
        "note-frontmatter-row",
        "note-properties",
        "note-breadcrumb",
        "receipt-row",
        "receipt-strip",
        "governance-receipt",
        "suggestion-card",
        "canvas-session-card",
        "canvas-action-row",
        "reorient-section",
        "find-candidate",
        "resurface-candidate",
        "panel-proposal-row",
        "panel-message",
        # Vault browser
        "vault-browser-list",
        "vault-browser-row-label",
        "vault-browser-action",
        "vault-browser-path-part",
        "workspace-vault-browser-meta",
        "workspace-vault-browser-state-identity-unavailable",
        # Inspector
        "inspector-panel",
        "inspector-row",
        "inspector-field",
        "inspector-label",
        "inspector-value",
        # Dev-mode chrome (topbar, load-bar) — legitimate in dev/staging profile
        "topbar",
        "topbar-api",
        "api-label",
        "api-url",
        "dev-chip",
        "load-bar",
        # Body edit panel
        "body-edit-header",
        "body-edit-label",
        "body-edit-note",
        "body-edit-actions",
        # Properties panel
        "vault-properties-header",
        "vault-properties-list",
        "vault-property",
        # In-shell Help drawer
        "help-toggle",
        "help-drawer-head",
        "help-drawer-title",
        "help-drawer-sub",
        "help-drawer-close",
        # In-shell Operator diagnostics drawer
        "operator-toggle",
        "operator-drawer-head",
        "operator-drawer-title",
        "operator-drawer-badge",
        "operator-drawer-close",
        "operator-drawer-loading",
        # Capture modal (#1791, SEP-08b)
        "capture-modal-title",
        "capture-modal-close",
        "capture-save",
        "capture-status",
        "capture-session-text",
        "capture-session-state",
        # ⌘K Panel command palette (#1786, SEP-04)
        "palette-not-chat",
        "palette-empty",
        "palette-proposal-row",
        "palette-blocked",
        "palette-receipt",
        "palette-title",
        # Guidance layer (#1788, SEP-06) — opt-in explanatory callouts plus
        # the ⓘ toggle affordance (topbar, overlay heads, re-entry card)
        "guidance-callout",
        "guidance-toggle",
    }
)

_VOID_TAGS: frozenset[str] = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
)

# Tags whose entire subtree is skipped (not user-facing rendered text)
_SKIP_SUBTREE_TAGS: frozenset[str] = frozenset({"head", "style", "script"})


class _StackWalker(HTMLParser):
    """SAX-style walker that maintains an ancestor stack and records orphans."""

    def __init__(self) -> None:
        super().__init__()
        # Each frame: {"tag": str, "testid": str, "classes": list[str]}
        self._stack: list[dict] = []
        self._skip_depth: int = 0
        # (text_snippet, path_str)
        self.orphans: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if self._skip_depth > 0:
            if tag not in _VOID_TAGS:
                self._skip_depth += 1
            return
        if tag in _SKIP_SUBTREE_TAGS:
            self._skip_depth += 1
            return
        if tag in _VOID_TAGS:
            return
        attr_dict = dict(attrs)
        self._stack.append(
            {
                "tag": tag,
                "testid": attr_dict.get("data-testid", ""),
                "classes": (attr_dict.get("class") or "").split(),
            }
        )

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if tag in _VOID_TAGS:
            return
        # Pop back to (and including) the most recent matching open tag.
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i]["tag"] == tag:
                del self._stack[i:]
                break

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        text = data.strip()
        if not text:
            return
        if self._in_safe_container():
            return
        path = " > ".join(
            f"{f['tag']}[{f['testid'] or ','.join(f['classes'][:1])}]"
            for f in self._stack[-5:]
        )
        self.orphans.append((text[:80], path))

    def _in_safe_container(self) -> bool:
        for frame in self._stack:
            if frame["testid"] in CONTAINER_TESTIDS:
                return True
            for cls in frame["classes"]:
                if cls in CONTAINER_CLASSES:
                    return True
        return False


def assert_no_orphan_text(html: str) -> None:
    """Assert every non-whitespace text node in *html* has a safe container ancestor.

    Raises ``AssertionError`` with the offending text and DOM path on failure.
    """
    walker = _StackWalker()
    walker.feed(html)
    if walker.orphans:
        lines = "\n".join(f"  {t!r} at {p}" for t, p in walker.orphans[:5])
        suffix = f"\n  … and {len(walker.orphans) - 5} more" if len(walker.orphans) > 5 else ""
        raise AssertionError(
            f"{len(walker.orphans)} orphan text node(s) — text outside a known design-system container:\n"
            f"{lines}{suffix}"
        )
