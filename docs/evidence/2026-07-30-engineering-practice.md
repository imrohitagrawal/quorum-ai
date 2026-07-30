# 2026-07-30 — engineering practice: what the evidence actually says

**Status:** Current.
**Scope:** Code review effectiveness and reviewer count; automated quality gates
(mutation, coverage, static analysis); documentation decay; session handoff;
LLM-based code review precision; the cost of running review on every pull request.
**Method:** Three parallel read-only research sweeps, each instructed to give a
primary source per number and to report `NOT-FOUND` rather than produce a
plausible-sounding figure. Local numbers measured on this repository the same day.

> **A method warning worth carrying.** One sweep's PDF-fetch path **fabricated
> numbers on its first attempt** — it invented a sample size and a statistic for a
> real paper. The agent caught it by cross-checking and re-extracted everything
> through a different path. A research agent can produce citation-shaped fiction.
> Every number below has a primary source attached for that reason.

---

## 1. Code review

| # | Claim | Grade | Source |
|---|---|---|---|
| 1.1 | **Two reviewers ≈ four reviewers. One is worse.** *"We found no difference in the interval or effectiveness of inspections of two- or four-person teams. The effectiveness of one-reviewer teams was poorer than both of the others."* | `ASSERTION` — **downgraded from `WELL-EVIDENCED` on 2026-07-30, see note below** | Porter, Siy, **Toman** & Votta, "An Experiment to Assess the Cost-Benefits of Code Inspections in Large Scale Software Development", *IEEE TSE* 23(6):329–346, 1997, DOI 10.1109/32.601071. **Randomized controlled experiment**, 88 inspections over 18 months, >55K new lines of C++ |
| 1.2 | **Defect-related comments are 14% of review comments** — fourth of nine categories. Code improvement is the largest at 29%. Defect-finding is practitioners' stated top motivation and is not what they mostly write | `WELL-EVIDENCED` | Bacchelli & Bird, ICSE 2013. 570 comments classified from 200 Microsoft review threads |
| 1.3 | **One reviewer is the norm in practice.** <25% of changes have more than one reviewer; median reviewer count 1; median change 24 lines | `WELL-EVIDENCED` | Sadowski et al., ICSE-SEIP 2018. ~9M changes, >25,000 authors/reviewers at Google |
| 1.4 | **Review's measured effect on post-release defects is weak and partly fails to replicate.** Coverage negatively associated with defects in 3 of 4 releases, significant in 2 — then a replication found review measures *"contributed little… R² remaining almost unchanged"* | `WELL-EVIDENCED` (both) | McIntosh et al., *EMSE* 2016 (Qt/VTK/ITK); Krutauz, Dey, Rigby & Mockus, arXiv:2005.09217, 2020 (Qt, Chrome) — **preprint; peer-reviewed version not confirmed** |
| 1.5 | Effective teams review small units — field median change sizes 24–78 lines (Apache 25, Linux 32, Android/AMD 44, Chrome 78) vs 263 for classic formal inspection | `WELL-EVIDENCED` | Rigby & Bird, ESEC/FSE 2013 |
| 1.6 | "Review 200–400 lines"; "under 300 LOC/hour" | `VENDOR` | SmartBear, *Best Kept Secrets of Peer Code Review* (Cisco case study). **SmartBear sells the tool that produced the data.** 50 developers, one product group. **61% of reviews found zero defects**; "defect" = a comment logged in their tool, not a shipped bug; the authors state ANOVA assumptions were violated |
| 1.7 | Fagan 1976: "82% of defects found by inspection" | `ASSERTION` | Could **not** be verified in the paper (paywalled); found only in secondary sources. 50 years old, single COBOL program, IBM, waterfall, in-person meetings. **No modern replication found** |
| 1.8 | Capers Jones defect-removal-efficiency table (formal code inspection 85% average) | `ASSERTION` | Consultancy-published; no sampling frame, no DRE denominator definition, proprietary database. Ranges so wide (unit testing 15–50%) they carry little decision value. **Conflicts with 1.1/1.4** — do not blend |
| 1.9 | McConnell's *Code Complete* defect-detection table | `ASSERTION` | Table values not obtained from primary source. It is a **synthesis largely of Capers Jones** — citing both double-counts one dataset. His actual point, usually dropped: no technique exceeds ~75%, average ~40%, **use a combination** |

