"""W54 step 3 (ADR-0153 decision 3): every PDF is parsed in a sandboxed child.

Failure modes 1, 2, 3, 6, 7 and 8 of
``docs/analysis/2026-10-08-w54-step3-pdf-reading-failure-modes.md``.

The function under test is ``source_fetcher.read_pdf_text(body, *,
deadline_seconds) -> (text, outcome)``. These tests are BEHAVIOURAL: they run
real children and read what the children did, never the source text.

THE HARNESS (``tests.pdf_fixtures``):

* ``ChildLaunches`` wraps ``subprocess.Popen`` (looked up on the
  ``subprocess`` module at call time, which ``subprocess.run`` and asyncio's
  subprocess support both do), records every launch whose argv names
  ``product_app.pdf_text``, and can swap the child's program for a probe that
  reports its pid and its environment's variable names, keeping every keyword
  argument the code under test chose (environment, working directory, limits
  set before ``exec``).
* Every PDF is built from raw bytes; nothing here imports pypdf except the
  in-process trap, which needs the class to trap.

PLATFORM. ``RLIMIT_AS`` cannot be set on macOS, so the memory-limit test runs
on Linux only (CI's ``ubuntu-latest`` runners, in the ordinary pytest job); it
is the ADR's required proof that the 256 MiB limit holds. Every other test
runs on both.

Every subprocess or wall-clock test is marked ``env_oracle`` (deselected under
mutmut, pyproject's marker note). Each names what turns it red.
"""

from __future__ import annotations

import importlib
import os
import resource
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from tests import pdf_fixtures as pdfs

from product_app import source_fetcher

pytestmark = pytest.mark.env_oracle

#: The directory that holds ``product_app`` (rule 16b: derived from the module
#: this test actually imported, so a fresh interpreter imports the same tree).
SRC_DIR = str(Path(source_fetcher.__file__).resolve().parents[1])


def _children_cpu_seconds() -> float:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


# ---------------------------------------------------------------------------
# A different process, with an empty environment
# ---------------------------------------------------------------------------


def test_the_child_is_another_process_launched_as_the_adr_says(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure mode 1. The probe stands in for the parser and reports its own
    pid. RED IF: the PDF is handled without launching
    ``sys.executable -m product_app.pdf_text`` (no launch, another program or
    another interpreter), more than one child is launched for one PDF, or the
    text returned is not the child's. Partner: the probe's text came back as
    ``fetched``, so the harness reached the child."""
    spy = pdfs.ChildLaunches(probe=True).install(monkeypatch)
    text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0)
    assert outcome == "fetched", (outcome, text)
    assert len(spy.launches) == 1, spy.launches
    (launch,) = spy.launches
    assert launch.args[0] == sys.executable
    assert "-m" in launch.args, launch.args
    assert launch.args[launch.args.index("-m") + 1] == pdfs.CHILD_MODULE, launch.args
    report = pdfs.probe_report(text)
    assert report["pid"] == launch.pid
    assert report["pid"] != os.getpid()
    assert report["ppid"] == os.getpid()


def test_the_child_cannot_see_the_parents_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure mode 6: the app's secrets live in its environment. The parent
    holds two sentinels; the probe lists the names the child really has.
    RED IF: the child inherits the environment (``env`` left out or copied
    from ``os.environ``), or any variable beyond the handful Python and the
    operating system add. Partner: the parent really holds both sentinels."""
    monkeypatch.setenv("QUORUM_W54_SENTINEL_SECRET", "do-not-leak")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-not-a-real-key")
    assert os.environ["QUORUM_W54_SENTINEL_SECRET"] == "do-not-leak"
    spy = pdfs.ChildLaunches(probe=True).install(monkeypatch)
    text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0)
    assert outcome == "fetched", (outcome, text)
    names = set(pdfs.probe_report(text)["env"])
    assert "QUORUM_W54_SENTINEL_SECRET" not in names
    assert "OPENROUTER_API_KEY" not in names
    # "Empty apart from what Python needs to start": a short allow-list. A
    # child started with env={} on macOS still shows LC_CTYPE (Python's own
    # locale coercion) and __CF_USER_TEXT_ENCODING (the OS): measured.
    allowed = {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "PYTHONPATH", "PYTHONIOENCODING"}
    allowed |= {"PYTHONHASHSEED", "PYTHONSAFEPATH", "PYTHONDONTWRITEBYTECODE"}
    allowed |= {"__CF_USER_TEXT_ENCODING"}
    assert names <= allowed, sorted(names - allowed)
    assert len(spy.launches) == 1


