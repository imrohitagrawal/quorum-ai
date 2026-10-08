"""W54 step 3, review round 1: six defects the break-it session found in the
PDF sandbox (ADR-0153), each pinned by a test that is RED on 6c72f39.

* A1 -- a ToUnicode map can put lone UTF-16 surrogates (Unicode category
  ``Cs``) into the text, and they reach the judge's prompt.
* A2 -- a 2,765-byte ToUnicode expansion drives the child to 532 MB with no
  pypdf limit applying; only the address-space limit can stop it (Linux).
* A3 -- a child that forks a sleeper holding its stdout pipe makes the call
  outlive the wall kill (12.02 s against 3 s).
* A4 -- the child's reply is read in full, however large (1.5 GB in the
  session).
* A5 -- the child runs at the app's own CPU priority.
* C2 -- the child writes ``.pyc`` files into the app's package directory.

Hostile children run through ``tests.pdf_fixtures.ChildLaunches``, which
swaps the child's PROGRAM but keeps every launch argument the code chose
(environment, session, priority, limits set before ``exec``). Every PDF is
built from raw bytes in ``tests.pdf_fixtures``. Real children run, so the
module is ``env_oracle``. Each test names what turns it red.
"""

from __future__ import annotations

import contextlib
import dataclasses
import os
import shutil
import signal
import sys
import threading
import time
import unicodedata
from pathlib import Path

import pytest
from tests import pdf_fixtures as pdfs
from tests.unit.test_w54_pdf_fetch_and_judge import (  # noqa: F401 - _hermetic is autouse
    ANSWER,
    _answer,
    _hermetic,
    _judge,
    _pdf,
    _sites,
)

from product_app import evaluation, source_fetcher

pytestmark = pytest.mark.env_oracle

#: The ceiling on the child's reply (round 1): 1 MiB. A real reply is at most
#: about 600 KB (50,000 characters at 12 escaped bytes each).
REPLY_CEILING = 1_048_576
SRC_DIR = Path(source_fetcher.__file__).resolve().parents[1]


def _surrogates(text: str) -> int:
    return sum(1 for char in text if unicodedata.category(char) == "Cs")


def _gone(pid: int, *, within: float = 1.0) -> bool:
    """True once ``pid`` no longer exists (a zombie still exists)."""
    give_up = time.monotonic() + within
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        if time.monotonic() >= give_up:
            return False
        time.sleep(0.02)


# ---------------------------------------------------------------------------
# A1: no lone surrogate in the text or in the judge's prompt
# ---------------------------------------------------------------------------


def test_a1_read_pdf_text_returns_no_lone_surrogate() -> None:
    """RED IF: the text ``read_pdf_text`` returns holds any character of
    Unicode category Cs (6 of them on 6c72f39). Partners: the outcome is
    still ``fetched`` and all 300 readable ``A`` characters arrive, so the fix
    removes the surrogates, not the page."""
    text, outcome = source_fetcher.read_pdf_text(pdfs.surrogate_pdf(), deadline_seconds=5.0)
    assert outcome == "fetched", outcome
    assert text.count("A") == 300
    assert _surrogates(text) == 0, [hex(ord(c)) for c in text if unicodedata.category(c) == "Cs"]


