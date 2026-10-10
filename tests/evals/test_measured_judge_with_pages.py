"""The page-reading judge prompt (PR-EVAL-JUDGE-v2), measured (ADR-0156).

The fixture ``tests/evals/golden/measured/judge_with_pages_2026-10-10.json``
records the two paid runs the product owner approved before page reading was
switched on (CHG-038): costs, run-slot and fetch seconds, which cited pages
were read and why the others were not, and the judge call's prompt id, model,
token counts, scores, labels and SHA-256 fingerprints of both prompts. It
keeps no judge rationale and no page text (D-5).

Everything here is HERMETIC: the tests read the stored file and the prompts
the code builds today; nothing is called over the network. Each test names
what turns it red; each red case was shown by performing it (a one-character
change to the v2 system prompt, a rationale planted in a copy of the file).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from product_app.evaluation import (
    JUDGE_PAGES_PROMPT_ID,
    JudgeEvidence,
    build_judge_pages_prompt,
    build_judge_prompt,
)

_FIXTURE = (
    Path(__file__).resolve().parent / "golden" / "measured" / "judge_with_pages_2026-10-10.json"
)
SCHEMA = "measured-judge-with-pages-v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
#: Every outcome the fetcher can record for a page (``source_fetcher.Outcome``).
_OUTCOMES = {
    "fetched",
    "unusable",
    "refused_scheme",
    "refused_host",
    "refused_address",
    "refused_redirect",
    "refused_content_type",
    "too_large",
    "timeout",
    "http_error",
    "network_error",
    "skipped_cap",
    "refused_robots",
    "robots_unchecked",
}
#: Longer than any value the capture legitimately holds (the longest, a
#: document note, is 253 characters; the longest URL 241), far shorter than a
#: page's text.
LONGEST_LEGITIMATE_VALUE = 400


def _doc() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return doc


def _system_prompt_sha256(build: Any) -> tuple[str, int]:
    """The SHA-256 (UTF-8) and length of the system prompt ``build`` returns.
    The system prompt is a constant: any evidence gives the same one."""
    evidence = JudgeEvidence(
        query_text="q", answer_texts=("a",), source_lines=(), synthesis_sections=()
    )
    system, _user = build(evidence)
    return hashlib.sha256(system.encode("utf-8")).hexdigest(), len(system)


def _is_decimal_string(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"\d+\.\d+", value) is not None


# ---------------------------------------------------------------------------
# 1. Structure
# ---------------------------------------------------------------------------


def test_the_capture_has_two_runs_with_every_field_adr_0156_relies_on() -> None:
    """CARDINALITY FLOOR (rule 6b) and structure (rule 8): the schema, two
    runs labelled ``en`` and ``ja``, and in each run every field ADR-0156's
    table is built from, with its type. RED IF: the file is missing, has
    another schema, fewer or more runs, or any field is missing or of the
    wrong type (a cost that is not a decimal string, a token count that is
    not an int, a fingerprint that is not 64 hex digits)."""
    doc = _doc()
    assert doc["schema"] == SCHEMA
    assert _is_decimal_string(doc["total_cost_usd"])
    runs = doc["runs"]
    assert isinstance(runs, list)
    assert [run["label"] for run in runs] == ["en", "ja"]
    for run in runs:
        for key in ("estimate_usd", "max_usd", "actual_cost_usd"):
            assert _is_decimal_string(run[key]), (run["label"], key, run[key])
        assert run["cost_source"] == "measured"
        for key in ("run_slot_seconds", "fetch_seconds"):
            assert isinstance(run[key], float) and run[key] > 0, (run["label"], key)
        assert isinstance(run["panel"], list) and len(run["panel"]) == 4
        assert isinstance(run["models_answered"], int)
        pages = run["pages"]
        for key in ("cited", "read", "preview_refused", "preview_other"):
            assert isinstance(pages[key], int) and pages[key] >= 0, (run["label"], key)
        assert isinstance(run["page_outcomes"], list) and run["page_outcomes"]
        for page in run["page_outcomes"]:
            assert isinstance(page["url"], str) and page["url"].startswith("https://")
            assert page["outcome"] in _OUTCOMES, page["outcome"]
            assert page["http_status"] is None or isinstance(page["http_status"], int)
            assert isinstance(page["bytes"], int) and isinstance(page["text_chars"], int)
        judge = run["judge"]
        assert isinstance(judge["prompt_id"], str) and isinstance(judge["model"], str)
        for key in ("system_prompt_sha256", "user_prompt_sha256"):
            assert _SHA256.fullmatch(judge[key]), (run["label"], key)
        for key in ("user_prompt_chars", "prompt_tokens", "completion_tokens"):
            assert isinstance(judge[key], int) and judge[key] > 0, (run["label"], key)
        scores = judge["scores"]
        assert isinstance(scores["faithfulness"], int) and 0 <= scores["faithfulness"] <= 5
        assert isinstance(scores["grounding"], int) and 0 <= scores["grounding"] <= 5
        assert isinstance(scores["disagreement_preserved"], bool)
        assert scores["hallucination_risk"] in {"low", "medium", "high"}
        labels = judge["labels"]
        for key in ("faithfulness_label", "hallucination_risk", "judge_status"):
            assert isinstance(labels[key], str) and labels[key], (run["label"], key)


# ---------------------------------------------------------------------------
# 2. The capture is of TODAY's v2 prompt
# ---------------------------------------------------------------------------


def test_the_capture_is_of_todays_v2_system_prompt() -> None:
    """Both runs were judged with ``PR-EVAL-JUDGE-v2`` and the v2 system
    prompt the code builds today: its SHA-256 equals the recorded one. RED
    IF: the v2 system prompt changes by even one character without a new
    capture (the fingerprint then differs), or the prompt id moves. Partners:
    the hash is of a non-empty prompt, and differs from the v1 prompt's, so
    it identifies v2 rather than any judge prompt."""
    v2_sha, v2_len = _system_prompt_sha256(build_judge_pages_prompt)
    v1_sha, _ = _system_prompt_sha256(build_judge_prompt)
    assert v2_len > 0
    assert v2_sha != v1_sha
    for run in _doc()["runs"]:
        assert run["judge"]["prompt_id"] == JUDGE_PAGES_PROMPT_ID, run["label"]
        assert run["judge"]["system_prompt_sha256"] == v2_sha, run["label"]


# ---------------------------------------------------------------------------
# 3. D-5: no rationale, no page text
# ---------------------------------------------------------------------------


def _d5_offenders(node: object, path: str = "$") -> list[str]:
    """Every key whose name holds ``rationale`` (any case), and every string
    value longer than ``LONGEST_LEGITIMATE_VALUE``, anywhere in the tree."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if "rationale" in str(key).lower():
                found.append(f"{path}.{key} (a rationale key)")
            found.extend(_d5_offenders(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_d5_offenders(value, f"{path}[{index}]"))
    elif isinstance(node, str) and len(node) > LONGEST_LEGITIMATE_VALUE:
        found.append(f"{path} ({len(node)} chars)")
    return found


def test_the_capture_keeps_no_rationale_and_no_page_text() -> None:
    """D-5 across the WHOLE document, structurally (rule 8): no key named
    like ``rationale`` at any depth, and no string value longer than 400
    characters (judge prose and page text are long; telemetry is not). RED
    IF: either appears anywhere. Partners: the detector, run on copies of
    the document, finds a planted ``judge_rationale`` key, a planted
    ``Rationale`` key and a 401-character string, and passes a 400-character
    one; and the sweep reaches the real values (more than 50 strings)."""
    doc = _doc()
    assert _d5_offenders(doc) == []

    planted_key = copy.deepcopy(doc)
    planted_key["runs"][0]["judge"]["judge_rationale"] = "short"
    assert _d5_offenders(planted_key) == ["$.runs[0].judge.judge_rationale (a rationale key)"]
    planted_case = copy.deepcopy(doc)
    planted_case["runs"][1]["judge"]["scores"]["Rationale"] = "short"
    assert len(_d5_offenders(planted_case)) == 1
    planted_long = copy.deepcopy(doc)
    planted_long["runs"][1]["page_outcomes"][0]["text"] = "x" * 401
    assert _d5_offenders(planted_long) == ["$.runs[1].page_outcomes[0].text (401 chars)"]
    at_limit = copy.deepcopy(doc)
    at_limit["runs"][1]["page_outcomes"][0]["text"] = "x" * 400
    assert _d5_offenders(at_limit) == []

    strings: list[str] = []

    def collect(node: object) -> None:
        if isinstance(node, dict):
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)
        elif isinstance(node, str):
            strings.append(node)

    collect(doc)
    assert len(strings) > 50, len(strings)