def test_no_pdf_parser_runs_in_the_apps_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure mode 1, from the other side: pypdf's reader is booby-trapped
    in THIS process. RED IF: the PDF is parsed in-process (the trap fires),
    whatever else the code does. Partner: the PDF really is read (outcome
    ``fetched`` with its sentinel), so the trap did not pass by default."""
    # Imported by name so a missing dependency is RED, not a skip.
    pypdf = importlib.import_module("pypdf")
    fired: list[str] = []

    def trap(self: Any, *args: Any, **kwargs: Any) -> None:
        fired.append("PdfReader built in the app's process")
        raise AssertionError("pypdf.PdfReader was built in the app's process")

    monkeypatch.setattr(pypdf.PdfReader, "__init__", trap)
    text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0)
    assert fired == []
    assert outcome == "fetched", outcome
    assert "PDFSENTINEL" in text


# ---------------------------------------------------------------------------
# Time: the CPU limit and the wall-clock kill
# ---------------------------------------------------------------------------


def test_a_cpu_burning_pdf_is_stopped_by_the_two_second_cpu_limit() -> None:
    """Failure mode 2. The fixture costs about 11 s of CPU with no limit
    (measured, ``cpu_bomb_pdf``). With a generous deadline the wall kill is
    at 3 s, so the CHILD'S CPU time tells the 2-second CPU limit apart from
    the 3-second wall kill. RED IF: the child has no CPU limit (it then
    accrues CPU until the wall kill: more than 2.4 s when the machine is not
    saturated), the call outlives about 3 s, the outcome is ``fetched``, or
    the child is never reaped. Partner:
    the child really burned CPU (at least 0.5 s), so the measurement saw it.
    Under heavy machine load a missing CPU limit can go undetected (the wall
    kill comes first); that is a false GREEN, never a false red."""
    before = _children_cpu_seconds()
    started = time.monotonic()
    text, outcome = source_fetcher.read_pdf_text(pdfs.cpu_bomb_pdf(), deadline_seconds=10.0)
    elapsed = time.monotonic() - started
    child_cpu = _children_cpu_seconds() - before
    assert (text, outcome) in {("", "timeout"), ("", "unusable")}, (outcome, text[:80])
    assert elapsed < 3.8, elapsed
    assert child_cpu >= 0.5, child_cpu
    assert child_cpu <= 2.4, child_cpu


def test_the_deadline_passed_in_caps_the_wall_time() -> None:
    """ADR decision 3: the parent kills the child at the smaller of 3 s and
    the fetch budget left. RED IF: ``deadline_seconds`` is ignored (the call
    then runs to the 2 s CPU limit or the 3 s kill), or a CPU-bound child is
    reported as anything but ``timeout``. Partner: it did not return before
    it started work (at least 0.3 s), so the bound is the deadline, not an
    early refusal."""
    started = time.monotonic()
    text, outcome = source_fetcher.read_pdf_text(pdfs.cpu_bomb_pdf(), deadline_seconds=0.5)
    elapsed = time.monotonic() - started
    assert (text, outcome) == ("", "timeout")
    assert 0.3 <= elapsed < 1.2, elapsed


def test_a_child_that_sleeps_is_killed_at_three_seconds_and_reaped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR decision 3: the parent kills the child at the smaller of 3 s and
    the budget left. The CPU-burning fixture cannot pin this, because the 2 s
    CPU limit always ends it first; this child (``SLEEPER``) uses no CPU and
    sleeps 10 s, so with 10 s of budget left ONLY the 3 s wall kill can end
    it. RED IF: the wall kill is raised above about 4 s or removed (the call
    then lasts 4 s or more), the call returns before about 3 s (a lower
    kill), the result is not ``("", "timeout")``, or the child is left
    behind unreaped (a zombie still answers ``os.kill(pid, 0)``). Partner:
    exactly one child was started, and it was the swapped program."""
    spy = pdfs.ChildLaunches(program=pdfs.SLEEPER).install(monkeypatch)
    started = time.monotonic()
    result = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=10.0)
    elapsed = time.monotonic() - started
    assert len(spy.launches) == 1, spy.launches
    pid = spy.launches[0].pid
    assert pid is not None and pid != os.getpid()
    assert result == ("", "timeout")
    assert 2.9 <= elapsed < 4.0, elapsed
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_no_budget_left_starts_no_child(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED IF: a child is started when the fetch budget is already spent, or
    the result is not empty. Partner: the same spy counts one launch for a
    readable PDF with budget left."""
    spy = pdfs.ChildLaunches().install(monkeypatch)
    text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=0.0)
    assert text == "" and outcome in {"timeout", "unusable"}
    assert spy.launches == []
    text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0)
    assert outcome == "fetched" and len(spy.launches) == 1


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

_FRESH_PARENT = """
import json, resource, sys
from product_app import source_fetcher
from tests import pdf_fixtures as pdfs
bomb = pdfs.flate_bomb_pdf()
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
text, outcome = source_fetcher.read_pdf_text(bomb, deadline_seconds=5.0)
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
unit = 1 if sys.platform == "darwin" else 1024
print(json.dumps({"outcome": outcome, "text": text, "grew": (after - before) * unit}))
"""


def test_a_decompression_bomb_does_not_grow_the_apps_memory() -> None:
    """Failure mode 1. A FRESH interpreter plays the app, so its peak memory
    (``ru_maxrss``, a high-water mark) is not hidden by an earlier test's
    peak. The bomb inflates to 256 MiB; pypdf's own default limit is
    75,000,000 bytes, and parsing it in-process with that default made this
    test fail in the designer's mutation run. RED IF: the parent's peak
    grows by 32 MiB or more (the PDF was parsed in the app's process with
    any limit above that), or the bomb yields text. Partner: the call
    completed and reported an outcome."""
    repo_root = str(Path(SRC_DIR).parent)
    result = pdfs.run_fresh_python(_FRESH_PARENT, SRC_DIR + os.pathsep + repo_root)
    assert result["outcome"] in {"unusable", "timeout"}, result
    assert result["text"] == ""
    assert result["grew"] < 32 * 2**20, result


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="RLIMIT_AS cannot be set on macOS; this is the ADR's Linux-only proof, run on CI",
)
def test_linux_the_256_mib_address_space_limit_stops_a_memory_bomb(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Failure mode 3, the ADR's required CI proof. An import hook in the
    child (``tests.pdf_fixtures.SITECUSTOMIZE``) allocates and touches 512
    MiB when the reader is made, after any limit the child sets itself and
    before parsing; every other launch argument, the empty environment
    included, is the code's own. The hook patches pypdf only when the child
    itself imports it (after ``set_limits``); it never imports pypdf at
    start-up. When a case fails, the message carries the hook's timestamped
    trace, the child's exit status, stderr and last ``/proc`` sample.
    RED IF: the child has no 256 MiB address-space limit (it then reads the
    PDF and returns its text), or the parent raises. Partners, in the same
    harness: with a 32 MiB allocation the same PDF is ``fetched`` and the
    hook's marker is in the text, so the hook really runs in the child and a
    refusal at 512 MiB is the limit, not a broken harness."""
    hook = pdfs.write_hook(str(tmp_path))

    def run(mib: int) -> tuple[str, str, str]:
        """One read with a ``mib`` MiB allocation; returns the text, the
        outcome and, for a failure message, everything CI can tell."""
        trace, stderr = tmp_path / f"trace-{mib}.txt", tmp_path / f"stderr-{mib}.txt"
        spy = pdfs.ChildLaunches(
            hook_dir=hook,
            extra_env={"W54_HOOK_ALLOC_MIB": str(mib), "W54_HOOK_TRACE": str(trace)},
            stderr_path=str(stderr),
        )
        spy.install(monkeypatch)
        monitor = pdfs.ChildMonitor(spy).start()
        started = time.monotonic()
        try:
            text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0)
        finally:
            monitor.stop()
        elapsed = time.monotonic() - started
        assert len(spy.launches) == 1
        why = pdfs.child_diagnostics(spy, elapsed, monitor=monitor, trace_path=str(trace))
        return text, outcome, f"outcome={outcome!r}\n{why}"

    text, outcome, why = run(32)
    assert outcome == "fetched", why
    assert "HOOKRANMARKER" in text, why

    text, outcome, why = run(512)
    assert (text, outcome) in {("", "unusable"), ("", "timeout")}, f"text={text[:80]!r}\n{why}"


