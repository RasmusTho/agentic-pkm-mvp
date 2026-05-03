"""Converse layout shell state contract for landscape layouts."""

COLLAPSED_RAIL_WIDTH_PX = 32
EXPANDED_RAIL_WIDTH_PX = 288
DOCUMENT_MAX_WIDTH_PX = 640
TOP_BAR_HEIGHT_PX = 38


class ConverseLayoutState:
    def __init__(
        self,
        *,
        rail_state: str,
        rail_width_px: int,
        document_max_width_px: int,
        rail_class: str,
    ) -> None:
        self.rail_state = rail_state
        self.rail_width_px = rail_width_px
        self.document_max_width_px = document_max_width_px
        self.rail_class = rail_class


def resolve_layout_state(rail_state: str) -> ConverseLayoutState:
    """Map a landscape rail state to deterministic geometry and class tokens."""
    if rail_state == "collapsed":
        return ConverseLayoutState(
            rail_state=rail_state,
            rail_width_px=COLLAPSED_RAIL_WIDTH_PX,
            document_max_width_px=DOCUMENT_MAX_WIDTH_PX,
            rail_class="rail rail--collapsed",
        )
    if rail_state == "expanded":
        return ConverseLayoutState(
            rail_state=rail_state,
            rail_width_px=EXPANDED_RAIL_WIDTH_PX,
            document_max_width_px=DOCUMENT_MAX_WIDTH_PX,
            rail_class="rail rail--expanded",
        )
    raise ValueError(f"Unsupported rail_state: {rail_state}")
