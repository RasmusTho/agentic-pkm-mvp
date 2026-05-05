"""Converse layout shell state contract for landscape, drawer, and portrait layouts."""

COLLAPSED_RAIL_WIDTH_PX = 32
EXPANDED_RAIL_WIDTH_PX = 288
DOCUMENT_MAX_WIDTH_PX = 640
TOP_BAR_HEIGHT_PX = 38

PORTRAIT_SHEET_COLLAPSED_HEIGHT_PX = 32
PORTRAIT_SHEET_PEEK_HEIGHT_PX = 240
PORTRAIT_SHEET_FULL_HEIGHT_VH = 80


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


class SessionDrawerState:
    def __init__(self, *, drawer_open: bool, drawer_state: str, drawer_class: str) -> None:
        self.drawer_open = drawer_open
        # data-drawer-state attribute value: "open" | "closed" — CSS selectors target this
        self.drawer_state = drawer_state
        self.drawer_class = drawer_class


class BottomSheetState:
    def __init__(
        self,
        *,
        sheet_snap: str,
        sheet_height_px: int | None,
        sheet_height_vh: int | None,
    ) -> None:
        self.sheet_snap = sheet_snap          # data-sheet-snap attribute value — CSS selectors target this
        self.sheet_height_px = sheet_height_px
        self.sheet_height_vh = sheet_height_vh
        self.sheet_class = "bottom-sheet"     # base class only; snap state is carried by sheet_snap


def resolve_session_drawer_state(*, drawer_open: bool) -> SessionDrawerState:
    """Map drawer open/closed boolean to data-attribute value and base class token."""
    if drawer_open:
        return SessionDrawerState(
            drawer_open=True,
            drawer_state="open",
            drawer_class="session-drawer-overlay",
        )
    return SessionDrawerState(
        drawer_open=False,
        drawer_state="closed",
        drawer_class="session-drawer-overlay",
    )


def resolve_portrait_layout_state(*, sheet_snap: str) -> BottomSheetState:
    """Map a portrait bottom-sheet snap point to geometry tokens.

    sheet_snap is the value for the data-sheet-snap attribute; CSS height
    selectors (.bottom-sheet[data-sheet-snap="peek"] etc.) target it directly.
    """
    if sheet_snap == "collapsed":
        return BottomSheetState(
            sheet_snap=sheet_snap,
            sheet_height_px=PORTRAIT_SHEET_COLLAPSED_HEIGHT_PX,
            sheet_height_vh=None,
        )
    if sheet_snap == "peek":
        return BottomSheetState(
            sheet_snap=sheet_snap,
            sheet_height_px=PORTRAIT_SHEET_PEEK_HEIGHT_PX,
            sheet_height_vh=None,
        )
    if sheet_snap == "full":
        return BottomSheetState(
            sheet_snap=sheet_snap,
            sheet_height_px=None,
            sheet_height_vh=PORTRAIT_SHEET_FULL_HEIGHT_VH,
        )
    raise ValueError(f"Unsupported sheet_snap: {sheet_snap!r}")


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
