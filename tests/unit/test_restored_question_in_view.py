"""W87-2 review rounds 1 to 3 (ADR-0175, CHG-074): a question put back after
sign-in ends in view, and the page stops moving it at the person's first
action.

Round 1 scrolled the box into view once, at the restore. The readiness
banner paints after that (it waits for ``/ready``), so at 390 px it pushed
the box back out of view. Round 3 keeps a watch, started first thing in
``boot()``: the restore names the question and checks the box, every
readiness paint (``confirmReadiness``) checks it again, and the watch ends
once, "cancelled" (a wheel, touch, pointer or key, a scroll the page did not
make, a typed change, an error) or "settled" (the boot's last paint), on
``<html data-restore-scroll>``.

Run under Node from the served ``app.js`` with the late-run suite's harness
(``tests/unit/test_late_run_question_rules.py``), with the REAL watch, restore,
readiness and error functions. The page is a small model: the box at 734-890
in an 844 px window; once readiness is confirmed a 159 px banner sits above
it; ``scrollIntoView`` moves the window so the box's bottom is at 828; the
listeners go on a real Node ``EventTarget``. Whether the box is really in
view in a browser is for the signed-in e2e lane (``session-max-age.spec.ts``).
"""

from __future__ import annotations

import json
from typing import Any

from tests.unit.test_late_run_question_rules import KEY, _node

FUNCTIONS = [
    "watchRestoredQuestionScroll",
    "endRestoredQuestionScroll",
    "restoredQuestionMovedUnderVisitor",
    "bringRestoredQuestionIntoView",
    "restoreLateRunQuestion",
    "lateRunQuestionToRestore",
    "confirmReadiness",
    "refreshReadiness",
    "readReadinessIntoCache",
    "armReadinessDisclosureFallback",
    "handleError",
    "showError",
]

QUESTION = "the kept question"

_PAGE = r"""
const BOX_TOP = 734, BOX_H = 156, BANNER = 159, VIEW = 844, MARGIN = 16;
const BODY = { tag: "body" };
const page = {
  banner: false, notice: false, above: 0, scrolls: [], focuses: 0, live: 0, errorFocus: false,
};
const events = new EventTarget();
const storage = window.sessionStorage;
window = {
  scrollY: 0,
  innerHeight: VIEW,
  sessionStorage: storage,
  location: { assign() {}, reload() {} },
  timers: [],
  setTimeout(fn) { this.timers.push(fn); return this.timers.length; },
  addEventListener(type, fn, options) {
    events.addEventListener(type, fn, options);
    page.live += 1;
    if (options && options.signal) {
      options.signal.addEventListener("abort", () => { page.live -= 1; }, { once: true });
    }
  },
  dispatchEvent(event) { return events.dispatchEvent(event); },
};
document = {
  documentElement: { dataset: {} },
  body: BODY,
  activeElement: BODY,
  createElement() {
    return { classList: { add() {} }, dataset: {}, append() {}, appendChild() {} };
  },
};
const boxTopInPage = () => BOX_TOP + page.above + (page.banner ? BANNER : 0);
queryTextarea = {
  value: "",
  dispatchEvent() {},
  getBoundingClientRect() {
    const top = boxTopInPage() - window.scrollY;
    return { top, bottom: top + BOX_H };
  },
  scrollIntoView(options) {
    page.scrolls.push(options);
    window.scrollY = Math.max(0, boxTopInPage() + BOX_H - (VIEW - MARGIN));
  },
  focus() { page.focuses += 1; },
};
applyReadinessState = () => { if (state.readinessConfirmed) page.banner = true; };
el = (id) => (id === "sign-in-notice" && page.notice ? { id } : null);
toast = () => {};
const routes = {};
api = (path) => (routes[path] ? routes[path]() : new Promise(() => {}));
const answerReadiness = () => {
  routes["/ready"] = () => Promise.resolve({ live_readiness: { state: "offline" } });
  routes["/v1/models/defaults"] = () => Promise.resolve({ stale_model_ids: [] });
};
proceedButton = null;
errorRegion = {
  dataset: {},
  hidden: true,
  focus() { document.activeElement = errorRegion; page.errorFocus = true; },
  scrollIntoView() {},
};
errorTitle = {};
errorMessage = { appendChild() {} };
errorActions = { replaceChildren() {}, appendChild() {} };
errorDetail = { replaceChildren() {}, hidden: true };
errorIcon = {};
errorActag = {};
errorFooter = {};
state.sessionAccountId = "A";
const seed = (entry) => window.sessionStorage.setItem(__KEY__, JSON.stringify(entry));
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const result = () => {
  const box = queryTextarea.getBoundingClientRect();
  return {
    inView: box.top >= 0 && box.bottom <= VIEW,
    scrolls: page.scrolls.length,
    blocks: page.scrolls.map((o) => o && o.block),
    attr: document.documentElement.dataset.restoreScroll ?? null,
    live: page.live,
    focuses: page.focuses,
    errorFocus: page.errorFocus,
    value: queryTextarea.value,
  };
};
"""


