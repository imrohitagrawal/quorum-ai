"""W54 step 3, review round 2: the PDF sandbox (ADR-0153) after 1992d44.

* R2-PGID (Codex) -- on a normal exit the child is reaped BEFORE its group
  is killed, so the group id may already belong to someone else.
* R2-1 (break-it) -- a page or preview made only of lone surrogates is
  counted (N, P or Q) and hides "(no page could be read)", yet is empty in
  the prompt.
* R2-3 (break-it, a MEASUREMENT, Linux only) -- does a valid PDF still get
  read at niceness 19 with one busy niceness-0 process on the same CPU?
* Coverage of the reader's remaining paths: the outer guard, a child that
  ends its reply but does not exit, a child that never reads its input, and
  a child object without pipes.

Hostile children run through ``tests.pdf_fixtures.ChildLaunches`` (the
program is swapped; every launch argument the code chose is kept). Real
children run, so the module is ``env_oracle``. Each test names what turns it
red.
"""

from __future__ import annotations

import dataclasses
import os
import selectors
import subprocess
import sys
import time
import types
import unicodedata
from decimal import Decimal
from typing import Any

import pytest
from tests import pdf_fixtures as pdfs
from tests.subprocess_env import env_without_coverage

from product_app import evaluation, source_fetcher
from product_app.config import settings
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    SourceReference,
)

pytestmark = pytest.mark.env_oracle

NO_PAGE_LINE = "(no page could be read)"
ANSWER = "Retention rose to 90 percent in the 2024 survey of participating firms [1]."


def _gone(pid: int | None, *, within: float = 1.0) -> bool:
    """True once ``pid`` no longer exists (a zombie still exists)."""
    assert pid is not None, "the child was never launched"
    give_up = time.monotonic() + within
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        if time.monotonic() >= give_up:
            return False
        time.sleep(0.02)


def _exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _slot_is_free() -> bool:
    """The one-child slot is free when a readable PDF is read at once."""
    text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0)
    return outcome == "fetched" and "PDFSENTINEL" in text


# ---------------------------------------------------------------------------
# R2-PGID: kill the group while the child is still unreaped
# ---------------------------------------------------------------------------


def test_r2_the_group_is_killed_before_the_child_is_reaped_on_a_normal_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A REAL child reads a valid PDF and exits on its own. At the moment of
    the first ``os.killpg`` on its group, the child must not yet be reaped:
    ``Popen.returncode`` still None and the pid still present (a zombie
    holds it, so the group id cannot have been reused). RED IF: the first
    group kill comes after the reap (on 159286f: ``child.wait`` then
    ``killpg``), no group kill is sent at all, or the child is left
    unreaped afterwards. Partners: the outcome is still ``fetched`` with the
    text intact and the exit status 0 (the kill after the exit changed
    nothing)."""
    spy = pdfs.ChildLaunches().install(monkeypatch)
    at_kill: list[tuple[bool, bool]] = []  # (returncode still None, pid present)
    real_killpg = os.killpg

    def recording_killpg(pgid: int, sig: int) -> None:
        for launch in spy.launches:
            if launch.pid == pgid:
                at_kill.append((launch.process.returncode is None, _exists(pgid)))
        real_killpg(pgid, sig)

    monkeypatch.setattr(os, "killpg", recording_killpg)
    text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0)
    assert outcome == "fetched", outcome
    assert "PDFSENTINEL" in text
    (launch,) = spy.launches
    assert at_kill, "the child's group was never killed"
    assert at_kill[0] == (True, True), at_kill
    assert launch.process.returncode == 0
    assert _gone(launch.pid)


def test_r2_a_child_ended_by_sigxcpu_is_still_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The partner on the other exit path: a child that dies of ``SIGXCPU``
    (the 2 s CPU limit's signal) is ``timeout``, and gone afterwards. RED
    IF: killing the group before reaping changes how that exit is read."""
    spy = pdfs.ChildLaunches(program=pdfs.SELF_SIGXCPU).install(monkeypatch)
    assert source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0) == ("", "timeout")
    (launch,) = spy.launches
    assert _gone(launch.pid)


# ---------------------------------------------------------------------------
# R2-1: an item made only of lone surrogates counts as nothing
# ---------------------------------------------------------------------------

ONLY_SURROGATES = "\ud800 \udc00 " * 100
READABLE_WITH_SURROGATES = "READABLEPAGE " + "evidence text \ud800 " * 30 + "READABLETAIL"


def _source(url: str, excerpt: str) -> SourceReference:
    return SourceReference(
        title=f"Title {url}",
        url=url,
        provider=ProviderPath.OPENROUTER_SEARCH,
        is_fallback=False,
        excerpt=excerpt,
    )


def _answer(sources: list[SourceReference]) -> InitialModelAnswer:
    return InitialModelAnswer(
        slot_number=1,
        model_id="vendor/model-a",
        display_name="Model A",
        answer_text=ANSWER,
        sources=sources,
        provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
        provider_path=ProviderPath.OPENROUTER_SEARCH,
        fallback_used=False,
        status=InitialAnswerStatus.COMPLETED,
        latency_ms=10,
        citation_coverage=CitationCoverage(
            answer_count=1,
            sourced_answer_count=1,
            sourced_answer_ratio=Decimal(1),
            target_met=True,
        ),
    )