**Correction, 2026-07-30 — row 1.1 was misattributed, and the grade was wrong.**
This record originally credited the 1997 paper to "Porter, Siy, **Mockus** &
Votta". The correct author list is **Porter, Siy, Toman & Votta**. Mockus is an
author of a *different* Porter/Siy study — "Understanding the Sources of Variation
in Software Inspections", *TOSEM* 1998. The wrong list was also copied into
`docs/DAY-ONE-PROMPT.md`.

This matters more than a typo. Row 1.1 is the single citation that changed
`AGENTS.md` rule 10 from "fan out 3–5 review lenses" to "two lenses, not five",
and `WELL-EVIDENCED` is defined in this directory's README as *peer-reviewed,
primary source read*. **An author list that wrong is proof the primary source was
not read** — the paper is paywalled, and neither the verbatim quote nor the
"88 inspections / 18 months / >55K lines of C++" figures were confirmed against
it. This directory's README says it plainly: *"A citation you have not read is
`ASSERTION`, not `WELL-EVIDENCED`, however respectable the name."* So the grade is
`ASSERTION`.

*(This note first downgraded the row to `INDUSTRY-PUBLISHED`. That was a second
error: the README defines that grade as "a named organisation reporting its own
practice", which a randomized academic experiment is not. Corrected the same day —
a wrong correction is still wrong.)*

**The conclusion still stands** — the finding is widely reported and no source
contradicts it — but it now rests on secondary reporting, not on a source anyone
here has read.

**What would change 1.1:** obtain the paper and confirm the quote and figures
directly, which would restore `WELL-EVIDENCED`; or a second randomized experiment
on modern pull-request review with different team sizes, of which none exists as
of this date.

---

## 2. LLM-based code review

| # | Claim | Grade | Source |
|---|---|---|---|
| 2.1 | **Best measured LLM review: precision 16.65%, recall 23.18%, F1 19.38%, 1.10 false positives per pull request.** Across models, precision ranged 6.8%–16.9%. Authors: *"not yet ready for real-world code review deployment"* | `WELL-EVIDENCED` for the measurement, but **preprint** | SWRBench, arXiv:2509.01494v2. 1,000 PRs — 500 with a real needed change, **500 verified defect-free** so any comment on them is provably a false positive. Python-only; SWE-Bench-derived, so possible training contamination |
| 2.2 | Google reports ~5% of reviewer comments are addressed by applying an ML-suggested edit | `INDUSTRY-PUBLISHED` | Frömmgen et al., ICSE-SEIP 2024. **Measures ML fixing comments a human already wrote — not ML finding defects.** Do not cite as evidence AI review works |
| 2.3 | Peer-reviewed measurement of LLM review precision/recall on a production codebase | `NOT-FOUND` | Searched. Does not appear to exist |

**Corroborating local number:** an earlier session here ran a five-lens fan that
raised 32 findings; independent verifiers **refuted 23** — **28% precision**, the
same neighbourhood as 2.1. A single later round (2026-07-30) hit 7 of 10, but n=1.
**The finding step is low-precision; the verification step is what makes it usable.**

**What would change 2.1:** a peer-reviewed multi-language benchmark, or a
measurement on non-public code. Re-check when either appears.

---

## 3. Quality gates

