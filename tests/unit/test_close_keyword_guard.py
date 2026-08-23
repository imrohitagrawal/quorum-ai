"""The close-keyword guard must catch a negated close and leave real ones alone.

GitHub closes an issue whenever a close keyword sits immediately before
``#<number>``, and its parser has no concept of negation. In this repository
**six** such texts named **five** issues, and **four** of those issues actually
closed — #105 was caught by a manual grep just before its merge and never
closed. Every text below is verbatim from the repository's own history, so the
corpus cannot drift away from the defect it exists to pin.

The whole design risk is the OPPOSITE failure: a checker that flags every
``Fixes #123`` fires on all 64 legitimate closes in the commit history and all
66 in the pull-request history, becomes noise and gets ignored. So every
"flagged" assertion here ships with a "not flagged" partner, and
``test_the_corpora_reject_a_degenerate_checker`` proves the two corpora together
admit neither a flag-everything nor a flag-nothing implementation.

No network and no ``gh``: these drive the pure functions over fixture text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from scripts.check_close_keywords import (
    _EMPHASIS,
    NEGATIONS,
    close_references,
    main,
    negated_closes,
)

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
        "This does **not** close #268. The `cost_system_prompt_tokens` / "
        "`cost_web_search_context_tokens` half remains, blocked on telemetry that "
        "does not exist.",
        [268],
    ),
    (
        # The one that got away from the DEFECT, not from the guard: a manual
        # grep caught it before the merge and the body was reworded, so #105
        # never closed. The text is real and must still be detected.
        "PR #289 body — caught by hand before merge; #105 never closed",
        "**This PR does not close #105, #268 or #203, and must not.**",
        [105],
    ),
)

#: Verified from each issue's `closed` timeline event on 2026-08-24. #105 is
#: absent because it was NEVER closed (`gh issue view 105` -> state=OPEN,
#: closedAt=null), which is why nothing in this diff may say "five issues were
#: closed". Five issues were TARGETED across six texts; four actually closed.
CLOSED_BY_A_NEGATED_SENTENCE = frozenset({175, 185, 268, 337})

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
    (
        # REAL, and it was a live false positive until the blank-line rule
        # landed: dropping the newline boundary entirely let the walk reach out
        # of the body and into the subject line above it.
        "9cfda0e — a legitimate close under a subject containing two negations",
        "fix(judge): tell a judge that produced nothing from one that never ran (#270)"
        "\n\nCloses #258.",
    ),
    (
        "b904ce6 — a legitimate close under a subject ending in 'does not'",
        "feat(deploy): prove production runs main's tip, and go red when it does not"
        " (#245)\n\nCloses #245's third failure mode.",
    ),
    (
        # GitHub does NOT close on `closing`; widening the keyword set to match
        # it would be a silent false-positive generator.
        "the gerund, which GitHub does not treat as a close keyword",
        "Work closing #123 is tracked separately.",
    ),
    # One per clause-boundary character. Each was unpinned until a reviewer
    # deleted it from _CLAUSE_BOUNDARY with the whole suite staying green.
    ("a colon boundary", "No blockers remain: closes #123."),
    ("a semicolon boundary", "No regressions; closes #123."),
    ("an exclamation boundary", "No more flakes! Closes #123."),
    ("a question-mark boundary", "Any regressions? None. Closes #123."),
    (
        # The look-back's UPPER bound. The negation is four words back, so this
        # must stay clean; it is the partner to the two-word case below.
        "a negation four words before the keyword",
        "This does not on its own close #337.",
    ),
    (
        # MEASURED: GitHub returns closingIssuesReferences [] for a reference
        # inside a code span, and [148] for the same text as prose.
        "a closing reference inside an inline code span",
        "The bad shape is `Closes #123` written in prose.",
    ),
    (
        "a closing reference inside a fenced block",
        "Example output:\n\n```\nCloses #123\n```\n\nThat is all.",
    ),
)

#: Negation words that are NOT exercised by the real corpus above (every real
#: text uses plain `not`). Without these the other members of `NEGATIONS` are
#: dead weight that could be deleted with the suite staying green — a reviewer
#: proved exactly that. Synthetic, and labelled as such.
SYNTHETIC_NEGATIONS: tuple[tuple[str, list[int]], ...] = (
    ("This never closes #123.", [123]),
    ("There is no fix #123 here.", [123]),
    ("This does nothing to close #123.", [123]),
    ("None of this closes #123.", [123]),
    ("It neither closes #123 nor reopens it.", [123]),
    ("It does not close issue 1, nor fixes #123.", [123]),
    ("This cannot close #123.", [123]),
    ("This doesn't close #123.", [123]),
    ("This won't fix #123.", [123]),
    # The look-back's LOWER bound: two intervening words must still reach.
    ("This does not yet close #123.", [123]),
    # The `newlines = 0` reset — without it a wrapped negation stops counting.
    ("This does not\nyet\nclose #123.", [123]),
    # The bracket/quote strip around a negation word.
    ("This does (not) close #123.", [123]),
    # One per markdown emphasis character, none of which were exercised.
    ("This does _not_ close #123.", [123]),
    ("This does `not` close #123.", [123]),
    ("This does ~not~ close #123.", [123]),
)


def test_every_real_negated_close_is_flagged_with_the_right_issue() -> None:
    """Turns red if the classifier stops matching any of the five real texts.

    Mutation proof: deleting any member of ``NEGATIONS``, or dropping the
    markdown-emphasis skip, drops at least one case here.
    """
    for label, text, expected in REAL_NEGATED_CLOSES:
        found = [finding.issue for finding in negated_closes(text)]
        assert found == expected, f"{label}: expected {expected}, got {found}"


def test_the_real_texts_yield_exactly_one_finding_each() -> None:
    """Cardinality, not just "something matched" (AGENTS.md rule 6b).

    Turns red if the classifier starts reporting the comma-chained numbers in
    the #185 case — that would make it seven or more and would be wrong, since
    GitHub closed only #185 there.
    """
    total = sum(len(negated_closes(text)) for _, text, _ in REAL_NEGATED_CLOSES)
    assert total == 6


def test_the_corpus_matches_the_verified_history() -> None:
    """The counts every prose file in this diff quotes, pinned to the corpus.

    Turns red if an entry is added or removed without updating them. It exists
    because the first version of this work said "five issues were closed" in
    four different files; #105 was never closed at all, and the ADR's own
    evidence column said so while its prose did not.
    """
    assert len(REAL_NEGATED_CLOSES) == 6, "six real texts"
    targeted = {issue for _, _, expected in REAL_NEGATED_CLOSES for issue in expected}
    assert targeted == {105, 175, 185, 268, 337}, "five issues targeted"
    assert {175, 185, 268, 337} == CLOSED_BY_A_NEGATED_SENTENCE, "four actually closed"
    assert 105 not in CLOSED_BY_A_NEGATED_SENTENCE


def test_every_negation_word_is_exercised_by_the_corpus() -> None:
    """No dead weight in NEGATIONS.

    Turns red if a word is added to NEGATIONS without a text that exercises it.
    A reviewer deleted ten of the original twelve members with the whole suite
    staying green, because every real text happens to use plain `not`.
    """
    corpus = [text for _, text, _ in REAL_NEGATED_CLOSES]
    corpus += [text for text, _ in SYNTHETIC_NEGATIONS]
    seen = {finding.negation for text in corpus for finding in negated_closes(text)}
    unexercised = {word for word in NEGATIONS if word not in seen}
    assert unexercised == set(), f"never exercised by any corpus text: {sorted(unexercised)}"
    assert any(word.endswith("n't") for word in seen), "the n't suffix branch is untested"


def test_synthetic_negations_are_classified_as_written() -> None:
    """Turns red if any single negation word stops being recognised.

    Deleting one member of NEGATIONS reds exactly the line that uses it.
    """
    for text, expected in SYNTHETIC_NEGATIONS:
        assert [f.issue for f in negated_closes(text)] == expected, text


def test_the_lookback_window_is_bounded_at_both_ends() -> None:
    """Pins the window without asserting against the constant (rule 7a).

    Turns red if the look-back shrinks below two intervening words (the first
    case stops being flagged) or grows past three (the second starts being
    flagged, reaching into an unrelated earlier phrase). Both bounds are
    literals here; neither is derived from _LOOKBACK_WORDS.
    """
    assert [f.issue for f in negated_closes("This does not yet close #123.")] == [123]
    assert negated_closes("This is not at all a good close #123.") == []


def test_a_hard_wrapped_commit_body_is_still_caught() -> None:
    """git wraps a commit body at ~72 characters.

    Turns red if a newline is treated as a clause boundary again. It was, in the
    first version, and it disarmed the guard on the ordinary shape of the very
    sentence it exists to catch — while close_references still agreed GitHub
    would close the issue.
    """
    wrapped = "Follow-up is filed separately and this pull request does NOT\nclose #337."
    assert len(close_references(wrapped)) == 1, "GitHub would still close #337 here"
    assert [f.issue for f in negated_closes(wrapped)] == [337]


def test_legitimate_closes_are_never_flagged() -> None:
    """Turns red if the guard starts firing on an ordinary ``Fixes #123``.

    This is the noise failure. Widening the look-back past a comma or a
    sentence end turns the last two cases red.
    """
    for label, text in MUST_NOT_FLAG:
        assert negated_closes(text) == [], f"{label}: wrongly flagged {text!r}"


def test_markdown_code_is_not_a_closing_reference_but_prose_is() -> None:
    """MEASURED against the live API, not assumed (AGENTS.md rule 8c).

    On 2026-08-24 PR #361's body was edited to carry `Closes #148` inside an
    inline span and inside a fenced block: closingIssuesReferences returned [].
    The positive control, the same text as prose, returned [148].

    Turns red if the code-span filter is removed. Without it this repository's
    own ADR yields 13 findings and the blocking lane rejects any pull request
    that documents the guard.
    """
    assert close_references("See `Closes #123` in the docs.") == []
    assert close_references("```\nCloses #123\n```") == []
    # The positive partner: the identical text outside code IS a reference.
    assert [issue for _, issue, _ in close_references("See Closes #123 in the docs.")] == [123]
    # And a negation inside code still counts, because the reference is outside
    # it — GitHub would close this one.
    assert [f.issue for f in negated_closes("This does `not` close #123.")] == [123]


def test_every_emphasis_character_is_exercised_by_the_corpus() -> None:
    """No dead weight in _EMPHASIS either.

    Turns red if a character is added to _EMPHASIS without a text that needs it.
    A reviewer reduced the set to a single character with the suite green.
    """
    corpus = [text for _, text, _ in REAL_NEGATED_CLOSES]
    corpus += [text for text, expected in SYNTHETIC_NEGATIONS if expected]
    for char in _EMPHASIS:
        assert any(char in text and negated_closes(text) for text in corpus), (
            f"no corpus text needs the emphasis character {char!r}"
        )


def test_a_negation_in_the_title_cannot_reach_a_close_in_the_body() -> None:
    """The blank line `main()` inserts between the variables is load-bearing.

    Turns red if the "\n\n" join is weakened to a single newline or a space:
    an ordinary title such as `fix(judge): a run that produced nothing` would
    then negate a perfectly legitimate `Closes #258` in the body and block the
    pull request.
    """
    import os

    os.environ["CG_T"] = "fix(judge): a run that produced nothing"
    os.environ["CG_B"] = "Closes #258."
    try:
        assert main(["prog", "--env", "CG_T", "CG_B", "--require-nonempty"]) == 0
    finally:
        del os.environ["CG_T"], os.environ["CG_B"]


def test_the_clean_corpus_really_contains_closing_references() -> None:
    """The positive partner for the assertion above (AGENTS.md rule 7).

    "Nothing was flagged" is trivially true over text with no close keyword at
    all. Turns red if ``close_references`` stops recognising a plain close, which
    would make ``test_legitimate_closes_are_never_flagged`` pass vacuously.
    """
    assert [issue for _, issue, _ in close_references("Fixes #123")] == [123]
    assert [issue for _, issue, _ in close_references("Closes #45")] == [45]
    assert [issue for _, issue, _ in close_references("resolves #7")] == [7]
    # And these are genuinely not REFERENCES, rather than merely un-flagged.
    # Asserting only "not flagged" let a reviewer widen the keyword set to
    # include the gerund with the whole suite staying green: `closing #123`
    # would then be a closing reference that GitHub does not honour, and every
    # sentence using it would become a candidate false positive.
    assert close_references("fix(#337): the mutation scope") == []
    assert close_references("Work closing #123 is tracked separately.") == []
    assert close_references("This is a fixture for #123.") == []
    # The LEADING word boundary: without it, `Hotfixes` ends in `fixes` and the
    # whole sentence becomes a closing reference.
    assert close_references("Hotfixes #123 land on release branches.") == []


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


def test_an_empty_input_refuses_to_pass(capsys: Any) -> None:
    """A gate that measured nothing is not a green gate.

    Turns red if ``--require-nonempty`` stops failing on empty text — which is
    what a typo in the workflow's ``env:`` names would produce.
    """
    code = main(["prog", "--env", "NO_SUCH_VAR_FOR_THIS_TEST", "--require-nonempty"])
    assert code == 2
    assert "not set in the environment" in capsys.readouterr().out


def test_one_missing_variable_fails_even_when_another_is_populated(
    capsys: Any, monkeypatch: Any
) -> None:
    """The floor is PER VARIABLE, because a title is never empty.

    Turns red if the check goes back to testing the joined text: a typo in the
    PR_BODY variable's name would then be hidden by the title, and the body is
    the half that carried both pull-request-surface cases (#268 and #105).
    """
    monkeypatch.setenv("CG_TITLE", "fix: a perfectly ordinary title")
    monkeypatch.delenv("CG_BODY_TYPO", raising=False)
    assert main(["prog", "--env", "CG_TITLE", "CG_BODY_TYPO", "--require-nonempty"]) == 2
    assert "CG_BODY_TYPO" in capsys.readouterr().out


def test_an_empty_body_that_is_actually_set_still_passes(monkeypatch: Any) -> None:
    """The partner: presence, not content.

    Turns red if the floor starts rejecting a legitimately empty body, which
    would block a pull request for a reason that is not a defect.
    """
    monkeypatch.setenv("CG_TITLE2", "fix: a title")
    monkeypatch.setenv("CG_BODY2", "")
    assert main(["prog", "--env", "CG_TITLE2", "CG_BODY2", "--require-nonempty"]) == 0


def test_reporting_counts_what_it_examined(capsys: Any) -> None:
    """Turns red if the guard stops printing the number of references it saw.

    Every gate here must report what it counted; a bare "OK" cannot be told
    apart from a gate that read nothing.
    """
    from scripts.check_close_keywords import _report

    assert _report("t", "This does NOT close #337.", advisory=False) == 1
    out = capsys.readouterr().out
    assert "1 closing reference(s), 1 negated" in out


def test_advisory_mode_reports_but_does_not_block(capsys: Any) -> None:
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


MAKEFILE = REPO_ROOT / "Makefile"


def _workflow() -> dict[str, Any]:
    # PyYAML reads the bare key `on` as the boolean True (the Norway problem's
    # cousin), so both spellings have to be tried.
    loaded: dict[Any, Any] = yaml.safe_load(CI_WORKFLOW.read_text())
    return {("on" if key is True else key): value for key, value in loaded.items()}


def test_the_workflow_reruns_when_the_pull_request_body_is_edited() -> None:
    """`edited` is NOT a default activity type, and the body is a checked surface.

    Turns red if `edited` is dropped from the pull_request trigger. Without it
    the blocking check vets a body that no longer exists at merge time: measured
    over the last 60 merged pull requests, 12 had title/body edits and 7 landed
    the last edit AFTER the last commit push — including PR #289, whose body was
    the one carrying a negated close.
    """
    types = _workflow()["on"]["pull_request"]["types"]
    assert "edited" in types
    # The partner: the defaults must not be lost by naming types at all.
    assert {"opened", "synchronize", "reopened"} <= set(types)


def test_the_guard_steps_carry_the_exact_event_conditions() -> None:
    """EQUALITY, not substring — the docstring below used to lie about this.

    Turns red if either `if:` is altered at all. A substring assertion passed
    happily when `==` was flipped to `!=`, which would run the BLOCKING step on
    every push to main with PR_TITLE and PR_BODY unset. That exits 2, reddens
    the required `validate-and-test` context, and strands the deploy — the exact
    failure this whole design is arranged to avoid.
    """
    steps = _validate_job_steps()
    pr_step = next(s for s in steps if "--env PR_TITLE PR_BODY" in str(s.get("run", "")))
    backstop = next(s for s in steps if "--commit" in str(s.get("run", "")))
    assert pr_step["if"] == "github.event_name == 'pull_request'"
    assert backstop["if"] == "github.event_name == 'push'"


def test_the_backstop_cannot_fail_on_an_unset_summary_path() -> None:
    """`set -o pipefail` makes tee's exit status the step's.

    Turns red if the `${GITHUB_STEP_SUMMARY:-/dev/null}` fallback is removed.
    With a bare "$GITHUB_STEP_SUMMARY" and the variable unset, tee fails and the
    step exits 1 — so a lane documented as "advisory by construction" could
    redden a required context after all.
    """
    backstop = next(s for s in _validate_job_steps() if "--commit" in str(s.get("run", "")))
    assert "GITHUB_STEP_SUMMARY:-" in str(backstop["run"])


def _close_guard_recipe() -> str:
    lines = MAKEFILE.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("close-guard:"))
    recipe = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        recipe.append(line)
    return "\n".join(recipe)


def test_the_close_guard_recipe_never_interpolates_merge_text_into_a_shell() -> None:
    """A merge body is full of backticks and quotes.

    Turns red if `$(SUBJECT)`/`$(BODY)` style expansion comes back. The first
    version had it, and a reviewer used it to execute a command from the body
    AND showed the target could not parse PR #360's real merge body at all —
    the one text this layer exists for. The text must arrive through the
    environment, exactly as the ci.yml step does.
    """
    recipe = _close_guard_recipe()
    assert "--env MERGE_SUBJECT MERGE_BODY" in recipe
    assert "--require-nonempty" in recipe, "layer 2 needs its vacuity floor too"

    # An ALLOWLIST, not a denylist. The first version banned four spellings and
    # a reviewer walked straight past it with ${BODY}, which make expands
    # identically to $(BODY) — the injection and the silent text loss both came
    # back with the suite green. Strip the two expansions that are meant to be
    # here and assert nothing else survives.
    residue = recipe.replace("$(PYTHON)", "").replace('"$${PR:?set PR=<pull request number>}"', "")
    assert "$" not in residue, f"unexpected shell/make expansion in the recipe: {residue!r}"


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
    # The two one-line downgrades that turn a blocking gate advisory. Both
    # survived the first version of this suite.
    assert "continue-on-error" not in step, "that silently downgrades the blocking lane"
    assert "--advisory" not in str(step["run"]), "the pull-request lane must be able to fail"


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
