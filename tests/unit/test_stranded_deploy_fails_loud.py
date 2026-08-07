"""A stranded merge must make the Deploy run RED, not silently skipped.

``scripts/deploy_gate.py`` already contains the whole stranding decision
(``deploy_gate.py:310-321``): when a required workflow did not succeed AND the
SHA is still ``main``'s tip, nothing else will ever deploy that commit, so the
gate returns 1 and the Deploy run reports failure. That code is unit-tested and
correct (``test_deploy_gate.py::test_main_blocked_failure_with_sha_still_tip_exits_nonzero``).

It had never once run. Measured 2026-08-07 over the last 200 Deploy runs::

    $ gh run list --workflow=deploy.yml --limit 200 --json conclusion \
        --jq 'group_by(.conclusion)|map({conclusion:.[0].conclusion,n:length})'
    [{"conclusion":"cancelled","n":35},
     {"conclusion":"skipped","n":130},
     {"conclusion":"success","n":35}]

Zero failures in 200 runs, and 130 skipped. The reason is the `gate` job's own
``if:`` condition, which required ``workflow_run.conclusion == 'success'``. A
*failing* required workflow therefore skipped the gate job **before**
``deploy_gate.py`` could classify the stranding — so the detection was gated on
the very condition it exists to detect. Issue #62's fix was present in the
script and unreachable through the workflow that guards it; issue #245 is that
observation.

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
        return _lookup(token, self.ctx)


def evaluate(expr: str, ctx: dict[str, Any]) -> bool:
    return bool(_Parser(_tokenize(expr), ctx).parse_or())


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
        "exactly when it is needed. Measured: 0 failures in 200 Deploy runs."
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
    """Security-critical (deploy.yml:46-53).

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


# --- the diagnostic that makes #245's claim 1 answerable ------------------


def _gate_steps() -> list[dict[str, Any]]:
    data: dict[Any, Any] = yaml.safe_load(_DEPLOY_YML.read_text(encoding="utf-8"))
    steps = data["jobs"]["gate"]["steps"]
    assert isinstance(steps, list) and steps, "the gate job must have steps"
    return steps


def test_the_gate_records_which_workflow_triggered_it() -> None:
    """#245 AC1 asks WHY the E2E trigger does not fire, measured not guessed.

    It could not be measured: the Actions API never exposes a Deploy run's
    triggering workflow, so the only evidence available was timestamp
    correlation — which contradicted itself across two SHAs on the same day.
    A run that prints its own trigger settles it from the log next time.
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
