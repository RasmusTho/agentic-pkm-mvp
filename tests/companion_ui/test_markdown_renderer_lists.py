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
