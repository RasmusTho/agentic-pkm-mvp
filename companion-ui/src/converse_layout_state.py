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
    def __init__(self, *, drawer_open: bool, drawer_class: str) -> None:
        self.drawer_open = drawer_open
        self.drawer_class = drawer_class


class BottomSheetState:
    def __init__(
        self,
        *,
        sheet_snap: str,
        sheet_height_px: int | None,
        sheet_height_vh: int | None,
        sheet_class: str,
    ) -> None:
        self.sheet_snap = sheet_snap
        self.sheet_height_px = sheet_height_px
        self.sheet_height_vh = sheet_height_vh
        self.sheet_class = sheet_class


def resolve_session_drawer_state(*, drawer_open: bool) -> SessionDrawerState:
    """Map drawer open/closed boolean to class tokens."""
    if drawer_open:
        return SessionDrawerState(
            drawer_open=True,
            drawer_class="session-drawer-overlay session-drawer-overlay--open",
        )
    return SessionDrawerState(
        drawer_open=False,
        drawer_class="session-drawer-overlay session-drawer-overlay--closed",
    )


def resolve_portrait_layout_state(*, sheet_snap: str) -> BottomSheetState:
    """Map a portrait bottom-sheet snap point to geometry and class tokens."""
    if sheet_snap == "collapsed":
        return BottomSheetState(
            sheet_snap=sheet_snap,
            sheet_height_px=PORTRAIT_SHEET_COLLAPSED_HEIGHT_PX,
            sheet_height_vh=None,
            sheet_class="bottom-sheet bottom-sheet--collapsed",
        )
    if sheet_snap == "peek":
        return BottomSheetState(
            sheet_snap=sheet_snap,
            sheet_height_px=PORTRAIT_SHEET_PEEK_HEIGHT_PX,
            sheet_height_vh=None,
            sheet_class="bottom-sheet bottom-sheet--peek",
        )
    if sheet_snap == "full":
        return BottomSheetState(
            sheet_snap=sheet_snap,
            sheet_height_px=None,
            sheet_height_vh=PORTRAIT_SHEET_FULL_HEIGHT_VH,
            sheet_class="bottom-sheet bottom-sheet--full",
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