def _proc_limits(pid: int) -> dict[str, tuple[str, str]]:
    """``/proc/<pid>/limits`` as {name: (soft, hard)}."""
    rows: dict[str, tuple[str, str]] = {}
    with open(f"/proc/{pid}/limits", encoding="ascii") as handle:
        lines = handle.read().splitlines()[1:]
    for line in lines:
        # "Max cpu time              2                    3                    seconds"
        name, soft, hard = line[:26].strip(), line[26:47].strip(), line[47:68].strip()
        rows[name] = (soft, hard)
    return rows


@pytest.mark.skipif(sys.platform != "linux", reason="/proc and RLIMIT_AS are Linux-only")
def test_linux_the_running_child_has_the_adrs_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decision 3, read from the kernel while the child runs, wherever the
    code sets the limits (before ``exec`` or in the child's first lines):
    CPU time 2 s, address space 256 MiB (268,435,456 bytes), no core files,
    ``oom_score_adj`` 1000. RED IF: any of the four is missing or different.
    Partner: the parent's own limits are NOT these (the child's were set for
    it, not inherited from a constrained test runner)."""
    spy = pdfs.ChildLaunches().install(monkeypatch)
    done: list[tuple[str, str]] = []
    worker = threading.Thread(
        target=lambda: done.append(
            source_fetcher.read_pdf_text(pdfs.cpu_bomb_pdf(), deadline_seconds=3.0)
        )
    )
    worker.start()
    try:
        assert spy.started.wait(5.0), "the child never started"
        pid = spy.launches[0].pid
        assert pid is not None
        limits: dict[str, tuple[str, str]] = {}
        oom = ""
        give_up = time.monotonic() + 1.5
        while time.monotonic() < give_up:
            try:
                limits = _proc_limits(pid)
                with open(f"/proc/{pid}/oom_score_adj", encoding="ascii") as handle:
                    oom = handle.read().strip()
            except OSError:
                break
            if limits.get("Max cpu time", ("", ""))[0] == "2" and oom == "1000":
                break
            time.sleep(0.02)
    finally:
        worker.join(timeout=10)
    assert limits.get("Max cpu time", ("", ""))[0] == "2", limits
    assert limits.get("Max address space", ("", ""))[0] == str(256 * 2**20), limits
    assert limits.get("Max core file size", ("", ""))[0] == "0", limits
    assert oom == "1000"
    own = _proc_limits(os.getpid())
    assert own["Max cpu time"][0] != "2" or own["Max address space"][0] != str(256 * 2**20)


# ---------------------------------------------------------------------------
# One child at a time
# ---------------------------------------------------------------------------


def test_a_second_pdf_while_one_is_parsing_is_unusable_without_a_second_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure mode 7: at most one PDF child per app process. RED IF: a
    second child is started while the first runs (cardinality), the second
    call waits for the first instead of returning at once, or it returns
    anything but ``("", "unusable")``. Partner: once the first has finished,
    the same PDF is read (``fetched``), so the refusal was the busy slot, not
    the file."""
    spy = pdfs.ChildLaunches().install(monkeypatch)
    first: list[tuple[str, str]] = []
    worker = threading.Thread(
        target=lambda: first.append(
            source_fetcher.read_pdf_text(pdfs.cpu_bomb_pdf(), deadline_seconds=3.0)
        )
    )
    worker.start()
    try:
        assert spy.started.wait(5.0), "the first child never started"
        started = time.monotonic()
        second = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0)
        waited = time.monotonic() - started
        assert len(spy.launches) == 1, spy.launches
    finally:
        worker.join(timeout=10)
    assert second == ("", "unusable")
    assert waited < 0.5, waited
    assert first and first[0][1] in {"timeout", "unusable"}
    text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0)
    assert outcome == "fetched" and "PDFSENTINEL" in text
    assert len(spy.launches) == 2


def test_a_child_that_cannot_start_is_unusable_and_frees_the_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure mode 8. RED IF: a launch failure raises into the caller, is
    reported as anything but ``("", "unusable")``, or leaves the one-child
    slot taken (the next PDF would then be refused). Partner: the next call,
    with launching restored, reads the PDF."""
    real_popen = __import__("subprocess").Popen

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise OSError("no interpreter")

    monkeypatch.setattr("subprocess.Popen", broken)
    assert source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0) == ("", "unusable")
    monkeypatch.setattr("subprocess.Popen", real_popen)
    text, outcome = source_fetcher.read_pdf_text(pdfs.valid_pdf(), deadline_seconds=5.0)
    assert outcome == "fetched" and "PDFSENTINEL" in text
