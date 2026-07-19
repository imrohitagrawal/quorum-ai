# Enforcement hooks — the local layer, and why CI is still the authority

**Scope:** Phase-0 item **P0-H** (plan Part B0 layer 3). This is the companion to
`03-enforcement-machinery.md` (the CI/e2e gates) and it deliberately covers the
*weakest* of the enforcement layers.

**Read this first, and do not let it be softened:**

> **`.claude/` is gitignored** (`.gitignore:21`, verified: `git check-ignore -v
> .claude/settings.json` → `.gitignore:21:.claude/`). Every hook described here
> lives in `.claude/settings.json`, so it exists **only on this machine, in this
> checkout**. A fresh clone has none of them. A teammate has none of them. A
> parallel agent in a different worktree has none of them. **CI has none of
> them.** A local hook is fast personal feedback; it is **not** durable
> enforcement, and it must never be cited as the reason a practice is safe.

Per the durability hierarchy in `docs/DAY-ONE-PROMPT.md` §1, a hook is
**below-the-line only if the settings file that defines it is tracked in git**.
Ours is not. So on the ladder these hooks sit **above the line** — stronger than
prose, because the harness runs them without anyone remembering to, but still
scoped to one machine.

```
chat instruction                             ← evaporates
skill / memory / AGENTS.md                   ← influence only
.claude/settings.json hook  (THIS DOC)       ← runs automatically, ONE MACHINE ONLY
──────────────────────────────────────────── the influence/enforcement line
CI job in .github/workflows/ (tracked)       ← the real, shared enforcement
evidence-artifact CI gate                    ← binds the process, not just the code
```

---

## 1. What was installed, and what was actually proven

Four hooks, merged **additively** into `.claude/settings.json` (the pre-existing
10-entry `permissions.allow` array was preserved — verified
`jq '.permissions.allow|length'` → `10`, unchanged).

| # | Hook | Event / matcher | Default state | Proof status |
|---|------|-----------------|---------------|--------------|
| H1 | **block-no-verify** — deny any *git* command carrying a gate-skipping flag | `PreToolUse` / `Bash` | **ARMED** | **RED+GREEN PROVEN, and observed firing in-harness** |
| H2 | **pre-commit gate** — `make validate` + full `pytest` must pass before a commit | `PreToolUse` / `Bash` | **DISARMED** (`QUORUM_PRECOMMIT_HOOK=1` to arm) | **RED+GREEN PROVEN** (incl. on a real, unplanned defect) |
| H3 | **test-evidence recorder** — stamp `.claude/state/last-test-run` when a test command succeeds | `PostToolUse` / `Bash` | **ARMED** | **PROVEN** (fires on pytest, not on `git commit`) |
| H4 | **claim gate** — block a turn-ending "all tests pass / all green" claim with no fresh test run | `Stop` | **DISARMED** (`QUORUM_STOP_HOOK=1` to arm) | **RED+GREEN PROVEN at the command level; wiring NOT demonstrated** |

### Why two of them ship DISARMED

Not timidity — **measurement**. H2 runs the real suite (**37s** measured, below)
and H4 blocks a turn from ending. This tree is currently being edited by several
parallel agents and an orchestrator that commits. An always-on H2 would have
denied the orchestrator's commits the moment any peer's work-in-progress was red
— which, as it turns out, is *exactly* what happened during testing (§2.2). So
the mechanism ships **off**, proven, with a one-variable activation queued to the
operator. This follows the `guardrail-values-need-measurement` rule: ship the
mechanism off, prove it by injection, hand activation to the human.

Arm them with:

```bash
export QUORUM_PRECOMMIT_HOOK=1   # H2: make validate + pytest before every commit
export QUORUM_STOP_HOOK=1        # H4: no unbacked "tests pass" claim
```

---

## 2. Proof (captured, not asserted)

### 2.1 H1 — block-no-verify: an 8-case RED/GREEN table

Commands read **out of the installed `.claude/settings.json`** (not from a draft
script), fed the real `PreToolUse` stdin payload shape:

```
PASS   expected=RED   actual=DENY   git commit --no-verify -m wip
PASS   expected=RED   actual=DENY   git push --no-verify
PASS   expected=RED   actual=DENY   git -c core.hooksPath=/dev/null commit -m wip
PASS   expected=RED   actual=DENY   SKIP=lint git commit -m wip
PASS   expected=GREEN actual=ALLOW  git commit -m 'real work'
PASS   expected=GREEN actual=ALLOW  grep -rn -- '--no-verify' docs/
PASS   expected=GREEN actual=ALLOW  uv run pytest -q --no-cov
PASS   expected=GREEN actual=ALLOW  echo core.hooksPath=/dev/null
```

**H1 is the only hook here observed firing inside the live harness, not just
pipe-tested.** While testing it, it denied *my own* `Bash` tool call — twice —
because my test command literally contained `git commit --no-verify`:

```
block-no-verify: this command skips a quality gate. Gates are not optional -
fix the failure instead of bypassing it (docs/analysis/09-enforcement-hooks.md).
```

That is genuine end-to-end evidence the harness loads and enforces the hook. It
also cost real work: the denied call was the one meant to update `settings.json`,
so the update silently didn't happen and a later check read a stale command. Both
are recorded because they are the kind of thing a "looks fine" review misses.

**The first version of H1 was wrong, and the accident found it.** It matched the
flag substring anywhere in the command, so `grep -rn -- '--no-verify' docs/` was
denied — precisely the failure mode AGENTS.md warns about ("never gate a check on
whole-line substrings; key off the matched token"). H1 now additionally requires a
real `git` token in command position. The two GREEN substring cases in the table
above are the regression evidence for that fix.

### 2.2 H2 — pre-commit gate: RED on a mutant *and* on a real defect

| Scenario | Result |
|---|---|
| Disarmed + `git commit -m x` | **ALLOW** (correct — off by default) |
| Armed + non-commit command (`ls -la`) | **ALLOW** (correct — matcher scoped to commits) |
| Armed + commit, `make` mutated to exit 2 | **DENY (RED)** |
| Armed + commit, real repo, clean tree | **ALLOW (GREEN), 17.5s** |
| Armed + commit, real repo, peer's work-in-progress | **DENY (RED — real defect)** |

Mutant RED (a stub `make` on `PATH` returning exit 2):

```json
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny",
"permissionDecisionReason":"pre-commit gate FAILED - `make validate` + pytest must be green before committing. Tail:\ntraceability FAIL"}}
```

GREEN, measured against the real repo earlier in the session (501-test suite,
`make validate` exit 0): **ALLOW, 17.5s wall**, and the hook wrote its evidence
marker.

**Unplanned real-defect RED.** Re-running the same gate later in the session, it
denied the commit on a genuine, live regression a peer agent had just introduced
— no mutant involved:

```
5 failed, 534 passed, 1 skipped, 15 warnings in 37.09s
FAILED tests/contract/test_api_contract_schemathesis.py::test_api_conforms_to_openapi_contract[POST /v1/query-runs/estimate]
FAILED tests/contract/test_api_contract_schemathesis.py::test_api_conforms_to_openapi_contract[POST /v1/query-runs/warnings]
FAILED tests/contract/test_api_contract_schemathesis.py::test_api_conforms_to_openapi_contract[GET /v1/query-runs/{query_run_id}]
FAILED tests/contract/test_api_contract_schemathesis.py::test_api_conforms_to_openapi_contract[DELETE /v1/query-runs/{query_run_id}]
FAILED tests/contract/test_api_contract_schemathesis.py::test_every_spec_operation_is_covered_or_explicitly_excluded
```

This is the strongest evidence available for H2: it blocked a commit over a defect
nobody planted. **It is also a live finding for whoever owns P0-F** — those five
failures are real and were red at the time of writing.

### 2.3 H3 — test-evidence recorder

| Command seen | `.claude/state/last-test-run` |
|---|---|
| `ls -la` | ABSENT (correct) |
| `git commit -m x` | ABSENT (correct) |
| `uv run pytest tests/ -q --no-cov` | **PRESENT** (correct) |

H3 is on `PostToolUse`, which fires only after a **successful** tool call, so a
failing pytest lands on `PostToolUseFailure` and leaves no marker. That is the
intended semantics — the marker means "a test command *passed* recently" — but it
is a property of the harness, not something this hook asserts itself.

### 2.4 H4 — the claim gate

Transcripts synthesised in the **real** `.jsonl` shape (confirmed by inspecting
this session's own transcript: lines carrying `"role":"assistant"` with
`.message.content[].text`).

| Armed? | Transcript claim | Evidence marker | Result |
|---|---|---|---|
| no | "all tests pass" | none | **ALLOW** (correct — off by default) |
| yes | "all tests pass" | none | **BLOCK (RED)** |
| yes | "all tests pass" | fresh (now) | **ALLOW (GREEN)** |
| yes | "all tests pass" | stale (20 min) | **BLOCK (RED)** |
| yes | "I summarised the file." | stale | **ALLOW (GREEN — no false block)** |

The block payload:

```json
{"decision":"block","reason":"Stop-hook claim gate: you asserted tests pass / all green, but no test run was recorded within the last 15 minutes (last recorded run: never in this checkout). Run the suite and quote its real output, or retract the claim. Evidence is the artifact, not the assertion."}
```

**What is NOT proven for H4:** that the harness invokes it. A `Stop` hook fires
when a turn ends, which is outside any turn I can observe, and the settings
watcher only picks up `.claude/` changes reliably from session start. So H4's
*decision logic* is proven RED and GREEN; its *wiring* is **UNVERIFIED**. Per the
brief's own rule — an undemonstrated hook is a proposal, not a gate — **H4 is a
PROPOSAL.** To confirm, the operator should open `/hooks` (or restart Claude
Code), then end a turn with an unbacked "all tests pass".

---

## 3. Honest limits — how each hook can be evaded

Recorded because a gate whose evasion surface is undocumented invites false
confidence.

- **H1 only inspects the literal command string.** Verified during testing:
  building the flag at runtime (`F='--no'; F="$F-verify"; git commit $F`) is not
  matched. It stops the careless path, not a determined one.
- **H1 has no reach outside the Bash tool.** A commit made in another terminal,
  by another agent, or by the orchestrator's own tooling never passes through it.
- **H2 is scoped to commands containing a `git … commit` token.** A commit issued
  by a script, or by any path that is not a `Bash` tool call, is invisible to it.
- **H3/H4 are coupled through a marker file whose contents nothing verifies.**
  `echo $(date +%s) > .claude/state/last-test-run` satisfies H4 outright. This is
  the same "artifact present ≠ artifact valid" hole the ledger records as **EN-2**
  for the evidence-artifact CI gate. It is not fixed here.
- **H4 matches a fixed phrase list** (`all green`, `all tests pass`, `everything
  passes`, …). Any paraphrase outside that list passes unblocked.
- **All four vanish on `git clone`.** This is the point of the doc.

---

## 4. Cross-check: which Phase-0 gates are durably enforced?

"Durable" = defined in a **tracked** file that runs for everyone. Rows verified
by reading `.github/workflows/ci.yml`, `Makefile`, and `pyproject.toml`.

| Phase-0 gate | CI job (tracked) | Blocking? | Durable? |
|---|---|---|---|
| P0-B FR→registry+matrix traceability | `fr-completeness` | yes | **YES** |
| P0-E hermetic perf p50/p95 + concurrency | `perf-gate` | yes | **YES** |
| P0-F Schemathesis API contract | `api-contract` | yes | **YES** |
| P0-G changed-lines coverage ≥95% | `diff-cover` | yes, **PR events only** | **PARTIAL** — no changed-lines gate on a direct push to `main` |
| P0-D mutation score | `mutation-baseline` | **no** (`continue-on-error: true`) | **ADVISORY ONLY** — reports, never fails |
| Global coverage floor 88% | inside `validate-and-test` (`--cov-fail-under=88`) | yes | **YES** |
| UI rendering invariants / visual / degraded banner | `.github/workflows/e2e.yml` | yes (per AGENTS.md) | **YES** |
| **P0-H pre-commit gate (H2)** | *none* — but `validate-and-test` runs the same `make validate` + pytest | yes | **YES via CI**; the hook only makes it faster |
| **P0-H block-no-verify (H1)** | *none possible* | — | **NO** — see §5 |
| **P0-H "no unbacked claim" (H4)** | *none* | — | **NO** — no CI job can inspect an agent's assertions |
| P0-I skill audit / router refresh | *none* | — | **NO** |
| P0-J documentation fixes | *none* | — | **NO** |

**Two Phase-0 behaviours have no durable home at all: the block-no-verify pattern
and the unbacked-claim gate.** Both constrain *how an agent behaves*, not what
the code is, and CI can only ever see the artifact. They remain local-only, and
the plan should say so rather than counting them as enforced.

---

## 5. The finding that outranks everything above

`gh api repos/:owner/:repo/branches/main/protection` →

```
{"message":"Branch not protected", "status":"404"}
```

**`main` has no branch protection.** Every "blocking" CI job in the table above
*runs*, but nothing requires it to *pass* before a merge. So the layer this
document calls authoritative is, right now, advisory in practice — a red required
check can simply be merged past.

That makes H1 (block-no-verify) locally useful but strategically beside the
point: there is nothing to bypass yet. **The single highest-leverage action from
this whole P0-H item is not a hook — it is enabling branch protection on `main`
with the blocking jobs as required status checks.** That is an operator action
(it needs repo-admin rights); it is not something a hook or a doc can do.

---

## 6. Recommended next steps, in priority order

1. **Operator: enable branch protection on `main`**, requiring `validate-and-test`,
   `fr-completeness`, `perf-gate`, `api-contract`, `diff-cover`, and the e2e
   invariants. Without this, §4 overstates the whole enforcement story.
2. **Fix the 5 red `test_api_contract_schemathesis.py` failures** surfaced in §2.2.
3. **Decide on tracking the hooks.** To move H1–H4 below the line, un-ignore a
   tracked `.claude/settings.json` (keeping `.claude/settings.local.json`
   ignored for personal overrides). This is a deliberate repo-policy change and
   is **not** taken unilaterally here.
4. **Arm and confirm H4** via `/hooks` or a restart, then record whether it fired.
   Until then it stays labelled a proposal.
5. **Close the H3/H4 marker hole (EN-2 class)** by having H4 require a marker
   written by the hook itself with a token the agent cannot forge, or drop the
   claim that H4 verifies anything stronger than "a test command ran".