def _row(url: str, outcome: str, text: str = "") -> source_fetcher.FetchedSource:
    return source_fetcher.FetchedSource(
        url=url,
        outcome=outcome,  # type: ignore[arg-type]
        final_status=200 if outcome == "fetched" else None,
        bytes_read=len(text),
        truncated=False,
        elapsed_seconds=0.0,
        text=text,
        fetched_at="2026-10-08T00:00:00Z",
        server_date=None,
        last_modified=None,
    )


def _read_and_prompt(
    monkeypatch: pytest.MonkeyPatch, rows: list[tuple[str, str, str, str]]
) -> tuple[Any, str]:
    """``rows`` is (url, outcome, page text, excerpt). The fetcher is
    replaced by one returning those rows; the result of
    ``judge_source_pages`` is built into the v2 prompt."""
    monkeypatch.setattr(settings, "quorum_source_fetch_max_text_chars", 4_000)
    monkeypatch.setattr(settings, "quorum_source_fetch_max_pages", 8)
    by_url = {url: _row(url, outcome, text) for url, outcome, text, _ in rows}
    monkeypatch.setattr(
        source_fetcher,
        "fetch_cited_pages",
        lambda urls, **_kwargs: tuple(by_url[u] for u in urls),
    )
    answers = [_answer([_source(url, excerpt) for url, _, _, excerpt in rows])]
    result = evaluation.judge_source_pages(answers)
    evidence = evaluation.build_judge_evidence(
        query_text="What retention figure do the pages report?",
        initial_answers=answers,
        final_synthesis=None,
    )
    evidence = dataclasses.replace(
        evidence, source_pages=result.pages, source_page_same_as=result.same_as
    )
    _system, user = evaluation.build_judge_pages_prompt(evidence)
    return result, user


@pytest.mark.parametrize(
    ("outcome", "page", "excerpt", "count"),
    [
        ("fetched", ONLY_SURROGATES, "", "read"),
        ("refused_robots", "", ONLY_SURROGATES, "preview"),
        ("http_error", "", ONLY_SURROGATES, "preview_other"),
    ],
    # Plain ids: a lone surrogate in a test id cannot be written to JUnit XML.
    ids=["page-counted-in-n", "preview-counted-in-p", "preview-counted-in-q"],
)
def test_r2_1_an_item_of_only_lone_surrogates_is_not_counted(
    monkeypatch: pytest.MonkeyPatch, outcome: str, page: str, excerpt: str, count: str
) -> None:
    """RED IF: a page or preview made only of lone surrogates (and spaces)
    is counted in N, P or Q, or, being the only item, it hides
    "(no page could be read)" from the prompt (on 159286f it is counted 1
    and the line is missing, while the item itself is empty in the
    prompt). Partner: no lone surrogate reaches the prompt."""
    result, user = _read_and_prompt(
        monkeypatch, [("https://a.example/doc", outcome, page, excerpt)]
    )
    assert getattr(result, count) == 0, (count, result)
    assert (result.read, result.preview, result.preview_other) == (0, 0, 0)
    assert NO_PAGE_LINE in user
    assert not any(unicodedata.category(c) == "Cs" for c in user)


def test_r2_1_readable_text_with_some_lone_surrogates_is_counted_and_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The partner: a fetched page and an unread page's preview that hold
    readable words among lone surrogates are counted (N = 1, Q = 1) and
    their words reach the prompt, without the surrogates and without
    "(no page could be read)". RED IF: the fix drops the whole item."""
    rows = [
        ("https://a.example/doc", "fetched", READABLE_WITH_SURROGATES, ""),
        ("https://b.example/doc", "http_error", "", "PREVIEWWORDS \ud800 seen in search"),
    ]
    result, user = _read_and_prompt(monkeypatch, rows)
    assert (result.read, result.preview_other) == (1, 1)
    assert "READABLEPAGE" in user and "READABLETAIL" in user and "PREVIEWWORDS" in user
    assert NO_PAGE_LINE not in user
    assert not any(unicodedata.category(c) == "Cs" for c in user)


# ---------------------------------------------------------------------------
# R2-3: niceness 19 against a busy neighbour on the same CPU (Linux)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform != "linux", reason="os.sched_setaffinity is Linux-only; a CI measurement"
)
def test_linux_r2_3_a_pdf_is_read_beside_a_busy_process_on_the_same_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A MEASUREMENT the session wants from CI. One busy loop at niceness 0
    and the PDF child (niceness 19, set by the code) are pinned to the SAME
    CPU: the busy loop pins itself, the child is pinned by the spy's
    ``preexec`` seam (after fork, before exec; the code's own launch is
    otherwise unchanged). Linux CFS gives niceness 19 about 1.4% of a CPU
    against one niceness-0 thread, so this may be RED: that is what we want
    to learn. RED IF: the valid PDF is not ``fetched``. Partner: the busy
    loop was running before and after the read, so there was contention."""
    # The affinity calls exist on Linux only; typed loosely so the type
    # check passes on macOS, where the skip mark keeps this test from running.
    linux_os: Any = os
    cpu = min(linux_os.sched_getaffinity(0))
    busy = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"import os\nos.sched_setaffinity(0, {{{cpu}}})\nwhile True:\n    pass\n",
        ],
        env=env_without_coverage(),
    )
    try:
        time.sleep(0.3)
        assert busy.poll() is None, "the busy loop did not start"
        assert linux_os.sched_getaffinity(busy.pid) == {cpu}

        def pin() -> None:
            linux_os.sched_setaffinity(0, {cpu})

        spy = pdfs.ChildLaunches(preexec=pin).install(monkeypatch)
        started = time.monotonic()
        text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=3.0)
        elapsed = time.monotonic() - started
        assert busy.poll() is None, "the busy loop stopped during the read"
        assert len(spy.launches) == 1
        assert outcome == "fetched", (outcome, round(elapsed, 2))
        assert "PDFSENTINEL" in text
    finally:
        busy.kill()
        busy.wait(timeout=5)


