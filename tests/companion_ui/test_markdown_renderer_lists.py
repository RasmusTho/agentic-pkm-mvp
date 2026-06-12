"""Markdown list rendering against Obsidian reference (#1410).

Covers the UAT note sections 3.1 (bulleted), 3.2 (numbered), 3.3 (task list):
- nested bulleted lists indent under their parent bullet;
- nested ordered lists render in a nested <ol> (restarting at 1), not as
  continued top-level items 4/5;
- checked task items render with an unambiguous checked state + completed
  treatment; unchecked tasks stay unchecked;
- bold and inline code inside list/task items still render.
"""

from __future__ import annotations

import re

from companion_ui.renderer.vault_markdown_renderer import render_vault_markdown
from companion_ui.workspace.serve_dev_page import render_index_html


def _html(md: str) -> str:
    return render_vault_markdown(md).html


# ---------------------------------------------------------------------------
# 3.1 — nested bulleted lists
# ---------------------------------------------------------------------------


def test_nested_bulleted_lists_indent_under_parent():
    md = "- Item A\n- Item B\n    - Nested bullet B\n- Item C\n"
    html = _html(md)
    # The nested bullet lives in a <ul> nested inside the Item B <li>, not as a
    # flat sibling.
    assert re.search(r"<li>Item B<ul><li>Nested bullet B</li></ul></li>", html), html
    # The flat-list bug (nested item as a sibling) must be gone.
    assert "<li>Nested bullet B</li><li>Item C</li>" not in html


def test_nested_bulleted_lists_allow_blank_spacer_lines():
    md = "- Item A\n\n- Item B\n\n    - Nested bullet B\n\n- Item C\n"
    html = _html(md)

    assert re.search(r"<li>Item B<ul><li>Nested bullet B</li></ul></li>", html), html
    assert html.count("<ul>") == 2


# ---------------------------------------------------------------------------
# 3.2 — nested ordered lists restart numbering
# ---------------------------------------------------------------------------


def test_nested_ordered_lists_render_nested_ol():
    md = (
        "1. First numbered item\n"
        "2. Second numbered item\n"
        "3. Third numbered item\n"
        "    1. Nested numbered item\n"
        "    2. Another nested numbered item\n"
    )
    html = _html(md)
    # Nested ordered items belong to a nested <ol> inside the third <li> so the
    # browser restarts numbering at 1 — they are NOT emitted as items 4/5.
    assert re.search(
        r"<li>Third numbered item<ol><li>Nested numbered item</li>"
        r"<li>Another nested numbered item</li></ol></li>",
        html,
    ), html
    # Exactly two <ol> open tags (outer + nested).
    assert html.count("<ol>") == 2


def test_nested_ordered_lists_allow_blank_spacer_lines():
    md = (
        "1. First numbered item\n\n"
        "2. Second numbered item\n\n"
        "3. Third numbered item\n\n"
        "    1. Nested numbered item\n\n"
        "    2. Another nested numbered item\n"
    )
    html = _html(md)

    assert re.search(
        r"<li>Third numbered item<ol><li>Nested numbered item</li>"
        r"<li>Another nested numbered item</li></ol></li>",
        html,
    ), html
    assert html.count("<ol>") == 2


# ---------------------------------------------------------------------------
# 3.3 — task list checked/unchecked
# ---------------------------------------------------------------------------


def test_checked_task_has_unambiguous_checked_state():
    html = _html("- [x] Completed task\n")
    li = re.search(r'<li class="task-list-item"[^>]*>.*?</li>', html, re.S).group(0)
    assert 'data-task-state="x"' in li
    assert "<input type=\"checkbox\" disabled checked>" in li or "checked>" in li


def test_unchecked_task_remains_unchecked():
    html = _html("- [ ] Open task\n")
    li = re.search(r'<li class="task-list-item"[^>]*>.*?</li>', html, re.S).group(0)
    assert 'data-task-state=" "' in li
    assert "checked" not in li
    assert "<input type=\"checkbox\" disabled>" in li


