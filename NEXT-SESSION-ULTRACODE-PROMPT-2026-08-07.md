# Next session — ultracode, autonomous

Paste this whole file as your first message. Then work autonomously.

---

## 0. The one rule that governs this document

**Treat every sentence below as UNVERIFIED until you have executed it.**

This is not politeness. AGENTS.md rule 11 records the measured decay rate of
claims inherited from handoff documents in this repository: **2 of 3** headline
findings refuted outright, **8 of 18** "would be lost outright" candidates
already done or largely wrong. *Roughly half of what a handoff asserts does not
survive contact with the tree.*

So: every factual claim here ships with **the command that proves it**. Run the
command. If it disagrees with the sentence, **the sentence is wrong** — say so
out loud, fix it, and carry on. Do not repair a false premise silently
(rule 3).

This document was written by the session that produced it, and that session got
things wrong **five times in one night** even while applying these rules. Those
five are listed in §6 precisely because your own list will look the same.

---

## 1. Read these first, in this order

1. `AGENTS.md` — the operating rules. Non-negotiable, and they bite.
2. `docs/00-factory-console.md` — current phase and next action.
3. `docs/session-handoff.md` — whatever the last `make handoff` recorded.

Then run:

```bash
make next
make skill-route
```

Prefer **installed skills** (`.agents/skills/*`) over inventing an approach.

---

## 2. Ground truth — re-derive it, do not trust it

Everything in this table was true at 2026-08-07T09:00Z. **Run the command in
the right-hand column before relying on any of it.**

| Claim | Command that settles it |
|---|---|
| `main` tip is `79ad02a` | `git rev-parse --short main` |
| local == origin | `git rev-parse main origin/main` |
| production runs `main`'s tip | `curl -s https://quorum-ai.fly.dev/status \| python3 -c 'import json,sys;print(json.load(sys.stdin)["build_sha"])'` |
| **1** branch, **1** worktree, **0** open PRs | `git branch; git worktree list; gh pr list --state open` |
| **15** open issues | `gh issue list --state open --limit 60 --json number --jq 'length'` |
| judge `max_tokens` is **1024** | `grep -n quorum_eval_judge_max_tokens src/product_app/config.py` |

The repository is in a **clean state**: no stale branches, no orphan worktrees,
no uncommitted work, no open pull requests. That is deliberate — it is the
right state to start from, and you should leave it that way.

**Free production probes** (never cost money): `/ready`, `/status`, `/metrics`,
`/ui/ops`, `/estimate`. A full run is **not** free — ask first.

---

## 3. What the previous session shipped

**Ten** pull requests, all merged and verified in production.

*(This sentence has now been wrong twice in one session. It said "Six" until the
author ran `grep -cE '^\| #2[0-9]+ \|'` against the table below and got `8`; it
then said "Eight" until two more rows were added and the same command returned
`10`. A count written from memory beside a list you can count is the rule-1a
trap, and it re-broke within the hour, under someone actively applying rule 1a.
**Do not trust this number. Run the grep.** The table is the record; the prose is
what rots.)*

| PR | What |
|---|---|
| #269 | price the Layer-B judge into the cap the user approves |
| #270 | distinguish a judge that produced nothing from one that never ran |
| #271 | stop paying a judge to grade answers no model wrote |
| #272 | a "verified" badge must not contradict the verdict behind it |
| #273 | ask the judge for output it can actually produce |
| #274 | **stop a real credential from ever reaching a test run** |
| #275 | measure what the judge actually does, and correct ADR-0021 |
| #276 | name the token `QUORUM_TOKEN_SECRET` actually protects, and pin it |
| #277 | **stop sending the user's query text to Sentry** |
| #278 | stop the mutation gate flagging mutmut's own generated file |

New ADRs: **0018–0023**. Read **ADR-0022** before touching `tests/conftest.py`
or anything that reads a credential, and **ADR-0023** before touching Sentry —
each records the incident, the rejected alternatives, and measured **known
limits** that are still open.

**#278 is the tail of #276, and the pattern is worth internalising.** #276's new
test was correct at the repo root and wrong inside `./mutants/`, where mutmut's
copy *is* the root — so a directory-based exclusion had nothing to match on. The
gate then went red having measured nothing. **A check that is correct in one
root can be wrong in another;** anything asserting over the whole tree has to be
thought about twice, once for each root it runs under.

