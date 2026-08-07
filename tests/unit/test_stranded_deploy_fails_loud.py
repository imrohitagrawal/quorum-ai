"""A stranded merge must make the Deploy run RED, not silently skipped.

``scripts/deploy_gate.py`` already contains the whole stranding decision
(``deploy_gate.py:310-321``): when a required workflow did not succeed AND the
SHA is still ``main``'s tip, nothing else will ever deploy that commit, so the
gate returns 1 and the Deploy run reports failure. That code is unit-tested and
correct (``test_deploy_gate.py::test_main_blocked_failure_with_sha_still_tip_exits_nonzero``).

It has never once run since it was written. Measured 2026-08-07, scoped to the
period after the check landed (``d671c6f``, 2026-08-01T16:33:59Z): **238**
Deploy runs — 150 skipped, 44 success, 44 cancelled — and **not one reported
failure**. (The repository does hold 27 failed Deploy runs, but every one is
from 2026-07-11..16, mostly under the older ``push``-triggered design, before
this check existed. ``--limit 200`` returns the most recent runs, not the
population; do not read a sample as an absolute.)

The reason is the `gate` job's own ``if:``, which required
``workflow_run.conclusion == 'success'``. A *failing* required workflow
therefore skipped the gate job **before** ``deploy_gate.py`` could classify the
stranding — so the detection was gated on the very condition it exists to
detect. Issue #62's fix was present in the script and unreachable through the
workflow that guards it; issue #245 is that observation.

**How often that actually bit — stated honestly, because the first draft of
this file overstated it by ~65x.** The 130-150 skipped runs are NOT 130
suppressed strandings. Over 2026-08-03T09:42Z..2026-08-07T13:29Z there were 80
genuine main-push completions of a required workflow, of which exactly **2**
were non-success — ``CI`` and ``Tests``, both on ``3444961``
(2026-08-03T17:03Z), the merge #245 was filed about. Those two are the only
occasions this term ever suppressed the gate. Every other skipped Deploy run is
a pull-request-branch trigger rejected by ``event == 'push'`` — a term this fix
KEEPS, so they still skip. The defect is real and it is demonstrated on one
real merge, not on a hundred.

The fix drops the ``conclusion`` term from the ``if:`` and lets
``deploy_gate.py`` — real, tested Python rather than an untestable YAML
expression — make the decision. The security-critical terms stay in the
``if:``: a fork PR whose source branch is literally named ``main`` must never
reach the gate.

WHAT TURNS THIS FILE RED: restore ``github.event.workflow_run.conclusion ==
'success' &&`` to the gate job's ``if:`` in ``.github/workflows/deploy.yml``.
``test_a_failed_required_workflow_still_reaches_the_gate`` then fails, because
the gate would skip exactly when a stranding needs detecting.

Rather than match substrings against the condition (AGENTS.md rule 8 — a
substring matches the prose that explains the thing), these tests EVALUATE the
real expression from the real file against a table of event contexts. The tiny
evaluator is itself covered by ``test_evaluator_*`` below, so it cannot pass by
being broken (AGENTS.md rule 7 — a negative check needs a positive partner).
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

import pytest
import yaml

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DEPLOY_YML = _ROOT / ".github" / "workflows" / "deploy.yml"

_OUR_REPO = "imrohitagrawal/quorum-ai"


# --------------------------------------------------------------------------
# A minimal evaluator for the GitHub expression subset used by this ``if:``.
# Supports: || && == != , parentheses, single-quoted literals, dotted context
# lookups. A missing path resolves to None, which is how GitHub treats an
# absent context field (e.g. ``workflow_run`` on a manual dispatch).
# --------------------------------------------------------------------------

_TOKEN = re.compile(
    r"\s*(\(|\)|\|\||&&|==|!=|'[^']*'|[A-Za-z_][A-Za-z0-9_.]*)"
)


def _tokenize(expr: str) -> list[str]:
    tokens: list[str] = []
    pos = 0
    while pos < len(expr):
        match = _TOKEN.match(expr, pos)
        if match is None:
            if expr[pos:].strip() == "":
                break
            raise ValueError(f"cannot tokenize at {expr[pos:pos + 40]!r}")
        tokens.append(match.group(1))
        pos = match.end()
    return tokens


def _lookup(path: str, ctx: dict[str, Any]) -> Any:
    node: Any = ctx
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


class _Parser:
    def __init__(self, tokens: list[str], ctx: dict[str, Any]) -> None:
        self.tokens = tokens
        self.pos = 0
        self.ctx = ctx

    def _peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _next(self) -> str:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def parse_or(self) -> Any:
        value = self.parse_and()
        while self._peek() == "||":
            self._next()
            right = self.parse_and()
            value = value or right
        return value

    def parse_and(self) -> Any:
        value = self.parse_cmp()
        while self._peek() == "&&":
            self._next()
            right = self.parse_cmp()
            value = value and right
        return value

    def parse_cmp(self) -> Any:
        left = self.parse_atom()
        while self._peek() in ("==", "!="):
            op = self._next()
            right = self.parse_atom()
            left = (left == right) if op == "==" else (left != right)
        return left

    def parse_atom(self) -> Any:
        token = self._next()
        if token == "(":
            value = self.parse_or()
            closing = self._next()
            assert closing == ")", f"expected ) got {closing!r}"
            return value
        if token.startswith("'"):
            return token[1:-1]
        # GitHub has real boolean literals. Resolving them as context paths
        # would make them None (falsy) and a wide-open `... || true` condition
        # would then read as FALSE here while admitting everything on GitHub —
        # a suite that passes against a condition with no security terms at all.
        if token == "true":
            return True
        if token == "false":
            return False
        return _lookup(token, self.ctx)


def evaluate(expr: str, ctx: dict[str, Any]) -> bool:
    tokens = _tokenize(expr)
    parser = _Parser(tokens, ctx)
    value = parser.parse_or()
    # Without this the parser returns after the longest prefix it understands
    # and DISCARDS the rest, so `<valid condition> || <anything>` evaluates as
    # the valid condition alone. Every assertion in this file would then be
    # blind to an appended disjunct. There is no workflow linter in this repo
    # (`grep -rn "actionlint\|yamllint" Makefile .github/ scripts/` is empty),
    # so this file is the only thing that reads the expression at all.
    assert parser.pos == len(tokens), (
        f"unconsumed tokens {tokens[parser.pos:]!r} — the condition has "
        "structure this evaluator does not model, so the assertions below "
        "would silently ignore it"
    )
    return bool(value)


def _gate_if() -> str:
    data: dict[Any, Any] = yaml.safe_load(_DEPLOY_YML.read_text(encoding="utf-8"))
    condition = data["jobs"]["gate"]["if"]
    assert isinstance(condition, str) and condition.strip(), (
        "deploy.yml's gate job must carry an `if:` condition"
    )
    return condition


def _ctx(
    *,
    event_name: str = "workflow_run",
    conclusion: str | None = "success",
    event: str | None = "push",
    head_branch: str | None = "main",
    head_repo: str | None = _OUR_REPO,
) -> dict[str, Any]:
    """Build a ``github`` context the way Actions would present it."""
    workflow_run: dict[str, Any] = {
        "conclusion": conclusion,
        "event": event,
        "head_branch": head_branch,
        "head_repository": {"full_name": head_repo},
    }
    return {
        "github": {
            "event_name": event_name,
            "repository": _OUR_REPO,
            "event": {"workflow_run": workflow_run},
        }
    }


# --------------------------------------------------------------------------
# The evaluator's own positive partners. Without these, every assertion below
# could pass against a broken evaluator that returns a constant.
# --------------------------------------------------------------------------


def test_evaluator_reads_a_dotted_context_path() -> None:
    assert evaluate("github.event_name == 'push'", {"github": {"event_name": "push"}})
    assert not evaluate("github.event_name == 'push'", {"github": {"event_name": "pull_request"}})


def test_evaluator_missing_path_is_none_not_a_crash() -> None:
    assert not evaluate("github.event.workflow_run.conclusion == 'success'", {"github": {}})


def test_evaluator_respects_and_or_precedence_and_parens() -> None:
    ctx = {"a": "1", "b": "2", "c": "3"}
    # a==1 || (b==9 && c==9)  -> True via the left branch alone
    assert evaluate("a == '1' || (b == '9' && c == '9')", ctx)
    # (a==9 || b==2) && c==3  -> True only if the parenthesised OR is honoured
    assert evaluate("(a == '9' || b == '2') && c == '3'", ctx)
    assert not evaluate("(a == '9' || b == '9') && c == '3'", ctx)


def test_evaluator_handles_the_real_condition_shape() -> None:
    """A sanity anchor: the real expression parses and is not constantly true."""
    condition = _gate_if()
    assert not evaluate(condition, _ctx(event_name="push", conclusion=None, event=None))


# --------------------------------------------------------------------------
# The contract.
# --------------------------------------------------------------------------


def test_a_failed_required_workflow_still_reaches_the_gate() -> None:
    """THE defect in #245/#62.

    A required workflow that FAILED on a genuine push to our own main is
    precisely when a stranding can happen. The gate job must RUN so
    ``deploy_gate.py`` can decide whether this SHA is stranded (still main's
    tip → exit 1 → red) or merely superseded (→ quiet exit 0).
    """
    condition = _gate_if()
    assert evaluate(condition, _ctx(conclusion="failure")), (
        "deploy.yml's gate job skips when a required workflow FAILED, so "
        "scripts/deploy_gate.py's stranding detection can never run — which is "
        "exactly when it is needed. Measured: 0 failed Deploy runs in the 238 "
        "since the stranding check landed."
    )


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "action_required"])
def test_every_non_success_terminal_conclusion_reaches_the_gate(conclusion: str) -> None:
    """Not just ``failure``: any non-success conclusion leaves the SHA unverified.

    ``deploy_gate.py`` uses an allow-LIST (only ``success`` proceeds), so
    letting these through cannot cause a deploy — it can only let the gate
    classify the stranding.
    """
    assert evaluate(_gate_if(), _ctx(conclusion=conclusion))


def test_a_successful_run_still_reaches_the_gate() -> None:
    """The happy path must keep working — this is what deploys today."""
    assert evaluate(_gate_if(), _ctx(conclusion="success"))


def test_a_manual_dispatch_still_reaches_the_gate() -> None:
    assert evaluate(_gate_if(), _ctx(event_name="workflow_dispatch", conclusion=None))


# --- the security terms the fix must NOT relax ---------------------------


def test_a_fork_pr_branch_named_main_never_reaches_the_gate() -> None:
    """Security-critical — see the comment above the gate's ``if:``.

    ``head_branch == 'main'`` alone is spoofable by a fork PR whose source
    branch is literally named ``main`` — that run carries attacker code. It
    must be rejected on BOTH the event type and the head repository.
    """
    assert not evaluate(_gate_if(), _ctx(event="pull_request", head_repo="attacker/quorum-ai"))
    assert not evaluate(_gate_if(), _ctx(conclusion="failure", head_repo="attacker/quorum-ai"))


def test_a_push_to_a_non_main_branch_never_reaches_the_gate() -> None:
    assert not evaluate(_gate_if(), _ctx(head_branch="feature/x"))
    assert not evaluate(_gate_if(), _ctx(conclusion="failure", head_branch="feature/x"))


def test_a_non_push_event_never_reaches_the_gate() -> None:
    assert not evaluate(_gate_if(), _ctx(event="pull_request"))
    assert not evaluate(_gate_if(), _ctx(conclusion="failure", event="pull_request"))


# --- the condition may not reach for a field the table does not model -----

#: Every context path the gate condition is allowed to read. Hand-written, so
#: it is an INDEPENDENT statement of intent rather than a restatement of the
#: file (AGENTS.md rule 7a). `_ctx()` below models exactly these.
_MODELLED_PATHS = frozenset(
    {
        "github.event_name",
        "github.repository",
        "github.event.workflow_run.event",
        "github.event.workflow_run.head_branch",
        "github.event.workflow_run.head_repository.full_name",
    }
)

_CONTEXT_PATH = re.compile(r"\bgithub\.[A-Za-z0-9_.]+")


def test_the_condition_reads_no_context_field_the_test_table_cannot_vary() -> None:
    """Closes the evasion this suite would otherwise be blind to.

    `_lookup` returns None for any path `_ctx()` does not build, so a NEW
    disjunct keyed on an unmodelled field is invisible: every assertion still
    passes while the real condition on GitHub admits more. The concrete case,
    demonstrated in review — appending
    ``|| github.event.workflow_run.head_branch == github.event.repository.default_branch``
    is a plausible "stop hardcoding main" refactor, keeps all 16 tests green,
    and admits a fork PR whose source branch is named `main`, because
    `default_branch` is present on every workflow_run payload.

    WHAT TURNS THIS RED: adding any `github.*` path to the gate's `if:` that is
    not in `_MODELLED_PATHS`. The fix is to model it in `_ctx()` and add the
    rows that pin its behaviour — not to widen this set.
    """
    referenced = set(_CONTEXT_PATH.findall(_gate_if()))
    assert referenced, "no github.* context path found — the condition is not being read"
    unmodelled = referenced - _MODELLED_PATHS
    assert not unmodelled, (
        f"the gate condition reads {sorted(unmodelled)}, which _ctx() does not "
        "build. Every assertion in this file treats it as None, so the table "
        "cannot see what it does. Model it in _ctx() and pin its behaviour."
    )


def test_the_deploy_job_still_requires_the_gate_to_have_proceeded() -> None:
    """The ADR's SECOND allow-list, which nothing pinned.

    ADR-0024 rests its "a red trigger cannot deploy a red build" argument on
    two independent allow-lists. The first is `deploy_gate.py` (well tested).
    The second is this `if:` — and `grep -rn "needs.gate" tests/` was empty
    before this test, so deleting it would have gone unnoticed. That is the
    same "a decision expressed as a GitHub `if:` cannot be tested" failure the
    ADR exists to end.

    WHAT TURNS THIS RED: dropping `needs: gate`, or relaxing the deploy job's
    `if:` so it no longer requires `proceed == 'true'`.
    """
    data: dict[Any, Any] = yaml.safe_load(_DEPLOY_YML.read_text(encoding="utf-8"))
    deploy = data["jobs"]["deploy"]
    needs = deploy.get("needs")
    needs = [needs] if isinstance(needs, str) else list(needs or [])
    assert "gate" in needs, "the deploy job must depend on the gate job"
    condition = (deploy.get("if") or "").replace('"', "'")
    assert "needs.gate.outputs.proceed == 'true'" in condition, (
        f"the deploy job's if: is {condition!r} — it must require the gate to "
        "have proceeded, which is the second of the two allow-lists ADR-0024 "
        "relies on"
    )


# --- the diagnostic that makes the trigger visible ------------------------


def _gate_steps() -> list[dict[str, Any]]:
    data: dict[Any, Any] = yaml.safe_load(_DEPLOY_YML.read_text(encoding="utf-8"))
    steps = data["jobs"]["gate"]["steps"]
    assert isinstance(steps, list) and steps, "the gate job must have steps"
    return steps


def test_the_gate_records_which_workflow_triggered_it() -> None:
    """Makes a Deploy run's trigger readable without timestamp archaeology.

    The Actions API never exposes a `workflow_run` run's triggering workflow,
    so attribution today rests on a 2-4s lag — and that is easy to misread,
    because such a run is stamped with the DEFAULT BRANCH's tip as its own
    head_sha, so pull-request-branch triggers masquerade as main's SHA.

    This does NOT settle #245's claim 1. "E2E never fires this workflow" is
    about a Deploy run that is never CREATED, and a run that does not exist
    has no log; that claim is settled by counting (E2E 0/26, CI 27/27,
    Tests 27/27 — see ADR-0024).
    """
    reads_trigger_name = [
        step
        for step in _gate_steps()
        if "github.event.workflow_run.name" in yaml.safe_dump(step)
    ]
    assert reads_trigger_name, (
        "no gate step reads github.event.workflow_run.name, so a Deploy run "
        "still cannot say which workflow triggered it"
    )


def test_the_trigger_diagnostic_does_not_interpolate_into_the_shell() -> None:
    """A workflow NAME is arbitrary text; ``run:`` is the script-injection sink.

    The values must arrive via ``env:`` and be dereferenced as shell variables.
    Positive partner for the negative check: the same step is asserted above to
    genuinely carry the expression, so this cannot pass over a missing step.
    """
    for step in _gate_steps():
        body = step.get("run") or ""
        assert "github.event.workflow_run.name" not in body, (
            f"step {step.get('name')!r} interpolates a workflow name straight "
            "into its run: body — pass it through env: instead"
        )
