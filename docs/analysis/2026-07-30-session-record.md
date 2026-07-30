# 2026-07-30 — complete session record

Everything one working session produced, where each item now lives, and what it
cost to learn. Written because the session generated roughly a dozen measured
findings, three research sweeps and two operator decisions that existed **only in a
chat window** — and a chat window is the least durable place there is.

**Read the honesty section (§7) before the accomplishments.** Three of this
session's most useful outputs are records of its own mistakes, and they are the
part most likely to be quietly dropped in a later summary.

---

## 1. What shipped

| Item | Where | Verified how |
|---|---|---|
| WP-H — short-panel disclosure fix | `81f6e9c`, merged + deployed | deploy job `success` (not skipped/cancelled), `/status.build_sha` == merged SHA, served `app.js` contains the new function; dead render gone (0 refs) |
| #118 closed | GitHub | the dead `.model-card-notice` render removed |
| #171 opened | GitHub | the largest defect found this session |
| #115 corrected and re-scoped | GitHub comment | its central premise was refuted |
| Evidence ledger, handoff template, triage | PR #173 | `make validate` green |
| Five issue comments carrying chat-only findings | #100 #106 #110 #122 #151 | posted |

**Net on the backlog: closed 1, opened 1.** Even, not better. Three further issues
(#129, #162, #63) were *verified* closeable but left open pending the operator.

---

## 2. The defect that justified the session

`renderResultDegraded` switched the "this result is degraded" banner on with
`localCount > 0` — *"were any answers simulated?"*. That is blind to the other way
a panel comes up short: **a slot that produced no answer at all**, which is counted
in neither `live_count` nor `local_count` (verified server-side,
`query_runs.py:2484-2489`).

Measured in a real browser on a run with 3 live answers and 1 missing:

| element | state |
|---|---|
| `#result-degraded` — the visible one | **hidden, 0×0** |
| `#demo-mode-banner` — the invisible one | 0×0, holding the only honest sentence |

The user was shown a verdict and synthesis built from three quarters of the panel
with **no disclosure anywhere**, under a headline reading *"3 of 4 models
aligned"* — which describes a disagreement, not a missing answer.

**This refuted the premise the work package rested on.** The handoff and #115 both
asserted the trapped banner "may simply be redundant". It was not: in that case it
was the only surface telling the truth. Had the plan been followed as written, the
fix would have **deleted the only honest disclosure**.

Also measured: two whole sections are hidden (`Debate and synthesis` →
`#synthesis-output`/`#debate-output`, 2,747 chars; `Model outputs` →
`#demo-mode-banner`/`#model-grid`, 10,857 chars) — **13,604 characters built on
every run and shown to nobody.**

---

## 3. The largest finding — #171

Tracing why the banner mattered exposed something bigger: **when one model's live
call fails, the product fabricates an answer for that slot, marks it `completed`,
and feeds it to the debate, the synthesis, the agreement count and the
source-coverage figure as if it were real.**

Four numbers the product leads with are wrong on any run where a provider failed.
The sharpest: a simulated answer is given a source with `is_fallback=False`
(`providers.py:1156-1163`) — which is exactly what makes a source count as
*primary* — so **a run with one real answer and three simulated ones reports 100%
source coverage, three quarters of it fabricated.**

Full evidence, the five-point rule, and the three-rung enforcement ladder are on
the issue. What belongs here is the shape: **four defects (#111, #115, #118, #128)
filed across four sessions turned out to be one habit expressed four times** —
*degrading by inventing plausible filler rather than admitting a gap.* We were
fixing surfaces one at a time and never naming the cause.

---

## 4. What the research killed

Three sweeps, each instructed to give a primary source per number and to report
`NOT-FOUND` rather than produce something plausible. Full record with grades and
re-check triggers: `docs/evidence/2026-07-30-engineering-practice.md`.

**One sweep's PDF path fabricated numbers on its first attempt** — invented a
sample size and a statistic for a real paper. It caught this by cross-checking.
A research agent can produce citation-shaped fiction; that is why every claim
carries its source.

Practices this repository was about to adopt, and did not:

- **"Fan out 3–5 review lenses"** → the only randomized experiment in the field
  found **two ≈ four, and one is worse** (Porter et al., *IEEE TSE* 1997).
- **"Review 200–400 lines"** → vendor-published by the company selling the review
  tool; **61% of those reviews found zero defects**.
- **"Review is how you find bugs"** → **14%** of review comments are
  defect-related (Bacchelli & Bird, ICSE 2013); the effect on post-release defects
  partly fails to replicate.

Three findings worth carrying anywhere:

- **Placement beats precision** — identical analyser, identical false-positive
  rate, **0% → 70%** fix rate purely by moving to diff time (Infer, *CACM* 2019).
- **Tier the false-positive bar by enforcement strength** — blocking needs ~zero,
  advisory-at-review tolerates <10%, with written probation triggers (Tricorder).
- **Never gate on a mutation score** — Google does not, because they could not make
  it actionable; coverage *"should not be used as a quality target"*.

And the best-evidenced thing found all session, from outside software: **I-PASS**
(*NEJM* 2014, 9 sites, 10,740 admissions) cut medical errors 23% and preventable
adverse events 30% at **no time cost**, with a negative control that held. Its
*Synthesis by receiver* element — the receiver confirms understanding before the
handoff is complete — **has no equivalent in any software handoff practice found.**

---

## 5. The review budget, derived rather than chosen

| Input | Value | Source |
|---|---|---|
| One review lens on a real diff here | **96k–122k tokens** | measured this session (two reviewers) |
| Pricing | $5/M input, $25/M output | verified table |
| Per lens | **≈ $0.90** | ~85/15 read/write split — **inferred, not measured** |
| Two lenses + verification | **≈ $2.75 per pull request** | ~$83 across 30 PRs. *Corrected 2026-07-30: this read ≈$3 / ~$90; the arithmetic did not follow from the inputs. See ADR-0003.* |

Revised down from $5 by Porter's two-reviewer finding. Settle the split with one
`count_tokens` run before treating ~$2.75 as measured rather than estimated.

---

## 6. Documentation redundancy — measured, not asserted

Claimed the four documentation homes did not overlap. Checked. They do:

| Number | Its one computed source | Files containing it, at HEAD |
|---|---|---|
| "0 of 16 caught by a gate" | `docs/metrics/defect-discovery-audit.md` | **8** |
| "13 of 21 could measure nothing" | `docs/analysis/03-enforcement-machinery.md` | **6** |
| "10 of 16 found by review" | same audit | **6** |

```bash
for p in "0 of 16" "13 of 21" "10 of 16"; do git grep -l "$p" -- . | wc -l; done
```

**These figures were 5 / 5 / 3 until 2026-07-30, and the triple reproduced at no
tree state** — a section headed *"measured, not asserted"* carried numbers nobody
could re-derive. (Strictly: the third element alone does reproduce — the merge base
gives 4 / 4 / 3. The set never did.) The counts above are from the command shown, at HEAD, and include the
source file itself. They will drift as documents are added, which is the finding:
**this is a count of a growing problem, not a fixed fact.** Re-run it rather than
quoting it.

**The redundancy is not between the four homes — their roles are distinct. It is
that `DAY-ONE-PROMPT.md` has absorbed content from all of them** — it restates
their numbers instead of citing them.

*Corrected 2026-07-30: this said DAY-ONE was "at 54,891 characters … larger than
`quality-ledger.md`, `adr/`, `study/` and `evidence/` combined". **That was false
when written and is more false now** — measured at HEAD, DAY-ONE is 56,200 bytes
against 64,910 for the four combined. It is comparable in size to all four homes
put together, which is the real point and did not need the exaggeration. The
size also moves every time anyone edits the file, so quoting it is a trap:
`wc -c docs/DAY-ONE-PROMPT.md` and the four paths is the honest form.*

One distinction worth keeping: `AGENTS.md` restating a number inline is
**legitimate** — it is always loaded into context, so a link would never be
followed. **Restatement for *influence* is not the same as restatement for
*reference*.** Only the second is pure duplication.

### The conversion this implies, not yet built

DAY-ONE answers *"should this be a gate?"* (§3, a target map) and — in a different
file — *"is it built?"*. **Nothing anywhere answers "in what order, and is it worth
building?"** A rulebook where every rule is equally weighted gets read once.

The ledger merges those two tables and adds four columns none of them has:

| Rule | Mechanism | Status | Evidence grade | Yield here | Priority |
|---|---|---|---|---|---|
| No fabricated value in a trust number | type signature + fault-injected assertion | **not built** | `LOCAL` (#171) | — | **1** |
| Tests must bite | mutation runner, diff-scoped, **never a score gate** | **broken** (#158) | `WELL-EVIDENCED` | 0/16 | 2 |
| Adversarial review happens | review job + artifact gate, **2 lenses** | **not built** | Porter + `LOCAL` 10/16 | 10/16 | 3 |
| Gates state their denominator | per-gate floors | partial, 6 left | `NOT-FOUND` — our coinage | n/a | 4 |
| Coverage floor | `--cov-fail-under` | built | `WELL-EVIDENCED` **against** as a target | 0/16 | ratchet only |
| Selection before work | one line in the PR template | **not built** | `LOCAL` | — | 5 |
| Degrade by admitting the gap | — | **prose only** | `LOCAL` | — | folds into 1 |
| Receiver confirms handoff | — | **never enforceable** | I-PASS | — | accept as influence |

Priority is **computed** — criticality × exposure × yield, effort as tiebreak — not
chosen. The ledger's real work is making two rows visibly `prose only` and one
`never enforceable`. Written as rows that is honest; written as three paragraphs of
persuasion it reads as done.

**Target: DAY-ONE under 30k, from 54.9k.** The next change to it should make it
smaller.

---

## 7. What this session got wrong

The most reusable part. All four are the same failure — **acting on a belief
without running the check that would settle it** — and all four were caught by
execution, not by review or by care.

**7.1 Built the lower-value item, knowing it was lower-value.** Ranked #171 above
WP-H in writing, then spent the session on WP-H because it was already half-built.
Sunk-cost reasoning dressed as sequencing. **The work was never at risk** — it was
on a branch, and branches wait. The cost was not two hours; it was the whole
session, and roughly half the copy written will be superseded by #171.
*Mechanism:* discovering a higher-ranked item is a **mandatory stop**, and a pull
request opens with one line on why this item outranks the top of the list.

**7.2 Reproduced the exact defect being filed, twice, within the hour.** After
writing "never substitute invented content" into the repository, the same diff
shipped an export that said *"Partly simulated result"* for a run where nothing was
simulated, and a branch claiming the whole result was simulated when half of it was
missing. **Writing the rule did not bind its own author.** Caught by an adversarial
reviewer, not by the rule. This is the strongest available argument for mechanism
over guidance.

**7.3 Answered a prose problem with more prose.** Argued DAY-ONE is too long
because it is append-only, proposed replacing a section with a ledger — then added
**two new prose sections** in the pull request making that argument.
*(This said "~150 lines", then "101 lines". Both were wrong by the time they were
read: a count of the PR's own diff keeps moving as the PR grows — it reached 116.
A self-referential number cannot be stated correctly in the thing it counts, so
it is stated as a shape instead: two sections.)*
Third instance of the same pattern in one day.

**7.4 Improvised a check that a repo command should own.** The deploy-verification
wait loop matched the **cancelled** concurrency-dedupe run and returned early;
production was still on the old SHA when it reported done. The trap is recorded in
project memory and the loop was still written wrong. *Mechanism:* deploy
verification belongs in one command in the repository (#134), not re-improvised per
session.

**Also caught by running rather than reading:**

- Three line-number references in the previous handoff were already stale.
- A partner assertion assumed the export carried a stub URL as text. It does not —
  the assertion failed on execution.
- The `.gitignore` rule for ephemeral handoffs **silently swallowed the handoff
  template**. An ignore pattern is a gate with no output; it never says what it hid.
- A "red" CI job showed 8 failing visual snapshots that had **measured nothing** —
  the browser-install step had been skipped by an earlier failure. The loud
  secondary red masked the real cause.

---

## 8. Still open

**Awaiting the operator:**

1. **~$2.75/PR review budget** — derived in §5, revised down from $5, arithmetic corrected 2026-07-30.
2. ~~**Permission to delete** — the 30 root handoff documents~~ **WITHDRAWN
   2026-07-30.** There are 32, not 30, and the deletion project is closed on
   evidence: 18 of them are referenced by tracked files and moving them broke 18
   tests. See the extraction ledger. Still open from this item: the Tier 2 gate
   issues that fail *"does this prevent a regression we actually had?"*
3. **Whether the legacy "Model outputs" section returns** — decides whether #115 is
   a move or a deletion.

**Queued, in order** (`docs/analysis/2026-07-30-backlog-triage.md`): #171 first —
it absorbs #128, unblocks #115, should swallow #112, and #100 must be built on its
two-mode split because *degrade to simulation* at the spend ceiling is only honest
if it degrades the **whole run**.

**Not built, designed only:** the enforcement ledger (§6) and the review job at diff
time. *(This also said `docs/adr/` had 2 records and none on method — stale within
this same pull request, which adds ADR-0003, the first method ADR.)*
