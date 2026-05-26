"""Read-only heading outline for rendered vault Markdown documents."""

from __future__ import annotations

import html

from companion_ui.renderer.models import HeadingRef, VaultMarkdownDocument


def render_note_outline(document: VaultMarkdownDocument) -> str:
    """Render a keyboard-accessible outline from parsed document headings."""

    headings = tuple(document.headings)
    if not headings:
        return (
            '<nav class="note-outline note-outline-empty" '
            'data-testid="note-outline" '
            'data-affordance-status="read-only" '
            'data-layout-desktop="side-panel" '
            'data-layout-portrait="inline" '
            'data-outline-heading-count="0" '
            'aria-label="Note outline">'
            '<div class="note-outline-heading">Outline</div>'
            '<p class="note-outline-empty-copy">No headings in this note.</p>'
            "</nav>"
        )

    items = "".join(_render_heading_item(heading) for heading in headings)
    return (
        '<nav class="note-outline" '
        'data-testid="note-outline" '
        'data-affordance-status="read-only" '
        'data-layout-desktop="side-panel" '
        'data-layout-portrait="inline" '
        f'data-outline-heading-count="{len(headings)}" '
        'aria-label="Note outline">'
        '<div class="note-outline-heading">Outline</div>'
        f'<ol class="note-outline-list">{items}</ol>'
        "</nav>"
    )


def note_outline_css() -> str:
    """CSS for desktop side-panel and portrait inline outline layouts."""

    return """
    .note-reading-layout {
      display: grid;
      flex: 1;
      grid-template-columns: minmax(176px, 232px) minmax(0, 1fr);
      min-height: 0;
      overflow: hidden;
    }
    .note-outline {
      background: rgba(7,11,18,0.72);
      border-right: 1px solid var(--border);
      color: var(--fg-2);
      min-height: 0;
      overflow-y: auto;
      padding: 18px 14px;
    }
    .note-outline-heading {
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      letter-spacing: 0.08em;
      margin-bottom: 10px;
      text-transform: uppercase;
    }
    .note-outline-list {
      display: flex;
      flex-direction: column;
      gap: 3px;
      list-style: none;
    }
    .note-outline-item {
      padding-left: calc((var(--outline-level, 1) - 1) * 12px);
    }
    .note-outline-link {
      border-radius: var(--radius-sm);
      color: var(--fg-2);
      display: block;
      font-size: var(--text-sm);
      line-height: 1.35;
      overflow: hidden;
      padding: 5px 6px;
      text-decoration: none;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .note-outline-link:hover,
    .note-outline-link:focus {
      background: var(--cyan-muted);
      color: var(--cyan);
      outline: 1px solid var(--border-focus);
      outline-offset: 1px;
    }
    .note-outline-empty-copy {
      color: var(--fg-3);
      font-size: var(--text-sm);
    }
    .note-reading-layout > .note-body {
      min-height: 0;
    }
    @media (max-width: 899px) {
      .note-reading-layout {
        display: flex;
        flex-direction: column;
        overflow: hidden;
      }
      .note-outline {
        border-bottom: 1px solid var(--border);
        border-right: 0;
        flex-shrink: 0;
        max-height: none;
        overflow: visible;
        padding: 12px 16px;
      }
      .note-outline-list {
        display: flex;
        flex-direction: row;
        gap: 8px;
        overflow-x: auto;
        padding-bottom: 2px;
      }
      .note-outline-item {
        flex: 0 0 auto;
        padding-left: 0;
      }
      .note-outline-link {
        max-width: 70vw;
      }
      .note-reading-layout > .note-body {
        flex: 1;
      }
    }
    """


def note_outline_script() -> str:
    """Client-side focus helper for outline anchor activation."""

    return """
  <script data-note-outline-script="true">
  (function () {
    function outlineLinkFrom(event) {
      if (!event.target || !event.target.closest) return null;
      return event.target.closest('[data-note-outline-link="true"]');
    }

    function focusTarget(link) {
      var targetId = link.getAttribute('data-scroll-target');
      if (!targetId) return;
      var target = document.getElementById(targetId);
      if (!target) return;
      if (!target.hasAttribute('tabindex')) {
        target.setAttribute('tabindex', '-1');
        target.setAttribute('data-note-outline-focus-target', 'true');
      }
      target.scrollIntoView({ block: 'start', behavior: 'smooth' });
      target.focus({ preventScroll: true });
    }

    document.addEventListener('click', function (event) {
      var link = outlineLinkFrom(event);
      if (!link) return;
      focusTarget(link);
    });

    document.addEventListener('keydown', function (event) {
      if (event.key !== ' ' && event.key !== 'Spacebar') return;
      var link = outlineLinkFrom(event);
      if (!link) return;
      event.preventDefault();
      link.click();
    });
  }());
  </script>"""


def _render_heading_item(heading: HeadingRef) -> str:
    level = _safe_level(heading.level)
    anchor = _e(heading.anchor)
    text = _e(heading.text)
    return (
        '<li class="note-outline-item" '
        f'data-heading-level="{level}" '
        f'style="--outline-level: {level}">'
        '<a class="note-outline-link" '
        'data-testid="note-outline-link" '
        'data-note-outline-link="true" '
        f'data-scroll-target="{anchor}" '
        f'aria-label="Jump to heading: {text}" '
        f'href="#{anchor}">{text}</a>'
        "</li>"
    )


def _safe_level(level: int) -> int:
    return min(max(int(level), 1), 6)


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)
