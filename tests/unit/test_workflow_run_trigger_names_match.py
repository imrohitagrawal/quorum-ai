r"""Every workflow named in ``on.workflow_run.workflows`` must actually match.

``on.workflow_run.workflows`` entries are **filter patterns, not literal
strings** — GitHub's filter-pattern language, where ``+``, ``*``, ``?``, ``[``
and ``]`` are metacharacters. A name containing one of them silently matches
nothing, because the pattern still compiles; there is no error and no warning.

Measured in this repository. Counting a "Deploy to Fly.io" run created within
20s of a required workflow's completion on a genuine push to main (the observed
trigger→creation lag is 2-4s), over every run the Actions API still retained on
**2026-08-07** (window 2026-08-01..08-07, 249 Deploy runs):

    CI                    47 / 47 fired a Deploy run
    Tests                 47 / 47 fired a Deploy run
    E2E (axe + parity)     0 / 46

These are a DATED SNAPSHOT, not constants: the API retains a rolling window, so
re-running the count later gives different totals (the ratio does not change).
Do not treat the digits as reproducible without the date.

``deploy.yml`` listed ``"E2E (axe + parity)"``. As a pattern that is
``E2E (axe`` + one-or-more **spaces** + `` parity)``, which matches the string
``E2E (axe  parity)`` and can never match the workflow's real name. ``CI`` and
``Tests`` contain no metacharacters, so they match literally and fire every
time, so one third of the intended redundancy was absent.

**Not "for the life of the repo"** — an earlier draft of this file said that and
it is false. ``deploy.yml`` was created 2026-06-22 (``bca4ba6``) with
``on: push``, no ``workflow_run`` at all; a ``workflow_run`` trigger first
appears 2026-07-16 (``2a218de``) listing only ``["CI"]``, and the three-name
list lands 2026-07-17 (``cb4010a``). The redundancy could only be absent from
the day it was written.

**Proven, not inferred.** A throwaway public repo
(``imrohitagrawal/wfrun-glob-probe``) with one upstream workflow named
``E2E (axe + parity)`` and two listeners, over two pushes::

    17:41:44  E2E (axe + parity)   push          success
    17:41:58  listener-escaped     workflow_run  success
    17:42:31  E2E (axe + parity)   push          success
    17:42:45  listener-escaped     workflow_run  success

    counts: upstream 2 | listener-escaped ('E2E (axe \+ parity)') 2
                       | listener-literal ("E2E (axe + parity)")  0

Corroborated upstream: ``actions/runner#3763`` — *"the ``workflows`` values are
treated as glob patterns and special characters have to be escaped… In the
particular case above, ``"C\+\+"`` does work."*

WHAT TURNS THIS FILE RED: unescape the ``+`` in ``deploy.yml``'s
``on.workflow_run.workflows`` list, i.e. go back to ``"E2E (axe + parity)"``.
``test_every_referenced_workflow_name_is_matched_by_its_pattern`` then fails.

**A YAML trap in the fix.** ``\+`` is an invalid escape inside a DOUBLE-quoted
YAML scalar. Verified on this box::

    "E2E (axe \+ parity)"  -> ScannerError
    'E2E (axe \+ parity)'  -> 'E2E (axe \\+ parity)'

so the escaped entry must be single-quoted. ``test_the_escaped_entry_parses``
pins that the file as written is loadable at all, which is the failure mode that
would take every deploy down rather than merely one trigger.
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

import yaml

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_WORKFLOWS = _ROOT / ".github" / "workflows"

#: The metacharacters GitHub's filter-pattern language gives meaning to. A
#: workflow name containing any of these must be escaped with a backslash in an
#: ``on.workflow_run.workflows`` entry, or it matches something else entirely.
#: The set is the cheat sheet's: ``*``, ``**``, ``?``, ``+``, ``[]``, ``!``.
#: ``(`` and ``)`` are deliberately ABSENT — they are not listed, and the probe
#: matched with both parens unescaped, so they are literal.
_METACHARACTERS = "+*?[]!"


def _load(path: pathlib.Path) -> dict[Any, Any]:
    # ``on:`` parses to the YAML boolean key True, not the string "on".
    data: dict[Any, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def _on_block(wf: dict[Any, Any]) -> dict[Any, Any]:
    raw = wf.get("on", wf.get(True, {}))
    return raw if isinstance(raw, dict) else {}


def _workflow_names() -> dict[str, pathlib.Path]:
    """Every workflow's declared ``name:`` -> the file that declares it."""
    names: dict[str, pathlib.Path] = {}
    for path in sorted(_WORKFLOWS.glob("*.yml")):
        name = _load(path).get("name")
        if isinstance(name, str):
            names[name] = path
    return names


def _workflow_run_references() -> list[tuple[pathlib.Path, str]]:
    """Every (file, pattern) in an ``on.workflow_run.workflows`` list."""
    refs: list[tuple[pathlib.Path, str]] = []
    for path in sorted(_WORKFLOWS.glob("*.yml")):
        block = _on_block(_load(path)).get("workflow_run")
        if not isinstance(block, dict):
            continue
        for pattern in block.get("workflows") or []:
            refs.append((path, pattern))
    return refs


def _pattern_matches(pattern: str, name: str) -> bool:
    """Does GitHub's filter pattern ``pattern`` match the literal ``name``?

    Models the subset that matters here: ``\\x`` is a literal ``x``, ``+`` means
    one-or-more of the preceding character, ``*`` means any run of characters.
    Everything else is literal.
    """
    regex = ""
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\" and index + 1 < len(pattern):
            regex += re.escape(pattern[index + 1])
            index += 2
            continue
        if char == "+":
            regex += "+"
        elif char == "*":
            regex += ".*"
        else:
            regex += re.escape(char)
        index += 1
    return re.fullmatch(regex, name) is not None


