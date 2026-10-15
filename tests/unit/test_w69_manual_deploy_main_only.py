"""W69: a manual deploy is refused from any ref but ``main``, on refs that carry W69.

``deploy.yml`` accepts ``workflow_dispatch``, and the "Run workflow" button
lets the person pressing it choose ANY branch or tag. Before W69 the deploy
gate (``scripts/deploy_gate.py``) waved every manual dispatch through, and the
``deploy`` job then checked out ``github.sha`` — the commit of whatever ref
was chosen. So anyone with write access could ship an unreviewed branch to
production without it ever passing CI.

After W69, two checks in the files of the chosen ref refuse it:

1. ``deploy_gate.main()`` on a ``workflow_dispatch`` proceeds only when
   ``GITHUB_REF`` is exactly ``refs/heads/main``. Any other ref, or no ref at
   all, writes ``proceed=false`` and returns 1, so the Deploy run shows a red
   failure rather than a quiet skip.
2. The ``deploy`` job's own ``if:`` also refuses a dispatch from any other ref.
   GitHub compares strings there ignoring case, so it is weaker than (1).

GitHub runs the CHOSEN ref's own ``deploy.yml`` and ``deploy_gate.py``, so
neither check stops a branch whose copies predate W69 or were edited. Since
2026-10-15 the token's home does: ``FLY_API_TOKEN`` is a secret of the
``production`` environment only, which allows only ``main`` (CHG-046,
ADR-0166 update; ``test_deploy_job_uses_production_environment.py``).

The gate JOB's ``if:`` deliberately still admits a dispatch from any ref — it
must run so the script can fail loudly.

Every test of ``main()`` sets or deletes ``GITHUB_REF`` itself: the CI runner
exports one (``refs/pull/N/merge`` on a pull request) into the pytest process,
and a test that inherited it would pass or fail depending on where it ran.

The ``if:`` expressions are EVALUATED with the evaluator from
``test_stranded_deploy_fails_loud.py`` (itself tested there), not matched as
substrings (AGENTS.md rule 8).

WHAT TURNS THIS FILE RED: make ``main()`` proceed on a dispatch from a ref
other than ``refs/heads/main`` (or return 0 when it refuses); drop the ref
condition from the ``deploy`` job's ``if:``, or key it on ``github.ref_name``
(which a TAG named ``main`` also satisfies); or add a ref condition to the
``gate`` job's ``if:``.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from tests.repo_root import find_repo_root
from tests.unit.test_stranded_deploy_fails_loud import evaluate

ROOT = find_repo_root(Path(__file__))
GATE_SCRIPT = ROOT / "scripts" / "deploy_gate.py"
DEPLOY_YML = ROOT / ".github" / "workflows" / "deploy.yml"
OUR_REPO = "imrohitagrawal/quorum-ai"
MAIN = "refs/heads/main"


def _load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("w69_deploy_gate_under_test", GATE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


def _no_network(*_args: object) -> str | None:
    raise AssertionError("a manual dispatch must be decided without calling the GitHub API")


def _dispatch_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ref: str | None) -> Path:
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    if ref is None:
        monkeypatch.delenv("GITHUB_REF", raising=False)
    else:
        monkeypatch.setenv("GITHUB_REF", ref)
    # A dispatch never has these; deleting them means a refusal cannot be
    # produced by falling through to the "Missing REPO or SHA" branch.
    monkeypatch.delenv("REPO", raising=False)
    monkeypatch.delenv("SHA", raising=False)
    monkeypatch.setattr(gate, "gh_fetch_conclusion", _no_network)
    monkeypatch.setattr(gate, "gh_fetch_main_tip", _no_network)
    return out


def _outputs(out: Path) -> list[str]:
    return out.read_text(encoding="utf-8").splitlines() if out.exists() else []


# ---------------------------------------------------------------------------
# deploy_gate.main()
# ---------------------------------------------------------------------------


def test_a_dispatch_from_main_proceeds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Positive partner for the refusals below; passes now.

    Red when: ``main()`` stops proceeding on a manual dispatch from
    ``refs/heads/main``, or writes ``proceed=`` other than exactly once."""
    out = _dispatch_env(monkeypatch, tmp_path, MAIN)
    assert gate.main() == 0
    assert _outputs(out) == ["proceed=true"]


