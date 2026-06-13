"""Architecture map — proactive reach-out gate (diagram arrow 3; issue #1964, gated on #1881).

Two layers, deliberately separated so the map is honest:

* The reach-out *decision logic* is BUILT and unit-tested — these tests PASS.
  They pin the scarcity contract: urgency must clear the context-dependent
  interruption threshold; the zero-tolerance floor never pushes; a below-threshold
  moment defers to the glance surface (never dropped); blocked writes / declared
  suppression also defer.
* The reach-out is wired into the governed relevance tick by #1964; the runtime
  call site must remain in app/watcher or app/api.
"""

from __future__ import annotations

import inspect

import app.watcher.relevance_tick as relevance_tick_mod
import app.watcher.watcher as watcher_mod
from app.relevance.attention_loop import decide_reachout
from app.relevance.interruptibility import threshold_for


def test_urgency_must_clear_the_threshold_to_reach_out() -> None:
    """At 'home', in-app fires at 'timely', OS-push at 'pressing'."""

    home = threshold_for("home")
    assert decide_reachout("routine", home)[0] == "defer"
    assert decide_reachout("timely", home)[:2] == ("in_app", "in_app_nudge")
    assert decide_reachout("pressing", home)[:2] == ("push", "os_push")
    assert decide_reachout("critical", home)[0] == "push"


def test_zero_tolerance_floor_never_pushes() -> None:
    """Sleep / DND is a hard floor: even a critical moment only defers to glance."""

    sleep = threshold_for("sleep")
    assert sleep.zero_tolerance is True
    outcome, rung, _ = decide_reachout("critical", sleep)
    assert outcome == "defer" and rung == "glance"


def test_below_threshold_defers_and_is_not_dropped() -> None:
    """In 'focus', a 'timely' moment is held back to the glance surface, not lost."""

    focus = threshold_for("focus")
    outcome, rung, _ = decide_reachout("timely", focus)
    assert outcome == "defer" and rung == "glance"


def test_blocked_writes_and_suppression_defer() -> None:
    """If the health gate blocks writes, or a pattern suppresses, the moment defers."""

    home = threshold_for("home")
    assert decide_reachout("critical", home, writes_blocked=True)[0] == "defer"
    assert decide_reachout("critical", home, suppressed=True)[0] == "defer"


def test_reachout_is_invoked_by_a_runtime_loop() -> None:
    """Arrow 3 wiring: a runtime entrypoint must drive AttentionLoop on a tick.

    #1964 wires it into the relevance tick, which is invoked from the watcher.
    """

    wired = "AttentionLoop" in inspect.getsource(watcher_mod) or "AttentionLoop" in inspect.getsource(
        relevance_tick_mod
    )
    assert wired, "no runtime loop invokes the proactive AttentionLoop yet"
