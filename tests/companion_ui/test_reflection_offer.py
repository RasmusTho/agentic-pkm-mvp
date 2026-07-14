from companion_ui.workspace.reflection_offer import render_evening_reflection_offer_html


def test_reflection_offer_renders_only_an_explicit_tap_trigger() -> None:
    markup = render_evening_reflection_offer_html(
        {
            "label": "Reflect on today?",
            "action": "journaling.reflection.begin",
            "tap_required": True,
        }
    )

    assert 'data-requires-explicit-tap="true"' in markup
    assert 'data-action="journaling.reflection.begin"' in markup
    assert "<button" in markup


def test_reflection_offer_refuses_non_tap_payloads() -> None:
    assert (
        render_evening_reflection_offer_html(
            {
                "action": "journaling.reflection.begin",
                "tap_required": False,
            }
        )
        == ""
    )