@pytest.mark.parametrize(
    "ref",
    [
        "refs/heads/feature-x",
        "refs/heads/main-old",
        "refs/heads/feature/main",
        "refs/tags/v1",
        "refs/tags/main",
        "refs/pull/5/merge",
        "main",
        "",
    ],
)
def test_a_dispatch_from_any_other_ref_fails_loud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ref: str
) -> None:
    """Red when: ``main()`` proceeds on a manual dispatch whose ``GITHUB_REF``
    is not exactly ``refs/heads/main`` (a branch, a branch whose name merely
    starts or ends with main, a tag — including one named ``main`` — a pull
    request ref, a bare name, or empty), or refuses quietly with exit 0."""
    out = _dispatch_env(monkeypatch, tmp_path, ref)
    assert gate.main() == 1
    assert _outputs(out) == ["proceed=false"]


def test_a_dispatch_with_no_ref_at_all_fails_loud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Red when: ``main()`` treats a missing ``GITHUB_REF`` as main (fail-open)
    instead of writing ``proceed=false`` and returning 1."""
    out = _dispatch_env(monkeypatch, tmp_path, None)
    assert gate.main() == 1
    assert _outputs(out) == ["proceed=false"]


# ---------------------------------------------------------------------------
# deploy.yml: the deploy job's if: and the gate job's if:
# ---------------------------------------------------------------------------


def _job_if(job: str) -> str:
    data: dict[Any, Any] = yaml.safe_load(DEPLOY_YML.read_text(encoding="utf-8"))
    condition = data["jobs"][job].get("if")
    assert isinstance(condition, str) and condition.strip(), f"deploy.yml {job} has no if:"
    condition = condition.strip()
    wrapped = re.fullmatch(r"\$\{\{(.*)\}\}", condition, flags=re.DOTALL)
    return (wrapped.group(1) if wrapped else condition).replace('"', "'")


def _ref_parts(ref: str) -> tuple[str, str]:
    """``(ref_name, ref_type)`` as GitHub derives them from ``github.ref``."""
    for prefix, kind in (("refs/heads/", "branch"), ("refs/tags/", "tag")):
        if ref.startswith(prefix):
            return ref[len(prefix) :], kind
    return ref.removeprefix("refs/pull/"), "branch"


def _ctx(*, event_name: str, ref: str, proceed: str | None) -> dict[str, Any]:
    """The ``github`` and ``needs`` contexts the deploy job's ``if:`` sees.

    ``workflow_run`` always runs with ``github.ref`` set to the default branch,
    so callers pass ``MAIN`` for it."""
    ref_name, ref_type = _ref_parts(ref)
    workflow_run = (
        {
            "event": "push",
            "head_branch": "main",
            "head_repository": {"full_name": OUR_REPO},
            "conclusion": "success",
        }
        if event_name == "workflow_run"
        else None
    )
    return {
        "github": {
            "event_name": event_name,
            "ref": ref,
            "ref_name": ref_name,
            "ref_type": ref_type,
            "repository": OUR_REPO,
            "event": {"workflow_run": workflow_run},
        },
        "needs": {"gate": {"result": "success", "outputs": {"proceed": proceed}}},
    }


#: Every context path the deploy job's ``if:`` may read — hand-written, so it
#: is a statement of intent, not a copy of the file (AGENTS.md rule 7a).
_MODELLED = frozenset(
    {
        "github.event_name",
        "github.ref",
        "github.ref_name",
        "github.ref_type",
        "github.repository",
        "needs.gate.outputs.proceed",
        "needs.gate.result",
    }
)
_PATH = re.compile(r"\b(?:github|needs)\.[A-Za-z0-9_.-]+")


def test_partner_the_context_reaches_the_evaluator() -> None:
    """Partner, passes now.

    Red when: ``_ctx`` stops building ``github.ref`` or
    ``needs.gate.outputs.proceed`` where the evaluator looks them up, so every
    deploy-job assertion below would compare against None."""
    ctx = _ctx(event_name="workflow_dispatch", ref="refs/tags/main", proceed="true")
    assert evaluate("needs.gate.outputs.proceed == 'true'", ctx)
    assert evaluate("github.ref == 'refs/tags/main'", ctx)
    assert evaluate("github.ref_name == 'main' && github.ref_type == 'tag'", ctx)
    assert not evaluate("github.ref == 'refs/heads/main'", ctx)


def test_the_deploy_job_reads_only_modelled_context_fields() -> None:
    """Red when: the deploy job's ``if:`` reads a ``github.*`` or ``needs.*``
    field ``_ctx`` does not build — every assertion here would see it as None
    and could not tell what it does. Model it, do not widen the set blindly."""
    referenced = set(_PATH.findall(_job_if("deploy")))
    assert "needs.gate.outputs.proceed" in referenced, referenced
    unmodelled = referenced - _MODELLED
    assert not unmodelled, f"the deploy job's if: reads unmodelled fields {sorted(unmodelled)}"


def test_the_deploy_job_runs_for_a_dispatch_from_main() -> None:
    """Positive partner; passes now.

    Red when: the deploy job's ``if:`` refuses a manual dispatch from
    ``refs/heads/main`` whose gate proceeded."""
    ctx = _ctx(event_name="workflow_dispatch", ref=MAIN, proceed="true")
    assert evaluate(_job_if("deploy"), ctx)


def test_the_deploy_job_runs_for_a_workflow_run_trigger() -> None:
    """Positive partner; passes now.

    Red when: the ref condition is written so it also blocks the normal
    ``workflow_run`` path whose gate proceeded."""
    ctx = _ctx(event_name="workflow_run", ref=MAIN, proceed="true")
    assert evaluate(_job_if("deploy"), ctx)


@pytest.mark.parametrize(
    "ref",
    ["refs/heads/x", "refs/heads/main-old", "refs/tags/main", "refs/tags/v1", "refs/pull/5/merge"],
)
def test_the_deploy_job_refuses_a_dispatch_from_another_ref(ref: str) -> None:
    """Red when: the deploy job's ``if:`` lets a manual dispatch from any ref
    but ``refs/heads/main`` deploy — even with the gate's ``proceed`` true —
    including a tag named ``main``, which ``github.ref_name == 'main'`` would
    wrongly admit."""
    ctx = _ctx(event_name="workflow_dispatch", ref=ref, proceed="true")
    assert not evaluate(_job_if("deploy"), ctx)


@pytest.mark.parametrize("event_name", ["workflow_dispatch", "workflow_run"])
@pytest.mark.parametrize("proceed", ["false", None])
def test_the_deploy_job_never_runs_without_the_gate_proceeding(
    event_name: str, proceed: str | None
) -> None:
    """Red when: the deploy job's ``if:`` runs when the gate wrote
    ``proceed=false`` or wrote nothing, on either trigger."""
    ctx = _ctx(event_name=event_name, ref=MAIN, proceed=proceed)
    assert not evaluate(_job_if("deploy"), ctx)


@pytest.mark.parametrize("ref", [MAIN, "refs/heads/feature-x", "refs/tags/v1"])
def test_the_gate_job_still_runs_for_a_dispatch_from_any_ref(ref: str) -> None:
    """Red when: a ref condition is added to the GATE job's ``if:``. A
    dispatch from another ref must still reach ``deploy_gate.py`` so it can
    fail loudly; a skipped gate would turn the refusal into a silent skip."""
    ctx = _ctx(event_name="workflow_dispatch", ref=ref, proceed=None)
    assert evaluate(_job_if("gate"), ctx)