def test_a1_a_fetched_pdf_puts_no_lone_surrogate_in_the_judge_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end on loopback: the PDF is fetched, read, picked and cut by
    ``judge_source_pages``, then built into the v2 prompt. RED IF: the user
    prompt holds any Cs character. Partners: the page was read (N = 1) and
    its ``A`` characters are in the prompt."""
    with _sites({"pdf.example": _pdf(pdfs.surrogate_pdf())}) as sites:
        url = sites.url("pdf.example")
        reading = _judge(monkeypatch, [url])
    assert reading.result.read == 1
    evidence = evaluation.build_judge_evidence(
        query_text="What retention figure does the document report?",
        initial_answers=[_answer([url])],
        final_synthesis=None,
    )
    evidence = dataclasses.replace(
        evidence, source_pages=reading.result.pages, source_page_same_as=reading.result.same_as
    )
    _system, user = evaluation.build_judge_pages_prompt(evidence)
    assert "A" * 40 in user
    assert _surrogates(user) == 0


def test_a1_the_prompt_builder_drops_a_lone_surrogate_from_any_page_text() -> None:
    """Defence in depth: a search preview arrives as JSON, which can carry an
    escaped lone surrogate, so the PROMPT must not depend on the PDF path
    alone. RED IF: a page text holding U+D800 and U+DC00 reaches the built v2
    prompt with either. Partner: the readable words around them do."""
    evidence = evaluation.JudgeEvidence(
        query_text="q",
        answer_texts=(ANSWER,),
        source_lines=("[1] Title https://example.org/doc.pdf",),
        synthesis_sections=(),
        source_pages=("READABLEWORDS \ud800 between \udc00 READABLETAIL " * 10,),
        source_page_same_as=(0,),
    )
    _system, user = evaluation.build_judge_pages_prompt(evidence)
    assert "READABLEWORDS" in user and "READABLETAIL" in user
    assert _surrogates(user) == 0


# ---------------------------------------------------------------------------
# A2: the ToUnicode expansion, under the Linux address-space limit
# ---------------------------------------------------------------------------

_FRESH_PARENT_B4 = """
import json, resource, sys
from product_app import source_fetcher
from tests import pdf_fixtures as pdfs
data = pdfs.tounicode_expansion_pdf()
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
text, outcome = source_fetcher.read_pdf_text(data, deadline_seconds=5.0)
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
unit = 1 if sys.platform == "darwin" else 1024
print(json.dumps({"outcome": outcome, "chars": len(text), "grew": (after - before) * unit}))
"""


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="RLIMIT_AS cannot be set on macOS; the ADR's Linux-only proof, run on CI",
)
def test_linux_a2_a_tounicode_expansion_pdf_is_stopped_and_the_parent_unharmed() -> None:
    """The REAL 2,765-byte file, beside the import-hook allocation of
    ``test_linux_the_256_mib_address_space_limit_stops_a_memory_bomb``. A
    fresh interpreter plays the app, so its peak memory is its own. RED IF:
    the file yields text, ends as anything but ``unusable`` or ``timeout``,
    or the app's peak memory grows by 32 MiB or more."""
    repo_root = str(SRC_DIR.parent)
    result = pdfs.run_fresh_python(_FRESH_PARENT_B4, str(SRC_DIR) + os.pathsep + repo_root)
    assert result["outcome"] in {"unusable", "timeout"}, result
    assert result["chars"] == 0
    assert result["grew"] < 32 * 2**20, result


# ---------------------------------------------------------------------------
# A3: a grandchild holding stdout
# ---------------------------------------------------------------------------


def test_a3_a_grandchild_holding_stdout_cannot_outlive_the_wall_kill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The child forks a sleeper (8 s) that keeps the stdout pipe open and
    exits at once. RED IF: the call lasts 4.0 s or more (8 s on 6c72f39: it
    waits for the pipe to close), the result is not empty, the sleeper is
    still alive afterwards, or the one-child slot is left taken. Partners:
    the sleeper really was started (its pid was written), and a readable PDF
    is read straight afterwards."""
    pid_file = tmp_path / "grandchild.pid"
    spy = pdfs.ChildLaunches(program=pdfs.forker(str(pid_file))).install(monkeypatch)
    sleeper = 0
    try:
        started = time.monotonic()
        text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=10.0)
        elapsed = time.monotonic() - started
        assert pid_file.exists(), "the hostile child never forked"
        sleeper = int(pid_file.read_text())
        assert elapsed < 4.0, elapsed
        assert text == "" and outcome in {"timeout", "unusable"}, outcome
        assert _gone(sleeper), f"the grandchild {sleeper} outlived the call"
    finally:
        if sleeper:
            with contextlib.suppress(OSError):
                os.kill(sleeper, signal.SIGKILL)
    spy.program = None
    text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0)
    assert outcome == "fetched" and "PDFSENTINEL" in text
    assert len(spy.launches) == 2


# ---------------------------------------------------------------------------
# A4: the reply is bounded at the read
# ---------------------------------------------------------------------------


def test_a4_a_flooding_child_is_read_only_up_to_the_ceiling_and_killed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The child writes 8 MiB of ``x``, recording after each 64 KiB block the
    pipe ACCEPTED, so what it managed to write is what the parent read plus
    at most one pipe buffer. That bounds the READ itself (AGENTS.md rule 8b):
    a parent that reads everything and then slices lets all 8 MiB through.
    RED IF: the child wrote more than 1,048,577 + 131,072 bytes (8,388,608
    on 6c72f39), the outcome is not ``unusable``, or the child is still
    alive afterwards. Partner: the child did write (at least 65,536 bytes),
    so the measurement saw it."""
    progress = tmp_path / "written"
    spy = pdfs.ChildLaunches(program=pdfs.flooder(8 * 2**20, str(progress))).install(monkeypatch)
    text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0)
    (launch,) = spy.launches
    assert launch.pid is not None
    assert _gone(launch.pid)
    written = int(progress.read_text())
    assert written >= 65_536
    assert written <= REPLY_CEILING + 1 + 131_072, written
    assert (text, outcome) == ("", "unusable")