def test_the_capture_holds_no_shell_expansion_residue() -> None:
    """The document was written through a shell; an unquoted ``$0`` in a
    heredoc expands to the shell's own path. RED IF: any string value holds
    a shell's path (``/bin/zsh``, ``/bin/bash``, ``/bin/sh``) -- the
    signature of an expanded ``$0``, ``$1``... where a dollar amount was
    meant. Partner: the check finds a planted one in a copy."""
    shells = ("/bin/zsh", "/bin/bash", "/bin/sh")

    def residue(node: object, path: str = "$") -> list[str]:
        if isinstance(node, dict):
            return [hit for k, v in node.items() for hit in residue(v, f"{path}.{k}")]
        if isinstance(node, list):
            return [hit for i, v in enumerate(node) for hit in residue(v, f"{path}[{i}]")]
        if isinstance(node, str) and any(shell in node for shell in shells):
            return [f"{path}: {node!r}"]
        return []

    doc = _doc()
    assert residue(doc) == []
    planted = copy.deepcopy(doc)
    planted["runs"][0]["label"] = "about /bin/zsh.19"
    assert residue(planted) == ["$.runs[0].label: 'about /bin/zsh.19'"]


# ---------------------------------------------------------------------------
# 4. Internal consistency
# ---------------------------------------------------------------------------


def test_the_total_is_the_sum_of_the_runs() -> None:
    """RED IF: ``total_cost_usd`` is not exactly the sum of the runs'
    ``actual_cost_usd`` (Decimal, no float rounding). Partner: both runs
    cost something."""
    doc = _doc()
    costs = [Decimal(run["actual_cost_usd"]) for run in doc["runs"]]
    assert all(cost > 0 for cost in costs)
    assert Decimal(doc["total_cost_usd"]) == sum(costs, Decimal(0))


def test_each_runs_page_counts_agree_with_its_page_outcomes() -> None:
    """RED IF: a run's ``pages.cited`` is not its number of page outcomes,
    ``pages.read`` is not its number of ``fetched`` outcomes, or the counted
    previews (``preview_refused`` + ``preview_other``) exceed the pages not
    read, or ``preview_refused`` exceeds the robots.txt refusals. Partner:
    each run read at least one page and left at least one unread, so every
    count is exercised."""
    for run in _doc()["runs"]:
        outcomes = [page["outcome"] for page in run["page_outcomes"]]
        pages = run["pages"]
        fetched = outcomes.count("fetched")
        assert pages["cited"] == len(outcomes), run["label"]
        assert pages["read"] == fetched, run["label"]
        assert pages["preview_refused"] + pages["preview_other"] <= len(outcomes) - fetched
        assert pages["preview_refused"] <= outcomes.count("refused_robots"), run["label"]
        assert 0 < fetched < len(outcomes), run["label"]