| # | Claim | Grade | Source |
|---|---|---|---|
| 3.1 | **Google does not gate on a mutation score and does not compute one.** *"we were also unable to find a good way to surface it to the engineers in an actionable way."* Mutants are surfaced **on changed lines, at review, one per line, with "arid" nodes suppressed** | `WELL-EVIDENCED` | Petrović & Ivanković, ICSE-SEIP 2018; Petrović et al., ICSE 2021 |
| 3.2 | Arid-node suppression + per-line caps moved productive-mutant ratio **15% → 89%**. Mutants coupled to **70% of high-priority bugs** in already-covered code | `WELL-EVIDENCED` | as 3.1 |
| 3.3 | **Placement beats precision.** *"the fix rate—the proportion of reported issues that developers resolved—was near zero… we switched Infer on at diff time… the fix rate rocketed to over 70%. **The same program analysis, with same false positive rate**"* | `WELL-EVIDENCED` | Distefano, Fähndrich, Logozzo & O'Hearn, *CACM* 62(8), 2019 |
| 3.4 | **False-positive tolerance is tiered by enforcement strength.** Blocking checks need *"essentially zero"* false positives; advisory-at-review tolerates **<10%**. Governance: **≥10% not-useful → probation; >25% → may disable immediately** | `WELL-EVIDENCED` | Sadowski et al., *Tricorder*, ICSE 2015. Their measured platform-wide not-useful rate ran ~5% |
| 3.5 | **Coverage should not be used as a quality target.** *"low to moderate correlation between coverage and effectiveness when the number of test cases is controlled for… should not be used as a quality target"* | `WELL-EVIDENCED` | Inozemtseva & Holmes, ICSE 2014. 31,000 suites, 5 Java systems. Caveat: their effectiveness measure is itself mutation score |
| 3.6 | Google enforces **no** codebase-wide coverage threshold; teams opt into their own. *"instead of treating 80% like a floor, engineers treat it like a ceiling"* | `INDUSTRY-PUBLISHED` | Ivanković et al., ESEC/FSE 2019; *Software Engineering at Google* Ch. 11 |
| 3.7 | Does mutation score predict real faults? **Two papers appear to conflict and mostly do not** — they controlled different confounds. Just et al. (FSE 2014, 357 real faults) found correlation independent of coverage, with 17% of real faults coupled to no mutant. Papadakis et al. (ICSE 2018, 420 faults) found correlations collapse to 0.05–0.20 once **suite size** is controlled | `WELL-EVIDENCED` (both) | as cited. Neither "mutation score is proven" nor "debunked" is supportable |
| 3.8 | A workable maximum number of blocking CI checks | `NOT-FOUND` | No published number. GitHub docs give none. **Practitioner folklore** |
| 3.9 | "Developers lose focus after N minutes of CI wait" | `NOT-FOUND` | No traceable primary source linking interruption research to CI build times. **Do not cite** |
| 3.10 | Tooling defaults on **zero tests** are inconsistent: `pytest` exits 5 (fails); Jest fails by default; **Maven Surefire passes**; **`go test` exits 0** with an easy-to-miss warning; Stryker's mutation-score gate defaults to never failing | `INDUSTRY-PUBLISHED` (vendor docs) | Each tool's own documentation. Directly actionable for gate-liveness work |

**What would change 3.1:** Google publishing a mutation-score gate. Re-check
before anyone proposes promoting ours to blocking.

---

## 4. Gate liveness — our own coinage

| # | Claim | Grade |
|---|---|---|
| 4.1 | **13 of 21 CI jobs here could reach a terminal status having measured nothing; four of them blocking.** `diff-cover` reproduced exiting **0** on a diff with genuinely uncovered new lines | `LOCAL` |
| 4.2 | Established literature or tooling for "a check that passed because it measured nothing" | `NOT-FOUND` |
| 4.3 | Formal-verification **vacuity detection** (Beer et al., CAV 1997; Kupferman & Vardi, STTT 2003) is real and mature — and is **temporal-logic model checking, not CI**. A sound analogy, **not inherited prior art**. Citing it as precedent would be the exact dishonesty this work exists to remove | `WELL-EVIDENCED` (as a different field) |