def _run(steps: str) -> Any:
    body = _PAGE.replace("__KEY__", json.dumps(KEY)) + steps + "\nreturn result();"
    return _node(FUNCTIONS, body)


SAVED = json.dumps({"account": "A", "question": QUESTION})


def test_h1_ready_paints_then_defaults_hangs_the_box_ends_in_view() -> None:
    """H1. ``/ready`` answers and paints the banner; the second defaults
    request never answers. Red when: the check in ``confirmReadiness`` is
    removed (the banner leaves the box out of view), or the check at the
    restore is removed (1 scroll, not 2)."""
    got = _run(
        f"""
        watchRestoredQuestionScroll();
        seed({SAVED});
        await restoreLateRunQuestion();
        routes["/ready"] = () => Promise.resolve({{ live_readiness: {{ state: "offline" }} }});
        refreshReadiness();
        await flush(); await flush();
        """
    )
    assert got["value"] == QUESTION, "partner: the question was put back"
    assert got["inView"] is True
    assert got["scrolls"] == 2
    assert got["attr"] is None, "the watch stays open while a request hangs"


def test_h2_fallback_paint_before_the_restore_then_ready_hangs() -> None:
    """H2. The 2 s fallback paints the banner before the question is put
    back, and ``/ready`` never answers. Red when: the check at the restore is
    removed (0 scrolls, the box out of view)."""
    got = _run(
        f"""
        watchRestoredQuestionScroll();
        armReadinessDisclosureFallback();
        window.timers[0]();
        seed({SAVED});
        await restoreLateRunQuestion();
        refreshReadiness();
        await flush();
        """
    )
    assert got["value"] == QUESTION
    assert got["inView"] is True
    assert got["scrolls"] == 1


def test_h3_a_wheel_before_the_restore_cancels_for_good() -> None:
    """H3, and Codex's last gap 1. A wheel before the question is put back
    ends the watch; the boot's own end later does not overwrite it. Red when:
    the restore creates or resets the watch (scrolls happen), the listeners
    are not removed (5 left), or the end is not idempotent ("settled"
    overwrites "cancelled")."""
    got = _run(
        f"""
        watchRestoredQuestionScroll();
        window.dispatchEvent(new Event("wheel"));
        seed({SAVED});
        await restoreLateRunQuestion();
        answerReadiness();
        await refreshReadiness();
        endRestoredQuestionScroll("settled");
        """
    )
    assert got["value"] == QUESTION, "partner: the question was still put back"
    assert got["scrolls"] == 0
    assert got["attr"] == "cancelled"
    assert got["live"] == 0


def test_h4_an_error_during_boot_wins() -> None:
    """H4. The real ``handleError`` during the boot shows the error box and
    focuses it; no scroll follows. Red when: the cancel at the top of
    ``showError`` is removed (the outcome stays unset). The focus guard alone
    would still stop the scroll; that is the real effect, and this test
    does not hide it."""
    got = _run(
        f"""
        watchRestoredQuestionScroll();
        seed({SAVED});
        await restoreLateRunQuestion();
        handleError(new Error("boom"));
        answerReadiness();
        await refreshReadiness();
        """
    )
    assert got["errorFocus"] is True, "partner: the error box took focus"
    assert got["scrolls"] == 1, "only the restore's own scroll"
    assert got["attr"] == "cancelled"


def test_h5_the_normal_return_ends_in_view_and_settled() -> None:
    """H5 (replaces round 1's "scrolled once, without focus" and round 2's
    "scrolls only as needed", which expected the restore alone to scroll
    once). Red when: the check in ``confirmReadiness`` is removed (out of
    view), the listeners are not removed, the box is focused, or a scroll
    goes further than needed (anything but ``block: "nearest"``)."""
    got = _run(
        f"""
        watchRestoredQuestionScroll();
        seed({SAVED});
        await restoreLateRunQuestion();
        answerReadiness();
        await refreshReadiness();
        endRestoredQuestionScroll("settled");
        """
    )
    assert got["value"] == QUESTION
    assert got["inView"] is True
    assert got["attr"] == "settled"
    assert got["live"] == 0
    assert got["focuses"] == 0
    assert got["blocks"] == ["nearest", "nearest"]


def test_a_typed_change_cancels() -> None:
    """Red when: the check that the box still holds the restored question is
    removed (the page scrolls the box again after the person changed it).
    Partner: H5."""
    got = _run(
        f"""
        watchRestoredQuestionScroll();
        seed({SAVED});
        await restoreLateRunQuestion();
        queryTextarea.value = "typed by hand";
        answerReadiness();
        await refreshReadiness();
        """
    )
    assert got["scrolls"] == 1
    assert got["attr"] == "cancelled"


