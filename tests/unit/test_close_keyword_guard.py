"""The close-keyword guard must catch a negated close and leave real ones alone.

GitHub closes an issue whenever a close keyword sits immediately before
``#<number>``, and its parser has no concept of negation. Five times in this
repository a sentence written to say "this is NOT closed" closed the issue.
Every text below is verbatim from the repository's own history, so the corpus
cannot drift away from the defect it exists to pin.

The whole design risk is the OPPOSITE failure: a checker that flags every
``Fixes #123`` fires on all 64 legitimate closes in this history, becomes noise
and gets ignored. So every "flagged" assertion here ships with a "not flagged"
partner, and ``test_the_corpora_reject_a_degenerate_checker`` proves the two
corpora together admit neither a flag-everything nor a flag-nothing
implementation.

No network and no ``gh``: these drive the pure functions over fixture text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from scripts.check_close_keywords import close_references, main, negated_closes

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: Every negated close that actually happened, verbatim, with the issue GitHub
#: really closed. Expected numbers are written as LITERALS: deriving them by
#: running the checker would make the test agree with any implementation.
#:
#: Re-derive the first four with:
#:   git log -1 --format=%B <sha> | grep -i -E '(not|never).{0,20}(clos|fix)'
REAL_NEGATED_CLOSES: tuple[tuple[str, str, list[int]], ...] = (
    (
        "e6c84ea / PR #174 commit — closed #175",
        "Filed, not fixed: #175 (whitespace completion served as a live answer with a",
        [175],
    ),
    (
        "8ca6a98 / PR #282 commit — closed #268",
        "This does NOT close #268: the `cost_system_prompt_tokens` /",
        [268],
    ),
    (
        # The comma-chained numbers must NOT appear: GitHub closed only #185,
        # and #171/#178/#180/#182 were all verified closed by something else.
        "0ace31e — closed #185, and only #185",
        "not fixed: #185, #171, #178, #180, #182 (unrelated, operator-gated, or",
        [185],
    ),
    (
        "4ea57ba / PR #360 merge body — closed #337",
        "**This does NOT close #337.** This PR's own mutation job is green having measured nothing",
        [337],
    ),
    (
        # Markdown emphasis between the negation and the verb. GitHub's parser
        # ignores `**`; so must this one, or the live PR #282 body slips past.
        "PR #282 body — GitHub reported closingIssuesReferences [268]",
        "This does **not** close #268. The `cost_system_prompt_tokens` half remains.",
        [268],
    ),
)

#: Text that must stay clean. A false positive here BLOCKS a pull request, so
#: these are as load-bearing as the corpus above. The last three are the
#: precision cases the clause-boundary rule exists for.
MUST_NOT_FLAG: tuple[tuple[str, str], ...] = (
    ("the ordinary close", "Fixes #123"),
    ("another ordinary close", "Closes #45"),
    ("lower-case resolves", "resolves #7"),
    ("a bare reference with no keyword", "See #123 for the background."),
    ("a conventional-commit scope with no issue", "fix(mutation-gate): name the oracle tests"),
    (
        # Measured non-vector: `fix(#N)` appears in 10 subjects on main; three
        # carry no other reference to that issue and none closed it. #148 was
        # closed 17 days BEFORE its `fix(#148)` commit, with commit_id null.
        "the conventional-commit scope holding an issue number",
        "fix(#337): the mutation scope names its oracle tests, and a truncated run "
        "is not a score (#360)",
    ),
    ("a real line from e6c84ea that closes nothing", "Closes nothing. Refs #171."),
    ("the safe rewording PR #289 shipped", "All three issues stay OPEN."),
    ("a negation in a preceding clause, comma-separated", "With no regressions, closes #123."),
    ("a negation in a preceding sentence", "This does not affect the cache. Closes #123."),
)


def test_every_real_negated_close_is_flagged_with_the_right_issue() -> None:
    """Turns red if the classifier stops matching any of the five real texts.

    Mutation proof: deleting any member of ``NEGATIONS``, or dropping the
    markdown-emphasis skip, drops at least one case here.
    """
    for label, text, expected in REAL_NEGATED_CLOSES:
        found = [finding.issue for finding in negated_closes(text)]
        assert found == expected, f"{label}: expected {expected}, got {found}"


def test_the_five_real_texts_yield_exactly_five_findings() -> None:
    """Cardinality, not just "something matched" (AGENTS.md rule 6b).

    Turns red if the classifier starts reporting the comma-chained numbers in
    the #185 case — that would make it six or more and would be wrong, since
    GitHub closed only #185.
    """
    total = sum(len(negated_closes(text)) for _, text, _ in REAL_NEGATED_CLOSES)
    assert total == 5


def test_legitimate_closes_are_never_flagged() -> None:
    """Turns red if the guard starts firing on an ordinary ``Fixes #123``.

    This is the noise failure. Widening the look-back past a comma or a
    sentence end turns the last two cases red.
    """
    for label, text in MUST_NOT_FLAG:
        assert negated_closes(text) == [], f"{label}: wrongly flagged {text!r}"


def test_the_clean_corpus_really_contains_closing_references() -> None:
    """The positive partner for the assertion above (AGENTS.md rule 7).

    "Nothing was flagged" is trivially true over text with no close keyword at
    all. Turns red if ``close_references`` stops recognising a plain close, which
    would make ``test_legitimate_closes_are_never_flagged`` pass vacuously.
    """
    assert [issue for _, issue, _ in close_references("Fixes #123")] == [123]
    assert [issue for _, issue, _ in close_references("Closes #45")] == [45]
    assert [issue for _, issue, _ in close_references("resolves #7")] == [7]
    # And the bracket form is genuinely not a reference, rather than merely
    # un-flagged — the reason it is safe to leave alone.
    assert close_references("fix(#337): the mutation scope") == []


def test_the_corpora_reject_a_degenerate_checker() -> None:
    """Both directions, in one place (AGENTS.md "prove both directions").

    Turns red if either corpus is emptied or weakened: a checker that flags
    NOTHING must fail the positive corpus, and one that flags EVERY closing
    reference must fail the clean corpus. If either assertion below stops
    holding, the suite has stopped discriminating.
    """
    flags_nothing_survives = all(not negated_closes(t) for _, t, _ in REAL_NEGATED_CLOSES)
    assert not flags_nothing_survives, "a checker returning [] would pass the positive corpus"

    flags_everything_survives = all(not close_references(t) for _, t in MUST_NOT_FLAG)
    assert not flags_everything_survives, (
        "a checker flagging every closing reference would pass the clean corpus"
    )


def test_an_empty_input_refuses_to_pass(capsys) -> None:  # type: ignore[no-untyped-def]
    """A gate that measured nothing is not a green gate.

    Turns red if ``--require-nonempty`` stops failing on empty text — which is
    what a typo in the workflow's ``env:`` names would produce.
    """
    code = main(["prog", "--env", "NO_SUCH_VAR_FOR_THIS_TEST", "--require-nonempty"])
    assert code == 2
    assert "EMPTY" in capsys.readouterr().out


def test_reporting_counts_what_it_examined(capsys) -> None:  # type: ignore[no-untyped-def]
    """Turns red if the guard stops printing the number of references it saw.

    Every gate here must report what it counted; a bare "OK" cannot be told
    apart from a gate that read nothing.
    """
    from scripts.check_close_keywords import _report

    assert _report("t", "This does NOT close #337.", advisory=False) == 1
    out = capsys.readouterr().out
    assert "1 closing reference(s), 1 negated" in out


def test_advisory_mode_reports_but_does_not_block(capsys) -> None:  # type: ignore[no-untyped-def]
    """The post-merge lane cannot block: a commit message is immutable.

    Turns red if ``--advisory`` starts returning non-zero, which would strand
    main — ci.yml's ``validate-and-test`` is a required context and the deploy
    gate needs it green, so a red push job would block production with no edit
    that could ever turn it green.
    """
    from scripts.check_close_keywords import _report

    assert _report("t", "This does NOT close #337.", advisory=True) == 0
    assert "ADVISORY" in capsys.readouterr().out


def _validate_job_steps() -> list[dict[str, Any]]:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text())
    return list(workflow["jobs"]["validate-and-test"]["steps"])


def test_the_pull_request_lane_is_wired_into_a_required_context() -> None:
    """Structure, not substring (AGENTS.md rule 8) — the step must EXIST.

    Turns red if the guard step is removed from ``validate-and-test``, which is
    the required status check; a step named only in a comment would not satisfy
    this because the YAML is parsed, not grepped.
    """
    steps = _validate_job_steps()
    guard = [s for s in steps if "--env PR_TITLE PR_BODY" in str(s.get("run", ""))]
    assert len(guard) == 1, "expected exactly one pull-request close-keyword guard step"
    step = guard[0]
    assert "pull_request" in str(step.get("if", "")), "the guard must be gated to pull requests"
    assert "--require-nonempty" in str(step["run"]), "the vacuity floor must stay wired"


def test_the_pull_request_text_reaches_the_script_through_the_environment() -> None:
    """A pull-request body is attacker-controlled text.

    Turns red if someone interpolates ``${{ github.event.pull_request.body }}``
    directly into the ``run:`` script, which is a shell-injection hole: a body
    containing backticks or ``$( )`` would execute on the runner. The value must
    arrive as an environment variable instead.
    """
    steps = _validate_job_steps()
    guard = next(s for s in steps if "--env PR_TITLE PR_BODY" in str(s.get("run", "")))
    env: dict[str, Any] = guard.get("env") or {}
    assert "github.event.pull_request.title" in str(env.get("PR_TITLE", ""))
    assert "github.event.pull_request.body" in str(env.get("PR_BODY", ""))
    assert "${{" not in str(guard["run"]), "no GitHub expression may be interpolated into run:"


def test_the_post_merge_backstop_runs_on_a_push_and_cannot_block() -> None:
    """Turns red if the main-push backstop is dropped, or made blocking.

    Blocking it would permanently strand production: the commit message it
    inspects can never be edited to make the check green.
    """
    steps = _validate_job_steps()
    backstop = [s for s in steps if "--commit" in str(s.get("run", ""))]
    assert len(backstop) == 1, "expected exactly one post-merge backstop step"
    assert "--advisory" in str(backstop[0]["run"]), "the backstop must not be able to block"
    assert "push" in str(backstop[0].get("if", "")), "the backstop belongs on the push lane"
