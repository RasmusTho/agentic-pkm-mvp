from __future__ import annotations

from app.agents.panel.parser import is_ai_fence, parse_panel


def strip_ai_panels(full_markdown: str) -> str:
    """
    Return markdown with AI panel blocks removed.
    Panels are:
      - fenced blocks between AI fences (%% ...AI... %%),
      - OR (fallback) heading-based panels with ## AI-instruktion/## AI-åtgärder/## AI-logg.
    """
    lines = full_markdown.splitlines()
    state = parse_panel(full_markdown)
    spans = state.spans or []
    if not spans:
        return full_markdown
    to_skip: set[int] = set()
    for start, end in spans:
        if start is None or end is None:
            continue
        for idx in range(max(0, start), min(len(lines) - 1, end) + 1):
            to_skip.add(idx)
    kept = [line for idx, line in enumerate(lines) if idx not in to_skip]
    return "\n".join(kept)


__all__ = ["strip_ai_panels", "is_ai_fence"]