def test_a_scroll_the_page_did_not_make_cancels() -> None:
    """A script or scrollbar scroll of 100 px after the restore. Red when:
    the scroll listener's check is removed (the banner paint scrolls the box
    back, 2 scrolls). Partner: an 8 px scroll is tolerated as layout noise
    (ADR-0175 Known limits) and the box still ends in view."""
    moved = _run(
        f"""
        watchRestoredQuestionScroll();
        seed({SAVED});
        await restoreLateRunQuestion();
        window.scrollY -= 100;
        window.dispatchEvent(new Event("scroll"));
        answerReadiness();
        await refreshReadiness();
        """
    )
    assert moved["scrolls"] == 1
    assert moved["attr"] == "cancelled"
    nudged = _run(
        f"""
        watchRestoredQuestionScroll();
        seed({SAVED});
        await restoreLateRunQuestion();
        window.scrollY -= 8;
        window.dispatchEvent(new Event("scroll"));
        answerReadiness();
        await refreshReadiness();
        """
    )
    assert nudged["attr"] is None
    assert nudged["scrolls"] == 2
    assert nudged["inView"] is True


def test_nothing_put_back_scrolls_nothing() -> None:
    """Red when: the box is scrolled on a load that put no question back (no
    saved entry, or another account's). Partner: H5 scrolls."""
    none = _run(
        """
        watchRestoredQuestionScroll();
        await restoreLateRunQuestion();
        answerReadiness();
        await refreshReadiness();
        """
    )
    assert none["scrolls"] == 0
    other = _run(
        """
        watchRestoredQuestionScroll();
        seed({ account: "B", question: "typed as B" });
        await restoreLateRunQuestion();
        answerReadiness();
        await refreshReadiness();
        """
    )
    assert other["value"] == ""
    assert other["scrolls"] == 0


def test_a_restore_under_the_sign_in_failure_notice_does_not_scroll() -> None:
    """W87-2 review round 2 (journey E37/E48): on ``/ui?sign_in=failed`` the
    server renders ``#sign-in-notice``, and the scroll pushed it off screen.
    Red when: the guard on ``#sign-in-notice`` is removed. Partner: H5."""
    got = _run(
        f"""
        page.notice = true;
        watchRestoredQuestionScroll();
        seed({SAVED});
        await restoreLateRunQuestion();
        answerReadiness();
        await refreshReadiness();
        endRestoredQuestionScroll("settled");
        """
    )
    assert got["value"] == QUESTION, "partner: the question was put back"
    assert got["scrolls"] == 0
    assert got["focuses"] == 0
    assert got["attr"] == "settled"


def test_focus_placed_elsewhere_is_not_scrolled_away() -> None:
    """The deletion return focuses "Delete my account…". Red when: the focus
    guard is removed (the page scrolls to the box). Partner: H5."""
    got = _run(
        f"""
        document.activeElement = {{ tag: "button" }};
        watchRestoredQuestionScroll();
        seed({SAVED});
        await restoreLateRunQuestion();
        answerReadiness();
        await refreshReadiness();
        """
    )
    assert got["value"] == QUESTION
    assert got["scrolls"] == 0
    assert got["focuses"] == 0


def test_scroll_anchoring_with_the_box_still_on_screen_does_not_cancel() -> None:
    """W87-2 restore race, review round 1: content grows 40 px
    above the view and the browser's scroll anchoring raises ``scrollY`` by
    40 px, so the box stays where it was on screen. Red when: a ``scrollY``
    move alone cancels (af774b2: "cancelled", 1 scroll), or the new place
    is not recorded (a visitor scroll of 40 px back up then reads as a
    layout move and the page places the box again). Partner: the banner
    paint after it still places the box (2 scrolls, in view)."""
    back = _run(
        f"""
        watchRestoredQuestionScroll();
        seed({SAVED});
        await restoreLateRunQuestion();
        page.above += 40;
        window.scrollY += 40;
        window.dispatchEvent(new Event("scroll"));
        window.scrollY -= 40;
        window.dispatchEvent(new Event("scroll"));
        """
    )
    assert back["attr"] == "cancelled"
    assert back["scrolls"] == 1
    got = _run(
        f"""
        watchRestoredQuestionScroll();
        seed({SAVED});
        await restoreLateRunQuestion();
        page.above += 40;
        window.scrollY += 40;
        window.dispatchEvent(new Event("scroll"));
        answerReadiness();
        await refreshReadiness();
        """
    )
    assert got["attr"] is None
    assert got["scrolls"] == 2
    assert got["inView"] is True