---

## 5. Documentation decay

| # | Claim | Grade | Source |
|---|---|---|---|
| 5.1 | **>25% of the top 1,000 GitHub projects contain at least one outdated code-element reference** — a doc reference to code every instance of which has been deleted | `WELL-EVIDENCED` | Tan, Wagner & Treude, *EMSE* 28, 2023 (arXiv:2212.01479 / 2307.04291) |
| 5.2 | **Derived facts decay faster than rationale** | `REFUTED` — **as stated.** Not tested anywhere. Derived facts are the only staleness class with detectors, so they are the only class counted; concluding they decay faster is a **tooling artifact, not a measurement**. The defensible rule is *derived facts are mechanically checkable and rationale is not* | — |
| 5.3 | Documentation goes stale **silently** — no crash, no error | `WELL-EVIDENCED` (as framing) | Tan/Treude line of work |
| 5.4 | Docs-as-code and freshness dates enforce **attention, not accuracy** | `INDUSTRY-PUBLISHED` | *Software Engineering at Google* Ch. 10. Their own chapter claims no more |
| 5.5 | DRY was explicitly intended to cover documentation — *"documentation and code are different views of the same underlying model"* | `WELL-EVIDENCED` (as authorial intent) | Hunt & Thomas, *The Pragmatic Programmer*; confirmed on the record in their Artima interview |
| 5.6 | Code-comment inconsistency ≈1.5× more bug-introducing | `ASSERTION` | Wen et al., ICPC 2019 — real paper, **PDF unreachable**; ratio from search summaries |
| 5.7 | ADRs (Nygard 2011) enforce anything | `REFUTED` — a filing convention with **zero** mechanical enforcement. Practitioner literature reports the hard problem is decisions going **quietly irrelevant**, which is harder to detect than a wrong line number |

---

## 6. Session handoff — the strongest evidence in this record, and it is not from software

| # | Claim | Grade | Source |
|---|---|---|---|
| 6.1 | **Structured handoff reduced medical errors 23% and preventable adverse events 30%, at no time cost.** 24.5 → 18.8 errors/100 admissions (p<0.001); 4.7 → 3.3 preventable AEs/100 (p<0.001); 2.4 → 2.5 min/patient (p=0.55). **Negative control held**: non-preventable AEs did not move (p=0.79) | `WELL-EVIDENCED` | **I-PASS** — Starmer et al., *NEJM* 2014;371(19):1803–12. 9 sites, **10,740 admissions**. Caveat: a **bundle** (mnemonic + training + faculty development), not a template alone |
| 6.2 | I-PASS elements: Illness severity / Patient summary / Action list / **Situation awareness and contingency planning** / **Synthesis by receiver** | `WELL-EVIDENCED` | as 6.1 |
| 6.3 | **"Synthesis by receiver" has no software equivalent.** Every software handoff practice found is write-only. UK HSE independently requires the same ("cross-checking by incoming personnel"; "two-way, with both participants taking joint responsibility") | `WELL-EVIDENCED` + `NOT-FOUND` for the software side | HSE *Human Factors: Shift Handover* |
| 6.4 | **SBAR** improves safety | `ASSERTION`/weak — low-certainty evidence; outcomes dominated by process metrics (documentation completeness 41.5%). **The famous protocol is the less-evidenced one.** Cite I-PASS |
| 6.5 | Cross-domain handoff strategies — 19 of 21 in use across NASA JSC, nuclear, rail, ambulance dispatch | `WELL-EVIDENCED` **as description only.** Measured **no** error reduction. A catalogue, not proof | Patterson et al., *Int J Qual Health Care* 2004;16(2):125–32 |
| 6.6 | HSE shift-handover principles; Piper Alpha and Sellafield attributions | `INDUSTRY-PUBLISHED`, incident-derived — retrospective causal attribution from inquiries, not experiment | HSE |
| 6.7 | Playbooks give ~3× MTTR improvement | `ASSERTION` | Google SRE book, Ch. 1. **No published methodology** — no sample, no period, no comparison definition. Say "Google reports", never "studies show" |
| 6.8 | Live state belongs in a queried dashboard; prose is for procedure and judgement a query cannot produce | `INDUSTRY-PUBLISHED` | Google SRE book Ch. 6, Ch. 11 |