# --- the evaluator's positive partners ------------------------------------


def test_pattern_model_treats_plus_as_a_quantifier() -> None:
    """Without this the whole file could pass by modelling `+` as a literal."""
    assert _pattern_matches("E2E (axe + parity)", "E2E (axe  parity)")
    assert not _pattern_matches("E2E (axe + parity)", "E2E (axe + parity)")


def test_pattern_model_honours_a_backslash_escape() -> None:
    assert _pattern_matches(r"E2E (axe \+ parity)", "E2E (axe + parity)")
    assert not _pattern_matches(r"E2E (axe \+ parity)", "E2E (axe  parity)")


def test_pattern_model_matches_a_plain_name_literally() -> None:
    assert _pattern_matches("CI", "CI")
    assert not _pattern_matches("CI", "Tests")


# --- the contract ---------------------------------------------------------


def test_there_is_something_to_check() -> None:
    """Positive partner for the two negative checks below (rule 7).

    Both assert "no reference fails to match". Over an empty list of references
    that is trivially true, so prove the list is not empty and that the names
    it points at exist.
    """
    refs = _workflow_run_references()
    assert refs, "no on.workflow_run.workflows entry found anywhere in .github/workflows"
    assert _workflow_names(), "no workflow declares a name:"


def test_every_referenced_workflow_name_is_matched_by_its_pattern() -> None:
    """THE defect (#245 claim 1).

    A pattern that matches no existing workflow fires nothing, silently.
    """
    names = _workflow_names()
    unmatched = [
        (path.name, pattern)
        for path, pattern in _workflow_run_references()
        if not any(_pattern_matches(pattern, name) for name in names)
    ]
    assert not unmatched, (
        "these on.workflow_run.workflows entries match no workflow in this "
        f"repository, so they trigger nothing: {unmatched}. Entries are FILTER "
        "PATTERNS — escape any of "
        f"{_METACHARACTERS!r} with a backslash, in SINGLE quotes."
    )


def test_a_name_with_a_metacharacter_is_escaped_where_it_is_referenced() -> None:
    """Belt and braces: catch the class, not just today's instance.

    ``test_every_referenced_workflow_name_is_matched_by_its_pattern`` would also
    pass if someone renamed a workflow so an unescaped pattern happened to match
    something. This asserts the escaping directly.
    """
    offenders = []
    for path, pattern in _workflow_run_references():
        stripped = re.sub(r"\\.", "", pattern)
        if any(char in stripped for char in _METACHARACTERS):
            offenders.append((path.name, pattern))
    assert not offenders, f"unescaped filter metacharacters {_METACHARACTERS!r} in {offenders}"


def test_the_scripts_required_list_matches_the_workflows_unescaped() -> None:
    """The two lists are written in DIFFERENT languages and must not drift.

    ``deploy.yml``'s entries are filter PATTERNS (escaped).
    ``scripts/deploy_gate.py``'s ``REQUIRED_WORKFLOWS`` holds LITERAL names,
    because it compares them against the ``name`` the Actions API reports for a
    run, which is never escaped. Both are correct and they now differ by a
    backslash — which is exactly the kind of near-identical pair that drifts.

    Nothing pinned them together before this test (`grep -rn REQUIRED_WORKFLOWS
    tests/` was empty). If they drift, the gate waits for a workflow that never
    reports, times out, and strands the merge.

    WHAT TURNS THIS RED: adding, removing or renaming a required workflow in
    one of the two places only.
    """
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "deploy_gate_for_name_check", _ROOT / "scripts" / "deploy_gate.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register BEFORE exec: the module defines dataclasses, and dataclass field
    # resolution looks the class's module up in sys.modules. Same reason
    # test_deploy_gate.py does this.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    # Scoped to deploy.yml ONLY. An earlier version compared against every
    # workflow_run reference in the whole directory, so adding an unrelated
    # listener (say a notifier on ["CI"]) turned this red with a message naming
    # deploy.yml — and the cheapest way to green would have been to edit
    # REQUIRED_WORKFLOWS, which strands merges. deploy.yml is the list the gate
    # actually waits on; it is the only one this invariant is about.
    from_yaml = tuple(
        re.sub(r"\\(.)", r"\1", pattern)
        for path, pattern in _workflow_run_references()
        if path.name == "deploy.yml"
    )
    assert from_yaml, "deploy.yml declares no on.workflow_run.workflows — nothing compared"
    assert tuple(module.REQUIRED_WORKFLOWS) == from_yaml, (
        f"scripts/deploy_gate.py REQUIRED_WORKFLOWS={module.REQUIRED_WORKFLOWS} "
        f"but deploy.yml (unescaped) lists {from_yaml}"
    )


def test_the_escaped_entry_parses_as_yaml() -> None:
    """The failure mode that would take EVERY deploy down, not just one trigger.

    ``\\+`` is invalid inside a double-quoted YAML scalar. If deploy.yml stops
    loading, `on:` is unparseable and nothing triggers at all — strictly worse
    than the defect being fixed. Loading the file here is that check; it throws
    before any assertion if the quoting is wrong.
    """
    data = _load(_WORKFLOWS / "deploy.yml")
    listed = _on_block(data)["workflow_run"]["workflows"]
    assert isinstance(listed, list) and listed, "deploy.yml must list required workflows"