def test_panel_selectable_option_checkbox_is_clickable_with_projection_attrs():
    md = "- [ ] Send email <!--ai:option_id=opt_ui--> <!--ai:id=send.email--> <!--ai:proposed=979-->\n"
    rendered = render_vault_markdown(
        md,
        panel_selectable_options=[
            {
                "artifact_id": "note-uuid-1",
                "note_path": "notes/panel.md",
                "panel_id": "panel-1",
                "option_id": "opt_ui",
                "action_id": "send.email",
                "label": "Send email",
                "checked": False,
                "proposal_pending": True,
                "source_range": {"start_line": 0, "end_line": 1},
                "source_hash": "source-hash",
                "content_hash": "content-hash",
                "selectable": True,
            }
        ],
    )

    li = re.search(r'<li class="task-list-item"[^>]*>.*?</li>', rendered.html, re.S).group(0)
    assert 'data-panel-checkbox="true"' in li
    assert 'data-panel-id="panel-1"' in li
    assert 'data-option-id="opt_ui"' in li
    assert 'data-source-hash="source-hash"' in li
    assert 'data-content-hash="content-hash"' in li
    assert "notes/panel.md lines 1-1; source hash source-hash" in li
    assert "notes/panel.md lines 0-1" not in li
    assert "<input type=\"checkbox\" disabled" not in li


def test_renderer_does_not_enable_task_without_runtime_declared_option():
    md = "- [ ] Send email <!--ai:option_id=opt_ui--> <!--ai:id=send.email--> <!--ai:proposed=979-->\n"
    html = render_vault_markdown(md, panel_selectable_options=[]).html
    li = re.search(r'<li class="task-list-item"[^>]*>.*?</li>', html, re.S).group(0)

    assert 'data-panel-checkbox="true"' not in li
    assert "<input type=\"checkbox\" disabled>" in li


def test_panel_checkbox_source_line_matches_full_markdown_with_frontmatter():
    md = (
        "---\n"
        "uuid: note-uuid-1\n"
        "---\n\n"
        "# Note\n\n"
        "- [ ] Send email <!--ai:option_id=opt_ui--> <!--ai:id=send.email--> <!--ai:proposed=979-->\n"
    )
    html = render_vault_markdown(
        md,
        panel_selectable_options=[
            {
                "artifact_id": "note-uuid-1",
                "note_path": "notes/panel.md",
                "panel_id": "panel-1",
                "option_id": "opt_ui",
                "action_id": "send.email",
                "label": "Send email",
                "checked": False,
                "proposal_pending": True,
                "source_range": {"start_line": 6, "end_line": 7},
                "source_hash": "source-hash",
                "content_hash": "content-hash",
                "selectable": True,
            }
        ],
    ).html

    assert 'data-panel-checkbox="true"' in html


def test_task_list_allows_blank_spacer_lines():
    html = _html("- [ ] Open task\n\n- [x] Completed task\n")

    assert html.count('<ul class="task-list">') == 1
    assert html.count('class="task-list-item"') == 2


def test_blank_separated_mixed_list_types_keep_marker_semantics():
    html = _html("- bullet\n\n1. ordered\n")

    assert re.search(r"<ul><li>bullet</li></ul><ol><li>ordered</li></ol>", html), html


def test_checked_task_has_completed_styling_hook_in_page_css():
    # The page provides a completed (strikethrough/muted) treatment keyed on the
    # checked task state, comparable to Obsidian.
    page = render_index_html(api_base_url="http://127.0.0.1:18001", note_path="")
    m = re.search(
        r'li\.task-list-item\[data-task-state="x"\][^{]*\{([^}]*)\}', page
    )
    assert m, "missing completed-task CSS rule for data-task-state=x"
    assert "line-through" in m.group(1)


def test_bold_and_inline_code_in_list_items():
    html = _html("- **bold item** with `code`\n")
    assert "<strong>bold item</strong>" in html
    assert "<code>code</code>" in html


def test_bold_and_inline_code_in_task_items():
    html = _html("- [ ] task with **bold** and `code`\n")
    assert "<strong>bold</strong>" in html
    assert "<code>code</code>" in html
