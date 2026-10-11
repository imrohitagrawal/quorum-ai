# One status, package B: failure modes listed before building (2026-10-11)

Package B makes a fresh reader reach one status, and makes a false "done" fail a check. The plan
is `docs/analysis/2026-10-11-how-we-work-review.md`, section "Package B". The baseline: a reader
with no project memory, on a copy of `main` at `c894f78`, got 9 of 19 expected facts right. It
named the wrong build, said 9 open issues where GitHub had 4, and missed that the board and
GitHub disagree.

## The three status homes and the readiness section

| # | Failure | Defence | Test |
|---|---|---|---|
| H1 | **The readiness section goes stale and is read as current.** A handoff written before a merge names the build before it, as `2a6959a` was read on 2026-10-11. | The section states the time and build it was generated from, and says how to get the current value (`GET /status`). | The generated text contains the generation time, the build and the instruction. |
| H2 | **The verdict says "Ready" when production is simulated.** | "Ready" only when `live_execution` is true and `/ready` reports `ready` with no reasons. Anything else is "Not ready", with the reason. | A fixture of today's `/status` and `/ready` gives "Not ready" and names live execution. A fixture with live execution on and no reasons gives "Ready". |
| H3 | **Offline, the section fails the handoff,** against ADR-0045. | Each fetch degrades to "unavailable". | A failed fetch still writes the file. |
| H4 | **An old status document is still read as current.** | Each one carries a banner naming the three homes, or is archived. The archived ones stop being named by skills and links. | The banner exists, and no live link points at an archived path. |

## The completion-word check

| # | Failure | Defence | Test |
|---|---|---|---|
| C1 | **A false "done" passes.** "W55 and W56 merged in #9558, in production" in a handoff. | A completion word in a scoped file must cite, in the same paragraph or table row, a pull request whose squash commit is on `main`, a commit on `main`, or an existing CHG row. | The planted claims are rejected with their messages. |
| C2 | **A true "done" is rejected,** and the check gets switched off. | A citation of a real merged pull request, a real commit or a real CHG row is accepted. | A true claim citing a real merged pull request is accepted. |
| C3 | **Old files flood the check.** 153 of 155 ADRs say "Accepted", and every narrative handoff says "merged" or "in production". | Only files changed after a named cut-off commit are checked, and the pull request states how many are exempt. | A file last changed before the cut-off is not checked. A file changed after it is. |
| C4 | **A negation reads as a claim.** "UNVERIFIED", "not merged". | Word boundaries, and a negation just before the word skips it. | Each is accepted. |
| C5 | **A citation of a pull request that exists but is not on `main`** (open or closed unmerged). | Look for the squash subject `(#N)` on `main`'s history, offline, with `git log`. | A number with no squash commit on `main` is rejected. |
| C6 | **The check passes over nothing.** | It reports how many files and claims it read. Reading zero scoped files is an error. | A copy with no scoped file fails. |

## The board

| # | Failure | Defence | Test |
|---|---|---|---|
| N1 | **A made-up `PRESENT` needle reads DONE at once** (claim I4). The needle states the open form, so a needle that was never in the file is "absent", which derives DONE. | A new `PRESENT` row must name a commit where its needle was in the file: `PRESENT@<sha>`. The 10 rows that use `PRESENT` today (W3, W10, W15, W16, W17, W18, W22, W28, W37, W47) keep working by name. | A made-up needle with no commit, or with a commit where the needle is absent, fails. A real needle at a real commit is accepted. |
| N2 | **The board and GitHub disagree, and nobody notices.** On 2026-10-11, four DONE rows had open issues, and #458 and #459 were open with no row. | A check lists every DONE row whose issue is open, and every open issue with no row. `make handoff` shows it. It needs `gh`, so offline it reports "unavailable" and does not fail. | Fake `gh` output for each mismatch kind. |
| N3 | **Flipping a row's polarity** (claim I3) still passes. | Out of scope. This is the limit the board already documents. Its test asserts the flip is accepted and names that limit. | The planted test asserts I3 is accepted. |