def test_a_visitor_scroll_after_a_small_anchored_drift_cancels() -> None:
    """W87-2 restore race, review round 2: content grows 47 px above the view
    and scroll anchoring raises ``scrollY`` by 40 px, so the box drifts 7 px
    on screen; then a script scrolls the view 10 px. Red when: the anchored
    step records only ``scrollY`` (the box then reads 3 px from its record and
    the scroll is missed), or the listener is main c40159e's. ADR-0175 keeps
    this choice (its known limits, "Two layout moves in turn"). Partner: the
    drift alone leaves the watch on."""
    drift = f"""
        watchRestoredQuestionScroll();
        seed({SAVED});
        await restoreLateRunQuestion();
        page.above += 47;
        window.scrollY += 40;
        window.dispatchEvent(new Event("scroll"));
    """
    alone = _run(drift)
    assert alone["attr"] is None
    got = _run(
        drift
        + """
        window.scrollY += 10;
        window.dispatchEvent(new Event("scroll"));
        """
    )
    assert got["attr"] == "cancelled"


def test_a_layout_move_with_the_view_still_places_the_box_again() -> None:
    """W87-2 restore race (X4 at unit level): the
    layout moves the box 44 px down and ``scrollY`` does not move. Red when:
    the listener cancels (main c40159e) or does nothing (1 scroll, the box
    out of view) in that case. Partner: the restore's own scroll (1 before)."""
    got = _run(
        f"""
        watchRestoredQuestionScroll();
        seed({SAVED});
        await restoreLateRunQuestion();
        const before = page.scrolls.length;
        page.above += 44;
        window.dispatchEvent(new Event("scroll"));
        const r = result();
        r.before = before;
        return r;
        """
    )
    assert got["before"] == 1
    assert got["attr"] is None
    assert got["scrolls"] == 2
    assert got["inView"] is True


def test_two_small_scrolls_add_up_and_cancel() -> None:
    """W87-2 restore race, review round 1: two script scrolls of 5 px each,
    with no layout move. Red when: a scroll under the tolerance resets the
    baseline (the two never add up to 10 px, so nothing cancels). Partner:
    one 5 px scroll alone leaves the watch on."""
    once = _run(
        f"""
        watchRestoredQuestionScroll();
        seed({SAVED});
        await restoreLateRunQuestion();
        window.scrollY -= 5;
        window.dispatchEvent(new Event("scroll"));
        """
    )
    assert once["attr"] is None
    twice = _run(
        f"""
        watchRestoredQuestionScroll();
        seed({SAVED});
        await restoreLateRunQuestion();
        window.scrollY -= 5;
        window.dispatchEvent(new Event("scroll"));
        window.scrollY -= 5;
        window.dispatchEvent(new Event("scroll"));
        """
    )
    assert twice["attr"] == "cancelled"


def test_a_scroll_whose_event_has_not_fired_still_cancels_a_placement() -> None:
    """W87-2 restore race, the Linux re-measure (2026-10-25): a browser fires
    the ``scroll`` event for a scroll at the next frame, so a readiness paint
    can place the box between the scroll and its event. Here the layout moves
    the box 44 px and a script scrolls the view 100 px, then readiness paints
    before the event. Red when: the placement records the new place without
    first checking the records (it pulls the view back, 2 scrolls, and the
    late event finds nothing to cancel). Partner: the same layout move with no
    scroll is placed again (2 scrolls, in view, the watch on)."""
    layout_only = _run(
        f"""
        watchRestoredQuestionScroll();
        seed({SAVED});
        await restoreLateRunQuestion();
        page.above += 44;
        answerReadiness();
        await refreshReadiness();
        """
    )
    assert layout_only["attr"] is None
    assert layout_only["scrolls"] == 2
    assert layout_only["inView"] is True
    got = _run(
        f"""
        watchRestoredQuestionScroll();
        seed({SAVED});
        await restoreLateRunQuestion();
        page.above += 44;
        window.scrollY += 100;
        answerReadiness();
        await refreshReadiness();
        window.dispatchEvent(new Event("scroll"));
        """
    )
    assert got["attr"] == "cancelled"
    assert got["scrolls"] == 1


def test_a_scroll_whose_event_has_not_fired_cancels_at_the_boots_end() -> None:
    """W87-2 restore race, the Linux re-measure: the same scroll, with the
    boot's end ("settled") reached before its event. Red when: the end
    records "settled" without checking the records. Partner: with no scroll
    the end records "settled"."""
    still = _run(
        f"""
        watchRestoredQuestionScroll();
        seed({SAVED});
        await restoreLateRunQuestion();
        endRestoredQuestionScroll("settled");
        """
    )
    assert still["attr"] == "settled"
    got = _run(
        f"""
        watchRestoredQuestionScroll();
        seed({SAVED});
        await restoreLateRunQuestion();
        page.above += 44;
        window.scrollY += 100;
        endRestoredQuestionScroll("settled");
        """
    )
    assert got["attr"] == "cancelled"