def test_a4_each_read_of_the_reply_asks_only_for_the_bytes_left(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Rule 8b, on the ARGUMENT: every ``os.read`` of the child's stdout pipe
    (that fd only) is recorded with the size it asked for and the size it
    got, while a child floods 8 MiB. RED IF: any read asks for more than the
    bytes left to 1,048,577 (one past the 1,048,576 ceiling), the parent
    reads other than exactly 1,048,577 bytes, or the last read asks for
    other than exactly the bytes left. A plain 65,536-byte read fails the
    first: its 17th read asks for 65,536 with 1,048,576 already read.
    The SUM of the sizes asked is not pinned: a read that returns short is
    asked again, so the sum can pass 1,048,577 in a correct reader.
    Partner: the pipe really was read (more than 16 reads), so the spy saw
    the reader."""
    progress = tmp_path / "written"
    spy = pdfs.ChildLaunches(program=pdfs.flooder(8 * 2**20, str(progress))).install(monkeypatch)
    reads: list[tuple[int, int, int]] = []  # (already read, asked, got)
    real_read = os.read

    def recording_read(fd: int, size: int) -> bytes:
        data = real_read(fd, size)
        if any(launch.stdout_fd == fd for launch in spy.launches):
            already = sum(got for _, _, got in reads)
            reads.append((already, size, len(data)))
        return data

    monkeypatch.setattr(os, "read", recording_read)
    text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0)
    assert (text, outcome) == ("", "unusable")
    assert len(reads) > 16, len(reads)
    over = [(already, asked) for already, asked, _ in reads if already + asked > 1_048_577]
    assert over == [], over[:3]
    assert sum(got for _, _, got in reads) == 1_048_577
    last_already, last_asked, _ = reads[-1]
    assert last_asked == 1_048_577 - last_already, reads[-1]


def test_a4_a_reply_of_exactly_the_ceiling_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The boundary from below, a literal (rule 8b): a valid reply of exactly
    1,048,576 bytes is read. GREEN on 6c72f39 by design: the partner of the
    next test. RED IF: the ceiling is lowered below 1,048,576."""
    pdfs.ChildLaunches(program=pdfs.reply_of_exactly(1_048_576, pdfs.EVIDENCE, 3)).install(
        monkeypatch
    )
    text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0)
    assert outcome == "fetched", outcome
    assert "PDFSENTINEL" in text


