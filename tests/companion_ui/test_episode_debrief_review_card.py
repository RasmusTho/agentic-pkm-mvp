"""DEBRIEF-03 rail card: rendered from the runtime projection, two dispositions only."""

from __future__ import annotations

from companion_ui.workspace.episode_debrief_review import EPISODE_DEBRIEFS_ENDPOINT
from companion_ui.workspace.serve_dev_page import make_handler, render_index_html
from tests.companion_ui.test_calibration_revisit_card import _fields


class _Client:
    pass


def test_workspace_rail_renders_client_loaded_debrief_review_card() -> None:
    html = render_index_html(api_base_url="http://127.0.0.1:18001", note_path="Notes/note.md", fields=_fields(None))

    assert 'data-testid="episode-debrief-review"' in html
    assert "episode-debrief-review-controller" in html
    assert f"fetchJson('{EPISODE_DEBRIEFS_ENDPOINT}', {{method: 'GET'}})" in html
    # Only the declared dispositions; no delete affordance exists.
    assert "data-debrief-disposition" in html and "'accepted'" in html and "'dismissed'" in html
    assert "method: 'DELETE'" not in html.split("episode-debrief-review-controller")[1].split("</script>")[0]
    # A failed read is surfaced as unavailable, not rendered as an empty list.
    assert "Debriefs unavailable" in html
    # Loaded only when opened: a plain page load issues no runtime request.
    controller = html.split("episode-debrief-review-controller")[1].split("</script>")[0]
    assert "root.addEventListener('toggle'" in controller
    assert not controller.rstrip().rstrip("})();").rstrip().endswith("load();")


def test_page_proxy_admits_only_the_debrief_projection_and_review_route() -> None:
    handler_cls = make_handler(client=_Client(), api_base_url="http://runtime")
    debrief_id = "debrief-" + "a" * 64

    assert handler_cls.route_allowed("GET", EPISODE_DEBRIEFS_ENDPOINT)
    assert handler_cls.route_allowed("POST", f"{EPISODE_DEBRIEFS_ENDPOINT}/{debrief_id}/review")
    assert not handler_cls.route_allowed("POST", f"{EPISODE_DEBRIEFS_ENDPOINT}/../review")
    assert not handler_cls.route_allowed("DELETE", f"{EPISODE_DEBRIEFS_ENDPOINT}/{debrief_id}")
