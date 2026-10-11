"""The router reads the change (ADR-0159, failure modes R1-R7).

``route()`` stops at the first product phase with missing documents, so today it
always lands on "Operate, learn, and improve" and names one driver and 39
reviewers for every item. ``route_work()`` instead classifies the paths (and the
changed lines) of one work item and adds only the roles, checks and skills each
matching class needs.

Every expected value below is a LITERAL taken from a real commit or from the
interface in ADR-0159. None is read from ``configs/skill-router.json``, because
a test that reads its expected value from the config it tests cannot fail
(AGENTS.md rule 7a). The config is read only to ENUMERATE names that must be
real skills, which is the thing under test there, not an expected value.
"""

from __future__ import annotations

import functools
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[2]
_ROUTER_PATH = _ROOT / "scripts" / "skill_router.py"
_SKILLS = _ROOT / ".agents" / "skills"

# 40249a6 (W47, anonymous spend counted per network): a real money change.
_W47_MONEY_PATHS = [
    "src/product_app/costs.py",
    "src/product_app/auth.py",
    "src/product_app/session_store.py",
]
# ef4a716 (#105, the :online web-search fee): a real money change that took 11
# review rounds because many files repeated the old value.
_FEE_MONEY_PATHS = [
    "src/product_app/config.py",
    ".env.example",
    "tests/unit/test_cost_breakdown.py",
]

# The one behavioural line of ef4a716, copied from
# `git show ef4a716 -- src/product_app/config.py` (the hunk header is the real
# one; the hunk is cut to the removed and added line only).
_FEE_DIFF = """\
diff --git a/src/product_app/config.py b/src/product_app/config.py
--- a/src/product_app/config.py
+++ b/src/product_app/config.py
@@ -571,1 +593,1 @@ class Settings(BaseSettings):
-    cost_web_search_request_fee_usd: float = Field(default=0.0, ge=0, allow_inf_nan=False)
+    cost_web_search_request_fee_usd: float = Field(default=0.007, ge=0, allow_inf_nan=False)
"""

# Same file, a constructed settings change: the removed and added lines change
# a real non-money field (`tavily_timeout_seconds`), and the money word sits
# only in an unchanged CONTEXT line (the real `cost_initial_output_tokens` line,
# placed next to it for this test; in the file the two are not adjacent). A
# context line must not count.
_NON_MONEY_SETTINGS_DIFF = """\
diff --git a/src/product_app/config.py b/src/product_app/config.py
--- a/src/product_app/config.py
+++ b/src/product_app/config.py
@@ -160,2 +160,2 @@ class Settings(BaseSettings):
     cost_initial_output_tokens: int = 700
-    tavily_timeout_seconds: float = 8.0
+    tavily_timeout_seconds: float = 10.0
"""

_DOCS_ONLY_PATHS = [
    "docs/65-open-work.md",
    "docs/adr/0113-the-online-search-fee-is-priced.md",
]