def test_a4_a_reply_one_byte_over_the_ceiling_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The boundary from above: the same valid reply, 1,048,577 bytes, is
    refused. RED IF: it is read (``fetched`` on 6c72f39), i.e. the ceiling
    is missing or above 1,048,576."""
    pdfs.ChildLaunches(program=pdfs.reply_of_exactly(1_048_577, pdfs.EVIDENCE, 3)).install(
        monkeypatch
    )
    assert source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0) == (
        "",
        "unusable",
    )


def test_a4_the_largest_real_reply_still_fits(monkeypatch: pytest.MonkeyPatch) -> None:
    """50,000 characters, each a 12-byte JSON escape: a 600,012-byte reply,
    the longest a real child can send. GREEN on 6c72f39 by design. RED IF:
    the ceiling is set below a real reply (it then comes back
    ``unusable``) or the text is not passed through whole."""
    pdfs.ChildLaunches(
        program=pdfs.reply_of_exactly(600_012, pdfs.ESCAPED_UNIT, pdfs.ESCAPED_COUNT)
    ).install(monkeypatch)
    text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0)
    assert outcome == "fetched", outcome
    assert text == pdfs.ESCAPED_UNIT * pdfs.ESCAPED_COUNT


# ---------------------------------------------------------------------------
# A5: the child runs at a lower CPU priority (niceness 5)
# ---------------------------------------------------------------------------


def test_a5_the_child_runs_at_niceness_5(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read from the operating system while the REAL child parses a
    CPU-burning PDF, wherever the code sets it (before ``exec`` or in the
    child). 5, not 19: CI measured niceness 19 starving a normal PDF beside
    one busy process (PR #550, ``timeout`` at 3.17 s); niceness 5 has CFS
    weight 335 against 1,024, about a quarter of a CPU (a calculation, not a
    measurement). RED IF: the child's niceness is not 5. Partners: the app's
    own niceness is not 5 (so the child's was set for it, not inherited) and
    is unchanged after the call (the app itself was not lowered)."""
    app_niceness = os.getpriority(os.PRIO_PROCESS, 0)
    assert app_niceness != 5
    spy = pdfs.ChildLaunches().install(monkeypatch)
    done: list[tuple[str, str]] = []
    worker = threading.Thread(
        target=lambda: done.append(
            source_fetcher.read_pdf_text(pdfs.cpu_bomb_pdf(), deadline_seconds=3.0)
        )
    )
    worker.start()
    niceness = None
    try:
        assert spy.started.wait(5.0), "the child never started"
        pid = spy.launches[0].pid
        assert pid is not None
        give_up = time.monotonic() + 1.5
        while time.monotonic() < give_up:
            try:
                niceness = os.getpriority(os.PRIO_PROCESS, pid)
            except OSError:
                break
            if niceness == 5:
                break
            time.sleep(0.02)
    finally:
        worker.join(timeout=10)
    assert niceness == 5, niceness
    assert done and done[0][1] in {"timeout", "unusable"}
    assert os.getpriority(os.PRIO_PROCESS, 0) == app_niceness


# ---------------------------------------------------------------------------
# C2: the child writes no bytecode
# ---------------------------------------------------------------------------


def test_c2_the_child_is_started_with_minus_b(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED IF: the child's interpreter flags do not include ``-B`` (it may
    then write ``.pyc`` files into the app's package). Partner: the launch
    is the one the ADR names and the PDF is read."""
    spy = pdfs.ChildLaunches().install(monkeypatch)
    text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0)
    assert outcome == "fetched" and "PDFSENTINEL" in text
    (launch,) = spy.launches
    module_at = launch.args.index("-m")
    assert launch.args[module_at + 1] == pdfs.CHILD_MODULE
    assert "-B" in launch.args[:module_at], launch.args


def _package_copy(root: Path) -> Path:
    """A copy of ``product_app`` with no ``__pycache__``; returns the
    directory that holds it (the child's working directory)."""
    holder = root / "src"
    shutil.copytree(
        SRC_DIR / "product_app",
        holder / "product_app",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    return holder


def test_c2_a_real_child_leaves_no_bytecode_in_the_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Behaviour: the child runs from a COPY of the package (only its working
    directory is redirected; its own flags are kept). RED IF: a
    ``__pycache__`` entry for ``pdf_text`` appears in the copy. Partner, in
    the same harness: with ``-B`` stripped from the code's own flags, the
    entry DOES appear, so the copy really is what the child imported and
    the check can see a write."""
    kept = _package_copy(tmp_path / "kept")
    pdfs.ChildLaunches(cwd=str(kept)).install(monkeypatch)
    text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0)
    assert outcome == "fetched" and "PDFSENTINEL" in text
    cache = kept / "product_app" / "__pycache__"
    written = sorted(p.name for p in cache.glob("pdf_text*")) if cache.exists() else []

    stripped = _package_copy(tmp_path / "stripped")
    pdfs.ChildLaunches(cwd=str(stripped), strip_flags=frozenset({"-B"})).install(monkeypatch)
    _text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0)
    assert outcome == "fetched"
    partner = stripped / "product_app" / "__pycache__"
    assert list(partner.glob("pdf_text*")), "the harness could not see a bytecode write"

    assert written == [], written
