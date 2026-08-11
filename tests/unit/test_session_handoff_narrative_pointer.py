"""scripts/session_handoff.py must point at the latest narrative handoff.

`docs/session-handoff.md` is auto-regenerated purely from live git/skill-route
state -- it never knew a hand-authored narrative handoff
(`docs/analysis/<date>-session-handoff.md`) existed, so AGENTS.md's mandated
"read docs/session-handoff.md first" sent a new session to a mechanically
accurate but narratively empty file while the real continuation context sat
in a differently-named doc nobody was pointed at. That gap is what let
`docs/session-handoff.md` go 17 days stale (branch `feat/ui-pr1-quickfixes`,
long since merged/deleted) without anyone noticing during a session start.

What turns it red: deleting the `_latest_narrative_handoff` call from
`session_handoff.py`'s generated text (or breaking its glob/sort) so the
newest `docs/analysis/*-session-handoff.md` file stops being surfaced.
"""

from __future__ import annotations

import datetime
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "session_handoff", REPO_ROOT / "scripts" / "session_handoff.py"
)
assert _spec is not None and _spec.loader is not None
session_handoff = importlib.util.module_from_spec(_spec)
sys.modules["session_handoff"] = session_handoff
_spec.loader.exec_module(session_handoff)


def test_finds_the_lexicographically_latest_dated_handoff(tmp_path: Path) -> None:
    analysis_dir = tmp_path / "docs" / "analysis"
    analysis_dir.mkdir(parents=True)
    for name in [
        "2026-07-30-session-handoff.md",
        "2026-08-11-session-handoff.md",
        "2026-08-01-session-handoff.md",
    ]:
        (analysis_dir / name).write_text("placeholder", encoding="utf-8")

    latest = session_handoff._latest_narrative_handoff(analysis_dir)

    assert latest is not None
    assert latest.name == "2026-08-11-session-handoff.md"


def test_none_when_no_narrative_handoff_exists(tmp_path: Path) -> None:
    analysis_dir = tmp_path / "docs" / "analysis"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "2026-07-30-backlog-triage-by-execution.md").write_text(
        "not a handoff", encoding="utf-8"
    )

    assert session_handoff._latest_narrative_handoff(analysis_dir) is None


def test_ignores_non_dated_or_malformed_names(tmp_path: Path) -> None:
    analysis_dir = tmp_path / "docs" / "analysis"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "session-handoff.md").write_text("no date prefix", encoding="utf-8")
    (analysis_dir / "2026-08-11-session-handoff.md").write_text("real one", encoding="utf-8")

    latest = session_handoff._latest_narrative_handoff(analysis_dir)

    assert latest is not None
    assert latest.name == "2026-08-11-session-handoff.md"


def test_generated_text_includes_a_pointer_to_the_latest_narrative_handoff(
    tmp_path: Path,
) -> None:
    analysis_dir = tmp_path / "docs" / "analysis"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "2026-08-11-session-handoff.md").write_text("narrative", encoding="utf-8")

    latest = session_handoff._latest_narrative_handoff(analysis_dir)
    pointer_line = session_handoff._narrative_pointer_line(latest)

    assert "docs/analysis/2026-08-11-session-handoff.md" in pointer_line


def test_generated_text_says_none_found_when_no_narrative_handoff_exists() -> None:
    pointer_line = session_handoff._narrative_pointer_line(None)

    assert "none found" in pointer_line.lower()


def test_a_second_same_day_handoff_gets_a_suffix_not_a_silent_overwrite(
    tmp_path: Path,
) -> None:
    """Two sessions on the same date must not clobber each other's narrative.

    Review finding on this feature's own PR: the original regex only matched
    the bare `<date>-session-handoff.md` name, so a second same-day session
    writing that exact path would silently overwrite the first session's
    content with no collision signal at all. A `-2`/`-3` suffix is a real
    second file the glob/sort must also find and correctly order after the
    unsuffixed one.
    """
    analysis_dir = tmp_path / "docs" / "analysis"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "2026-08-11-session-handoff.md").write_text("first", encoding="utf-8")
    (analysis_dir / "2026-08-11-session-handoff-2.md").write_text("second", encoding="utf-8")

    latest = session_handoff._latest_narrative_handoff(analysis_dir)

    assert latest is not None
    assert latest.name == "2026-08-11-session-handoff-2.md"


def test_suffix_only_breaks_ties_within_the_same_date_not_across_dates(
    tmp_path: Path,
) -> None:
    analysis_dir = tmp_path / "docs" / "analysis"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "2026-08-11-session-handoff-9.md").write_text("older date", encoding="utf-8")
    (analysis_dir / "2026-08-12-session-handoff.md").write_text("newer date", encoding="utf-8")

    latest = session_handoff._latest_narrative_handoff(analysis_dir)

    assert latest is not None
    assert latest.name == "2026-08-12-session-handoff.md"


def test_pointer_line_flags_age_when_the_latest_handoff_is_not_from_today(
    tmp_path: Path,
) -> None:
    """A stale fallback (e.g. the current latest got archived before a
    replacement was written) must say it's stale, not present an old doc
    with the same unqualified confidence as a fresh one -- otherwise this
    mechanism reintroduces the exact silent-staleness failure it exists to
    fix, just with a one-session lag.
    """
    old_path = tmp_path / "docs" / "analysis" / "2026-07-20-session-handoff.md"

    pointer_line = session_handoff._narrative_pointer_line(
        old_path, today=datetime.date(2026, 8, 11)
    )

    assert "22 day" in pointer_line


def test_pointer_line_does_not_flag_age_for_a_same_day_handoff(tmp_path: Path) -> None:
    fresh_path = tmp_path / "docs" / "analysis" / "2026-08-11-session-handoff.md"

    pointer_line = session_handoff._narrative_pointer_line(
        fresh_path, today=datetime.date(2026, 8, 11)
    )

    assert "day" not in pointer_line.lower() or "today" in pointer_line.lower()
