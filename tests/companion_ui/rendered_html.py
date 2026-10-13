"""Inspect emitted DOM elements without counting selectors in script text."""
from html.parser import HTMLParser


def elements_with_test_id(html: str, test_id: str) -> list[dict[str, str | None]]:
    class Elements(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.elements: list[dict[str, str | None]] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            attributes = dict(attrs)
            if attributes.get("data-testid") == test_id:
                self.elements.append(attributes)

    parser = Elements()
    parser.feed(html)
    return parser.elements
