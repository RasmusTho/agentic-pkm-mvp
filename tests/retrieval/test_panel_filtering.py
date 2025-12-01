from __future__ import annotations

import textwrap

from app.agents.panel.filters import strip_ai_panels
from app.retrieval.hybrid import get_store


def test_strip_ai_panels_removes_fenced_content() -> None:
    markdown = textwrap.dedent(
        """
        # Note with panel

        This is real content before.

        %% AI:Start %%
        ## AI-instruktion
        Fact check: The Earth has two moons.
        ## AI-åtgärder
        - [ ] ...
        ## AI-logg
        - inserted by system
        %% AI:End %%

        This is real content after.
        """
    )
    stripped = strip_ai_panels(markdown)
    assert "The Earth has two moons" not in stripped
    assert "This is real content before." in stripped
    assert "This is real content after." in stripped


def test_strip_ai_panels_removes_heading_only_panels() -> None:
    markdown = textwrap.dedent(
        """
        # Note with legacy panel

        This is before.

        ## AI-instruktion
        Panel content should go away.
        ## AI-åtgärder
        - [ ] Do not leak
        ## AI-logg
        - logged

        This is after.
        """
    )
    stripped = strip_ai_panels(markdown)
    assert "Panel content should go away" not in stripped
    assert "Do not leak" not in stripped
    assert "logged" not in stripped
    assert "This is before." in stripped
    assert "This is after." in stripped


def test_hybrid_store_does_not_contain_panel_text() -> None:
    markdown = textwrap.dedent(
        """
        # Note with panel

        Before panel text.

        %% ai panel %%
        ## AI-instruktion
        Fact check: The Earth has two moons.
        %% ai %%

        After panel text.
        """
    )
    store = get_store()
    store.set_documents([])
    store.add_document(doc_id="note1", text=strip_ai_panels(markdown), source_ref="note.md")
    docs = store.all()
    assert docs
    assert all("The Earth has two moons" not in doc.text for doc in docs)
    assert any("Before panel text." in doc.text for doc in docs)
    assert any("After panel text." in doc.text for doc in docs)