@functools.lru_cache(maxsize=1)
def _router() -> ModuleType:
    """Load the script by path. Called INSIDE each test, so a missing function
    fails that test alone instead of erroring the whole module at collection."""
    spec = importlib.util.spec_from_file_location("skill_router_work_item_under_test", _ROUTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _route_work(paths: list[str], diff_text: str = "") -> dict:  # type: ignore[type-arg]
    return _router().route_work(paths, diff_text)  # type: ignore[no-any-return]


# --------------------------------------------------------------------------
# R1: a money change gets the money roles (by path, or by the changed line).
# --------------------------------------------------------------------------


def test_real_money_changes_route_money_roles_and_the_sweep_check() -> None:
    # Red when: the money class stops matching costs.py / test_cost_breakdown.py by path, or
    # stops adding the "failure-modes-first" role or the "sweep-old-value" check.
    for paths in (_W47_MONEY_PATHS, _FEE_MONEY_PATHS):
        r = _route_work(paths)
        assert "money" in r["classes"], (paths, r["classes"])
        assert "failure-modes-first" in r["roles"], (paths, r["roles"])
        assert "sweep-old-value" in r["checks"], (paths, r["checks"])
        assert r["driver"] == "work-item-delivery"


def test_config_py_is_settings_by_path_and_money_only_by_its_changed_line() -> None:
    # Red when: config.py routes "money" by its path alone (over-routing, R2), or the real
    # ef4a716 fee line in the diff text no longer adds "money" (under-routing, R1), or a money
    # word in an unchanged context line adds "money".
    bare = _route_work(["src/product_app/config.py"])
    assert "settings" in bare["classes"], bare["classes"]
    assert "money" not in bare["classes"], bare["classes"]

    # Positive partner: the same path WITH the real fee line is money.
    fee = _route_work(["src/product_app/config.py"], _FEE_DIFF)
    assert "money" in fee["classes"], fee["classes"]
    assert "failure-modes-first" in fee["roles"], fee["roles"]
    assert "sweep-old-value" in fee["checks"], fee["checks"]

    # A money word only in a context line does not count; only +/- lines do.
    context_only = _route_work(["src/product_app/config.py"], _NON_MONEY_SETTINGS_DIFF)
    assert "settings" in context_only["classes"], context_only["classes"]
    assert "money" not in context_only["classes"], context_only["classes"]


# --------------------------------------------------------------------------
# R2: a docs-only change gets no money role, skill or check.
# --------------------------------------------------------------------------


def test_docs_only_change_is_docs_only_even_when_a_file_name_says_fee() -> None:
    # Red when: a docs-only change is given any class besides "docs-only" (e.g. "money" from
    # the ADR's file name), or loses its "prose-auditor" role.
    r = _route_work(_DOCS_ONLY_PATHS)
    assert r["classes"] == ["docs-only"], r["classes"]
    for absent in ("failure-modes-first", "test-designer"):
        assert absent not in r["roles"], (absent, r["roles"])
    assert "sweep-old-value" not in r["checks"], r["checks"]
    # Positive partner: the docs-only route does add its own role.
    assert "prose-auditor" in r["roles"], r["roles"]

    # Positive partner: one code path next to the same docs ends docs-only.
    mixed = _route_work([*_DOCS_ONLY_PATHS, "src/product_app/costs.py"])
    assert "docs-only" not in mixed["classes"], mixed["classes"]
    assert "money" in mixed["classes"], mixed["classes"]


# --------------------------------------------------------------------------
# R3: every src/ file falls in a class, counted against the TREE.
# --------------------------------------------------------------------------


def test_every_tracked_src_file_falls_in_a_code_class() -> None:
    # Red when: a file under src/ (any extension: .py, .js, .css, .html, .png, .svg, .md)
    # is reported unclassified, gets no class, or is routed as docs-only.
    listed = subprocess.run(
        ["git", "ls-files", "src"], cwd=_ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    # Partner: the enumeration is not empty (57 files on 2026-10-11).
    assert len(listed) >= 50, f"only {len(listed)} src files enumerated"
    bad: list[tuple[str, object, object]] = []
    for path in listed:
        r = _route_work([path])
        if not r["classes"] or r["classes"] == ["docs-only"] or r["unclassified"]:
            bad.append((path, r["classes"], r["unclassified"]))
    assert bad == [], f"src files with no code class: {bad}"


# --------------------------------------------------------------------------
# R4: every routed name is a real skill; every blocking gate is a skill or
# a make target.
# --------------------------------------------------------------------------


def test_every_routed_skill_name_has_a_skill_file() -> None:
    # Red when: the config, route(), or route_work() names a skill with no
    # .agents/skills/<name>/SKILL.md, or route_work()'s driver skill file is missing.
    router = _router()
    config = json.loads((_ROOT / "configs" / "skill-router.json").read_text(encoding="utf-8"))
    names: set[str] = set()
    for phase in config["phases"]:
        names.add(phase["driver"])
        names.update(phase.get("reviewers", []))
    for skills in config.get("risk_triggers", {}).values():
        names.update(skills)
    old = router.route()
    names.add(old["driver"])
    names.update(old["reviewers"])

    probe_paths = [
        *_W47_MONEY_PATHS,
        *_FEE_MONEY_PATHS,
        "docs/65-open-work.md",
        "src/product_app/static/app.js",
        ".github/workflows/ci.yml",
    ]
    routed_by_work = 0
    for path in probe_paths:
        r = router.route_work([path])
        names.update(r["reviewer_skills"])
        routed_by_work += len(r["reviewer_skills"])
        driver = r["driver"]
        assert (_SKILLS / driver / "SKILL.md").is_file(), f"driver skill missing: {driver}"
    assert (_SKILLS / "work-item-delivery" / "SKILL.md").is_file()

    missing = sorted(n for n in names if not (_SKILLS / n / "SKILL.md").is_file())
    assert missing == [], f"routed names that are not skills: {missing}"
    # Partners: the check ran over a real population, and route_work() named at least one skill.
    assert len(names) > 50, f"only {len(names)} names checked"
    assert routed_by_work > 0, "route_work() named no reviewer skill for any probe path"


def _makefile_targets() -> set[str]:
    text = (_ROOT / "Makefile").read_text(encoding="utf-8")
    # `name:` or `name: deps`, but not `NAME := value` / `NAME ?= value`.
    return set(re.findall(r"^([A-Za-z0-9_.-]+)[ \t]*:(?![=:])", text, re.M))


def test_every_blocking_gate_is_a_skill_or_a_defined_make_target() -> None:
    # Red when: a phase's blocking_gates names something that is neither a skill with SKILL.md
    # nor "make <target>" for a target the Makefile defines (today: no-placeholder-gate,
    # release-evidence-gate, and skill-onboarding-check written without "make").
    config = json.loads((_ROOT / "configs" / "skill-router.json").read_text(encoding="utf-8"))
    targets = _makefile_targets()
    # Partner: the Makefile parse found the targets the config is known to cite.
    assert {"handoff", "skill-route", "skill-onboarding-check"} <= targets, sorted(targets)[:20]
    gates = [g for phase in config["phases"] for g in phase.get("blocking_gates", [])]
    assert len(gates) >= 10, f"only {len(gates)} gates enumerated"
    bad = []
    for gate in gates:
        if gate.startswith("make "):
            if gate.removeprefix("make ").strip() not in targets:
                bad.append(gate)
        elif not (_SKILLS / gate / "SKILL.md").is_file():
            bad.append(gate)
    assert bad == [], f"blocking gates that are neither a skill nor a make target: {bad}"


# --------------------------------------------------------------------------
# Interface class.
# --------------------------------------------------------------------------


def test_app_js_routes_interface_and_the_user_journey_tester() -> None:
    # Red when: src/product_app/static/app.js stops matching the "interface" class, or that
    # class stops adding the "user-journey-tester" role.
    r = _route_work(["src/product_app/static/app.js"])
    assert "interface" in r["classes"], r["classes"]
    assert "user-journey-tester" in r["roles"], r["roles"]


# --------------------------------------------------------------------------
# Item mode (R6).
# --------------------------------------------------------------------------

_BOARD = """\
| Id | Work | State | Evidence | Blocked by | Issue |
|---|---|---|---|---|---|
| W55 | Delete old spend keys from `src/product_app/costs.py` and `src/product_app/session_store.py` after 24 hours | UNPINNED | `—` | — | — |
| W5 | Unrelated row whose id is a prefix of the one above; touches `src/product_app/evaluation.py` | UNPINNED | `—` | — | — |
| W56 | A different row about `src/product_app/static/app.js` | UNPINNED | `—` | — | — |
"""  # noqa: E501


def test_paths_for_item_reads_the_backticked_paths_of_exactly_that_row() -> None:
    # Red when: paths_for_item() misses a backticked path in the row, matches a neighbouring
    # row (W5 is a prefix of W55), returns the "—" placeholder as a path, or returns another
    # row's text.
    paths, row = _router().paths_for_item("W55", board_text=_BOARD)
    assert "src/product_app/costs.py" in paths, paths
    assert "src/product_app/session_store.py" in paths, paths
    assert "src/product_app/evaluation.py" not in paths, paths
    assert "src/product_app/static/app.js" not in paths, paths
    assert "—" not in paths, paths
    assert "W55" in row and "Delete old spend keys" in row, row
    assert "A different row" not in row and "Unrelated row" not in row, row

    # W5 is a prefix of W55, and the W55 row comes first: a prefix match returns W55's row.
    paths5, row5 = _router().paths_for_item("W5", board_text=_BOARD)
    assert paths5 == ["src/product_app/evaluation.py"], paths5
    assert "Unrelated row" in row5 and "Delete old spend keys" not in row5, row5


def test_paths_for_item_also_reads_the_path_inside_an_evidence_needle() -> None:
    # Red when: paths_for_item() ignores the path inside an evidence cell
    # ("ABSENT <path> :: <needle>"), which is where every real board row cites its file.
    board = (
        "| W3 | Raise the daily cap | PENDING "
        '| `PRESENT src/product_app/costs.py :: DAILY_CAP_USD = Decimal("0.20")` | — | — |\n'
    )
    paths, _row = _router().paths_for_item("W3", board_text=board)
    assert "src/product_app/costs.py" in paths, paths


def test_paths_for_item_refuses_an_unknown_id() -> None:
    # Red when: an id that is no row (a typo, W5S) returns an empty result instead of raising
    # LookupError, so a typo prints an empty checklist that reads as "nothing needed".
    router = _router()
    try:
        router.paths_for_item("W5S", board_text=_BOARD)
    except LookupError:
        pass
    else:
        raise AssertionError("paths_for_item('W5S') did not raise LookupError")
    # Positive partner: a real id in the same board does not raise.
    router.paths_for_item("W56", board_text=_BOARD)


def test_cli_item_with_an_unknown_id_exits_1_with_a_message() -> None:
    # Red when: `skill_router.py --item W5S` exits 0, or exits 1 without a message on stderr.
    proc = subprocess.run(
        [sys.executable, str(_ROUTER_PATH), "--item", "W5S"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, (proc.returncode, proc.stdout[-500:], proc.stderr[-500:])
    assert proc.stderr.strip(), "no message on stderr"


# --------------------------------------------------------------------------
# Diff mode (R6, R7).
# --------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _clean_repo(tmp: Path) -> Path:
    """A git repo holding the router script and its config, all committed."""
    repo = tmp / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "configs").mkdir()
    shutil.copy2(_ROUTER_PATH, repo / "scripts" / "skill_router.py")
    shutil.copy2(_ROOT / "configs" / "skill-router.json", repo / "configs" / "skill-router.json")
    (repo / "src").mkdir()
    (repo / "src" / "kept.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "src" / "untouched.py").write_text("OTHER = 1\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "scripts", "configs", "src")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def test_paths_for_diff_includes_uncommitted_and_untracked_files(tmp_path: Path) -> None:
    # Red when: paths_for_diff() reads only committed changes and misses a modified-but-not-
    # committed tracked file or a new untracked file, or leaves the modified line out of the
    # diff text.
    router = _router()
    repo = _clean_repo(tmp_path)

    clean_paths, _clean_text = router.paths_for_diff("HEAD", repo=repo)
    assert clean_paths == [], clean_paths

    (repo / "src" / "kept.py").write_text("VALUE = 2\n", encoding="utf-8")
    (repo / "src" / "brand_new.py").write_text("NEW = 1\n", encoding="utf-8")
    paths, text = router.paths_for_diff("HEAD", repo=repo)
    assert "src/kept.py" in paths, paths
    assert "src/brand_new.py" in paths, paths
    assert "src/untouched.py" not in paths, paths
    assert "+VALUE = 2" in text, text


def test_cli_diff_with_no_changed_paths_exits_1(tmp_path: Path) -> None:
    # Red when: `skill_router.py --diff HEAD` on a repo with no changes exits 0 (an empty
    # checklist that reads as "nothing needed").
    repo = _clean_repo(tmp_path)
    script = repo / "scripts" / "skill_router.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--diff", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, (proc.returncode, proc.stdout[-500:], proc.stderr[-500:])
    assert proc.stderr.strip(), "no message on stderr"

    # Positive partner: the same repo with one untracked money file exits 0.
    (repo / "src" / "costs.py").write_text("DAILY_CAP_USD = 1\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(script), "--diff", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (proc.returncode, proc.stdout[-500:], proc.stderr[-500:])


# --------------------------------------------------------------------------
# R5: the old route is unchanged.
# --------------------------------------------------------------------------


def test_no_arguments_still_prints_the_old_route() -> None:
    # Red when: running the script with no arguments stops printing format_route(route())
    # (the phase and driver lines that docs/00 and the mechanical handoff are built from).
    proc = subprocess.run(
        [sys.executable, str(_ROUTER_PATH)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (proc.returncode, proc.stderr[-500:])
    assert "Phase: Operate, learn, and improve" in proc.stdout, proc.stdout[:500]
    assert "Driver skill: production-feedback-loop" in proc.stdout, proc.stdout[:500]