---

## 7. DORA

| # | Claim | Grade |
|---|---|---|
| 7.1 | DORA findings are survey-based, self-reported, cross-sectional, non-probability sampled, and **the raw data is not published** — external re-analysis is impossible. Its own FAQ concedes results *"may be artifacts of sampling and analysis methods"* | `VENDOR` (Google Cloud research programme) |
| 7.2 | Its structural-equation model *"optimizes for prediction… vs testing for model fit"* — and the method page carries **no limitations section**. **Do not present DORA paths as causal** | `VENDOR` |
| 7.3 | External change-approval bodies (manager/CAB) correlated negatively with lead time and deployment frequency and had **no correlation with change failure rate** — "worse than having no change approval process at all" | `INDUSTRY-PUBLISHED`; verified via consistent secondary quotes, **not against the book itself** |
| 7.4 | A peer-reviewed critique of DORA's construct validity | `NOT-FOUND` |

---

## 8. Local measurements — this repository, 2026-07-30

| # | Measurement | How |
|---|---|---|
| 8.1 | **0 of 16** `src/` defects were caught by an automated check; **10 of 16** by adversarial review; 3 manual; 1 production | `git blame` per fix commit — `docs/metrics/defect-discovery-audit.md` |
| 8.2 | Merged pull-request size: **p50 419 changed lines**, p90 2,111, max 29,996 (PR #96). **5–17× the field medians in 1.5** | `gh pr list --state merged --limit 30` |
| 8.3 | **One thorough review lens costs 96k–122k tokens** on a real diff here (round-1 reviewer 95,986; round-2 121,908) | Measured, this session |
| 8.4 | Verified pricing: Claude Opus 5 **$5/M input, $25/M output**; cache reads ~0.1×, writes 1.25× | Anthropic pricing table, cached 2026-06-24 |
| 8.5 | **Derived review cost ≈ $0.90 per lens**; two lenses + verification ≈ **$2.75 per pull request**; ~$83 across 30 PRs *(corrected 2026-07-30 — the arithmetic did not follow from the inputs; see ADR-0003)*. **Input/output split is inferred, not measured** — settle with one `count_tokens` run | 8.3 × 8.4 |
| 8.6 | Review precision here: **28%** unverified (32 findings, 23 refuted, earlier session); 70% on one later round (n=1) | Session records |

**What would change 8.5:** a `count_tokens` run against a representative diff.
Until then the figure is an estimate with a stated method, not a measurement.

---

## 9. What this record changed

Decisions revised the same day it was compiled:

| Was going to | Now | Because |
|---|---|---|
| Fan out 3–5 review lenses | **Two** | 1.1 |
| Budget $5/PR for review | **~$2.75/PR** | 1.1 → fewer lenses |
| Cite review as "the method with the track record" | Keep the claim, **shrink it to local n=16** | 1.2, 1.4 |
| Encode "review 200–400 lines" | **Dropped**; use the field-median observation instead | 1.6 |
| Tune gate precision | **Check gate placement first** | 3.3 |
| Promote gates to blocking on green | **Measure not-useful rate first; blocking needs ~0%** | 3.4 |
| Defend the coverage floor as quality evidence | **Ratchet only; not evidence** | 3.5, 3.6 |
| Argue derived facts decay faster | **Argue they are mechanically checkable** | 5.2 |
| Cite the SRE 3× playbook figure | **"Google reports", or not at all** | 6.7 |