**The judge is going PERMANENTLY ON in production.** Treat every judge defect as
a live money/UX defect, never a latent one.

---

## 4. Pending work — ranked, with the honest reason

There are **no undone loose ends from the previous session.** Everything it
found was either built, filed, or deleted with evidence. What follows is the
real backlog.

### 4.1 The one thing a human must do

**Delete the historical Sentry events. The code leak is fixed; the stored data
is not.** #277 stopped future sends, but everything already in the project stays
until someone deletes it there. Two separate things to look at:

- **`environment: local`, 6–7 Aug 2026** — a few hundred error events from
  `product_app.costs` and `product_app.feedback_store`, generated by test runs
  when a real `SENTRY_DSN` in `.env` activated a live client. Test noise. Delete
  or ignore; it inflates error counts and burns quota.
- **`environment: production`** — open a Performance/transaction event and check
  whether **real user queries are visible**. Before #277, `before_send` was never
  called for transactions, so `request.data` shipped raw at
  `traces_sample_rate=0.1`. If they are there, that is stored user data and
  should be deleted.

The leaked `QUORUM_EVAL_JUDGE_API_KEY` was **deleted at the provider by the
owner**, so it is dead — no rotation is outstanding.

### 4.2 Strongest candidates from the 15 open issues

Re-run selection yourself (rule 20 — a PR opens with one line saying why the
item outranks the top of the backlog). These three are the previous session's
read, offered as a starting point and **not** as a shortlist to recycle —
AGENTS.md records handoff chains narrowing the backlog to ~5 items while it grew
to ~55.

- **#245 — deploy signal is unreliable.** *Has fresh, perishable evidence
  attached.* On 2026-08-07 a merge to `main` produced **zero** workflow runs, so
  nothing triggered the deploy and production sat on a stale build for 23
  minutes **while every health probe stayed green**. The next merge, 21 minutes
  later, fired 4 runs. Evidence and reproduction are in a comment on the issue.
  The argued fix is a **positive** check — assert `main`'s tip equals
  production's `build_sha` and go red otherwise — rather than more care around
  the existing triggers. There is a `Deploy drift watchdog` workflow; whether it
  can already see this case is **UNVERIFIED** and is the first thing to check.

- **#216 — a judge re-dispatched after memo eviction bills with no ledger
  correction.** Money, and the judge is going always-on. Split from #110 and
  deliberately deferred.

- **#105 — 5xx classified as possibly-billed on a premise with no evidence.**
  Closeable with data. AGENTS.md rule 8c already banks free facts about the live
  OpenRouter API (errors are `Transfer-Encoding: chunked`, no `Content-Length`,
  ~50 bytes, `Server: cloudflare`; a bad key returns
  `401 {"error":{"message":"User not found.","code":401}}` with no
  `error.metadata`). A `401` costs nothing — **go and look** before gating on
  any upstream behaviour.

### 4.3 A stale detail to correct when you touch it