# ---------------------------------------------------------------------------
# Coverage of the reader's other paths, with behavioural assertions
# ---------------------------------------------------------------------------


def test_a_failure_inside_the_exchange_is_unusable_kills_the_child_and_frees_the_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``read_pdf_text``'s outer guard: an ``OSError`` raised while talking to
    the child (here: no selector can be made). RED IF: it raises into the
    caller, is reported as anything but ``("", "unusable")``, leaves the
    child running, or leaves the one-child slot taken."""

    def no_selector() -> selectors.BaseSelector:
        raise OSError("no selector available")

    spy = pdfs.ChildLaunches().install(monkeypatch)
    monkeypatch.setattr(selectors, "DefaultSelector", no_selector)
    assert source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0) == (
        "",
        "unusable",
    )
    monkeypatch.undo()
    (launch,) = spy.launches
    assert _gone(launch.pid)
    assert _slot_is_free()


def test_a_child_that_ends_its_reply_but_keeps_running_is_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The child writes a VALID reply, closes its stdout and sleeps 10 s, so
    its exit status is never known in time. RED IF: the outcome is not
    ``("", "timeout")`` (a reply without an exit status must not be read),
    the call does not end at the 3 s wall kill (between 2.9 and 4.0 s with
    10 s of budget), the child is left running, or the slot is left taken."""
    spy = pdfs.ChildLaunches(
        program=pdfs.closes_stdout_and_keeps_running(pdfs.EVIDENCE * 3)
    ).install(monkeypatch)
    started = time.monotonic()
    result = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=10.0)
    elapsed = time.monotonic() - started
    assert result == ("", "timeout")
    assert 2.9 <= elapsed < 4.0, elapsed
    (launch,) = spy.launches
    assert _gone(launch.pid)
    monkeypatch.undo()
    assert _slot_is_free()


def test_a_child_that_never_reads_a_large_body_is_judged_by_its_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 4,194,304-byte PDF goes to a child that closes its input at once,
    waits 0.3 s and then sends a valid reply: the parent's write meets a
    closed pipe (``BrokenPipeError``), stops writing, and reads the reply.
    RED IF: the broken pipe raises, ends the read early (the reply is then
    lost), or the call takes 2.5 s or more. Partners: the broken pipe really
    happened (recorded on ``os.write``), and the reply is ``fetched``."""
    pdfs.ChildLaunches(program=pdfs.replies_without_reading(pdfs.EVIDENCE * 3)).install(monkeypatch)
    broken: list[int] = []
    real_write = os.write

    def recording_write(fd: int, data: Any) -> int:
        try:
            return real_write(fd, data)
        except BrokenPipeError:
            broken.append(fd)
            raise

    monkeypatch.setattr(os, "write", recording_write)
    body = pdfs.text_pdf([pdfs.EVIDENCE * 3], pad_to=4_194_304)
    started = time.monotonic()
    text, outcome = source_fetcher.read_pdf_text(body, deadline_seconds=5.0)
    elapsed = time.monotonic() - started
    assert broken, "the parent's write never met a closed pipe"
    assert outcome == "fetched", outcome
    assert "PDFSENTINEL" in text
    assert elapsed < 2.5, elapsed


def test_a_child_without_pipes_is_unusable() -> None:
    """``_exchange``'s guard for a child object with no pipes (``Popen``
    always has them with ``PIPE``; the guard keeps "never raises" true under
    ``python -O``). RED IF: it raises, or returns anything but
    ``("unusable", b"")``."""
    fake = types.SimpleNamespace(stdin=None, stdout=None, pid=0)
    assert source_fetcher._exchange(fake, b"%PDF-1.7", time.monotonic() + 1.0) == (  # type: ignore[arg-type]
        "unusable",
        b"",
    )