**#268's body says "the judge's 512-token cap".** The cap is now **1024**
(`config.py:144`, raised by #273). The issue's *mechanism* claim still holds —
`costs.py:1640` prices it from the setting, not a literal, so it tracks
automatically. Only the number in the prose is stale. Verify with
`grep -n quorum_eval_judge_max_tokens src/product_app/config.py` before
repeating either figure.

---

## 5. How to work

- **Ask before**: any paid API call, any deploy, any push, any PR, any merge.
  Commit locally as freely as you like.
- **One concern per PR** (rule 17). Branch in a **dedicated `git worktree`**,
  never the main checkout. Merge `main` in **before** starting.
- **Fan out for review, never for building** (rule 9). Subagents share one
  working tree. Tell every reviewer **IN CAPITALS** not to write, edit,
  `git checkout`, `git stash` or `sed -i` anything. **Two lenses, not five**
  (rule 10). Cap review at **two rounds** (rule 12), and budget one for the
  defect your own fix introduces.
- **Tell reviewers to audit the diff's PROSE, not only its code** (rule 11a),
  verbatim: *"for every number, superlative, and causal claim in the diff's
  comments, commit body and PR description, name the command that produces it —
  or mark it UNVERIFIED."*
- **An ADR in the same PR as the decision** (rule 16d). Regenerate the index
  with `python3 scripts/generate_adr_index.py`; never hand-edit it.
- **Build in-session findings in-session.** Do not hand the next session a list
  of things you noticed and skipped. That is what this section of the previous
  handoff got wrong, and the owner called it out.
- **Close more than you open** (rule 19).

### The six merge gates

`make quality` and `make validate` do **not** cover them. Re-derive the list —
do not trust any table, including this one:

```bash
gh api repos/:owner/:repo/branches/main/protection \
  --jq '.required_status_checks.contexts[]'
```

```bash
uv sync --all-extras          # NOT --extra dev
make quality && make validate
make diff-cover DIFF_BASE=origin/main   # commit FIRST; run serially after quality
make api-contract
make openapi-check
make security-scan
```

`docker-build` is covered by **nothing local**. Run e2e per rule 13 if you
touched UI, specs or fixtures.

### Close-out, in this order, every time (rule 18a)

1. Local gates green **and** every review finding resolved
2. Merge with an **explicit** squash message (rule 17c — a bare `--squash`
   concatenates every intermediate commit body onto `main`)
3. **Verify the deploy**: the deploy **job** ran (not `skipped`/`cancelled` —
   read the job, not the run's rollup), `/status.build_sha` equals the merged
   SHA, and the thing you built actually fires. A merge produces two runs; one
   is `cancelled` by concurrency dedupe. **Resolve the newest by `createdAt`.**
4. `git merge --ff-only origin/main`, delete the branch local **and** remote,
   remove the worktree

---

## 6. Traps measured on 2026-08-06/07 — these cost real time

Each of these is a mistake the previous session actually made. They are here so
you do not repeat them.

- **`git checkout <file>` destroyed a fix mid-review.** Rule 6 forbids it. To
  revert a mutation, `cp` the file aside and restore **from the copy**, then
  `diff -q` to prove the restore was byte-exact.

- **zsh does NOT word-split unquoted variables.** `pytest $SPECS` collected
  **zero** tests and printed nothing that looked wrong. `set -- $pair` inside a
  loop silently produced one argument. Use `${=var}` in zsh, or arrays, or
  explicit function parameters — and always assert a non-zero count.

- **A git worktree does NOT share untracked files.** A `make quality` run in a
  fresh worktree had **no `.env`**, so it never exercised the credential path it
  was written to test, and looked green. If your test depends on `.env`, copy it
  in deliberately and **remove it before committing**.

- **Ruff's E402 allowance in `tests/conftest.py` covers `os.environ` mutation
  only.** A plain module-level assignment (`_KEEP = ...`) before the imports
  produced **8 errors**; an `if` block does the same. Use conditional
  *expressions* on `os.environ[...] = ...`.

- **`gh run list --commit <SHA>` can return `[]`.** Query the API directly:
  `gh api "repos/:owner/:repo/actions/runs?head_sha=<SHA>"`.

- **A merge can produce no workflow run at all** — see #245 above. Never infer
  "deployed" from a healthy `/health` or `/ready`; they answer from the *stale*
  build just as cheerfully.

- **`e2e/tests/review/` makes `make quality` RED locally and green in CI.** That
  directory is gitignored. Before blaming your diff, run `ls e2e/tests/review/`.

- **A credential must never appear on an `assert` line.** pytest's rewriting
  prints **intermediate** values, so `not`, `len()` and `bool()` all leak.
  Measured on a 40-char canary. Reduce to a non-secret **in its own statement**,
  then assert on that. `tests/unit/test_no_credential_reaches_a_test_run.py`
  enforces this repo-wide.

- **A grep of a path that does not exist returns nothing, and looks like proof
  of absence.** `git grep -- src/product_app/auth/` returned nothing because
  `auth` is a **module**, not a directory. A **positive partner** (rule 7)
  caught it. Every absence check needs one — that is the whole argument.

---

## 7. Your first four commands

```bash
cd /Users/rohitagrawal/Projects/quorum-ai
git fetch origin && git status && git log --oneline -8
gh issue list --state open --limit 60
curl -s https://quorum-ai.fly.dev/status | python3 -m json.tool | head -20
```

Then re-derive §2, pick a work package, and **state in one line why it outranks
the top of the backlog**. If you cannot write that line honestly, the ranking is
wrong — re-rank before writing any code.
